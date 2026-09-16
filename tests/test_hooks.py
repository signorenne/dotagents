# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for the shared hooks, fed with each agent's payload shape."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "home" / ".agents" / "hooks"
EM, EN = "\u2014", "\u2013"


def run(script: str, payload, tool: str = "claude") -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOKS / script), "--tool", tool],
                          input=data, capture_output=True, text=True, check=False)


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class GuardBash(unittest.TestCase):
    BLOCKED = [
        "git commit -m 'feat(x): y' --no-verify",
        "git commit -n -m x",
        "git commit -nm x",
        "NEXENNE_SKIP_HOOK=1 git push",
        "cd a && NEXENNE_SKIP_HOOK=1 git commit -m x",
        "export NEXENNE_SKIP_HOOK=1; git commit -m x",
        "HUSKY=0 git commit -m x",
        "SKIP=clang-format git commit -m x",
        "git push --force origin main",
        "git push -f",
        "git push origin +main",
        "git push --force-with-lease",
        "git push origin main -f",
        "git -C . push -uf origin x",
        "git config --unset core.hooksPath",
        "git -c core.hooksPath=/dev/null commit -m x",
        "git push --no-verify origin x",
        "/usr/bin/git commit --no-verify -m x",
    ]
    ALLOWED = [
        "git commit -m 'feat(cli): add -n flag'",
        'git commit -m "docs(x): explain --no-verify"',
        "git commit -m x",
        "git push origin feat/x",
        "git push -u origin feat/x",
        "NEXENNE_SKIP_HOOK=0 git commit -m x",
        "grep -rn no-verify docs",
        "git log --oneline -n 5",
        "cmake --build --preset ci --target nexenne_tests",
        "git config core.hooksPath .githooks",
        "curl --no-verify-ssl x",
        "git commit -m 'unbalanced",
        "git diff --stat | head -n 5",
        "git commit -F msg.txt -a",
    ]

    def test_blocks_gate_bypass_and_history_rewrite(self):
        for command in self.BLOCKED:
            with self.subTest(command=command):
                result = run("guard_bash.py", bash(command))
                self.assertEqual(result.returncode, 2)
                self.assertIn("Blocked:", result.stderr)

    def test_allows_ordinary_commands(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(run("guard_bash.py", bash(command)).returncode, 0)

    def test_payload_shapes_of_each_agent(self):
        bad = "git push --force"
        shapes = {
            "codex": bash(bad),
            "gemini": {"tool_name": "run_shell_command", "tool_input": {"command": bad}},
            "copilot": {"toolName": "bash", "toolArgs": json.dumps({"command": bad})},
            "cursor": {"command": bad, "cwd": "/tmp"},
        }
        for tool, payload in shapes.items():
            with self.subTest(tool=tool):
                self.assertEqual(run("guard_bash.py", payload, tool).returncode, 2)

    def test_gemini_needs_json_on_success(self):
        result = run("guard_bash.py", bash("ls"), "gemini")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "{}"))

    def test_unreadable_input_never_blocks(self):
        self.assertEqual(run("guard_bash.py", "not json").returncode, 0)
        self.assertEqual(run("guard_bash.py", "not json", "gemini").stdout.strip(), "{}")


class AfterEdit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".git").mkdir()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_flags_dashes_only_in_new_text(self):
        target = str(self.tmp / "notes.md")
        cases = [
            ("claude", {"tool_name": "Edit", "tool_input": {"file_path": target, "old_string": "a", "new_string": f"a {EM} b"}}),
            ("claude", {"tool_name": "Write", "tool_input": {"file_path": target, "content": f"1{EN}2"}}),
            ("gemini", {"tool_name": "replace", "tool_input": {"file_path": target, "new_string": f"x {EM} y"}}),
            ("copilot", {"tool_name": "Write", "tool_input": {"path": target, "file_text": f"a {EN} b"}}),
            ("cursor", {"file_path": target, "edits": [{"old_string": "a", "new_string": f"q {EM} r"}]}),
        ]
        for tool, payload in cases:
            with self.subTest(tool=tool):
                result = run("after_edit.py", payload, tool)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Em/en dash", result.stderr)

    def test_clean_text_passes(self):
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(self.tmp / "a.md"), "new_string": "plain - hyphen"}}
        result = run("after_edit.py", payload)
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual(run("after_edit.py", payload, "gemini").stdout.strip(), "{}")

    def test_codex_patch_is_parsed(self):
        patch = f"*** Begin Patch\n*** Update File: b.md\n@@\n-old\n+new {EM} text\n*** End Patch\n"
        payload = {"tool_name": "apply_patch", "cwd": str(self.tmp), "tool_input": {"command": patch}}
        result = run("after_edit.py", payload, "codex")
        self.assertEqual(result.returncode, 2)
        self.assertIn("b.md", result.stderr)

    @unittest.skipUnless(shutil.which("clang-format"), "clang-format not installed")
    def test_formats_cpp_when_project_has_clang_format(self):
        (self.tmp / ".clang-format").write_text("BasedOnStyle: LLVM\n")
        source = self.tmp / "a.cpp"
        source.write_text("int   f( ){return 1;}\n")
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(source), "content": source.read_text()}}
        result = run("after_edit.py", payload)
        self.assertEqual(result.returncode, 0)
        self.assertIn("reformatted", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(source.read_text(), "int f() { return 1; }\n")

    def test_leaves_cpp_alone_without_clang_format_config(self):
        source = self.tmp / "b.cpp"
        source.write_text("int   g( ){return 0;}\n")
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(source), "content": "x"}}
        self.assertEqual(run("after_edit.py", payload).returncode, 0)
        self.assertEqual(source.read_text(), "int   g( ){return 0;}\n")


class SessionRefresh(unittest.TestCase):
    def test_prints_reminder_and_git_state(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo)
        subprocess.run(["git", "init", "-q", "-b", "work", str(repo)], check=True)
        result = subprocess.run([sys.executable, str(HOOKS / "session_refresh.py")],
                                input=json.dumps({"cwd": str(repo), "source": "compact"}),
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Session restarted from compact", result.stdout)
        self.assertIn("Current branch: work", result.stdout)


if __name__ == "__main__":
    unittest.main()
