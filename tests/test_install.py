# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for install.py, run against a temporary HOME."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.py"
PACK_SKILLS = sorted(p.name for p in (ROOT / "home/.agents/skills").iterdir())
ONLINE_SKILLS = sorted(p.name for p in (ROOT / "claude-ai/skills").iterdir())
AGENTS = sorted(p.stem for p in (ROOT / "home/.agents/agents").glob("*.md"))

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None


class Install(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        for folder in (".claude", ".codex", ".gemini", ".copilot", ".cursor"):
            (self.home / folder).mkdir()

    def run_install(self, *args: str, installer: Path = INSTALL) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin"}
        return subprocess.run([sys.executable, "-B", str(installer), *args], env=env,
                              capture_output=True, text=True, check=False)

    def install(self, *args: str) -> str:
        result = self.run_install(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def snapshot(self) -> dict:
        return {str(p.relative_to(self.home)): (os.readlink(p) if p.is_symlink() else p.read_bytes())
                for p in sorted(self.home.rglob("*")) if p.is_file() or p.is_symlink()}

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        self.install("--dry-run")
        self.assertEqual(self.snapshot(), before)

    def test_second_run_changes_nothing(self):
        self.install()
        self.assertIn("0 change(s).", self.install())

    def test_shared_source_and_claude_links(self):
        self.install()
        agents = self.home / ".agents"
        for name in PACK_SKILLS + ONLINE_SKILLS:
            self.assertTrue((agents / "skills" / name / "SKILL.md").is_file(), name)
        claude_skills = self.home / ".claude" / "skills"
        for name in PACK_SKILLS + ONLINE_SKILLS:
            link = claude_skills / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(os.readlink(link), str(agents / "skills" / name))
        self.assertIn("@~/.agents/AGENTS.md", (self.home / ".claude/CLAUDE.md").read_text())
        for name in AGENTS:
            self.assertTrue((self.home / ".claude/agents" / f"{name}.md").is_file())

    def test_skills_folder_shared_with_agents_is_left_alone(self):
        shared = self.home / ".agents/skills"
        shared.mkdir(parents=True)
        (self.home / ".claude/skills").symlink_to(shared)
        out = self.install()
        for name in PACK_SKILLS + ONLINE_SKILLS:
            self.assertFalse((shared / name).is_symlink(), name)
            self.assertTrue((shared / name / "SKILL.md").is_file(), name)
        self.assertFalse((self.home / ".agents-backup").exists())
        self.assertIn(f"{self.home / '.claude/skills'} resolves to {shared.resolve()}", out)
        self.assertIn("0 change(s).", self.install().splitlines())

    def test_link_reached_through_a_linked_folder_is_left_alone(self):
        (self.home / ".codex").rmdir()
        (self.home / ".agents").mkdir()
        (self.home / ".codex").symlink_to(self.home / ".agents")
        out = self.install("--tools", "codex")
        instructions = self.home / ".agents/AGENTS.md"
        self.assertFalse(instructions.is_symlink())
        self.assertEqual(instructions.read_bytes(), (ROOT / "home/.agents/AGENTS.md").read_bytes())
        self.assertIn(f"{self.home / '.codex/AGENTS.md'} resolves to {instructions}; left as it is.", out)

    def test_synced_copies_of_repository_skills_are_turned_off(self):
        settings = self.home / ".claude/settings.json"
        settings.write_text(json.dumps({"skillOverrides": {"anthropic-skills:tutor": "on", "other": "off"}}))
        self.install()
        overrides = json.loads(settings.read_text())["skillOverrides"]
        uploaded = set(ONLINE_SKILLS) | set(json.loads((ROOT / "claude-ai/overrides.json").read_text())["skills"])
        self.assertIn("decide", uploaded)
        for name in uploaded - {"tutor"}:
            self.assertEqual(overrides["anthropic-skills:" + name], "off", name)
        self.assertEqual(overrides["anthropic-skills:tutor"], "on", "a value set by hand must win")
        self.assertEqual(overrides["other"], "off")
        self.assertNotIn("anthropic-skills:spec", overrides, "only skills uploaded to claude.ai")

    def test_audit_lists_foreign_entries_and_broken_links_without_changes(self):
        self.install()
        mine = self.home / ".claude/skills/my-own-skill"
        mine.mkdir()
        dangling = self.home / ".claude/skills/gone"
        dangling.symlink_to(self.home / ".agents/skills/gone")
        (self.home / ".codex/agents/old.toml").write_text("")
        before = self.snapshot()
        out = self.install("--audit")
        self.assertEqual(self.snapshot(), before)
        foreign, broken = out.split("Broken links")
        self.assertIn(str(mine), foreign)
        self.assertIn(str(self.home / ".codex/agents/old.toml"), foreign)
        self.assertIn(str(dangling), broken)
        self.assertNotIn(str(dangling), foreign)
        for name in PACK_SKILLS + ONLINE_SKILLS:
            self.assertNotIn(str(self.home / ".claude/skills" / name) + "\n", out)

    def test_claude_settings_merge_keeps_user_values(self):
        settings = self.home / ".claude/settings.json"
        settings.write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(npm test *)"]}}))
        self.install()
        merged = json.loads(settings.read_text())
        self.assertEqual(merged["model"], "opus")
        self.assertIn("Bash(npm test *)", merged["permissions"]["allow"])
        self.assertIn("Bash(cmake --build *)", merged["permissions"]["allow"])
        self.assertEqual(sorted(merged["hooks"]), ["PostToolUse", "PreToolUse", "SessionStart"])
        self.install()
        again = json.loads(settings.read_text())
        self.assertEqual(len(again["hooks"]["PreToolUse"]), 1, "hook entries must not duplicate")

    def test_other_agents_get_instructions_agents_and_hooks(self):
        self.install()
        target = str(self.home / ".agents/AGENTS.md")
        for path in (".codex/AGENTS.md", ".gemini/GEMINI.md", ".copilot/copilot-instructions.md"):
            self.assertEqual(os.readlink(self.home / path), target, path)
        gemini = json.loads((self.home / ".gemini/settings.json").read_text())
        self.assertEqual(gemini["context"]["fileName"], ["AGENTS.md", "GEMINI.md"])
        self.assertIn("BeforeTool", gemini["hooks"])
        copilot = json.loads((self.home / ".copilot/hooks/agents-global.json").read_text())
        self.assertEqual(copilot["version"], 1)
        for name in AGENTS:
            self.assertTrue((self.home / ".gemini/agents" / f"{name}.md").is_file())
            self.assertTrue((self.home / ".copilot/agents" / f"{name}.agent.md").is_file())
            toml = (self.home / ".codex/agents" / f"{name}.toml").read_text()
            if tomllib:
                parsed = tomllib.loads(toml)
                self.assertEqual(parsed["name"], name)
                self.assertTrue(parsed["developer_instructions"].strip())

    def test_cursor_note_matches_what_was_installed(self):
        alone = self.install("--tools", "cursor")
        self.assertFalse((self.home / ".claude/agents").exists())
        self.assertIn("Cursor: this run gave it no subagents and no hooks", alone)
        self.assertNotIn("~/.claude/agents and the Claude Code hooks", alone)
        with_claude = self.install("--tools", "cursor,claude")
        self.assertIn("Cursor: it reads ~/.agents/skills, ~/.claude/agents and the Claude Code hooks", with_claude)

    def run_hook(self, command: str, payload: dict) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin"}
        return subprocess.run(["sh", "-c", command], input=json.dumps(payload), env=env,
                              capture_output=True, text=True, check=False)

    def test_copilot_hooks_follow_the_documented_native_format(self):
        # GitHub's hooks reference: camelCase events get the native payload (toolName,
        # toolArgs) and a matcher compiled as ^(?:PATTERN)$ against toolName; native
        # tool names are bash, edit, create, view..., and str_replace_editor and
        # apply_patch are edit tools too. User hooks live in ~/.copilot/hooks/*.json.
        self.install("--tools", "copilot")
        config = json.loads((self.home / ".copilot/hooks/agents-global.json").read_text())
        self.assertEqual(config["version"], 1)
        self.assertEqual(sorted(config["hooks"]), ["postToolUse", "preToolUse"])
        (pre,), (post,) = config["hooks"]["preToolUse"], config["hooks"]["postToolUse"]
        for entry, script, matching, other in (
                (pre, "guard_bash.py", ["bash"], ["powershell", "edit", "create", "view", "Bash"]),
                (post, "after_edit.py", ["edit", "create", "str_replace_editor", "apply_patch"],
                 ["bash", "view", "Edit", "Write"])):
            self.assertEqual(entry["type"], "command")
            self.assertEqual(entry["bash"], f'python3 "$HOME/.agents/hooks/{script}" --tool copilot')
            self.assertIsInstance(entry["timeoutSec"], int)
            for name in matching:
                self.assertTrue(re.fullmatch(f"(?:{entry['matcher']})", name), (script, name))
            for name in other:
                self.assertFalse(re.fullmatch(f"(?:{entry['matcher']})", name), (script, name))
        # The native payload as GitHub's Copilot CLI hooks guide shows it.
        blocked = self.run_hook(pre["bash"], {"timestamp": 1704614400000, "cwd": "/tmp", "toolName": "bash",
                                              "toolArgs": json.dumps({"command": "git commit --no-verify"})})
        decision = json.loads(blocked.stdout or "{}").get("permissionDecision")
        self.assertTrue(blocked.returncode != 0 or decision == "deny", blocked)
        allowed = self.run_hook(pre["bash"], {"timestamp": 1704614400000, "cwd": "/tmp", "toolName": "bash",
                                              "toolArgs": json.dumps({"command": "ls"})})
        self.assertEqual(allowed.returncode, 0, allowed)
        self.assertNotEqual(json.loads(allowed.stdout or "{}").get("permissionDecision"), "deny")

    def test_replaced_files_are_backed_up(self):
        claude_md = self.home / ".claude/CLAUDE.md"
        claude_md.write_text("my old notes\n")
        self.install()
        backups = list((self.home / ".agents-backup").rglob("CLAUDE.md"))
        self.assertEqual([b.read_text() for b in backups], ["my old notes\n"])


if __name__ == "__main__":
    unittest.main()
