# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for install.py, run against a temporary HOME."""

import json
import os
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

    def install(self, *args: str) -> str:
        env = {**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin"}
        result = subprocess.run([sys.executable, "-B", str(INSTALL), *args], env=env,
                                capture_output=True, text=True, check=False)
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

    def test_replaced_files_are_backed_up(self):
        claude_md = self.home / ".claude/CLAUDE.md"
        claude_md.write_text("my old notes\n")
        self.install()
        backups = list((self.home / ".agents-backup").rglob("CLAUDE.md"))
        self.assertEqual([b.read_text() for b in backups], ["my old notes\n"])


if __name__ == "__main__":
    unittest.main()
