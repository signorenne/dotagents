# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for the shared hooks, fed with each agent's payload shape."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HOOKS = Path(__file__).resolve().parent.parent / "home" / ".agents" / "hooks"
EM, EN = "\u2014", "\u2013"
DEEP_JSON = "[" * 100000
# Variables that change a hook's behavior; tests set them explicitly when they need them.
HOOK_ENV = ("CURSOR_VERSION", "CLANG_FORMAT")


def run(script: str, payload, tool: str = "claude", env: dict = None) -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    base = {k: v for k, v in os.environ.items() if k not in HOOK_ENV}
    return subprocess.run([sys.executable, str(HOOKS / script), "--tool", tool],
                          input=data, capture_output=True, text=True, check=False,
                          env={**base, **(env or {})})


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def fake_program(folder: Path, name: str, body: str) -> Path:
    program = folder / name
    program.write_text("#!/bin/sh\n" + body)
    program.chmod(0o755)
    return program


def committed_repo(test: unittest.TestCase) -> tuple:
    """A repository on branch work with one commit, removed after the test."""
    # An empty global config keeps the user's git settings out of the test; status.branch
    # is a setting some users have, and its "## branch" line is not a change.
    repo = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, repo)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
           "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "work", str(repo)], check=True, env=env)
    subprocess.run([*git, "config", "status.branch", "true"], check=True, env=env)
    (repo / "tracked.txt").write_text("one\n")
    subprocess.run([*git, "add", "tracked.txt"], check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True, env=env)
    return repo, env


def linked_worktree(test: unittest.TestCase, repo: Path, env: dict, branch: str = "feat/task") -> Path:
    """A linked worktree of repo on a new branch, in a sibling folder removed after the test."""
    worktree = Path(tempfile.mkdtemp()) / "wt"
    test.addCleanup(shutil.rmtree, worktree.parent)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", branch, str(worktree)],
                   check=True, env=env)
    return worktree


def write_notes(repo: Path, notes: dict) -> None:
    """Create .private files {relative path: modification time in epoch seconds},
    git-ignored as in a real project."""
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(".private/\n")
    for name, mtime in notes.items():
        path = repo / ".private" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("notes\n")
        os.utime(path, (mtime, mtime))


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

    def assert_blocked(self, commands, tool: str = "claude", env: dict = None):
        for command in commands:
            with self.subTest(command=command, tool=tool):
                result = run("guard_bash.py", bash(command), tool, env)
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

    def test_remote_deletion_mirror_and_prune(self):
        self.assert_blocked([
            "git push --delete origin main",
            "git push origin --delete main",
            "git push origin :main",
            "git push -d origin main",
            "git push --mirror",
            "git push --mirror origin",
            "git push --prune origin",
            "git push --de origin x",
            "git push --m",
            "git push --pru origin",
            "git push origin +HEAD:main",
            "git push origin --force-with-lease=main main",
            "git push --force-if-includes",
            "git push --forc origin main",
        ])
        # These options neither force nor delete: the push is blocked only as a push.
        for command in ("git push origin HEAD:refs/heads/feat/x", "git push -o ci.skip origin feat/x",
                        "git push --follow-tags origin feat/x", "git push --dry-run origin feat/x"):
            with self.subTest(command=command):
                result = run("guard_bash.py", bash(command))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("git push publishes", result.stderr)
                for history in ("rewrites", "destroys", "deletes remote refs", "overwrites"):
                    self.assertNotIn(history, result.stderr)

    # Every form of push the parser sees: plain, after git's global options, wrappers,
    # keywords, substitutions, quoting and the rough split of unparsable text.
    PUSHES = [
        "git push", "git push origin feat/x", "git push -u origin feat/x", "git push --dry-run",
        "cd a && git push origin x", "git -C repo push", "git -C repo push origin x",
        "git --git-dir .git push", "git --git-dir=.git push", "git --work-tree . --git-dir .git push",
        "git -c push.default=current push", "git --no-pager push", "/usr/bin/git push", "git.exe push",
        "env git push", "env GIT_TRACE=1 git push", "GIT_TRACE=1 git push", "command git push",
        "sudo git push", "nohup git push", "timeout 60 git push", "xargs git push", "time git push",
        "if true; then git push; fi", "for r in a; do git push; done", "! git push", "{ git push; }",
        "(git push)", "echo $(git push)", "echo `git push`", "git 'push' origin", "git pu\\sh",
        "git push origin x # it's fine",
        "git subtree push --prefix=lib origin main", "git subtree push -P lib origin main",
        "git subtree -P lib push origin main", "git -C repo subtree push --prefix lib origin x",
        "gh pr create --fill", "gh pr new --fill", "gh -R o/r pr create --title x", "gh pr -R o/r create",
        "gh pr merge 12 --squash", "gh pr merge --auto --squash 12", "gh -R o/r pr merge 1",
    ]

    def test_every_push_is_blocked_in_every_tool(self):
        # The maintainer reviews everything before it leaves the machine, so no agent pushes
        # or publishes, Claude Code included.
        for tool in ("claude", "codex", "gemini", "copilot", "cursor"):
            self.assert_blocked(self.PUSHES, tool)
        for command in ("git push", "gh pr create --fill", "git subtree push -P lib origin main"):
            with self.subTest(command=command):
                self.assertIn("Pushing and publishing are the maintainer's",
                              run("guard_bash.py", bash(command)).stderr)
        # Cursor runs the Claude Code hook command with --tool claude.
        self.assert_blocked(["git push"], env={"CURSOR_VERSION": "1.7.2"})
        payload = {**bash("git push"), "cursor_version": "1.7.2"}
        self.assertEqual(run("guard_bash.py", payload).returncode, 2)

    def test_releases_and_repository_syncs_are_blocked(self):
        for tool in ("claude", "codex", "gemini", "copilot", "cursor"):
            self.assert_blocked(["gh release create v1.0 --notes x", "gh repo sync",
                                 "gh repo sync owner/fork --source owner/repo",
                                 "gh -R owner/repo release create v2"], tool)
        self.assertIn("Pushing and publishing are the maintainer's",
                      run("guard_bash.py", bash("gh release create v1.0")).stderr)

    def test_commands_that_do_not_publish_are_allowed(self):
        self.assert_allowed([
            "git fetch origin", "git pull origin main", "git remote -v", "git log --grep push",
            "echo git push", "grep -rn 'git push' docs", "git subtree split -P lib -b split",
            "git subtree add --prefix push origin main", "git subtree pull --prefix=lib origin main",
            "gh pr view 12", "gh pr list", "gh pr checkout 12", "gh pr diff 12",
            "gh release list", "gh release view v1.0", "gh repo view", "gh repo clone owner/repo",
        ])

    def test_other_ways_to_skip_hooks(self):
        self.assert_blocked([
            "LEFTHOOK=0 git commit -m x",
            "LEFTHOOK=false git commit -m x",
            "OVERCOMMIT_DISABLE=1 git commit -m x",
            "HUSKY=false git commit -m x",
            "git config unset core.hooksPath",
            "git config unset --all core.hooksPath",
            "git config --unset-all core.hooksPath",
            "git config --unset core.hookspath",
            "git config core.hooksPath /dev/null",
            "git config --local core.hooksPath /dev/null",
            "git config --global core.hooksPath ''",
            "git config --system core.hooksPath /dev/null",
            "git config set core.hooksPath /dev/null",
            "git config set --global core.hooksPath ''",
            "git config --file .git/config core.hooksPath /dev/null",
            "git --config-env=core.hooksPath=X commit -m x",
            "git --config-env core.hooksPath=X commit -m x",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x",
            "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null'\" git commit -m x",
        ])
        self.assert_allowed([
            "git config --get core.hooksPath",
            "git config core.hooksPath",
            "git config get core.hooksPath",
            "git config set core.hooksPath .githooks",
            "LEFTHOOK=1 git commit -m x",
            "HUSKY=1 git commit -m x",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x git commit -m x",
        ])

    def test_more_git_gh_and_wrapper_forms(self):
        self.assert_blocked([
            "git --attr-source HEAD push -f",
            "git.exe push -f",
            "function f { git push -f; }; f",
            "coproc git push -f",
            "setsid git push -f",
            "stdbuf -oL git push -f",
            "ionice -c 3 git push -f",
            "flock /tmp/lock git push -f",
            "taskset 0x1 git push -f",
            "git config core.hooksPath /dev/null/",
            "gh pr -R o/r merge 1 --admin",
            "gh -R o/r pr merge 1 --admin",
        ])

    def test_admin_merge_skips_required_checks(self):
        self.assert_blocked(["gh pr merge 12 --admin --squash", "gh pr merge --admin"])
        self.assertIn("--admin merges without the required checks",
                      run("guard_bash.py", bash("gh pr merge --admin")).stderr)
        self.assert_allowed(["gh pr view 12"])

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

    def test_arithmetic_shift_is_not_a_heredoc(self):
        self.assert_blocked([
            'echo "$((1<<2))"\ngit push -f origin main',
            "(( x = 1 << 2 ))\ngit commit --no-verify -m x",
            "for ((i = 0; i < 1 << 2; i++)); do git push -f; done",
            "echo $[1<<2]\ngit push -f",
            "echo $(( $(git push -f) + 1 ))",
        ])
        self.assert_allowed([
            "echo $((1 + (2 * 3)))",
            "x=$(( (1 + 2) * 3 )); echo $x",
            "( (cd a && ls) )",
            "echo $( (cd a && ls) )",
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

    def test_copilot_deny_reason_reaches_the_agent(self):
        # Copilot CLI shows stderr of a denying hook only to the user; the agent sees
        # permissionDecisionReason (docs.github.com/en/copilot/reference/hooks-reference).
        payload = {"toolName": "bash", "toolArgs": json.dumps({"command": "git push --force"})}
        result = run("guard_bash.py", payload, "copilot")
        self.assertEqual(result.returncode, 2)
        output = json.loads(result.stdout)
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("force push", output["permissionDecisionReason"])
        allowed = run("guard_bash.py", {"toolName": "bash", "toolArgs": json.dumps({"command": "ls"})}, "copilot")
        self.assertEqual((allowed.returncode, allowed.stdout), (0, ""))

    def test_antigravity_gets_a_decision_as_json(self):
        # Antigravity hooks docs (antigravity.google/docs/hooks?tab=cli): PreToolUse reads
        # toolCall {name, args} (run_command's args hold CommandLine) and answers on stdout
        # with JSON: decision (required; "allow" defers to the next hook or the default
        # policy, "deny" blocks) and reason, shown to the agent. Exit codes are not
        # documented, so the hook always exits 0 with its decision.
        def call(command):
            return {"toolCall": {"name": "run_command", "args": {"CommandLine": command, "Cwd": "/tmp",
                                                                  "WaitMsBeforeAsync": 5000}},
                    "stepIdx": 19, "conversationId": "c", "workspacePaths": ["/tmp"], "modelName": "m"}
        blocked = run("guard_bash.py", call("git push --force origin main"), "antigravity")
        self.assertEqual((blocked.returncode, blocked.stderr), (0, ""))
        reply = json.loads(blocked.stdout)
        self.assertEqual(sorted(reply), ["decision", "reason"])
        self.assertEqual(reply["decision"], "deny")
        self.assertIn("force push", reply["reason"])
        self.assertIn("ready for their review", reply["reason"])
        for payload in (call("npm test"), "not json", DEEP_JSON, [1], {"toolCall": "x"},
                        {"toolCall": {"name": "run_command", "args": {"CommandLine": 5}}}):
            with self.subTest(payload=str(payload)[:40]):
                allowed = run("guard_bash.py", payload, "antigravity")
                self.assertEqual((allowed.returncode, allowed.stderr), (0, ""))
                self.assertEqual(json.loads(allowed.stdout), {"decision": "allow"})

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
            ("cursor", {"file_path": target, "edits": [{"old_string": "a", "new_string": f"q {EM} r"}]}),
        ]
        for tool, payload in cases:
            with self.subTest(tool=tool, payload=payload):
                result = run("after_edit.py", payload, tool)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Em/en dash", result.stderr)

    def test_copilot_gets_problems_as_context(self):
        # Copilot CLI shows a postToolUse exit 2 only to the user; additionalContext with
        # exit 0 reaches the model (docs.github.com/en/copilot/reference/hooks-reference).
        target = str(self.tmp / "notes.md")
        cases = [
            {"toolName": "edit", "toolArgs": json.dumps({"path": target, "old_str": "a", "new_str": f"x {EM} y"})},
            {"toolName": "create", "toolArgs": json.dumps({"path": target, "file_text": f"a {EN} b"})},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                result = run("after_edit.py", payload, "copilot")
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertIn("Em/en dash", json.loads(result.stdout)["additionalContext"])
                self.assertIn(target, json.loads(result.stdout)["additionalContext"])

    def test_antigravity_reply_is_an_empty_object(self):
        # Antigravity hooks docs: PostToolUse reads toolCall {name, args} (write_to_file:
        # TargetFile, CodeContent; replace_file_content: TargetFile, ReplacementContent) and
        # answers {}; no exit code and no field that reaches the agent are documented, so
        # the dash report goes to stderr with exit 0.
        target = str(self.tmp / "notes.md")
        cases = [
            {"toolCall": {"name": "write_to_file", "args": {"TargetFile": target, "CodeContent": f"a {EM} b",
                                                             "Overwrite": True}}},
            {"toolCall": {"name": "replace_file_content",
                          "args": {"TargetFile": target, "TargetContent": "a", "ReplacementContent": f"x {EN} y",
                                   "AllowMultiple": False}}},
        ]
        for payload in cases:
            with self.subTest(tool=payload["toolCall"]["name"]):
                result = run("after_edit.py", payload, "antigravity")
                self.assertEqual((result.returncode, result.stdout.strip()), (0, "{}"))
                self.assertIn("Em/en dash", result.stderr)
                self.assertIn(target, result.stderr)
        for payload in ({"toolCall": {"name": "write_to_file", "args": {"TargetFile": target, "CodeContent": "plain"}}},
                        {"toolCall": {"name": "write_to_file", "args": {"TargetFile": target, "CodeContent": f"a {EM}"}},
                         "error": "permission denied"},
                        "not json", DEEP_JSON, [1], {"toolCall": "x"}, {"toolCall": {"args": {"TargetFile": 5}}},
                        {"toolCall": {"args": {"TargetFile": "a.md", "CodeContent": "x"}}, "workspacePaths": 5}):
            with self.subTest(payload=str(payload)[:60]):
                result = run("after_edit.py", payload, "antigravity")
                self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "{}", ""))

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

    def test_codex_patch_line_starting_with_plus_plus(self):
        # apply_patch has no "+++" file headers: "+++i;" is the added line "++i;".
        patch = f"*** Begin Patch\n*** Update File: c.cpp\n@@\n-i++;\n+++i; // a {EM} b\n*** End Patch\n"
        payload = {"tool_name": "apply_patch", "cwd": str(self.tmp), "tool_input": {"command": patch}}
        result = run("after_edit.py", payload, "codex")
        self.assertEqual(result.returncode, 2)
        self.assertIn("++i; // a", result.stderr)

    def test_wrong_types_never_fail(self):
        target = str(self.tmp / "a.md")
        payloads = [
            {"cwd": 5, "tool_input": {"file_path": "a.md", "new_string": "x"}},
            {"tool_input": {"file_path": 5, "new_string": "x"}},
            {"tool_input": {"file_path": ["a"], "content": "x"}},
            {"tool_input": {"file_path": target, "new_string": 5}},
            {"file_path": target, "edits": [{"new_string": 5}]},
            {"tool_input": {"command": "*** Begin Patch\n*** Add File: x\n+a\n*** End Patch"}, "cwd": 5},
            {"tool_input": {"file_path": target, "new_string": "x"}, "tool_response": "[1]"},
            {"tool_input": {"file_path": target, "new_string": "x"},
             "tool_response": {"structuredPatch": [5, {"newStart": True, "lines": [1]}]}},
            {"tool_input": {"file_path": target, "new_string": "x"},
             "tool_response": {"structuredPatch": [{"newStart": 1, "lines": "+x"}]}},
            {"toolArgs": "[1]"},
            [1],
            DEEP_JSON,
        ]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:60]):
                result = run("after_edit.py", payload, "gemini")
                self.assertEqual((result.returncode, result.stdout.strip(), result.stderr), (0, "{}", ""))

    def fake_clang_format(self, body: str) -> dict:
        (self.tmp / ".clang-format").write_text("BasedOnStyle: LLVM\n")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        return {"CLANG_FORMAT": str(fake_program(bin_dir, "clang-format", body))}

    def test_reformat_notice_reaches_each_agent(self):
        # The fake formatter rewrites the file named last on its command line.
        env = self.fake_clang_format('for f; do :; done\nprintf "int f();\\n" > "$f"\n')
        source = self.tmp / "a.cpp"
        expected = {
            "claude": lambda out: out["hookSpecificOutput"],
            "codex": lambda out: out["hookSpecificOutput"],
            "gemini": lambda out: out["hookSpecificOutput"],
            "copilot": lambda out: out,
        }
        events = {"claude": "PostToolUse", "codex": "PostToolUse", "gemini": "AfterTool"}
        for tool, context_of in expected.items():
            with self.subTest(tool=tool):
                source.write_text("int   f( );\n")
                payload = {"tool_name": "Write", "tool_input": {"file_path": str(source), "content": "int   f( );\n"}}
                result = run("after_edit.py", payload, tool, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                context = context_of(json.loads(result.stdout))
                self.assertIn("reformatted", context["additionalContext"])
                if tool in events:
                    self.assertEqual(context["hookEventName"], events[tool])

    def test_antigravity_reformat_notice_goes_to_stderr(self):
        # Antigravity's PostToolUse reply is {} only, so the notice has nowhere else to go;
        # stderr at least keeps it where its logs may show it.
        env = self.fake_clang_format('for f; do :; done\nprintf "int f();\\n" > "$f"\n')
        source = self.tmp / "a.cpp"
        source.write_text("int   f( );\n")
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(source),
                                                                   "CodeContent": "int   f( );\n"}}}
        result = run("after_edit.py", payload, "antigravity", env)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "{}"))
        self.assertIn("reformatted", result.stderr)

    def test_formatting_stays_within_hook_timeout(self):
        # In-process with a 3 s budget, so the test does not wait for the real 60 s timeout.
        env = self.fake_clang_format("exec sleep 2\n")
        names = ["a.cpp", "b.cpp", "c.cpp", "d.cpp"]
        for name in names:
            (self.tmp / name).write_text("int x;\n")
        patch = "*** Begin Patch\n" + "".join(f"*** Add File: {n}\n+int x;\n" for n in names) + "*** End Patch\n"
        payload = json.dumps({"tool_name": "apply_patch", "cwd": str(self.tmp), "tool_input": {"command": patch}})
        spec = importlib.util.spec_from_file_location("after_edit_under_test", HOOKS / "after_edit.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DEADLINE_SECONDS = 3
        stderr = io.StringIO()
        start = time.monotonic()
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "argv", ["after_edit.py", "--tool", "codex"]), \
                mock.patch.object(sys, "stdin", io.StringIO(payload)), contextlib.redirect_stderr(stderr), \
                contextlib.redirect_stdout(io.StringIO()):
            code = module.main()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(code, 2)
        self.assertIn("Formatting not applied", stderr.getvalue())
        self.assertIn("d.cpp", stderr.getvalue())

    def test_formats_only_the_lines_each_edit_changed(self):
        # The fake formatter records its arguments. An edit formats only the lines it changed:
        # from the line numbers in the payload when it has them (Claude Code's tool_response
        # carries a structuredPatch), else where its new text stands, when that is only
        # once in the file or the edit replaced every occurrence. A file written in full is
        # formatted whole.
        log = self.tmp / "args.txt"
        env = self.fake_clang_format(f'printf "%s\\n" "$@" > "{log}"\n')
        source = self.tmp / "a.cpp"
        path = str(source)
        whole = ["-i", "--style=file", path]

        def lines(*ranges):
            return ["-i", "--style=file", *[f"--lines={r}" for r in ranges], path]

        def edit(new, **extra):
            return {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "x", "new_string": new,
                                                        **extra.pop("tool_input", {})}, **extra}

        def patch_response(new_start, *hunk_lines):
            return {"structuredPatch": [{"oldStart": new_start, "oldLines": 1, "newStart": new_start,
                                         "newLines": 1, "lines": list(hunk_lines)}]}

        def codex(body):
            return {"tool_name": "apply_patch", "cwd": str(self.tmp),
                    "tool_input": {"command": f"*** Begin Patch\n{body}*** End Patch\n"}}

        def agy(name, **args):
            return {"toolCall": {"name": name, "args": args}, "workspacePaths": ["/elsewhere"]}

        write = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "int   a( );\n"}}
        cases = [
            ("one line", "claude", edit("int   b( );"), lines("2:2")),
            ("part of a line", "claude", edit("b( )"), lines("2:2")),
            ("several lines", "claude", edit("int   c( );\nint   d( );\n"), lines("3:4")),
            ("text found twice", "claude", edit("int   a( );"), None),
            ("deletion", "claude", edit(""), None),
            ("replace all", "claude", edit("int   a( );", tool_input={"replace_all": True}), lines("1:1", "5:5")),
            ("patch line numbers", "claude",
             edit("int   a( );", tool_response=patch_response(4, " int   d( );", "-int x;", "+int   a( );")),
             lines("5:5")),
            ("patch without added lines", "claude", edit("", tool_response=patch_response(2, "-int x;")), None),
            ("write", "claude", write, whole),
            ("write of a new file", "claude", {**write, "tool_response": {"type": "create", "structuredPatch": []}},
             whole),
            ("write over a file", "claude",
             {**write, "tool_response": {"type": "update", "structuredPatch": [
                 {"oldStart": 2, "oldLines": 2, "newStart": 2, "newLines": 2,
                  "lines": ["-x", "-y", "+int   b( );", "+int   c( );"]}]}},
             lines("2:3")),
            ("gemini replace", "gemini",
             {"tool_name": "replace", "tool_input": {"file_path": path, "old_string": "x", "new_string": "int   d( );"}},
             lines("4:4")),
            ("copilot edit", "copilot",
             {"toolName": "edit", "toolArgs": json.dumps({"path": path, "old_str": "x", "new_str": "int   c( );"})},
             lines("3:3")),
            ("cursor edits", "cursor",
             {"file_path": path, "edits": [{"old_string": "x", "new_string": "int   b( );"},
                                           {"old_string": "y", "new_string": "int   d( );"}]},
             lines("2:2", "4:4")),
            ("codex update", "codex",
             codex("*** Update File: a.cpp\n@@\n int   b( );\n-int x;\n+int   c( );\n int   d( );\n"), lines("3:3")),
            # apply_patch tolerates whitespace changes in context lines; the added lines still locate.
            ("codex update, loose context", "codex",
             codex("*** Update File: a.cpp\n@@\n int b( );\n-int x;\n+int   c( );\n int d( );\n"), lines("3:3")),
            ("codex move", "codex",
             codex("*** Update File: old.cpp\n*** Move to: a.cpp\n@@\n-int x;\n+int   b( );\n"), lines("2:2")),
            ("codex add", "codex", codex("*** Add File: a.cpp\n+int   a( );\n"), whole),
            ("antigravity replace", "antigravity",
             agy("replace_file_content", TargetFile=path, TargetContent="x", ReplacementContent="int   c( );",
                 AllowMultiple=False), lines("3:3")),
            ("antigravity replace all", "antigravity",
             agy("replace_file_content", TargetFile=path, TargetContent="x", ReplacementContent="int   a( );",
                 AllowMultiple=True), lines("1:1", "5:5")),
            ("antigravity write", "antigravity",
             agy("write_to_file", TargetFile=path, CodeContent="int   a( );\n", Overwrite=True), whole),
            ("antigravity relative path", "antigravity",
             {**agy("replace_file_content", TargetFile="a.cpp", ReplacementContent="int   b( );"),
              "workspacePaths": [str(self.tmp)]}, lines("2:2")),
            ("antigravity failed call", "antigravity",
             {**agy("write_to_file", TargetFile=path, CodeContent="int   a( );\n"), "error": "exit status 1"}, None),
            # The docs give a string; any other error value still means the call failed.
            ("antigravity failed call, error object", "antigravity",
             {**agy("write_to_file", TargetFile=path, CodeContent="int   a( );\n"), "error": {"message": "e"}}, None),
            # Antigravity documents no fields for the chunks of multi_replace_file_content.
            ("antigravity multi replace", "antigravity",
             agy("multi_replace_file_content", TargetFile=path,
                 ReplacementChunks=[{"ReplacementContent": "int   b( );"}]), None),
        ]
        for name, tool, payload, expected in cases:
            with self.subTest(case=name):
                source.write_text("int   a( );\nint   b( );\nint   c( );\nint   d( );\nint   a( );\n")
                if log.exists():
                    log.unlink()
                result = run("after_edit.py", payload, tool, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                called = log.read_text().splitlines() if log.exists() else None
                self.assertEqual(called, expected)

    @unittest.skipUnless(shutil.which("clang-format"), "clang-format not installed")
    def test_edit_leaves_lines_it_did_not_change_alone(self):
        (self.tmp / ".clang-format").write_text("BasedOnStyle: LLVM\n")
        source = self.tmp / "a.cpp"
        source.write_text("int   a( );\nint   b( );\nint   c( );\n")
        payload = {"tool_name": "Edit", "tool_input": {"file_path": str(source), "old_string": "int x;",
                                                       "new_string": "int   b( );"}}
        result = run("after_edit.py", payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reformatted", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(source.read_text(), "int   a( );\nint b();\nint   c( );\n")

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
    def refresh_with(self, payload, env: dict = None) -> subprocess.CompletedProcess:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(HOOKS / "session_refresh.py")], input=data,
                              capture_output=True, text=True, check=False, env=env)

    def test_prints_reminder_and_git_state(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo)
        subprocess.run(["git", "init", "-q", "-b", "work", str(repo)], check=True)
        result = self.refresh_with({"cwd": str(repo), "source": "compact"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("Session restarted from compact", result.stdout)
        self.assertIn("Current branch: work", result.stdout)

    def committed_repo(self) -> tuple:
        return committed_repo(self)

    def refresh(self, repo: Path, env: dict) -> subprocess.CompletedProcess:
        return self.refresh_with({"cwd": str(repo), "source": "resume"}, env)

    def test_status_keeps_the_index_column(self):
        # " M" (changed, not staged) must not lose its space and read as "M " (staged).
        repo, env = self.committed_repo()
        (repo / "tracked.txt").write_text("two\n")
        result = self.refresh(repo, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Uncommitted changes:\n M tracked.txt\n", result.stdout)

    SKILL_AGAIN = "Invoke your workflow skill again before the next step"

    def test_after_compaction_asks_to_invoke_the_workflow_skill_again(self):
        # After a compaction Claude Code re-attaches only the first 5,000 tokens of each
        # invoked skill and may drop older ones (code.claude.com/docs/en/skills). Codex runs
        # the same hook and documents no such limit, so the line gives no tool's reason.
        repo, env = self.committed_repo()
        compact = self.refresh_with({"cwd": str(repo), "source": "compact"}, env)
        self.assertEqual((compact.returncode, compact.stderr), (0, ""))
        self.assertIn(self.SKILL_AGAIN + ".\n", compact.stdout)
        for source in ("resume", "startup"):
            with self.subTest(source=source):
                other = self.refresh_with({"cwd": str(repo), "source": source}, env)
                self.assertEqual(other.returncode, 0)
                self.assertNotIn(self.SKILL_AGAIN, other.stdout)

    def test_clean_tree_reports_no_changes(self):
        repo, env = self.committed_repo()
        result = self.refresh(repo, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Last commits:", result.stdout)
        self.assertNotIn("Uncommitted changes", result.stdout)

    def test_detached_head_shows_the_commit(self):
        repo, env = self.committed_repo()
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach"], check=True, env=env)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], check=True,
                              capture_output=True, text=True, env=env).stdout.strip()
        (repo / "tracked.txt").write_text("two\n")
        result = self.refresh(repo, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn(f"Detached HEAD at {head}", result.stdout)
        self.assertIn("Uncommitted changes:\n M tracked.txt\n", result.stdout)
        self.assertIn("Last commits:", result.stdout)

    def test_failed_status_is_not_reported_as_clean(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        fake_program(tmp, "git", '[ "$1" = branch ] && echo work && exit 0\n'
                                 '[ "$1" = log ] && echo "abc123 init" && exit 0\n'
                                 'echo "fatal: index file corrupt" >&2\nexit 128\n')
        env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = self.refresh_with({"cwd": str(tmp), "source": "resume"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Current branch: work", result.stdout)
        self.assertIn("Uncommitted changes not shown: git status failed", result.stdout)

    REREAD = "Re-read the task's progress log before the next step."

    def write_notes(self, repo: Path, notes: dict) -> None:
        write_notes(repo, notes)

    def test_points_to_the_most_recent_task_notes(self):
        repo, env = self.committed_repo()
        day = 1_790_000_000
        self.write_notes(repo, {"progress/old.org": day, "progress/a.org": day + 60,
                                "progress/task/b.org": day + 120, "progress/c.org": day + 180,
                                "handoff/h.org": day + 30, "specs/s.org": day + 300})
        (repo / "src").mkdir()
        for cwd in (repo, repo / "src"):
            with self.subTest(cwd=cwd):
                result = self.refresh_with({"cwd": str(cwd), "source": "compact"}, env)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                listed = [f".private/{name} ({time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))})"
                          for name, mtime in (("progress/c.org", day + 180), ("progress/task/b.org", day + 120),
                                              ("progress/a.org", day + 60), ("handoff/h.org", day + 30))]
                positions = [result.stdout.find(line) for line in listed]
                self.assertNotIn(-1, positions, result.stdout)
                self.assertEqual(positions, sorted(positions), "most recent first, progress before handoff")
                self.assertNotIn("old.org", result.stdout)
                self.assertNotIn("s.org", result.stdout)
                self.assertTrue(result.stdout.rstrip("\n").endswith(self.REREAD), result.stdout)

    def test_linked_worktree_lists_the_main_checkouts_notes(self):
        # A worktree has no .private/: its notes are in the main checkout's, the parent
        # of git rev-parse --git-common-dir. They are listed with absolute paths, since
        # the agent's folder is the worktree, not the checkout that holds them.
        repo, env = self.committed_repo()
        day = 1_790_000_000
        self.write_notes(repo, {"progress/task.org": day, "handoff/2026-11-12-task.org": day + 60})
        worktree = linked_worktree(self, repo, env)
        (worktree / "src").mkdir()
        for cwd in (worktree, worktree / "src"):
            with self.subTest(cwd=cwd):
                result = self.refresh_with({"cwd": str(cwd), "source": "compact"}, env)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertIn("Current branch: feat/task", result.stdout)
                for name, mtime in (("progress/task.org", day), ("handoff/2026-11-12-task.org", day + 60)):
                    when = time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))
                    self.assertIn(f"{(repo / '.private' / name).as_posix()} ({when})", result.stdout)
                self.assertTrue(result.stdout.rstrip("\n").endswith(self.REREAD), result.stdout)

    def test_lists_the_other_worktrees(self):
        # Work in parallel or in isolation runs in sibling worktrees; after a compaction
        # the agent must know they exist and which branch each holds.
        repo, env = self.committed_repo()
        alone = self.refresh(repo, env)
        self.assertEqual((alone.returncode, alone.stderr), (0, ""))
        self.assertNotIn("worktrees", alone.stdout.lower())
        worktree = linked_worktree(self, repo, env)
        gone = linked_worktree(self, repo, env, branch="feat/gone")
        shutil.rmtree(gone)  # prunable: its folder no longer exists
        for cwd, other, branch in ((repo, worktree, "feat/task"), (worktree, repo, "work")):
            with self.subTest(cwd=cwd):
                result = self.refresh(cwd, env)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertIn(f"Other worktrees of this repository:\n{other.resolve().as_posix()} ({branch})\n",
                              result.stdout + "\n")
                self.assertNotIn(f"{cwd.resolve().as_posix()} (", result.stdout)
                self.assertNotIn("feat/gone", result.stdout)

    def test_no_task_notes_no_reminder(self):
        repo, env = self.committed_repo()
        for notes in ({}, {"specs/s.org": 1_790_000_000}):
            with self.subTest(notes=notes):
                self.write_notes(repo, notes)
                result = self.refresh(repo, env)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertNotIn(".private", result.stdout)
                self.assertNotIn(self.REREAD, result.stdout)

    def test_unreadable_task_notes_never_fail(self):
        repo, env = self.committed_repo()
        (repo / ".private").mkdir()
        (repo / ".private/progress").write_text("a file, not a folder\n")
        self.write_notes(repo, {"handoff/h.org": 1_790_000_000})
        (repo / ".private/handoff/gone.org").symlink_to(repo / "missing")
        result = self.refresh(repo, env)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertIn(".private/handoff/h.org", result.stdout)
        self.assertNotIn("gone.org", result.stdout)

    def test_wrong_types_never_fail(self):
        for payload in ([1], {"cwd": 5}, {"cwd": [], "source": 5}, {"source": {"a": 1}}, DEEP_JSON,
                        {"cwd": "bad\u0000path"}):
            with self.subTest(payload=str(payload)[:40]):
                result = self.refresh_with(payload)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertIn("Session restarted from resume or compaction.", result.stdout)

    def test_slow_git_stays_within_hook_timeout(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        fake_program(tmp, "git", 'sleep 4\n[ "$1" = branch ] && echo work\nexit 0\n')
        (tmp / ".git").mkdir()
        self.write_notes(tmp, {"progress/p.org": 1_790_000_000})
        env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
        start = time.monotonic()
        result = self.refresh_with({"cwd": str(tmp), "source": "resume"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - start, 9.5)
        self.assertIn("Session restarted from resume", result.stdout)
        self.assertIn("Current branch: work", result.stdout)
        self.assertIn("Uncommitted changes not shown", result.stdout)
        self.assertIn("Last commits not shown", result.stdout)
        self.assertIn("Other worktrees not shown", result.stdout)
        # The notes are files, not git output: a slow git does not hide them.
        self.assertIn(".private/progress/p.org", result.stdout)
        self.assertIn(self.REREAD, result.stdout)


class CompactBrief(unittest.TestCase):
    # Claude Code's PreCompact: stdout of an exit 0 becomes instructions for the summary,
    # cut at 10,000 characters; exit 2 blocks the compaction (code.claude.com/docs/en/hooks).
    ITEMS = ["The task:", "its slug", "progress log and handoff", "The current plan step",
             "Review: pending", "The files changed", "commands still needed",
             "last result of each"]

    def brief(self, payload, env: dict = None, script: Path = HOOKS / "compact_brief.py",
              cwd: Path = None):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(script)], input=data, capture_output=True,
                              text=True, check=False, env=env, cwd=cwd)

    def assert_brief(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        for item in self.ITEMS:
            self.assertIn(item, result.stdout)
        self.assertLess(len(result.stdout), 10000)

    def test_keeps_what_resuming_needs_with_the_real_state(self):
        repo, env = committed_repo(self)
        write_notes(repo, {"progress/task.org": 1_790_000_000,
                                   "handoff/2026-11-12-task.org": 1_790_000_060})
        (repo / "tracked.txt").write_text("two\n")
        result = self.brief({"cwd": str(repo), "hook_event_name": "PreCompact", "trigger": "auto",
                             "custom_instructions": None}, env)
        self.assert_brief(result)
        self.assertIn("The branch: work.", result.stdout)
        self.assertIn(".private/progress/task.org", result.stdout)
        self.assertIn(".private/handoff/2026-11-12-task.org", result.stdout)
        self.assertIn("Uncommitted now:\n   M tracked.txt", result.stdout)

    def test_linked_worktree_points_to_the_main_checkouts_notes(self):
        repo, env = committed_repo(self)
        write_notes(repo, {"progress/task.org": 1_790_000_000})
        worktree = linked_worktree(self, repo, env)
        result = self.brief({"cwd": str(worktree)}, env)
        self.assert_brief(result)
        self.assertIn("The branch: feat/task.", result.stdout)
        self.assertIn(f"{(repo / '.private/progress/task.org').as_posix()} (", result.stdout)

    def test_keeps_the_running_workflow_skill_and_its_step(self):
        # After a compaction the session refresh asks the agent to invoke its workflow
        # skill again; the summary must say which one and where in it the work stood.
        result = self.brief({"cwd": "/no/such/folder"})
        self.assert_brief(result)
        self.assertIn("- The workflow skill in use (such as implement or spec) and the section or step "
                      "of it that was running, so it is invoked again there.", result.stdout)

    def test_keeps_the_users_unrecorded_constraints_and_what_is_blocked(self):
        # A constraint the user stated in the chat (do not commit, an approach ruled out)
        # lives nowhere else; a paraphrase can lose it, so it is kept word for word.
        result = self.brief({"cwd": "/no/such/folder"})
        self.assert_brief(result)
        self.assertIn("- Each constraint the user stated in this session that no file records, word for "
                      "word, and what is blocked and on what.", result.stdout)

    def test_long_state_stays_under_the_cap(self):
        repo, env = committed_repo(self)
        for index in range(60):
            (repo / f"{index:02}{'x' * 200}.txt").write_text("new\n")
        result = self.brief({"cwd": str(repo)}, env)
        self.assert_brief(result)
        self.assertIn("... and 45 more", result.stdout)

    def test_never_blocks_on_bad_input(self):
        # Without a usable cwd the hook reads its own working folder, here not a repository.
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        for payload in ("not json", DEEP_JSON, [1], {"cwd": 5}, {"cwd": "bad\u0000path"},
                        {"cwd": "/no/such/folder"}):
            with self.subTest(payload=str(payload)[:40]):
                result = self.brief(payload, cwd=outside)
                self.assert_brief(result)
                self.assertIn("- The branch the work is on.", result.stdout)

    def test_brief_survives_no_stdin_and_a_narrow_stdout(self):
        # Exit 1 does not block a compaction, but it loses the whole brief.
        repo, env = committed_repo(self)
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "w\u00f6rk"], check=True, env=env)
        closed = subprocess.run(["sh", "-c", f'"{sys.executable}" "{HOOKS / "compact_brief.py"}" 0<&-'],
                                capture_output=True, text=True, check=False, env=env, cwd=repo)
        self.assert_brief(closed)
        ascii_out = self.brief({"cwd": str(repo)}, {**env, "PYTHONIOENCODING": "ascii"})
        self.assert_brief(ascii_out)
        self.assertIn("The branch: w?rk.", ascii_out.stdout)

    def test_reuses_session_refresh_without_leaving_a_cache(self):
        hooks = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, hooks)
        repo, env = committed_repo(self)
        for name in ("compact_brief.py", "session_refresh.py"):
            shutil.copy(HOOKS / name, hooks)
        env = {k: v for k, v in env.items() if k != "PYTHONDONTWRITEBYTECODE"}
        result = self.brief({"cwd": str(repo)}, env, script=hooks / "compact_brief.py")
        self.assert_brief(result)
        self.assertIn("The branch: work.", result.stdout)
        self.assertEqual(sorted(p.name for p in hooks.iterdir()), ["compact_brief.py", "session_refresh.py"])

    def test_brief_without_session_refresh(self):
        hooks = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, hooks)
        repo, env = committed_repo(self)
        shutil.copy(HOOKS / "compact_brief.py", hooks)
        result = self.brief({"cwd": str(repo)}, env, script=hooks / "compact_brief.py")
        self.assert_brief(result)
        self.assertIn("- The branch the work is on.", result.stdout)

    def test_slow_git_stays_within_hook_timeout(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        fake_program(tmp, "git", 'sleep 4\n[ "$1" = branch ] && echo work\nexit 0\n')
        (tmp / ".git").mkdir()
        write_notes(tmp, {"progress/p.org": 1_790_000_000})
        env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
        start = time.monotonic()
        result = self.brief({"cwd": str(tmp)}, env)
        self.assertLess(time.monotonic() - start, 9.5)
        self.assert_brief(result)
        self.assertIn("The branch: work.", result.stdout)
        self.assertIn(".private/progress/p.org", result.stdout)


def commit(folder: Path, env: dict, message: str) -> tuple:
    """An empty commit in folder: (its full hash, its committer time in epoch seconds)."""
    git = ["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@example.com",
           "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", message], check=True, env=env)
    out = subprocess.run([*git, "log", "-1", "--format=%H %ct"], check=True, env=env,
                         capture_output=True, text=True).stdout.split()
    return out[0], int(out[1])


class ProgressCheck(unittest.TestCase):
    # Claude Code's Stop hook (code.claude.com/docs/en/hooks): input stop_hook_active
    # (true when Claude Code already continues because of a stop hook), cwd; output
    # {"decision": "block", "reason": ...} keeps Claude going with the reason. Codex's Stop
    # (learn.chatgpt.com/docs/hooks) reads the same fields and the same JSON on exit 0.
    def check(self, payload, env: dict = None, script: Path = HOOKS / "progress_check.py"):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(script)], input=data, capture_output=True,
                              text=True, check=False, env=env)

    def stop(self, cwd: Path, **fields) -> dict:
        return {"session_id": "s", "cwd": str(cwd), "hook_event_name": "Stop", "stop_hook_active": False,
                "last_assistant_message": "Done.", **fields}

    def task(self, worktree: bool = True) -> tuple:
        """(repository, folder of branch feat/task, env, progress log of the task)."""
        repo, env = committed_repo(self)
        if worktree:
            folder = linked_worktree(self, repo, env)
        else:
            folder = repo
            subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/task"], check=True, env=env)
        write_notes(repo, {"progress/task.org": time.time()})
        return repo, folder, env, repo / ".private/progress/task.org"

    def assert_lets_stop(self, result):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def assert_blocks(self, result, log: Path, short: str):
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        reply = json.loads(result.stdout)
        self.assertEqual(sorted(reply), ["decision", "reason"])
        self.assertEqual(reply["decision"], "block")
        lines = reply["reason"].splitlines()
        self.assertEqual(len(lines), 3, reply["reason"])
        self.assertIn(log.as_posix(), lines[0])
        self.assertIn(short, lines[0])
        self.assertIn("feat/task", lines[0])
        self.assertIn("commit hash", lines[1])
        self.assertIn("check", lines[1])
        self.assertEqual(lines[2], "Then end the turn.")

    def test_blocks_when_a_commit_is_missing_from_the_log(self):
        for worktree in (True, False):
            with self.subTest(worktree=worktree):
                repo, folder, env, log = self.task(worktree)
                full, when = commit(folder, env, "feat(x): step one")
                log.write_text("* Steps\n** step one\n")
                os.utime(log, (when + 60, when + 60))
                self.assert_blocks(self.check(self.stop(folder), env), log, full[:7])
                log.write_text(f"* Steps\n** step one {full[:7]}: check passed\n")
                os.utime(log, (when + 60, when + 60))
                self.assert_lets_stop(self.check(self.stop(folder), env))

    def test_blocks_when_a_commit_is_newer_than_the_log(self):
        repo, folder, env, log = self.task()
        full, when = commit(folder, env, "feat(x): step one")
        log.write_text(f"** step one {full}\n")
        os.utime(log, (when - 120, when - 120))
        self.assert_blocks(self.check(self.stop(folder), env), log, full[:7])

    def test_a_longer_or_shorter_hash_prefix_counts(self):
        repo, folder, env, log = self.task()
        first, when = commit(folder, env, "one")
        second, _ = commit(folder, env, "two")
        log.write_text(f"one: {first[:12]}\ntwo: commit {second[:7].upper()}\n")
        os.utime(log, (when + 60, when + 60))
        self.assert_lets_stop(self.check(self.stop(folder), env))
        log.write_text(f"one: {first[:6]}\ntwo: {second[:7]}\n")  # 6 characters are not a hash
        os.utime(log, (when + 60, when + 60))
        self.assert_blocks(self.check(self.stop(folder), env), log, first[:7])

    def test_only_the_branchs_own_commits_count(self):
        # The base branch's commits (here init on work) are not the task's steps.
        repo, folder, env, log = self.task()
        log.write_text("* Steps\n")
        self.assert_lets_stop(self.check(self.stop(folder), env))

    def test_lets_the_stop_through_once_continued_or_without_the_flag(self):
        repo, folder, env, log = self.task()
        commit(folder, env, "feat(x): step one")
        log.write_text("* Steps\n")
        os.utime(log, (1, 1))
        # Cursor runs Claude Code's Stop hooks with its own input (status, loop_count) and
        # no cap on follow-ups (cursor.com/docs/reference/third-party-hooks), so a missing
        # flag lets the stop through too.
        for payload in (self.stop(folder, stop_hook_active=True), self.stop(folder, stop_hook_active="false"),
                        {"cwd": str(folder), "status": "completed", "loop_count": 0},
                        {k: v for k, v in self.stop(folder).items() if k != "stop_hook_active"}):
            with self.subTest(payload=payload):
                self.assert_lets_stop(self.check(payload, env))

    def test_lets_the_stop_through_outside_a_task_branch_with_a_log(self):
        repo, env = committed_repo(self)
        commit(repo, env, "two")
        write_notes(repo, {"progress/work.org": 1, "progress/other.org": 1})
        self.assert_lets_stop(self.check(self.stop(repo), env))  # work: not <type>/<slug>
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/task"], check=True, env=env)
        commit(repo, env, "three")
        self.assert_lets_stop(self.check(self.stop(repo), env))  # no .private/progress/task.*
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach"], check=True, env=env)
        write_notes(repo, {"progress/task.org": 1})
        self.assert_lets_stop(self.check(self.stop(repo), env))  # detached HEAD
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        self.assert_lets_stop(self.check(self.stop(outside), env))  # not a repository

    def test_bad_input_lets_the_stop_through(self):
        for payload in ("not json", "", DEEP_JSON, [1], {"stop_hook_active": False},
                        {"stop_hook_active": False, "cwd": 5}, {"stop_hook_active": False, "cwd": "bad\u0000path"},
                        {"stop_hook_active": False, "cwd": "/no/such/folder"}):
            with self.subTest(payload=str(payload)[:40]):
                self.assert_lets_stop(self.check(payload))

    def test_without_session_refresh_the_stop_goes_through(self):
        hooks = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, hooks)
        shutil.copy(HOOKS / "progress_check.py", hooks)
        repo, folder, env, log = self.task()
        commit(folder, env, "feat(x): step one")
        os.utime(log, (1, 1))
        self.assert_lets_stop(self.check(self.stop(folder), env, script=hooks / "progress_check.py"))
        self.assertEqual([p.name for p in hooks.iterdir()], ["progress_check.py"])

    def test_slow_git_stays_within_hook_timeout(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        fake_program(tmp, "git", 'sleep 4\n[ "$1" = branch ] && echo feat/p\nexit 0\n')
        (tmp / ".git").mkdir()
        write_notes(tmp, {"progress/p.org": 1})
        env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
        start = time.monotonic()
        result = self.check(self.stop(tmp), env)
        self.assertLess(time.monotonic() - start, 9.5)
        self.assert_lets_stop(result)


if __name__ == "__main__":
    unittest.main()
