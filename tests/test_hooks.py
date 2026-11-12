# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for the shared hooks, fed with each agent's payload shape."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "home" / ".agents" / "hooks"
EM, EN = "\u2014", "\u2013"
DEEP_JSON = "[" * 100000


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
        "git commit -anm x",
        "git commit -vn",
        "git commit -m x -n",
        "git commit --amend -n",
        "NEXENNE_SKIP_HOOK=1 git push",
        "cd a && NEXENNE_SKIP_HOOK=1 git commit -m x",
        "export NEXENNE_SKIP_HOOK=1; git commit -m x",
        "HUSKY=0 git commit -m x",
        "SKIP=clang-format git commit -m x",
        "export SKIP=clang-format; git commit -m x",
        "SKIP=clang-format pre-commit run --all-files",
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

    def assert_blocked(self, commands, tool: str = "claude"):
        for command in commands:
            with self.subTest(command=command, tool=tool):
                result = run("guard_bash.py", bash(command), tool)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Blocked:", result.stderr)

    def assert_allowed(self, commands, tool: str = "claude"):
        for command in commands:
            with self.subTest(command=command, tool=tool):
                result = run("guard_bash.py", bash(command), tool)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")

    def test_blocks_gate_bypass_and_history_rewrite(self):
        self.assert_blocked(self.BLOCKED)

    def test_allows_ordinary_commands(self):
        self.assert_allowed(self.ALLOWED)

    def test_newline_separates_commands(self):
        self.assert_blocked([
            "cd repo\ngit commit --no-verify -m x",
            "git fetch\ngit push -f origin feat",
            "cd repo\nHUSKY=0 git commit -m x",
            "git add -A\ngit commit --no-verify -m x",
            "git push \\\n  --force origin main",
        ])
        # A newline inside quotes stays in the message.
        self.assert_allowed(['git commit -m "fix: x\n\nKeep the -n flag\nand --no-verify docs"'])

    def test_merged_punctuation_is_an_operator(self):
        self.assert_blocked([
            "(cd a);git push -f",
            "(cd a)&&git push -f",
            "git status;(git push -f)",
            "true&&git push -f",
            "(cd a && git push -f)",
            "git push origin main 2>&1 --force",
            "git push -f&>/dev/null",
            "echo $(git push -f)",
        ])

    def test_unparsable_command_is_checked_cautiously(self):
        self.assert_blocked([
            "git commit --no-verify -m x # skip hooks, they're slow",
            "git push -f origin main  # don't worry, it's my branch",
            "git push -f; echo $'don\\'t'",
            "cat <<'X' > a.txt\nit's\nX\ngit push -f",
            'git push -f origin main; echo "unterminated',
            "git commit -m x ` -n 'unterminated",
            "echo $(git push -f; echo 'unterminated",
        ])
        self.assert_allowed([
            "git commit -m 'unbalanced",
            'echo "it\'s',
            "ls # it's fine",
        ])

    def test_git_after_keywords_and_wrappers(self):
        self.assert_blocked([
            "for r in a; do git push -f; done",
            "if true; then git push -f; fi",
            "while true; do git commit -n -m x; done",
            "{ git push -f; }",
            "! git push -f",
            "sudo git push -f",
            "sudo -u me git push -f",
            "sudo HUSKY=0 git commit -m x",
            "command git push -f",
            "time git push -f",
            "time -p git push -f",
            "nice git push -f",
            "nice -n 5 git push -f",
            "env -i git push -f",
            "env -u FOO git push -f",
            "env - HUSKY=0 git commit -m x",
            "/usr/bin/env HUSKY=0 git commit -m x",
            "xargs git push -f",
            "echo b | xargs -I {} git push -f origin {}",
            "exec git push -f",
            "nohup git push -f",
            "timeout 60 git push -f",
        ])

    def test_no_verify_prefixes_on_hook_subcommands(self):
        self.assert_blocked([
            "git commit --no-verif -m x",
            "git commit --no-veri -m x",
            "git am --no-v a.patch",
            "git am -n a.patch",
            "git push --no-veri origin x",
            "git merge --no-verify x",
            "git rebase --no-verify main",
            "git pull --no-verify",
            "git cherry-pick --no-verify x",
        ])
        # Option values and subcommands that run no hooks are not flags to block.
        self.assert_allowed([
            "git grep -- --no-verify",
            "git grep -e --no-verify",
            "git log --grep=--no-verify",
            "git commit -minit",
            "git commit -uno -m x",
            "git commit -sm x",
            "git commit --amend --no-edit",
            "SKIP=1 pytest",
            "SKIP=slow make test",
        ])

    def test_heredoc_body_is_not_a_command(self):
        self.assert_allowed([
            "cat > notes.md <<'X'\nNever run: true && git push -f\nX",
            "cat > guide.md <<'X'\nRun: cd repo && git push -f only with approval\nX",
            "cat <<-X > a.md\n\tgit commit --no-verify\n\tX\necho done",
            "git commit -F - <<'X'\nAdd the -n flag to the CLI\nX",
            "git commit -F - <<'X'\ndocs: never use --no-verify\nX",
            "git commit -F- <<'X'\nfix(x): handle -n flag\nX",
            "git commit -m \"$(cat <<'EOF'\nfix: x\n\nNever run git push -f; it's \"banned\".\nEOF\n)\"",
            "cat <<'X'\n$(git push -f) and `git push -f`\nX",
        ])
        # The shell runs the substitutions in the body of an unquoted delimiter.
        self.assert_blocked([
            "cat <<X\n$(git push -f)\nX",
            "cat <<X\nsee `git push -f`\nX",
        ])

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

    def test_deeply_nested_json_never_blocks(self):
        for payload in (DEEP_JSON, {"toolArgs": DEEP_JSON}):
            with self.subTest(payload=str(payload)[:20]):
                result = run("guard_bash.py", payload, "gemini")
                self.assertEqual((result.returncode, result.stdout.strip()), (0, "{}"))


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

    def committed_repo(self) -> tuple[Path, dict]:
        # An empty global config keeps the user's git settings out of the test; status.branch
        # is a setting some users have, and its "## branch" line is not a change.
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
               "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", "-b", "work", str(repo)], check=True, env=env)
        subprocess.run([*git, "config", "status.branch", "true"], check=True, env=env)
        (repo / "tracked.txt").write_text("one\n")
        subprocess.run([*git, "add", "tracked.txt"], check=True, env=env)
        subprocess.run([*git, "commit", "-q", "-m", "init"], check=True, env=env)
        return repo, env

    def refresh(self, repo: Path, env: dict) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(HOOKS / "session_refresh.py")],
                              input=json.dumps({"cwd": str(repo), "source": "resume"}),
                              capture_output=True, text=True, check=False, env=env)

    def test_status_keeps_the_index_column(self):
        # " M" (changed, not staged) must not lose its space and read as "M " (staged).
        repo, env = self.committed_repo()
        (repo / "tracked.txt").write_text("two\n")
        result = self.refresh(repo, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Uncommitted changes:\n M tracked.txt\n", result.stdout)

    def test_clean_tree_reports_no_changes(self):
        repo, env = self.committed_repo()
        result = self.refresh(repo, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Last commits:", result.stdout)
        self.assertNotIn("Uncommitted changes", result.stdout)

    def test_slow_git_stays_within_hook_timeout(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        fake = tmp / "git"
        fake.write_text('#!/bin/sh\nsleep 4\n[ "$1" = branch ] && echo work\nexit 0\n')
        fake.chmod(0o755)
        env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
        start = time.monotonic()
        result = subprocess.run([sys.executable, str(HOOKS / "session_refresh.py")],
                                input=json.dumps({"cwd": str(tmp), "source": "resume"}),
                                capture_output=True, text=True, check=False, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - start, 9.5)
        self.assertIn("Session restarted from resume", result.stdout)
        self.assertIn("Current branch: work", result.stdout)
        self.assertIn("Uncommitted changes not shown", result.stdout)
        self.assertIn("Last commits not shown", result.stdout)


if __name__ == "__main__":
    unittest.main()
