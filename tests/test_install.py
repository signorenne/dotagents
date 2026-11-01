# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for install.py, run against a temporary HOME."""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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

_spec = importlib.util.spec_from_file_location("install", INSTALL)
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)
OUR_GUARD = {"type": "command", "command": 'python3 "$HOME/.agents/hooks/guard_bash.py" --tool claude'}
USER_HOOK = {"type": "command", "command": 'python3 "$HOME/.agents/hooks/my_own.py"'}


class MergeEventHooks(unittest.TestCase):
    def test_user_scripts_in_the_agents_hooks_folder_are_kept(self):
        existing = {"PreToolUse": [{"matcher": "Bash", "hooks": [USER_HOOK, OUR_GUARD]},
                                   {"matcher": "Bash", "hooks": [
                                       {"type": "command", "command": "python3 ~/.claude/hooks/guard_bash.py"}]}]}
        merged = install.merge_event_hooks(existing, {"PreToolUse": [{"matcher": "Bash", "hooks": [OUR_GUARD]}]})
        self.assertEqual(merged, {"PreToolUse": [{"matcher": "Bash", "hooks": [USER_HOOK]},
                                                 {"matcher": "Bash", "hooks": [OUR_GUARD]}]})

    def test_unexpected_items_and_values_are_kept_unchanged(self):
        existing = {"PreToolUse": [{"matcher": "Bash", "hooks": ["text", 3, OUR_GUARD]}, "loose",
                                   {"matcher": "Edit", "hooks": []}],
                    "Stop": {"not": "a list"}, "Custom": "text"}
        merged = install.merge_event_hooks(existing, {"PreToolUse": [{"matcher": "Bash", "hooks": [OUR_GUARD]}]})
        self.assertEqual(merged, {"PreToolUse": [{"matcher": "Bash", "hooks": ["text", 3]}, "loose",
                                                 {"matcher": "Edit", "hooks": []},
                                                 {"matcher": "Bash", "hooks": [OUR_GUARD]}],
                                  "Stop": {"not": "a list"}, "Custom": "text"})

    def test_hooks_that_cannot_take_our_entries_are_refused(self):
        ours = {"PreToolUse": [{"matcher": "Bash", "hooks": [OUR_GUARD]}]}
        for existing in (["an entry"], {"PreToolUse": {"matcher": "Bash"}}, "text"):
            with self.assertRaises(ValueError, msg=existing):
                install.merge_event_hooks(existing, ours)
        for empty in (None, {}, []):
            self.assertEqual(install.merge_event_hooks(empty, ours), ours)


class Install(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        for folder in (".claude", ".codex", ".gemini", ".gemini/antigravity-cli", ".copilot", ".cursor"):
            (self.home / folder).mkdir()

    def run_install(self, *args: str, installer: Path = INSTALL, env: dict = None,
                    cwd: Path = None) -> subprocess.CompletedProcess:
        # The tester's own COPILOT_HOME would send the Copilot files out of the temporary HOME.
        base = {k: v for k, v in os.environ.items() if k != "COPILOT_HOME"}
        env = {**base, "HOME": str(self.home), "PATH": "/usr/bin:/bin", **(env or {})}
        return subprocess.run([sys.executable, "-B", str(installer), *args], env=env,
                              capture_output=True, text=True, check=False, cwd=cwd)

    def install(self, *args: str, env: dict = None) -> str:
        result = self.run_install(*args, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def snapshot(self) -> dict:
        return {str(p.relative_to(self.home)): (os.readlink(p) if p.is_symlink() else p.read_bytes())
                for p in sorted(self.home.rglob("*")) if p.is_file() or p.is_symlink()}

    def test_a_renamed_skill_leaves_no_installed_copy(self):
        # review became branch-review: its old copy would still load in the tools that read
        # ~/.agents/skills, and its Claude Code link would point at it.
        old = self.home / ".agents/skills/review"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_text('---\nname: review\nlicense: "MIT, Copyright (c) 2026 '
                                      'Nicolò Plebani (nexenne). See LICENSE.txt"\n---\n', encoding="utf-8")
        (self.home / ".claude/skills").mkdir(parents=True)
        (self.home / ".claude/skills/review").symlink_to(old)
        mine = self.home / ".agents/skills/my-review"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("---\nname: my-review\n---\n", encoding="utf-8")
        self.install()
        self.assertFalse(old.exists())
        self.assertFalse((self.home / ".claude/skills/review").is_symlink())
        self.assertTrue((self.home / ".claude/skills/branch-review").is_symlink())
        self.assertTrue((mine / "SKILL.md").is_file())
        self.assertTrue(list((self.home / ".agents-backup").rglob("review/SKILL.md")))

    def test_a_folder_of_the_same_name_that_is_not_ours_stays(self):
        theirs = self.home / ".agents/skills/review"
        theirs.mkdir(parents=True)
        (theirs / "SKILL.md").write_text("---\nname: review\nlicense: Apache-2.0\n---\n", encoding="utf-8")
        self.install()
        self.assertTrue((theirs / "SKILL.md").is_file())

    def test_dry_run_changes_nothing(self):
        before = self.snapshot()
        self.install("--dry-run")
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_counts_what_a_real_run_changes(self):
        # Gemini CLI and Antigravity CLI share ~/.gemini/GEMINI.md: one link, one change.
        def count(out):
            return next(line for line in out.splitlines() if "change(s)." in line).split()[0]
        dry = self.install("--dry-run")
        self.assertEqual(len([line for line in dry.splitlines() if "GEMINI.md ->" in line]), 1, dry)
        self.assertEqual(count(dry), count(self.install()))

    def test_second_run_changes_nothing(self):
        self.install()
        self.assertIn("0 change(s).", self.install().splitlines())

    def test_dry_run_says_backups_would_be_saved(self):
        (self.home / ".claude/CLAUDE.md").write_text("my old notes\n")
        out = self.install("--dry-run", "--tools", "claude")
        self.assertIn(" Replaced files would be saved in ", out)
        self.assertFalse((self.home / ".agents-backup").exists())

    def test_tools_list_drops_empty_items_and_duplicates(self):
        out = self.install("--dry-run", "--tools", "claude,")
        self.assertIn("Agents: claude", out.splitlines())
        out = self.install("--dry-run", "--tools", "codex, claude,codex")
        self.assertIn("Agents: codex, claude", out.splitlines())

    def test_empty_tools_list_is_an_error(self):
        for value in ("", " , "):
            result = self.run_install("--dry-run", "--tools", value)
            self.assertEqual(result.returncode, 2, value)
            self.assertIn("--tools", result.stderr)
            self.assertNotIn("Agents:", result.stdout)

    def test_install_stops_before_writing_when_a_subagent_cannot_be_converted(self):
        pack = Path(tempfile.mkdtemp()) / "pack"
        self.addCleanup(shutil.rmtree, pack.parent)
        shutil.copytree(ROOT, pack, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__"))
        scout = pack / "home/.agents/agents/scout.md"
        scout.write_text(scout.read_text() + "\nA TOML end marker: '''\n")
        before = self.snapshot()
        result = self.run_install(installer=pack / "install.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("home/.agents/agents/scout.md", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.home / ".agents").exists())

    def test_a_replaced_file_counts_as_one_change(self):
        self.install()
        (self.home / ".agents/AGENTS.md").write_text("edited by hand\n")
        out = self.install()
        summary = [line for line in out.splitlines() if "change(s)." in line]
        self.assertEqual(len(summary), 1, out)
        self.assertTrue(summary[0].startswith("1 change(s). "), summary[0])

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
        self.assertEqual(sorted(merged["hooks"]), ["PostToolUse", "PostToolUseFailure", "PreCompact", "PreToolUse",
                                                  "SessionStart", "Stop"])
        self.install()
        again = json.loads(settings.read_text())
        self.assertEqual(len(again["hooks"]["PreToolUse"]), 1, "hook entries must not duplicate")

    def test_claude_settings_deny_every_push(self):
        # The maintainer reviews everything before it leaves the machine, so a push is denied,
        # not asked. Claude Code evaluates deny, then ask, then allow; a trailing " *" also
        # matches the bare command only when it is the rule's only wildcard, hence the bare
        # git -C form (code.claude.com/docs/en/permissions).
        settings = self.home / ".claude/settings.json"
        pushes = ["Bash(git push *)", "Bash(git -C * push *)", "Bash(git -C * push)"]
        older_install = {"permissions": {"ask": ["Bash(git push *)", "Bash(npm publish *)"]}}
        for before in (None, older_install):
            with self.subTest(before=before):
                if before:
                    settings.write_text(json.dumps(before))
                self.install("--tools", "claude")
                permissions = json.loads(settings.read_text())["permissions"]
                for rule in pushes:
                    self.assertIn(rule, permissions["deny"])
                    self.assertNotIn(rule, permissions["ask"])
                if before:
                    self.assertIn("Bash(npm publish *)", permissions["ask"])

    def test_claude_settings_ask_before_landing_commands(self):
        # Landing a branch rebases it, moves a branch ref (update-ref, merge --ff-only,
        # branch -f) and force-deletes the branch: each rewrites or drops history, so
        # Claude Code asks first, also in the git -C form. Claude Code evaluates deny, then
        # ask, then allow, and matches the words before a rule's first * as written
        # (code.claude.com/docs/en/permissions), so each spelling of a forced delete
        # needs its own rule; those that start with -f or --force fall under the rules for
        # a forced move.
        self.install("--tools", "claude")
        permissions = json.loads((self.home / ".claude/settings.json").read_text())["permissions"]
        forced_deletes = ["-D", "-df", "-fd", "-d -f", "-d --force", "--delete -f", "--delete --force"]
        # A forced rename (-M) or copy (-C) overwrites the target branch too.
        landing = (["rebase", "update-ref", "merge", "branch -f", "branch --force", "branch -M", "branch -C"]
                   + [f"branch {flags}" for flags in forced_deletes])
        for command in landing:
            for rule in (f"Bash(git {command} *)", f"Bash(git -C * {command} *)"):
                with self.subTest(rule=rule):
                    self.assertIn(rule, permissions["ask"])
                    self.assertNotIn(rule, permissions["deny"])
                    self.assertNotIn(rule, permissions["allow"])

    def test_claude_guard_blocks_when_it_cannot_run(self):
        # Claude Code hooks docs: "onFailure": "block" on a command hook (v2.1.295 or later)
        # makes a hook that cannot start, exits other than 0 or 2, times out or prints
        # invalid JSON block the tool call as exit 2 would. Only the guard needs it: a
        # broken guard must not let a push through, and the other hooks report, not guard.
        self.install("--tools", "claude")
        hooks = json.loads((self.home / ".claude/settings.json").read_text())["hooks"]
        handlers = {h["command"]: h for groups in hooks.values() for g in groups for h in g["hooks"]}
        guard = handlers.pop('python3 "$HOME/.agents/hooks/guard_bash.py" --tool claude')
        self.assertEqual(guard.get("onFailure"), "block")
        for command, handler in handlers.items():
            self.assertNotIn("onFailure", handler, command)
        # Unreadable input is not a failure: the guard exits 0 and the command runs.
        result = subprocess.run(["sh", "-c", guard["command"]], input="not json", capture_output=True, text=True,
                                env={**os.environ, "HOME": str(self.home), "PATH": "/usr/bin:/bin"}, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_settings_that_cannot_be_merged_are_left_unchanged(self):
        claude = self.home / ".claude/settings.json"
        claude.write_text(json.dumps({"model": "opus", "hooks": ["an entry"]}))
        codex = self.home / ".codex/hooks.json"
        codex.write_text("[]\n")
        gemini = self.home / ".gemini/settings.json"
        gemini.write_text(json.dumps({"context": "AGENTS.md"}))
        antigravity = self.home / ".gemini/config/hooks.json"
        antigravity.parent.mkdir()
        antigravity.write_text("[]\n")
        manifest = self.home / ".gemini/config/skills.json"
        manifest.write_text(json.dumps({"entries": {"path": "/x"}}))
        paths = (claude, codex, gemini, antigravity, manifest)
        before = [path.read_text() for path in paths]
        out = self.install("--tools", "claude,codex,gemini,antigravity")
        self.assertEqual([path.read_text() for path in paths], before)
        for path in paths:
            self.assertIn(f"Could not merge {path}", out)

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

    def test_claude_compaction_brief_never_blocks_compaction(self):
        # Claude Code's PreCompact: exit 2 blocks the compaction, and stdout of an exit 0
        # becomes instructions for the summary (code.claude.com/docs/en/hooks). python3
        # itself exits 2 when the script is missing, so the command must not pass that on.
        self.install("--tools", "claude")
        groups = json.loads((self.home / ".claude/settings.json").read_text())["hooks"]["PreCompact"]
        (group,) = groups
        self.assertNotIn("matcher", group, "manual and automatic compactions both")
        (handler,) = group["hooks"]
        self.assertEqual(handler["type"], "command")
        self.assertLessEqual(handler["timeout"], 10)
        payload = {"hook_event_name": "PreCompact", "trigger": "auto", "custom_instructions": None,
                   "cwd": str(self.home)}
        installed = self.run_hook(handler["command"], payload)
        self.assertEqual(installed.returncode, 0, installed)
        self.assertIn("Review: pending", installed.stdout)
        (self.home / ".agents/hooks/compact_brief.py").unlink()
        missing = self.run_hook(handler["command"], payload)
        self.assertEqual(missing.returncode, 0, missing)

    def test_copilot_files_follow_copilot_home(self):
        # Copilot CLI's configuration directory reference: COPILOT_HOME replaces the whole
        # ~/.copilot path (copilot-instructions.md, agents/, hooks/); user hook files are
        # *.json in $COPILOT_HOME/hooks/ when it is set (hooks configuration reference).
        (self.home / ".copilot").rmdir()
        custom = self.home / "config" / "copilot"
        custom.mkdir(parents=True)
        out = self.install(env={"COPILOT_HOME": str(custom)})
        self.assertIn("copilot", out.splitlines()[0], "an existing COPILOT_HOME means Copilot CLI is here")
        self.assertEqual(json.loads((custom / "hooks/agents-global.json").read_text())["version"], 1)
        self.assertEqual(os.readlink(custom / "copilot-instructions.md"), str(self.home / ".agents/AGENTS.md"))
        for name in AGENTS:
            self.assertTrue((custom / "agents" / f"{name}.agent.md").is_file(), name)
        self.assertFalse((self.home / ".copilot").exists())
        (custom / "agents/old.agent.md").write_text("")
        audit = self.install("--audit", env={"COPILOT_HOME": str(custom)})
        self.assertIn(str(custom / "agents/old.agent.md"), audit)
        self.assertIn("0 change(s).", self.install(env={"COPILOT_HOME": str(custom)}).splitlines())

    def test_relative_copilot_home_is_refused(self):
        # Copilot CLI would read a relative path from wherever it starts; the installer
        # would write it under its own working folder. Neither is the folder meant.
        result = self.run_install("--tools", "copilot", env={"COPILOT_HOME": "rel/copilot"}, cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / "rel").exists())
        self.assertIn("COPILOT_HOME", result.stdout)

    def test_empty_copilot_home_means_the_default(self):
        self.install("--tools", "copilot", env={"COPILOT_HOME": ""})
        self.assertTrue((self.home / ".copilot/hooks/agents-global.json").is_file())

    def assert_hook_group(self, group: dict, script: str, tool: str, matching, other, timeout_range):
        """One matcher group with one command handler, as Codex and Gemini CLI document it."""
        for name in matching:  # the matcher is a regex on the tool name
            self.assertTrue(re.search(group["matcher"], name), (script, name))
        for name in other:
            self.assertFalse(re.search(group["matcher"], name), (script, name))
        (handler,) = group["hooks"]
        self.assertEqual(handler["type"], "command")
        self.assertEqual(handler["command"], f'python3 "$HOME/.agents/hooks/{script}" --tool {tool}')
        self.assertIn(handler["timeout"], timeout_range)

    def test_codex_hooks_follow_the_documented_format(self):
        # Codex hooks docs: ~/.codex/hooks.json holds a hooks object keyed by event; the
        # matcher is a regex on the tool name (shell commands match as Bash, file edits as
        # apply_patch, Edit or Write); timeout is in seconds.
        self.install("--tools", "codex")
        hooks = json.loads((self.home / ".codex/hooks.json").read_text())["hooks"]
        self.assertEqual(sorted(hooks), ["PostToolUse", "PreToolUse", "SessionStart", "Stop"])
        (pre,), (post,) = hooks["PreToolUse"], hooks["PostToolUse"]
        self.assert_hook_group(pre, "guard_bash.py", "codex", ["Bash"], ["apply_patch", "Edit", "Write"],
                               range(1, 601))
        self.assert_hook_group(post, "after_edit.py", "codex", ["apply_patch", "Edit", "Write"], ["Bash"],
                               range(1, 601))

    def assert_stop_check(self, groups: list, payload: dict, scripts=("progress_check.py",)):
        """One Stop group without a matcher whose commands, one per script, never keep the
        agent going on their own failure: exit 2 from a Stop hook continues the turn, and
        python3 exits 2 when the script is missing, so each command ends in || true."""
        (group,) = groups
        self.assertNotIn("matcher", group)
        self.assertEqual([handler["command"] for handler in group["hooks"]],
                         [f'python3 "$HOME/.agents/hooks/{script}" || true' for script in scripts])
        for handler, script in zip(group["hooks"], scripts):
            with self.subTest(script=script):
                self.assertEqual(handler["type"], "command")
                self.assertLessEqual(handler["timeout"], 10)
                self.assertNotIn("onFailure", handler)
                installed = self.run_hook(handler["command"], payload)
                self.assertEqual((installed.returncode, installed.stdout, installed.stderr), (0, "", ""))
                (self.home / ".agents/hooks" / script).unlink()
                missing = self.run_hook(handler["command"], payload)
                self.assertEqual((missing.returncode, missing.stdout), (0, ""))

    def test_claude_checks_the_progress_log_and_a_test_claim_before_a_stop(self):
        # Claude Code's Stop: no matcher; input transcript_path, stop_hook_active,
        # last_assistant_message. The claim check reads the transcript, whose shape only
        # Claude Code's is known; Codex calls its own format not a stable interface.
        self.install("--tools", "claude")
        hooks = json.loads((self.home / ".claude/settings.json").read_text())["hooks"]
        self.assert_stop_check(hooks["Stop"], {"session_id": "s", "transcript_path": str(self.home / "t.jsonl"),
                                               "cwd": str(self.home), "hook_event_name": "Stop",
                                               "stop_hook_active": False, "last_assistant_message": "Tests pass."},
                               scripts=("progress_check.py", "claim_check.py"))

    def test_claude_points_repeated_bash_failures_to_a_change_of_approach(self):
        # Claude Code's PostToolUseFailure: matcher on the tool name; input session_id,
        # tool_name, tool_input, error, is_interrupt; additionalContext reaches Claude.
        self.install("--tools", "claude")
        (group,) = json.loads((self.home / ".claude/settings.json").read_text())["hooks"]["PostToolUseFailure"]
        self.assertTrue(re.fullmatch(group["matcher"], "Bash"))
        for name in ("Edit", "Write", "Read"):
            self.assertFalse(re.fullmatch(group["matcher"], name), name)
        (handler,) = group["hooks"]
        self.assertEqual(handler["command"], 'python3 "$HOME/.agents/hooks/repeated_failure.py" || true')
        self.assertLessEqual(handler["timeout"], 10)
        temp = self.home / "tmp"
        temp.mkdir()
        payload = {"session_id": "s", "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                   "tool_input": {"command": "make"}, "error": "Exit code 2\nmake: *** no rule", "is_interrupt": False}
        results = [subprocess.run(["sh", "-c", handler["command"]], input=json.dumps(payload), capture_output=True,
                                  text=True, check=False, env={**os.environ, "HOME": str(self.home),
                                                               "PATH": "/usr/bin:/bin", "TMPDIR": str(temp)})
                   for _ in range(3)]
        self.assertEqual([(r.returncode, r.stdout) for r in results[:2]], [(0, ""), (0, "")])
        self.assertIn("systematic-debugging",
                      json.loads(results[2].stdout)["hookSpecificOutput"]["additionalContext"])
        (self.home / ".agents/hooks/repeated_failure.py").unlink()
        missing = self.run_hook(handler["command"], payload)
        self.assertEqual((missing.returncode, missing.stdout), (0, ""))

    def test_codex_checks_the_progress_log_before_a_stop(self):
        # Codex hooks docs: Stop ignores matcher; input turn_id, stop_hook_active,
        # last_assistant_message; JSON on stdout with exit 0, and no output lets it stop.
        self.install("--tools", "codex")
        hooks = json.loads((self.home / ".codex/hooks.json").read_text())["hooks"]
        self.assert_stop_check(hooks["Stop"], {"session_id": "s", "turn_id": "t", "cwd": str(self.home),
                                               "hook_event_name": "Stop", "model": "m", "permission_mode": "default",
                                               "stop_hook_active": False, "last_assistant_message": None})

    def test_codex_refreshes_the_session_after_a_compaction_or_a_resume(self):
        # Codex hooks docs: the SessionStart matcher filters the source (startup, resume, clear,
        # compact, fork); after a compaction the hook runs before the next model request, and
        # plain text on stdout is added as developer context. Input: session_id,
        # transcript_path, cwd, hook_event_name, model, source.
        self.install("--tools", "codex")
        (start,) = json.loads((self.home / ".codex/hooks.json").read_text())["hooks"]["SessionStart"]
        for source in ("compact", "resume"):
            self.assertTrue(re.search(start["matcher"], source), source)
        for source in ("startup", "clear", "fork"):
            self.assertFalse(re.search(start["matcher"], source), source)
        (handler,) = start["hooks"]
        self.assertEqual(handler["type"], "command")
        self.assertEqual(handler["command"], 'python3 "$HOME/.agents/hooks/session_refresh.py"')
        self.assertIn(handler["timeout"], range(1, 601))
        payload = {"session_id": "s", "transcript_path": None, "cwd": str(self.home),
                   "hook_event_name": "SessionStart", "model": "m", "source": "compact"}
        result = self.run_hook(handler["command"], payload)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertTrue(result.stdout.startswith("Session restarted from compact."), result.stdout)

    def codex_rules(self) -> list:
        """The fields of each prefix_rule() call in the installed rules file, read as the
        Starlark it is (for these calls, Python syntax)."""
        tree = ast.parse((self.home / ".codex/rules/dotagents.rules").read_text())
        rules = []
        for node in tree.body:
            self.assertIsInstance(node, ast.Expr)
            self.assertEqual(node.value.func.id, "prefix_rule")
            self.assertEqual(node.value.args, [])
            rules.append({k.arg: ast.literal_eval(k.value) for k in node.value.keywords})
        return rules

    def test_codex_rules_forbid_every_push_and_publish(self):
        # Codex rules docs (learn.chatgpt.com/docs/agent-configuration/rules, experimental):
        # Codex loads every .rules file in ~/.codex/rules/ at startup; prefix_rule() takes a
        # pattern (literals, or a list of alternatives at one position), a decision
        # (forbidden blocks without prompting) and a justification. Codex writes
        # default.rules itself, so ours has its own name and default.rules is left alone.
        default = self.home / ".codex/rules/default.rules"
        default.parent.mkdir(parents=True)
        default.write_text('prefix_rule(pattern = ["gh", "pr", "view"], decision = "prompt")\n')
        self.install("--tools", "codex")
        self.assertEqual(default.read_text(), 'prefix_rule(pattern = ["gh", "pr", "view"], decision = "prompt")\n')
        forbidden, token_rules = set(), set()
        for fields in self.codex_rules():
            self.assertEqual(set(fields), {"pattern", "decision", "justification"})
            self.assertEqual(fields["decision"], "forbidden")
            prefixes = [[]]
            for part in fields["pattern"]:
                prefixes = [p + [word] for p in prefixes for word in (part if isinstance(part, list) else [part])]
            forbidden |= {" ".join(p) for p in prefixes}
            # A rule says why and what to do instead: a token stays out of the session, the
            # rest is the maintainer's to publish.
            if "prints the authentication token" in fields["justification"]:
                self.assertIn("ask the user to run any command that needs the token", fields["justification"])
                self.assertNotIn("maintainer", fields["justification"])
                token_rules |= {" ".join(p) for p in prefixes}
            else:
                self.assertIn("maintainer", fields["justification"])
        self.assertEqual(token_rules, {"gh auth token", "gh auth git-credential", "gh config get oauth_token",
                                       *(f"gh auth status {flag}" for flag in
                                         ("-t", "--show-token", "-at", "-ta", "-t=true", "--show-token=true"))})
        self.assertEqual({p for p in forbidden if p.startswith("git ")},
                         {"git push", "git subtree push", "git send-pack", "git http-push", "git lfs push",
                          "git svn dcommit", "git p4 submit", "git send-email"})
        # gh: only read-only commands run. A prefix rule cannot allow some commands and
        # forbid the rest, so the rules forbid every other command of gh 2.100.0's tree,
        # aliases included (gh help, 25 Oct 2026); a command gh adds later is the guard's.
        def forbids(command):
            return any(command == prefix or command.startswith(prefix + " ") for prefix in forbidden)
        for command in ("gh pr create", "gh pr new", "gh pr merge 1", "gh pr comment 1", "gh pr ready 1",
                        "gh issue create", "gh issue new", "gh issue close 1", "gh release create v1",
                        "gh release upload v1 a", "gh release delete v1", "gh repo create x", "gh repo new x",
                        "gh repo sync", "gh repo fork", "gh repo autolink create", "gh gist create a", "gh gist new a",
                        "gh label clone o/r", "gh workflow run ci", "gh secret set X", "gh variable set X",
                        "gh config set editor vim", "gh auth login", "gh cs create", "gh codespace ports",
                        "gh ext install x", "gh run rerun 7", "gh attestation download a", "gh copilot",
                        "gh preview prompter", "gh auth token", "gh auth git-credential get", "gh auth status -t",
                        "gh auth status --show-token", "gh auth status -at", "gh config get oauth_token"):
            with self.subTest(command=command):
                self.assertTrue(forbids(command))
        # Read or local commands (the maintainer's decision on D-v) have no rule.
        for command in ("gh pr view 1", "gh pr list", "gh pr ls", "gh pr diff 1", "gh pr checks 1", "gh pr status",
                        "gh issue list", "gh issue view 1", "gh run view 1 --log", "gh repo view",
                        "gh repo clone o/r", "gh gist clone a", "gh repo license view mit", "gh repo autolink list",
                        "gh auth status", "gh auth status -a", "gh search issues x", "gh status", "gh browse -n",
                        "gh browse", "gh api repos/o/r", "gh --version", "gh cs list", "gh pr checkout 1",
                        "gh pr co 1", "gh run watch 7", "gh run download 7", "gh release download v1",
                        "gh config get editor", "gh variable get X", "gh repo read-file a", "gh repo read-dir a",
                        "gh ruleset check", "gh rs check", "gh attestation verify a", "gh at verify a",
                        "gh completion -s bash", "gh licenses"):
            with self.subTest(command=command):
                self.assertFalse(forbids(command))

    @unittest.skipUnless(shutil.which("codex"), "codex not installed")
    def test_codex_reads_the_rules_as_written(self):
        self.install("--tools", "codex")
        rules = self.home / ".codex/rules/dotagents.rules"
        env = {**os.environ, "HOME": str(self.home), "CODEX_HOME": str(self.home / ".codex")}
        cases = {("git", "push", "--force", "origin", "main"): "forbidden", ("gh", "pr", "new"): "forbidden",
                 ("gh", "repo", "sync"): "forbidden", ("gh", "pr", "comment", "7", "--body", "x"): "forbidden",
                 ("git", "send-email", "a.patch"): "forbidden", ("gh", "pr", "checkout", "7"): None,
                 ("gh", "release", "download", "v1"): None, ("gh", "auth", "token"): "forbidden",
                 ("gh", "auth", "status", "-t"): "forbidden", ("gh", "auth", "status"): None,
                 ("gh", "label", "clone", "o/r"): "forbidden", ("git", "status"): None,
                 ("gh", "pr", "view", "7"): None, ("gh", "issue", "list"): None,
                 ("gh", "run", "view", "7", "--log"): None, ("gh", "repo", "clone", "o/r"): None}
        for command, decision in cases.items():
            with self.subTest(command=command):
                result = subprocess.run(["codex", "execpolicy", "check", "--rules", str(rules), "--", *command],
                                        env=env, capture_output=True, text=True, timeout=60, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout).get("decision"), decision)

    def test_gemini_hooks_follow_the_documented_format(self):
        # Gemini CLI hooks reference: settings.json holds a hooks object keyed by event
        # (BeforeTool, AfterTool); the matcher is a regex on the tool name; timeout is in
        # milliseconds. Tool names: run_shell_command, write_file, replace.
        self.install("--tools", "gemini")
        hooks = json.loads((self.home / ".gemini/settings.json").read_text())["hooks"]
        self.assertEqual(sorted(hooks), ["AfterTool", "BeforeTool"])
        (before,), (after,) = hooks["BeforeTool"], hooks["AfterTool"]
        self.assert_hook_group(before, "guard_bash.py", "gemini", ["run_shell_command"],
                               ["write_file", "replace", "read_file"], range(1000, 600001))
        self.assert_hook_group(after, "after_edit.py", "gemini", ["write_file", "replace"],
                               ["run_shell_command", "read_file"], range(1000, 600001))

    def test_antigravity_hooks_follow_the_documented_format(self):
        # Antigravity hooks docs (antigravity.google/docs/hooks?tab=cli): the CLI reads global
        # hooks from ~/.gemini/config/hooks.json, an object that maps a hook name to its events
        # (an optional "enabled": false turns one off); PreToolUse and PostToolUse hold matcher
        # groups whose matcher is a regex on the tool name and whose handlers have type
        # "command", command and timeout in seconds. run_command runs shell commands;
        # write_to_file, replace_file_content and multi_replace_file_content edit files.
        config_file = self.home / ".gemini/config/hooks.json"
        config_file.parent.mkdir(parents=True)
        mine = {"my-linter-hook": {"PostToolUse": [{"matcher": "run_command", "hooks": [
            {"type": "command", "command": "./scripts/lint.sh", "timeout": 10}]}]}}
        config_file.write_text(json.dumps(mine))
        self.install("--tools", "antigravity")
        config = json.loads(config_file.read_text())
        self.assertEqual(config["my-linter-hook"], mine["my-linter-hook"])
        ours = [events for name, events in config.items() if name != "my-linter-hook"]
        self.assertEqual(len(ours), 2)
        self.assertEqual(sorted(event for events in ours for event in events), ["PostToolUse", "PreToolUse"])
        (pre,), (post,) = [group for events in ours for group in events.get("PreToolUse", [])], \
            [group for events in ours for group in events.get("PostToolUse", [])]
        edits = ["write_to_file", "replace_file_content", "multi_replace_file_content"]
        self.assert_hook_group(pre, "guard_bash.py", "antigravity", ["run_command"], edits + ["view_file"],
                               range(1, 601))
        self.assert_hook_group(post, "after_edit.py", "antigravity", edits, ["run_command", "view_file"],
                               range(1, 601))
        for name in edits:
            self.assertTrue(re.fullmatch(post["matcher"], name), name)
        # The documented PreToolUse input; the reply is a JSON decision.
        payload = {"toolCall": {"name": "run_command", "args": {"CommandLine": "git push origin main",
                                                                "Cwd": "/workspace/project",
                                                                "WaitMsBeforeAsync": 5000}},
                   "stepIdx": 19, "conversationId": "c", "workspacePaths": ["/workspace/project"]}
        blocked = self.run_hook(pre["hooks"][0]["command"], payload)
        self.assertEqual((blocked.returncode, json.loads(blocked.stdout)["decision"]), (0, "deny"))
        payload["toolCall"]["args"]["CommandLine"] = "npm test"
        allowed = self.run_hook(pre["hooks"][0]["command"], payload)
        self.assertEqual((allowed.returncode, json.loads(allowed.stdout)), (0, {"decision": "allow"}))
        # A hook turned off by hand stays off, and a second run changes nothing.
        names = [n for n in config if n != "my-linter-hook"]
        for name in names:
            config[name]["enabled"] = False
        config_file.write_text(json.dumps(config))
        self.install("--tools", "antigravity")
        for name in names:
            self.assertIs(json.loads(config_file.read_text())[name]["enabled"], False, name)
        self.assertIn("0 change(s).", self.install("--tools", "antigravity").splitlines())

    def test_antigravity_reads_the_global_rules_and_the_skills(self):
        # Antigravity docs: the CLI reads global rules from ~/.gemini/GEMINI.md (rules,
        # gcli-migration), and a personal manifest ~/.gemini/config/skills.json adds the skill
        # folders listed in entries[].path, absolute because ~ is not expanded (customization
        # discovery).
        manifest = self.home / ".gemini/config/skills.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"entries": [{"path": "/home/developer/team-config/skills"}],
                                        "exclude": ["load-test"]}))
        self.install("--tools", "antigravity")
        self.assertEqual(os.readlink(self.home / ".gemini/GEMINI.md"), str(self.home / ".agents/AGENTS.md"))
        data = json.loads(manifest.read_text())
        self.assertEqual(data, {"entries": [{"path": "/home/developer/team-config/skills"},
                                            {"path": str(self.home / ".agents/skills")}],
                                "exclude": ["load-test"]})
        for name in PACK_SKILLS + ONLINE_SKILLS:
            self.assertTrue((self.home / ".agents/skills" / name / "SKILL.md").is_file(), name)
        self.assertFalse((self.home / ".gemini/skills").exists(), "Gemini CLI reads that folder too")

    def test_antigravity_is_detected_by_its_folder(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home)
        (home / ".gemini/antigravity-cli").mkdir(parents=True)
        with mock.patch.object(install.shutil, "which", return_value=None):
            self.assertIn("antigravity", install.detect(home))
            (home / ".gemini/antigravity-cli").rmdir()
            self.assertNotIn("antigravity", install.detect(home))

    def test_gemini_subagents_outlast_the_default_limits(self):
        # Gemini CLI stops a subagent at max_turns (default 30) and timeout_mins (default 10),
        # positive integers in a strict frontmatter schema that rejects unknown fields
        # (google-gemini/gemini-cli docs/core/subagents.md, packages/core/src/agents/agentLoader.ts).
        self.install("--tools", "gemini")
        schema = {"kind", "name", "description", "display_name", "tools", "mcp_servers", "model",
                  "temperature", "max_turns", "timeout_mins"}
        minutes = {}
        for name in AGENTS:
            with self.subTest(agent=name):
                text = (self.home / ".gemini/agents" / f"{name}.md").read_text()
                head = text[len("---\n"):].split("\n---\n", 1)[0]
                fields = dict(line.split(":", 1) for line in head.splitlines() if not line.startswith(" "))
                self.assertLessEqual(set(fields), schema)
                self.assertIn("max_turns", fields)
                self.assertIn("timeout_mins", fields)
                self.assertRegex(fields["max_turns"], r"^ [1-9][0-9]*$")
                self.assertRegex(fields["timeout_mins"], r"^ [1-9][0-9]*$")
                self.assertGreater(int(fields["max_turns"]), 30)
                self.assertGreater(int(fields["timeout_mins"]), 10)
                minutes[name] = int(fields["timeout_mins"])
        self.assertIn("gate-runner", minutes)
        self.assertEqual(sorted(minutes, key=minutes.get)[-1], "gate-runner")
        self.assertEqual(list(minutes.values()).count(minutes["gate-runner"]), 1, "gate-runner runs longest")

    def source_agents(self) -> dict:
        return {name: install.parse_agent((ROOT / "home/.agents/agents" / f"{name}.md").read_text())[0]
                for name in AGENTS}

    @staticmethod
    def frontmatter_keys(text: str) -> set:
        head = text[len("---\n"):].split("\n---\n", 1)[0]
        return {line.split(":", 1)[0] for line in head.splitlines() if line and not line.startswith(" ")}

    def test_effort_reaches_codex_and_no_other_generated_copy(self):
        # Claude Code reads effort from the agent file (code.claude.com/docs/en/sub-agents);
        # Codex's custom agents take model_reasoning_effort; Gemini CLI's strict schema and
        # Copilot CLI's agent profiles have no such field. gate-runner only runs commands
        # and reports, so it runs at low effort.
        self.install("--tools", "claude,codex,gemini,copilot")
        source = self.source_agents()
        self.assertEqual(source["gate-runner"].get("effort"), "low")
        for name, meta in source.items():
            with self.subTest(agent=name):
                self.assertEqual(self.frontmatter_keys((self.home / ".claude/agents" / f"{name}.md").read_text())
                                 >= {"effort"}, "effort" in meta)
                codex = (self.home / ".codex/agents" / f"{name}.toml").read_text()
                if tomllib:
                    self.assertEqual(tomllib.loads(codex).get("model_reasoning_effort"), meta.get("effort"))
                for copy in (self.home / ".gemini/agents" / f"{name}.md", self.home / ".copilot/agents" / f"{name}.agent.md"):
                    self.assertNotIn("effort", self.frontmatter_keys(copy.read_text()), copy)

    def test_turn_limits_have_one_source(self):
        # Claude Code stops a subagent at maxTurns and returns its output marked partial,
        # which Claude can resume (code.claude.com/docs/en/sub-agents, v2.1.246 or later).
        # Gemini CLI's max_turns comes from the same field; Codex custom agents and Copilot
        # CLI agent profiles have no turn limit field, so their copies carry none.
        self.install("--tools", "claude,codex,gemini,copilot")
        for name, meta in self.source_agents().items():
            with self.subTest(agent=name):
                self.assertRegex(meta.get("maxTurns", ""), r"^[1-9][0-9]*$")
                claude = (self.home / ".claude/agents" / f"{name}.md").read_text()
                self.assertIn(f"\nmaxTurns: {meta['maxTurns']}\n", claude)
                gemini = (self.home / ".gemini/agents" / f"{name}.md").read_text()
                self.assertIn(f"\nmax_turns: {meta['maxTurns']}\n", gemini)
                self.assertNotIn("maxTurns", gemini)
                codex = (self.home / ".codex/agents" / f"{name}.toml").read_text()
                keys = re.findall(r"^(\w+) = ", codex, re.M)
                self.assertIn("developer_instructions", keys)
                self.assertEqual([key for key in keys if "turn" in key.lower()], [])
                copilot = (self.home / ".copilot/agents" / f"{name}.agent.md").read_text()
                self.assertNotIn("maxTurns", self.frontmatter_keys(copilot))

    @staticmethod
    def glob_regex(pattern: str) -> list:
        """Regexes for a path glob as Claude Code's rules read it: braces expand, ** spans
        folders (none too), * and ? stay inside one name."""
        match = re.search(r"\{([^{}]*)\}", pattern)
        if match:
            return [r for option in match.group(1).split(",")
                    for r in Install.glob_regex(pattern[:match.start()] + option + pattern[match.end():])]
        out, i = "", 0
        while i < len(pattern):
            if pattern.startswith("**/", i):
                out, i = out + "(?:.*/)?", i + 3
            elif pattern.startswith("**", i):
                out, i = out + ".*", i + 2
            elif pattern[i] == "*":
                out, i = out + "[^/]*", i + 1
            elif pattern[i] == "?":
                out, i = out + "[^/]", i + 1
            else:
                out, i = out + re.escape(pattern[i]), i + 1
        return [out]

    def test_claude_path_rules_load_the_matching_skill(self):
        # Claude Code loads ~/.claude/rules/*.md with a paths list of globs, relative to the
        # session's primary working directory, only when it works with a matching file;
        # paths is the only field it reads (code.claude.com/docs/en/memory).
        rules = self.home / ".claude/rules"
        rules.mkdir()
        mine = rules / "my-rule.md"
        mine.write_text("Mine.\n")
        (rules / "dotagents-qt-quick.md").write_text("edited by hand\n")
        (rules / "dotagents-retired-skill.md").write_text("an old rule of ours\n")
        source = json.loads((ROOT / "home/.agents/path-rules.json").read_text())["rules"]
        self.install("--tools", "claude")
        self.assertEqual(mine.read_text(), "Mine.\n")
        self.assertFalse((rules / "dotagents-retired-skill.md").exists())
        backups = {p.name: p.read_text() for p in (self.home / ".agents-backup").rglob("dotagents-*.md")}
        self.assertEqual(backups, {"dotagents-qt-quick.md": "edited by hand\n",
                                   "dotagents-retired-skill.md": "an old rule of ours\n"})
        self.assertEqual(sorted(p.name for p in rules.iterdir()),
                         sorted(["my-rule.md"] + [f"dotagents-{skill}.md" for skill in source]))
        for skill, globs in source.items():
            with self.subTest(skill=skill):
                text = (rules / f"dotagents-{skill}.md").read_text()
                head, body = text[len("---\n"):].split("\n---\n", 1)
                self.assertEqual(head.splitlines()[0], "paths:")
                self.assertEqual([json.loads(line[len("  - "):]) for line in head.splitlines()[1:]], globs)
                self.assertEqual(body.strip(), f"Use the {skill} skill for work on these files. If it is not in "
                                               f"your skill list, read ~/.agents/skills/{skill}/SKILL.md and follow it.")
        # Which skill each kind of file calls for.
        expected = {"src/ui/Main.qml": "qt-quick", "imports/App/qmldir": "qt-quick",
                    "docs/diagrams/flow.puml": "plantuml-diagrams", "a.plantuml": "plantuml-diagrams",
                    "docs/palette.iuml": "plantuml-diagrams", "test_cli.py": "trustworthy-tests",
                    "pkg/io_test.py": "trustworthy-tests", "tests/data/input.json": "trustworthy-tests",
                    "src/net/socket_test.cpp": "trustworthy-tests", "tests/tst_model.cpp": "trustworthy-tests",
                    "cmd/app/main_test.go": "trustworthy-tests", "web/a.test.ts": "trustworthy-tests",
                    "web/b.spec.ts": "trustworthy-tests", "web/__tests__/c.jsx": "trustworthy-tests",
                    "src/main.py": None, "README.md": None, "src/ui/Main.cpp": None, "web/testing.ts": None}
        for path, skill in expected.items():
            with self.subTest(path=path):
                found = sorted(s for s, globs in source.items()
                               if any(re.fullmatch(r, path) for g in globs for r in self.glob_regex(g)))
                self.assertEqual(found, [skill] if skill else [])
        self.assertIn(str(mine), self.install("--audit"))
        self.assertIn("0 change(s).", self.install("--tools", "claude").splitlines())
        self.install("--tools", "codex")
        self.assertEqual(sorted(p.name for p in rules.iterdir()),
                         sorted(["my-rule.md"] + [f"dotagents-{skill}.md" for skill in source]))

    def test_replaced_files_are_backed_up(self):
        claude_md = self.home / ".claude/CLAUDE.md"
        claude_md.write_text("my old notes\n")
        out = self.install()
        backups = list((self.home / ".agents-backup").rglob("CLAUDE.md"))
        self.assertEqual([b.read_text() for b in backups], ["my old notes\n"])
        self.assertIn(f"- Claude Code: replaced {claude_md}, which did not import ~/.agents/AGENTS.md; "
                      f"the old one is in {backups[0]}.", out.splitlines())

    def test_claude_md_sends_edits_to_the_repository(self):
        claude_md = self.home / ".claude/CLAUDE.md"
        old_generated = ("@~/.agents/AGENTS.md\n\n<!-- Global instructions live in ~/.agents/AGENTS.md, "
                         "shared by every coding agent. Edit them there. -->\n")
        claude_md.write_text(old_generated)
        out = self.install("--tools", "claude")
        text = claude_md.read_text()
        self.assertTrue(text.startswith("@~/.agents/AGENTS.md\n"))
        self.assertIn("home/.agents/AGENTS.md", text)
        self.assertNotIn("Edit them there", text)
        self.assertNotIn("did not import", out)

    def test_skill_overrides_note_needs_merged_settings(self):
        (self.home / ".claude/settings.json").write_text("{not json")
        out = self.install("--tools", "claude")
        self.assertIn("Could not parse", out)
        self.assertNotIn("skillOverrides", out)


if __name__ == "__main__":
    unittest.main()
