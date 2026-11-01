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

    # Posts on GitHub and patch mail publish text; the rest change what GitHub shows or runs.
    POSTS = ["gh gist create notes.md", "gh gist new -p notes.md", "gh pr comment 12 --body x",
             "gh issue comment 3 --body x", "gh discussion create --title x --body y",
             "gh pr review --approve", "gh pr edit 12 --title x", "gh release edit v1 --notes x",
             "gh issue create --title x --body y", "gh issue new", "git send-email --to a@example.com 0001.patch"]
    OTHER_PUBLISHES = ["gh release upload v1 dist/a.zip", "gh pr ready 12", "gh pr ready --undo",
                       "gh workflow run ci.yml"]

    # gh 2.100.0's help (25 Oct 2026): only read-only or local commands run, any other gh
    # command is blocked, so a write command gh adds later is blocked too. list has the alias
    # ls, pr checkout the alias co, ruleset rs and attestation at; -h is --hostname under gh
    # auth; gh label clone copies labels into a repository. gh co is a user alias (gh's
    # default one, redefinable with gh alias set), so it is not read as pr checkout.
    GH_READS = ["gh pr view 12", "gh pr diff 12", "gh pr checks 12 --watch", "gh pr status", "gh pr ls",
                "gh issue list --state open", "gh issue view 3 --comments", "gh issue status",
                "gh run view 7 --log", "gh run list", "gh repo view", "gh repo clone owner/repo",
                "gh gist clone abc", "gh repo license view mit", "gh repo gitignore list", "gh -R o/r pr list",
                "gh auth status", "gh search issues bug --repo o/r", "gh status", "gh browse -n",
                "gh browse 12 --no-browser", "gh pr create --help", "gh issue close 3 -h", "gh help pr",
                "gh --version", "gh version", "gh", "gh api repos/o/r", "gh release list", "gh label list",
                "gh skills ls", "gh cs list",
                # read or local, by the maintainer's decision on D-v
                "gh pr checkout 12", "gh pr co 12 --detach", "gh run watch 7 --exit-status",
                "gh run download 7 -D out", "gh release download v1 -p '*.zip'", "gh config get editor",
                "gh config get -h github.com git_protocol", "gh variable get X", "gh repo read-file README.md",
                "gh repo read-dir src --ref main", "gh ruleset check main", "gh rs check --default",
                "gh attestation verify a.tgz -R o/r", "gh at verify a.tgz --owner o", "gh completion -s bash",
                "gh licenses", "gh browse", "gh browse 12 --settings", "gh auth status -a",
                "gh auth status -h github.com"]
    GH_OTHERS = ["gh co 12", "gh repo create x --private", "gh repo create x --push=false", "gh repo fork",
                 "gh repo delete o/r --yes", "gh label clone o/r", "gh issue close 1", "gh secret set X",
                 "gh extension install o/gh-x", "gh some-new-command", "gh auth login -h github.com",
                 "gh run rerun 7", "gh repo autolink create x", "gh codespace ports", "gh cs create",
                 "gh config set editor vim", "gh variable set X", "gh attestation download a.tgz",
                 "gh release delete v1", "gh run cancel 7"]

    def test_only_read_only_gh_commands_run(self):
        self.assert_allowed(self.GH_READS)
        for tool in ("claude", "codex", "gemini", "copilot", "cursor"):
            self.assert_blocked(self.GH_OTHERS, tool)
        stderr = run("guard_bash.py", bash("gh repo fork")).stderr
        self.assertIn("gh repo fork is not one of the read-only gh commands", stderr)
        self.assertIn("Pushing and publishing are the maintainer's", stderr)
        self.assertIn("ask the user to run any other", stderr)

    def test_a_flag_before_the_subcommand_makes_a_gh_command_unknown(self):
        # gh's parser takes an unknown flag's next word as the flag's value while it looks
        # for the subcommand, so gh pr -b checkout merge 5 runs gh pr merge 5. A flag other
        # than -R or --repo before the word that makes a command read-only blocks it.
        shifted = ["gh pr -b checkout merge 5", "gh pr -t view merge 5", "gh -x y pr merge 5", "gh pr -- view 1",
                   "gh repo -x autolink list", "gh repo autolink -x list create", "gh -L 5 search x pr merge 1"]
        for tool in ("claude", "codex", "gemini", "copilot", "cursor"):
            self.assert_blocked(shifted, tool)
        stderr = run("guard_bash.py", bash("gh pr -b checkout merge 5")).stderr
        self.assertIn("gh pr with a flag before its subcommand is not one of the read-only gh commands", stderr)
        self.assertIn("Pushing and publishing are the maintainer's", stderr)
        # The repository flag, in each spelling, and flags after the subcommand are fine.
        self.assert_allowed(["gh --repo=o/r pr list", "gh -Ro/r pr view 3", "gh pr --repo o/r view 3",
                             "gh pr list -L 5", "gh search issues -L 5 bug", "gh repo autolink list -R o/r",
                             "gh pr view 3 -- 4", "gh api -X GET repos/o/r"])

    # gh 2.100.0: gh auth token prints the token, gh auth status prints it with -t or
    # --show-token (a flag pflag also reads in a cluster such as -at, or as -t=true), gh auth
    # git-credential get prints it as the password, and gh config get oauth_token prints a
    # token stored in plain text (checked on a scratch GH_CONFIG_DIR with a fake token).
    TOKEN_PRINTS = ["gh auth token", "gh auth token -h github.com", "gh auth token --user me", "gh auth status -t",
                    "gh auth status --show-token", "gh auth status -a -t", "gh auth status -at", "gh auth status -ta",
                    "gh auth status -h github.com -t", "gh auth status -th github.com",
                    "gh auth status --hostname github.com --show-token", "gh auth status --show-token=true",
                    "gh auth status -t=1", "gh auth git-credential get", "gh config get oauth_token",
                    "gh config get -h github.com oauth_token", "gh config get --host=github.com oauth_token",
                    "gh config get -hgithub.com oauth_token",
                    # the last value wins: a first-wins reading would let this one through
                    "gh auth status --show-token=false -t",
                    # gh's parser takes an unknown flag's next word as its value while it looks
                    # for the subcommand, so a flag before it moves the subcommand along
                    "gh auth -h status token -h github.com", "gh auth -h view status -h github.com -t",
                    "gh config -h view get -h github.com oauth_token",
                    # after "--", --help is an argument, not help
                    "gh auth token -- --help"]

    def test_commands_that_print_a_token_are_blocked(self):
        for tool in ("claude", "codex", "gemini", "copilot", "cursor"):
            self.assert_blocked(self.TOKEN_PRINTS, tool)
        for command in self.TOKEN_PRINTS:
            with self.subTest(command=command):
                stderr = run("guard_bash.py", bash(command)).stderr
                self.assertIn("prints the authentication token", stderr)
                self.assertIn("stays in this session's transcript", stderr)
                self.assertIn("ask the user to run any command that needs the token", stderr)
                for other in ("Pushing and publishing", "Gates and published history", "read-only gh commands"):
                    self.assertNotIn(other, stderr)
        # A false value turns the flag off; -h takes the rest of a cluster as its value; help
        # prints help.
        self.assert_allowed(["gh auth status --show-token=false", "gh auth status -t=false", "gh auth status -ah x",
                             "gh auth token --help", "gh auth status -t --help", "gh config get -h github.com user"])

    def test_posts_and_other_publish_forms_are_blocked(self):
        for tool in ("claude", "codex", "gemini", "copilot", "cursor"):
            self.assert_blocked(self.POSTS + self.OTHER_PUBLISHES, tool)
        for command in self.POSTS + self.OTHER_PUBLISHES:
            with self.subTest(command=command):
                stderr = run("guard_bash.py", bash(command)).stderr
                self.assertIn("Pushing and publishing are the maintainer's", stderr)
                if command in self.POSTS:  # what to do instead: hand the text over
                    self.assertIn("write its text in your reply for the user to post", stderr)
                else:
                    self.assertNotIn("in your reply", stderr)

    def test_commands_that_do_not_publish_are_allowed(self):
        self.assert_allowed([
            "git fetch origin", "git pull origin main", "git remote -v", "git log --grep push",
            "echo git push", "grep -rn 'git push' docs", "git subtree split -P lib -b split",
            "git subtree add --prefix push origin main", "git subtree pull --prefix=lib origin main",
            "gh pr view 12", "gh pr list", "gh pr diff 12",
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

    def test_parallel_arguments_are_not_part_of_its_command(self):
        # GNU parallel's command ends at its first argument separator (::: :::: :::+
        # ::::+); what follows are arguments, not refspecs, so the push is only a push.
        for command in ("parallel git push ::: origin", "parallel git push :::: remotes.txt",
                        "parallel git push :::+ a ::: b", "parallel -j2 git push ::::+ a.txt"):
            with self.subTest(command=command):
                result = run("guard_bash.py", bash(command))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("git push publishes commits to a remote", result.stderr)
                self.assertNotIn("deleting a remote ref", result.stderr)

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


class GuardBypassBattery(unittest.TestCase):
    """Ways to push, publish or skip the gates, as git, gh and the shell accept them. Out
    of scope, as DESIGN.org says: one string run by bash -c, sh -c or su -c, eval,
    aliases, scripts, and gh api; those forms are not listed here."""

    BLOCKED = [
        # git's global options before the subcommand
        "git -C /tmp/repo push origin main", "git -C repo -C sub push", "git -c user.name=x push",
        "git -c a.b=c -C repo push --force", "git --git-dir=.git --work-tree=. push", "git --namespace=x push",
        "git --bare push", "git -P push", "git --no-pager -C r push", "git --exec-path=/usr/lib/git-core push",
        "git --literal-pathspecs push", "git --no-optional-locks push", "git --config-env=user.name=U push",
        # assignments and env before the command
        "GIT_DIR=.git git push", "GIT_TRACE=1 GIT_SSH_COMMAND='ssh -v' git push", "env GIT_DIR=.git git push",
        "env -C /tmp git push", "env --chdir=/tmp git push", "env -u HOME -i git push", "/usr/bin/env -- git push",
        # quoting and escapes
        "'git' push", '"git" push', "gi''t push", "git p''ush", 'git "push"', "$'git' $'push'", "\\git push",
        "g\\it pu\\sh", "git push \\\n  --force origin main",
        # chaining, newlines and pipes
        "true; git push", "true && git push", "false || git push", "echo | git push", "true & git push",
        "git status;git push", "git status&&git push", "git status|git push", "true\ngit push", "true\r\ngit push",
        # subshells, groups and substitutions
        "(git push)", "( cd repo && git push )", "{ git push; }", "echo $(git push)", "echo `git push`",
        "cat <(git push)", "x=$(git push)", 'echo "$(git push -f)"',
        # keywords
        "if git push; then :; fi", "while git push; do break; done", "until git push; do :; done",
        "case x in x) git push;; esac", "[[ -n x ]] && git push", "! git push", "time git push",
        # wrappers
        "sudo git push", "sudo -E git push", "sudo -u root -H git push", "sudo -- git push", "doas -u me git push",
        "command git push", "command -p git push", "builtin command git push", "exec git push",
        "exec -a name git push", "nohup git push &", "nohup sudo git push", "env sudo git push",
        "nice -n 10 git push", "timeout -s KILL 10 git push", "timeout -k 5 10 git push", "xargs -n1 git push",
        "setsid -w git push", "flock -w 5 /tmp/lock git push", "find . -maxdepth 0 -exec git push \\;",
        "find . -execdir git push {} +", "watch -n 5 git push", "strace -f -o /tmp/trace git push",
        "ltrace git push", "chroot / git push", "pkexec --user root git push", "runuser -u me -- git push",
        "unbuffer git push", "torsocks git push", "proxychains4 -q -f /etc/p.conf git push",
        "find . -exec find . -exec git push {} + \\;", "find . -execdir sudo find . -ok git push \\; \\;",
        "find . -exec env HUSKY=0 git commit -m x \\;",
        "parallel git push ::: origin", "parallel -j 4 git -C {} push ::: a b",
        "parallel --jobs 2 --halt now,fail=1 git push", "parallel -j4 -k gh pr create --fill ::: x",
        # options that take a value, from GNU parallel 20261022's option table
        "parallel --trim lr git push ::: a", "parallel --sshdelay 2 git push ::: a",
        "parallel --termseq INT,200 git push", "parallel --sql-master sqlite3:///x.db git push",
        "parallel -S host git push ::: a", "parallel --nice 5 --tmpl a=b git push",
        "systemd-run --user --wait git push", "systemd-run -p Nice=5 --unit x -- git push",
        "systemd-run --user --property=CPUQuota=10% git push", "firejail git push",
        "firejail --noprofile --net=none git push", "firejail -- git push", "unshare -r git push",
        "unshare --map-root-user --wd /tmp git push", "unshare -m --propagation private git push",
        "nsenter -t 1 -m git push", "nsenter --target 1 --mount -- git push", "nsenter -t 1 -S 0 -G 0 git push",
        # util-linux 2.42: -S and -G take an optional glued value; older versions a separate one
        "nsenter -t 1 -S git push", "nsenter -t 1 -U -G git push origin main", "nsenter --setuid git push",
        "nsenter -t 1 -S0 git push", "nsenter --setuid=0 --setgid 0 git push",
        # ssh runs its words after the destination as one command line on the remote host
        "ssh host git push", "ssh -p 2222 user@host 'cd repo && git push -f'", "ssh host -t git push origin main",
        "ssh -o BatchMode=yes host gh pr create --fill", "ssh -i ~/.ssh/k -- host git push", "ssh host sudo git push",
        "ssh a ssh b git push", 'ssh host "git commit --no-verify -m x"', "ssh host 'git push; echo \"unterminated'",
        # absolute paths and git's own programs
        "/usr/bin/git push", "/usr/local/bin/git push origin main", "./git push",
        "/usr/lib/git-core/git-push origin main", "git-push origin main", "git-subtree push -P lib origin main",
        "git-lfs push origin main",
        # refspecs and history rewriting
        "git push origin +main", "git push origin +HEAD:refs/heads/main", "git push origin :main",
        "git push --mirror", "git push --all", "git push --tags", "git push -fu origin x",
        "git push --force-with-lease=main:abc origin main", "git push --prune origin", "git push -d origin x",
        # other git commands that publish
        "git send-pack origin main", "git http-push https://example.com/r.git main", "git lfs push origin main",
        "git svn dcommit", "git p4 submit",
        # gh
        "gh pr create --fill", "gh pr new", "gh --repo o/r pr create", "gh pr create -R o/r",
        "gh pr --repo=o/r create", "GH_REPO=o/r gh pr create", "gh pr merge 1 --squash", "gh pr merge --admin 1",
        "gh release create v1", "gh release new v1", "gh repo sync", "gh repo create x --source=. --push",
        "gh repo new x --push",
        "gh co 12", "gh repo create x --private", "gh repo create x --push=false", "gh release delete v1",
        "gh label clone o/r", "gh -R o/r issue close 1", "gh codespace create", "gh new-subcommand-of-tomorrow",
        # commands that print the authentication token, also behind wrappers and in substitutions
        "gh auth token", "sudo gh auth token", "echo $(gh auth token)", "GH_TOKEN=$(gh auth token) make",
        "gh auth token | wl-copy", "ssh host gh auth token", "gh auth status -t", "gh auth status --show-token",
        "gh auth status -a -t", "gh auth status -at", "gh auth status -ta", "gh auth status -th github.com",
        "gh auth status --show-token=True", "env GH_HOST=x gh auth status -t", "gh auth git-credential get",
        "gh config get oauth_token", "gh config get -h github.com oauth_token", "gh config get -hgithub.com oauth_token",
        "gh auth status --show-token=false -t", "gh auth token -- --help",
        # a flag before the subcommand: gh takes the next word as its value (verified: exit 0 before)
        "gh auth -h status token -h github.com", "gh auth -h view status -h github.com -t",
        "gh config -h view get -h github.com oauth_token", "gh pr -b checkout merge 5", "gh pr -t view merge 5",
        "gh gist create a.md", "gh -R o/r issue create -t x -b y", "gh pr --repo o/r comment 1 -b x",
        "gh release upload v1 a.zip --clobber", "gh workflow run ci.yml -f x=1", "gh pr ready",
        "git send-email a.patch", "git -C repo send-email --annotate a.patch", "git-send-email a.patch",
        # gate bypasses
        "git commit --no-verify -m x", "git commit --no-verif -m x", "git commit -n -m x", "git commit -qn -m x",
        "git commit --amend --no-edit -n", "git -C r commit -n -m x", "git merge --no-verify x",
        "git rebase --no-verify main", "git pull --no-verify", "git am --no-verify a.patch",
        "git cherry-pick --no-verify x", "git push --no-verify", "git -c core.hooksPath=/dev/null commit -m x",
        "git -c CORE.HOOKSPATH= commit -m x", "git --config-env=core.hooksPath=V commit -m x",
        "git config core.hooksPath /dev/null", "git config --unset core.hooksPath",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit -m x",
        "HUSKY=0 git commit -m x", "export HUSKY=0; git commit -m x", "env HUSKY=0 git commit -m x",
        "LEFTHOOK=0 git commit -m x", "SKIP=lint git commit -m x", "PRE_COMMIT_SKIP_HOOKS=1 git commit -m x",
        "git-commit --no-verify -m x",
    ]
    NEAR_MISSES = [
        "git status", "git log --grep push", 'echo "git push"', "printf '%s\\n' 'git push'", "git stash push -m wip",
        "git -C push status", "git remote set-url --push origin x", "git config push.default current",
        "git help push", "man git-push", "git log -- push.c", "grep -rn 'gh pr create' docs", "gh pr view 1",
        "gh release view v1", "git lfs ls-files",
        "git svn fetch", "git p4 sync", "find . -name '*.py' -exec grep -n push {} +", "watch -n 5 git status",
        "strace -f git status", "git commit -m 'feat(x): explain git push --force'", "cat <<'X'\ngit push\nX",
        # third-party git-* programs are not git: SKIP= here is the tool's own variable
        "SKIP=changelog git-cliff -o CHANGELOG.md", "git-crypt unlock",
        "find . -type d -exec find {} -maxdepth 1 -name '*.py' \\;",
        "gh pr view 12 --comments", "gh pr checks 12", "gh issue list", "gh issue view 3", "gh gist list",
        "gh gist view abc", "gh workflow list", "gh workflow view ci.yml",
        "gh pr diff 3", "gh run view 7 --log", "gh repo view o/r", "gh repo clone o/r",
        "git format-patch -1", "git log --grep send-email",
        "ssh host git status", "ssh -T git@github.com", "ssh host 'git log --grep push'",
        "ssh -N -L 8080:localhost:80 host", "ssh host echo git push", "ssh -p 2222 host", "parallel gzip ::: a b",
        "systemd-run --user --wait make test", "firejail --net=none curl https://example.com", "unshare -r id",
        "nsenter -t 1 -m ls",
        # read or local gh commands (the maintainer's decision on D-v), and token near misses
        "gh pr checkout 12", "gh pr co 12 --force", "gh -R o/r pr checkout 3 --worktree ../pr3",
        "gh run watch 7", "gh run download 7 -n dist", "gh release download v1 -O -", "gh config get git_protocol",
        "gh variable get X -e prod", "gh repo read-file README.md -R o/r", "gh repo read-dir", "gh ruleset check",
        "gh rs check main", "gh attestation verify a.tgz -o org", "gh at verify a.tgz -R o/r", "gh completion -s fish",
        "gh licenses", "gh browse", "gh browse main.go:12 --blame", "gh auth status", "gh auth status -a",
        "gh auth status -h github.com", "gh auth status --show-token=false", "gh auth status -ah github.com",
        "gh auth token --help", "gh config get -h github.com user", "gh config list",
        "gh --repo=o/r pr checkout 3", "gh -Ro/r run watch 7", "gh pr --repo o/r view 3", "gh pr view 3 -- 4",
    ]

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("guard_under_test", HOOKS / "guard_bash.py")
        cls.guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.guard)

    def exit_code(self, command: str) -> int:
        """main() in-process, as Claude Code runs it, so the battery stays fast."""
        with mock.patch.object(sys, "argv", ["guard_bash.py", "--tool", "claude"]), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(bash(command)))), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return self.guard.main()

    def test_every_bypass_is_blocked(self):
        self.assertGreaterEqual(len(self.BLOCKED), 90)
        for command in self.BLOCKED:
            with self.subTest(command=command):
                self.assertEqual(self.exit_code(command), 2)

    def test_deep_nesting_is_checked_quickly(self):
        # Each nested find or ssh would read the rest of the text again (quadratic time);
        # past a few levels, or past a budget of remote text, the rest is split roughly at
        # git and gh, so a push still shows.
        for depth in (3, 20000):
            with self.subTest(depth=depth):
                start = time.monotonic()
                self.assertEqual(self.exit_code("find . -exec " * depth + "git push"), 2)
                self.assertLess(time.monotonic() - start, 2)
        # Following nested ssh calls costs less than parsing the text once more.
        start = time.monotonic()
        commands = self.guard.parse_commands("ssh a " * 40000 + "git push")
        parse = time.monotonic() - start
        start = time.monotonic()
        self.assertIn(self.guard.PUSH_REASON, self.guard.command_reasons(commands))
        self.assertLess(time.monotonic() - start, parse)

    def test_near_misses_pass(self):
        for command in self.NEAR_MISSES:
            with self.subTest(command=command):
                self.assertEqual(self.exit_code(command), 0)

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

    def edited(self, name: str, content: str) -> tuple:
        """Write content to name in the project; return (its path, a Claude Code Edit payload)."""
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path, {"tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": "x",
                                                          "new_string": "y"}}

    BROKEN = {"bad.py": ("def f(:\n    return 1\n", "Python syntax error in {path}:1"),
              "bad.json": ('{"a": 1\n "b": 2}\n', "JSON syntax error in {path}:2:2"),
              # // and /* inside a string are text, not comments.
              "links.json": ('{"url": "https://example.com/*", "a": "\\"//"\n "b": 2}\n',
                             "JSON syntax error in {path}:2:2"),
              # A string that never closes: the // of a later URL is not a comment, and
              # the error is reported where it is, past the stripped text.
              "package.json": ('{\n  "name": "x",\n  "homepage": https://example.com",\n  "a": 1\n}\n',
                               "JSON syntax error in {path}:3:15"),
              "oneline.json": ('{"name": "x, "homepage": "https://example.com"}\n', "JSON syntax error in {path}:1:"),
              # Without a comment, a trailing comma is an error of strict JSON.
              "trailing.json": ('{"a": [1, 2],\n "b": 3,\n}\n', "JSON syntax error in {path}:"),
              "bad.toml": ('[tool]\nname = "x\n', "TOML syntax error in {path}")}

    def test_reports_a_syntax_error_in_the_edited_file(self):
        # The whole file is checked, since an edit can break code around the new text.
        for name, (content, report) in self.BROKEN.items():
            if name.endswith(".toml") and sys.version_info < (3, 11):
                continue  # tomllib arrived in Python 3.11
            with self.subTest(name=name):
                path, payload = self.edited(name, content)
                result = run("after_edit.py", payload)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(report.format(path=path), result.stderr)
        self.assertIn(f"(checked with Python {sys.version_info[0]}.{sys.version_info[1]})",
                      run("after_edit.py", self.edited("bad.py", "def f(:\n")[1]).stderr)

    def test_valid_files_and_files_with_comments_by_convention_pass(self):
        cases = {"good.py": "def f(x):\n    return '\\d'  # an invalid escape only warns\n",
                 "good.json": '\ufeff{"a": [1, 2]}\n',  # a byte order mark
                 "good.toml": '[tool]\nname = "x"\n',
                 "tsconfig.json": '{\n  // comments are allowed here\n  "compilerOptions": {},\n}\n',
                 "tsconfig.base.json": "{ /* allowed */ }\n",
                 ".vscode/settings.json": '{\n  // allowed\n  "a": 1,\n}\n',
                 # The dev container spec's file at the project root.
                 ".devcontainer.json": '{\n  "image": "x", // allowed\n}\n',
                 # Other tools read comments too (turbo, cspell...): a comment marks such a file.
                 "turbo.json": '{\n  // allowed\n  "tasks": {},\n}\n',
                 "cspell.json": '{ "words": ["a"], /* allowed */ }\n',
                 "biome.json": '{\n  "files": ["a", "b",], // trailing commas too\n  "x": "http://y",\n}\n',
                 "notes.txt": "{not json",
                 "missing.json": None}
        for name, content in cases.items():
            with self.subTest(name=name):
                path, payload = self.edited(name, content or "")
                if content is None:
                    path.unlink()
                result = run("after_edit.py", payload)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_a_broken_json_file_is_checked_quickly_whatever_its_strings(self):
        # Escaped quotes in a string that never closes: a pattern that backtracks takes
        # minutes on this file (quadratic), past the 60 s hook timeout.
        path, payload = self.edited("quotes.json", '{"a": "' + '\\"' * 20000 + "\n}\n")
        start = time.monotonic()
        result = run("after_edit.py", payload)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(f"JSON syntax error in {path}", result.stderr)

    def test_syntax_errors_reach_each_agent(self):
        path, _ = self.edited("bad.json", "[1,,2]")
        target = str(path)
        cases = {
            "gemini": {"tool_name": "replace", "tool_input": {"file_path": target, "new_string": "x"}},
            "codex": {"tool_name": "apply_patch", "cwd": str(self.tmp),
                      "tool_input": {"command": "*** Begin Patch\n*** Update File: bad.json\n@@\n-[1]\n+[1,,2]\n"
                                                "*** End Patch\n"}},
            "cursor": {"file_path": target, "edits": [{"old_string": "a", "new_string": "b"}]},
        }
        for tool, payload in cases.items():
            with self.subTest(tool=tool):
                result = run("after_edit.py", payload, tool)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(f"JSON syntax error in {target}:1:4", result.stderr)
        copilot = run("after_edit.py", {"toolName": "edit", "toolArgs": json.dumps({"path": target, "new_str": "x"})},
                      "copilot")
        self.assertEqual((copilot.returncode, copilot.stderr), (0, ""))
        self.assertIn("JSON syntax error", json.loads(copilot.stdout)["additionalContext"])
        agy = run("after_edit.py", {"toolCall": {"name": "replace_file_content",
                                                 "args": {"TargetFile": target, "ReplacementContent": "x"}}},
                  "antigravity")
        self.assertEqual((agy.returncode, agy.stdout.strip()), (0, "{}"))
        self.assertIn("JSON syntax error", agy.stderr)

    def test_toml_is_skipped_without_tomllib(self):
        # Python 3.9 and 3.10 (CI runs 3.9) have no tomllib: TOML goes unchecked, the rest
        # is still checked. In-process, with the module hidden as it is on those versions.
        toml, toml_payload = self.edited("bad.toml", self.BROKEN["bad.toml"][0])
        _, json_payload = self.edited("bad.json", self.BROKEN["bad.json"][0])
        with mock.patch.dict(sys.modules, {"tomllib": None}):
            spec = importlib.util.spec_from_file_location("after_edit_without_tomllib", HOOKS / "after_edit.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertIsNone(module.tomllib)
        for payload, code in ((toml_payload, 0), (json_payload, 2)):
            stderr = io.StringIO()
            with mock.patch.object(sys, "argv", ["after_edit.py", "--tool", "claude"]), \
                    mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                    contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), code, stderr.getvalue())


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
        # After a rebase every hash changes: mapping old to new is the whole fix.
        self.assertIn("if a rebase only changed their hashes", lines[1])
        self.assertIn("each old hash with its new one is enough", lines[1])
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

    def test_commits_a_remote_branch_holds_are_not_asked_for(self):
        # A commit the maintainer already pushed (a remote-tracking branch holds it) is
        # not a step of the open task, whether or not the log names it.
        repo, folder, env, log = self.task()
        full, _ = commit(folder, env, "feat(x): step one")
        log.write_text("* Steps\n")
        os.utime(log, (1, 1))
        self.assert_blocks(self.check(self.stop(folder), env), log, full[:7])
        subprocess.run(["git", "-C", str(folder), "update-ref", "refs/remotes/origin/feat/task", "HEAD"],
                       check=True, env=env)
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


class ClaimCheck(unittest.TestCase):
    # Claude Code's Stop hook (code.claude.com/docs/en/hooks): input transcript_path,
    # stop_hook_active, last_assistant_message; "the transcript file isn't guaranteed to
    # include the final message at Stop time on all versions". The transcript's shape is
    # not documented; these records follow the JSON lines Claude Code writes: assistant
    # records hold text and tool_use blocks, user records tool_result blocks (is_error)
    # and toolUseResult (bashEditDiff when a Bash call changed files).
    CLAIM = "Fixed the parser; all 12 tests pass."

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.calls = 0

    def call(self, name: str, given: dict, output: str = "", failed: bool = False, extra: dict = None,
             answered: bool = True) -> list:
        """A tool call and, when answered, its result."""
        self.calls += 1
        ident = f"toolu_{self.calls:03d}"
        records = [{"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": name, "input": given}]}}]
        if answered:
            records.append({"type": "user", "isSidechain": False, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": ident, "content": output, "is_error": failed}]},
                "toolUseResult": extra if extra is not None else {"stdout": output, "stderr": "", "interrupted": False}})
        return records

    def edit(self, path: str = "/w/src/app.py", tool: str = "Edit", failed: bool = False) -> list:
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        return self.call(tool, {key: path, "old_string": "a", "new_string": "b"},
                         "<tool_use_error>String not found</tool_use_error>" if failed else "The file was updated.",
                         failed)

    def tests(self, passed: bool = True, command: str = "python3 -m pytest -q", output: str = None) -> list:
        if output is None:
            output = "12 passed in 0.31s" if passed else "Exit code 1\nFAILED tests/test_app.py::test_x\n1 failed, 11 passed"
        return self.call("Bash", {"command": command, "description": "Run the tests"}, output, failed=not passed)

    @staticmethod
    def said(text: str) -> list:
        return [{"type": "assistant", "isSidechain": False,
                 "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}]

    def transcript(self, *parts, final: str = CLAIM) -> str:
        """A transcript of the parts, ending with the final message unless final is None."""
        records = [record for part in parts for record in part] + (self.said(final) if final is not None else [])
        path = self.tmp / f"session-{len(list(self.tmp.iterdir()))}.jsonl"  # a new file for each
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        return str(path)

    def check(self, transcript, message: str = CLAIM, **fields) -> subprocess.CompletedProcess:
        payload = {"session_id": "s", "transcript_path": transcript, "cwd": "/w", "permission_mode": "default",
                   "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": message,
                   "background_tasks": [], "session_crons": [], **fields}
        return subprocess.run([sys.executable, str(HOOKS / "claim_check.py")], input=json.dumps(payload),
                              capture_output=True, text=True, check=False, timeout=20)

    def assert_lets_stop(self, result):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def assert_blocks(self, result, detail: str):
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        reply = json.loads(result.stdout)
        self.assertEqual(sorted(reply), ["decision", "reason"])
        self.assertEqual(reply["decision"], "block")
        self.assertIn("says the tests pass", reply["reason"])
        self.assertIn(detail, reply["reason"])
        self.assertIn("Run the tests now and report their result", reply["reason"])
        self.assertIn("say plainly that they were not run", reply["reason"])

    BEFORE = "every test run came before your last file edit"
    FAILED = "the last test runs failed"

    def test_a_passing_run_after_the_last_edit_supports_the_claim(self):
        self.assert_lets_stop(self.check(self.transcript(self.tests(False), self.edit(), self.tests())))
        for command, output in (
                ("cd /w && timeout 600 python3 -m unittest discover -s tests 2>&1 | tail -3", "Ran 12 tests in 0.5s\n\nOK"),
                ("go test ./...", "ok  \texample.com/app\t0.012s"), ("cargo test", "test result: ok. 5 passed; 0 failed"),
                ("npm test", "Tests:       4 passed, 4 total"), ("make -C build check", "PASS: 4"),
                ("ctest --test-dir build", "100% tests passed, 0 tests failed out of 2"),
                ("./gradlew test", "BUILD SUCCESSFUL in 3s")):
            with self.subTest(command=command):
                self.assert_lets_stop(self.check(self.transcript(self.edit(), self.tests(True, command, output))))

    def test_a_run_only_before_the_last_edit_blocks_once(self):
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            with self.subTest(tool=tool):
                transcript = self.transcript(self.tests(), self.edit(tool=tool))
                self.assert_blocks(self.check(transcript), self.BEFORE)
                self.assert_lets_stop(self.check(transcript, stop_hook_active=True))  # continued once already

    NONE = "no test ran after your last file edit"

    def test_an_edit_with_no_test_run_at_all_blocks_once(self):
        # The maintainer's decision of 29 October 2026: block when, after the last edit, no test run
        # came, whether or not a run came before it.
        for label, parts in (("edit only", (self.edit(),)),
                             ("edit, then a quiet command", (self.edit(), self.tests(True, "git status --short", "")))):
            with self.subTest(label=label):
                transcript = self.transcript(*parts)
                self.assert_blocks(self.check(transcript), self.NONE)
                self.assert_lets_stop(self.check(transcript, stop_hook_active=True))  # continued once already

    def test_a_failing_run_blocks(self):
        for parts in ((self.edit(), self.tests(False)), (self.tests(False),),
                      (self.edit(), self.tests(False), self.tests(False)),
                      # a pipe into tail hides the exit status, not the runner's summary
                      (self.edit(), self.tests(True, "python3 -m unittest 2>&1 | tail -3",
                                               "Ran 5 tests in 0.1s\n\nFAILED (failures=1)"))):
            with self.subTest(parts=len(parts)):
                self.assert_blocks(self.check(self.transcript(*parts)), self.FAILED)

    def test_a_run_is_judged_by_its_runners_summary(self):
        # Output lines that mention failures or errors (a test's own log, jest's
        # console.error, Go's t.Log, pytest --lf's header) do not make a pass a failure.
        passing = {
            "python3 -m pytest --lf": "run-last-failure: rerun previous 2 failures\ntests/test_a.py ....\n"
                                      "============================== 4 passed in 0.21s ===============================",
            "python3 -m pytest -rA": "tests/test_parse.py::test_report PASSED\n----- Captured log call -----\n"
                                     "WARNING parse: found 2 errors in input\n===== 1 passed in 0.05s =====",
            "npx jest": "  console.error\n    Error: 3 errors while loading fixtures\n\n      at Object.<anonymous> "
                        "(src/a.test.js:4:13)\n\nPASS src/a.test.js\nTest Suites: 1 passed, 1 total\n"
                        "Tests:       4 passed, 4 total",
            "go test ./...": "=== RUN   TestRetry\n    retry_test.go:12: attempt 1 failed, retrying\n"
                             "--- PASS: TestRetry (0.00s)\nPASS\nok  \texample.com/app\t0.012s"}
        for command, output in passing.items():
            with self.subTest(command=command):
                self.assert_lets_stop(self.check(self.transcript(self.edit(), self.tests(True, command, output))))
        # A pipe into tail hides the exit status; the summary still tells a failure.
        failing = {
            "python3 -m pytest | tail -2": "FAILED tests/test_a.py::test_x - assert 1 == 2\n"
                                           "========= 1 failed, 3 passed in 0.30s =========",
            "go test ./... | tail -3": "--- FAIL: TestX (0.00s)\nFAIL\nFAIL\texample.com/app\t0.010s",
            "cargo test 2>&1 | tail -1": "test result: FAILED. 4 passed; 1 failed; 0 ignored; 0 measured",
            "npx jest 2>&1 | tail -1": "Tests:       1 failed, 3 passed, 4 total"}
        for command, output in failing.items():
            with self.subTest(command=command):
                self.assert_blocks(self.check(self.transcript(self.edit(), self.tests(True, command, output))),
                                   self.FAILED)
        # The call failed but the runner's summary says the tests passed: a later command
        # of the chain failed, so the outcome is unknown and the stop goes through.
        chained = self.call("Bash", {"command": "python3 -m pytest -q && git diff --exit-code"},
                            "Exit code 1\n.....\n5 passed in 0.20s\ndiff --git a/x b/x", failed=True)
        self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), chained)))

    def test_the_last_run_after_the_last_edit_decides(self):
        # A later failing run wins over an earlier pass, and a later pass over an earlier
        # failure; a subagent call (outcome unknown) counts only when it comes last.
        gates = self.call("Agent", {"subagent_type": "gate-runner", "prompt": "Run the gates."}, "PASS")
        for parts, blocks in (((self.edit(), self.tests(), self.tests(False)), True),
                              ((self.edit(), self.tests(False), self.tests()), False),
                              ((self.edit(), gates, self.tests(False)), True),
                              ((self.edit(), self.tests(False), gates), False)):
            with self.subTest(parts=[record["message"]["content"][0].get("name") for part in parts
                                     for record in part[:1]], blocks=blocks):
                result = self.check(self.transcript(*parts))
                (self.assert_blocks(result, self.FAILED) if blocks else self.assert_lets_stop(result))

    def test_no_claim_lets_the_stop_through(self):
        # Each transcript would block a claim: only the message lets the stop through.
        for message in ("Done.", "The tests do not pass yet: 2 failures remain.", "I did not run the tests.",
                        "If the tests pass, merge it.", "Run the tests to make sure the tests pass.",
                        "The tests were not run after the last edit."):
            with self.subTest(message=message):
                self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), final=message), message))

    def test_claims_in_their_usual_words_are_checked(self):
        for message in ("All tests pass.", "Tests passed.", "The suite is green.", "189 tests OK",
                        "Gates: validate OK, 189 tests OK, build OK.", "The test suite passes.",
                        "All 12 tests are passing now.", "The hook tests pass."):
            with self.subTest(message=message):
                self.assert_blocks(self.check(self.transcript(self.tests(), self.edit(), final=message), message),
                                   self.BEFORE)

    def test_continued_or_without_the_flag_lets_the_stop_through(self):
        # Cursor runs Claude Code's Stop hooks with its own input (no stop_hook_active) and
        # no cap on follow-ups (cursor.com/docs/reference/third-party-hooks).
        transcript = self.transcript(self.tests(), self.edit())
        for fields in ({"stop_hook_active": True}, {"stop_hook_active": "false"}, {"stop_hook_active": None}):
            with self.subTest(fields=fields):
                self.assert_lets_stop(self.check(transcript, **fields))
        payload = {"transcript_path": transcript, "last_assistant_message": self.CLAIM, "status": "completed",
                   "loop_count": 0}
        result = subprocess.run([sys.executable, str(HOOKS / "claim_check.py")], input=json.dumps(payload),
                                capture_output=True, text=True, check=False, timeout=20)
        self.assert_lets_stop(result)

    def test_a_lagging_or_unknown_transcript_lets_the_stop_through(self):
        cases = {
            "final message not written yet": self.transcript(self.tests(), self.edit(), final=None),
            "last text before the last call": self.transcript(self.said("Running the tests."), self.tests(),
                                                              self.edit(), final=None),
            "another final message": self.transcript(self.tests(), self.edit(), final="Something else."),
            "no file edit to compare with": self.transcript(self.tests(True, "git status --short", "")),
        }
        codex = self.tmp / "rollout.jsonl"
        codex.write_text("".join(json.dumps(r) + "\n" for r in (
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": self.CLAIM}]}})))
        cases["another tool's format"] = str(codex)
        for label, transcript in cases.items():
            with self.subTest(label=label):
                self.assert_lets_stop(self.check(transcript))

    def test_unreadable_transcripts_let_the_stop_through(self):
        junk = self.tmp / "junk.jsonl"
        junk.write_bytes(bytes(range(256)) * 100)
        text = self.tmp / "text.jsonl"
        text.write_text("not json\n" + DEEP_JSON + "\n[1, 2]\n\"a string\"\n")
        empty = self.tmp / "empty.jsonl"
        empty.write_text("")
        fifo = self.tmp / "fifo.jsonl"
        os.mkfifo(fifo)  # opening it for reading would wait for a writer
        unreadable = [str(self.tmp / "missing.jsonl"), str(self.tmp), "/dev/zero", str(fifo), str(junk), str(text),
                      str(empty), "", 5, None, ["a"], "bad\u0000path"]
        if os.geteuid() != 0:  # root reads a file of mode 0
            locked = self.tmp / "locked.jsonl"
            locked.write_text(Path(self.transcript(self.tests(), self.edit())).read_text())
            locked.chmod(0)
            unreadable.append(str(locked))
        start = time.monotonic()
        for transcript in unreadable:
            with self.subTest(transcript=transcript):
                self.assert_lets_stop(self.check(transcript))
        self.assertLess(time.monotonic() - start, 15)
        for payload in ("not json", "", DEEP_JSON, "[1]", json.dumps({"stop_hook_active": False})):
            with self.subTest(payload=payload[:20]):
                self.assert_lets_stop(subprocess.run([sys.executable, str(HOOKS / "claim_check.py")], input=payload,
                                                     capture_output=True, text=True, check=False, timeout=20))

    def test_a_huge_transcript_is_read_within_its_budget(self):
        # 20 MB of other work: evidence older than the tail is not read, so it cannot
        # block; evidence in the tail still counts.
        filler = [record for index in range(2000) for record in self.said(f"note {index}: " + "x" * 10000)]
        for parts, blocks in (((self.tests(), self.edit(), filler), False), ((filler, self.tests(), self.edit()), True)):
            with self.subTest(blocks=blocks):
                transcript = self.transcript(*parts)
                self.assertGreater(Path(transcript).stat().st_size, 20_000_000)
                start = time.monotonic()
                result = self.check(transcript)
                self.assertLess(time.monotonic() - start, 3)
                (self.assert_blocks(result, self.BEFORE) if blocks else self.assert_lets_stop(result))
        one_line = self.tmp / "one-line.jsonl"
        one_line.write_text('{"type": "assistant", "text": "' + "x" * 20_000_000)
        start = time.monotonic()
        self.assert_lets_stop(self.check(str(one_line)))
        self.assertLess(time.monotonic() - start, 3)

    def test_a_possible_run_after_the_last_edit_lets_the_stop_through(self):
        # Tests may run in a subagent (the gates skill's gate-runner), in the background or
        # in a call whose result is missing: the claim is not checked then.
        for label, later in (
                ("subagent", self.call("Agent", {"subagent_type": "gate-runner", "prompt": "Run the gates."}, "PASS")),
                ("background", self.call("Bash", {"command": "python3 -m pytest", "run_in_background": True},
                                         "Command running in background with ID: b1")),
                ("no result", self.call("Bash", {"command": "python3 -m pytest"}, answered=False))):
            with self.subTest(label=label):
                self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), later)))
        # A run started in the background before the last edit supports no claim about the edit: with
        # nothing after the edit, the claim blocks (the maintainer's decision of 29 October 2026).
        background = self.call("Bash", {"command": "python3 -m pytest", "run_in_background": True},
                               "Command running in background with ID: b2")
        self.assert_blocks(self.check(self.transcript(background, self.edit())), self.NONE)

    def failing(self, command: str) -> list:
        return self.call("Bash", {"command": command}, "Exit code 1\nsomething went wrong", failed=True)

    def test_a_quiet_command_showing_a_runner_summary_counts_as_that_run(self):
        # The maintainer's decision: git commit's hooks may run the tests, and any quiet
        # command may show a runner's summary, so output with a summary (pre-commit's per-hook
        # Passed and Failed lines too) is judged as a run with that outcome; output without
        # one leaves the command quiet.
        commit = {"command": "git commit -m 'feat: x'"}
        hooks_passed = self.call("Bash", commit, "pytest" + "." * 60 + "Passed\n[feat/x 1a2b3c4] feat: x\n"
                                 " 1 file changed, 2 insertions(+)")
        self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), hooks_passed)))
        for label, output in (("runner summary", "pytest" + "." * 60 + "Failed\n- hook id: pytest\n- exit code: 1\n\n"
                                                 "1 failed, 3 passed in 0.30s"),
                              ("pre-commit line", "ruff" + "." * 62 + "Failed\n- hook id: ruff\n- exit code: 1")):
            with self.subTest(failed=label):
                hooks_failed = self.call("Bash", commit, output, failed=True)
                self.assert_blocks(self.check(self.transcript(self.tests(), self.edit(), hooks_failed)), self.FAILED)
        shown = self.call("Bash", {"command": "cat test.log"}, "===== 4 passed in 0.21s =====")
        self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), shown)))
        for label, output in (("no runner output", "[feat/x 1a2b3c4] feat: x\n 1 file changed"),
                              ("hook skipped", "pytest" + "." * 41 + "(no files to check)Skipped\n[feat/x 1a2b3c4] x")):
            with self.subTest(quiet=label):
                plain = self.call("Bash", commit, output)
                self.assert_blocks(self.check(self.transcript(self.tests(), self.edit(), plain)), self.BEFORE)

    def test_an_unknown_command_that_changes_files_is_an_edit_then_a_doubt(self):
        # pre-commit run --all-files may reformat a file and then run the tests: an edit,
        # then a run of unknown outcome. A quiet command that changes files is an edit only.
        def changing(command, output, failed=False):
            return self.call("Bash", {"command": command}, output, failed=failed, extra={
                "stdout": output, "stderr": "", "interrupted": False,
                "bashEditDiff": {"changedFiles": ["/w/src/app.py"], "files": [], "moreFiles": 0}})
        reformat = changing("pre-commit run --all-files", "black" + "." * 63 + "Failed\n- files were modified by "
                            "this hook\npytest" + "." * 62 + "Passed", failed=True)
        self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), reformat)))
        copied = changing("cp /tmp/app.py src/app.py", "")
        self.assert_blocks(self.check(self.transcript(self.tests(), copied)), self.BEFORE)

    def test_powershell_is_read_like_bash_and_an_mcp_tool_may_run_tests(self):
        # Claude Code's PowerShell tool takes its command in the same fields as Bash
        # (code.claude.com/docs/en/tools-reference, PowerShell tool); an MCP tool's effect is
        # unknown, so it may have run tests (the maintainer's decision); the other built-in
        # tools (Read, Grep...) run none.
        powershell = self.call("PowerShell", {"command": "python -m pytest"},
                               "Exit code 1\n1 failed, 2 passed in 0.20s", failed=True)
        self.assert_blocks(self.check(self.transcript(self.tests(), self.edit(), powershell)), self.FAILED)
        mcp = self.call("mcp__ci__run_suite", {"suite": "unit"}, "ok")
        self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), mcp)))
        read = self.call("Read", {"file_path": "/w/src/app.py"}, "1\tx = 1")
        self.assert_blocks(self.check(self.transcript(self.tests(), self.edit(), read)), self.BEFORE)

    def test_a_launcher_s_own_options_come_before_the_program(self):
        # uv run's options that take a value (docs.astral.sh/uv/reference/cli, uv run) and
        # npx's (npm exec --help) are skipped with their value; npx -c runs its text; pnpm,
        # npm and yarn exec or dlx and bunx launch the program after them.
        for command in ("uv run --with pytest-cov pytest", "uv --directory app run -p 3.12 --frozen pytest",
                        "uv run -m pytest", "npx --yes jest", "npx --package=jest jest --ci", "npx -c 'jest --ci'",
                        "pnpm exec vitest run", "npm exec -- jest", "yarn exec jest", "bunx vitest", "bun x vitest"):
            with self.subTest(command=command):
                self.assert_blocks(self.check(self.transcript(self.edit(), self.failing(command))), self.FAILED)
        for command in ("uv run --with pytest-cov python gen.py", "uv sync", "npx --yes prettier --write ."):
            with self.subTest(command=command):
                self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), self.failing(command))))

    def test_a_build_tool_runs_tests_only_through_a_target_named_so(self):
        # Option values (make -C, -f; ninja -C; mvn -pl; gradle -p, -x; just --justfile) and
        # VAR=value words are not targets, and cmake builds only its --target or -t values.
        # A build whose targets name no test may still run some: kind 3, the stop goes
        # through even when it failed; a target named test, check... is a known run.
        for command in ("ninja -C build-tests", "cmake -B build-test -S .", "make -C tests clean",
                        "mvn -pl checkstyle compile", "gradle build -x test", "cmake --build build-test",
                        "make -f test.mk all", "just --justfile test.just build", "make -j 4", "make CHECK=1",
                        "ninja -t targets test"):
            with self.subTest(kind=3, command=command):
                self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), self.failing(command))))
        for command in ("make -C build check", "ninja -C build test", "cmake --build build --target test",
                        "cmake --build b -t check", "cmake --build b --target all check", "mvn -pl core verify",
                        "./gradlew -p app test", "make -j4 test", "make -j 4 check", "make test CC=clang",
                        "rake test", "just test"):
            with self.subTest(kind=1, command=command):
                self.assert_blocks(self.check(self.transcript(self.edit(), self.failing(command))), self.FAILED)

    def test_commands_after_the_last_edit_fall_in_three_kinds(self):
        # The maintainer's rule: (1) a known test runner, or a script or build target named
        # test, gate, check or verify, counts by its outcome; (2) a command that certainly
        # runs no tests never counts; (3) anything else may have run tests: the outcome is
        # unknown and the stop goes through. Only a known runner can block on its failure.
        runners = ("sh tools/gates.sh", "./run_tests.sh", "python3 tools/check.py", "bash -c 'cd w && pytest -q'",
                   "uv run pytest", "npx jest", "npm run test:unit", "make -C build check", "mvn -q verify",
                   "cmake --build build --target test", "env CI=1 timeout 600 python3 -m pytest",
                   "cd /w && python3 -m unittest discover -s tests 2>&1 | tail -3", "yarn vitest run")
        for command in runners:
            with self.subTest(kind=1, command=command):
                self.assert_blocks(self.check(self.transcript(self.edit(), self.failing(command))), self.FAILED)
        quiet = ("git status", "git add tests/test_a.py", "git commit -m 'fix tests'", "git -C /w diff --stat",
                 "git diff -- tests/test_unittest.py", "git log --grep verify", "git show HEAD", "git restore src/a.py",
                 "git stash", "cat tests/x.py | head -5", "ls tests", "tail -5 log.txt", "wc -l a.py",
                 "grep -rn pytest docs", "rg pytest", "find tests -name '*.py'",
                 "find . -name '*.py' -exec grep -n pytest {} +", "echo make test", "printf done", "mkdir -p out",
                 "cp a b", "mv a b", "sed -n 1,5p a.py", "true", "cd /w && git status", "bash -c 'git status'")
        for command in quiet:
            with self.subTest(kind=2, command=command):
                later = self.call("Bash", {"command": command}, "")
                self.assert_blocks(self.check(self.transcript(self.tests(), self.edit(), later)), self.BEFORE)
        unknown = ("test -f setup.cfg", "python3 -c \"print('test')\"", "date", "sed -i s/a/b/ a.py", "npm install",
                   "python3 gen.py", "find . -name '*.js' -exec node {} \\;", "git checkout -b x", "sed -n -i 1p a.py",
                   "cd /w && python3 gen.py")
        for command in unknown:
            with self.subTest(kind=3, command=command):
                self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), self.failing(command))))
        # Runners the hook does not know (the second review's list) pass through as kind 3.
        for command in ("node --test", "uv run --with pytest-cov pytest", "xcodebuild test -scheme App",
                        "php artisan test", "bin/rails test", "hatch test", "pnpm exec vitest run", "gotestsum",
                        "yarn workspace app test"):
            with self.subTest(review=command):
                later = self.call("Bash", {"command": command}, "done")
                self.assert_lets_stop(self.check(self.transcript(self.tests(), self.edit(), later)))
        # A failed known run decides unless a command of unknown kind follows it.
        for later, blocks in ((self.call("Bash", {"command": "date"}, "Thu"), False),
                              (self.call("Bash", {"command": "git status"}, ""), True)):
            with self.subTest(after_the_failure=later[0]["message"]["content"][0]["input"]["command"]):
                result = self.check(self.transcript(self.edit(), self.tests(False), later))
                (self.assert_blocks(result, self.FAILED) if blocks else self.assert_lets_stop(result))

    def test_without_the_guard_the_stop_goes_through(self):
        # The hook reads commands with the guard's shell parser; a missing or broken copy
        # lets every stop through, and importing it leaves no cache in the hooks folder.
        hooks = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, hooks)
        shutil.copy(HOOKS / "claim_check.py", hooks)
        transcript = self.transcript(self.tests(), self.edit())
        self.assert_blocks(self.check(transcript), self.BEFORE)  # with the guard next to it
        alone = subprocess.run([sys.executable, str(hooks / "claim_check.py")], capture_output=True, text=True,
                               timeout=20, check=False, input=json.dumps({
                                   "transcript_path": transcript, "stop_hook_active": False,
                                   "last_assistant_message": self.CLAIM}))
        self.assert_lets_stop(alone)
        shutil.copy(HOOKS / "guard_bash.py", hooks)
        paired = subprocess.run([sys.executable, str(hooks / "claim_check.py")], capture_output=True, text=True,
                                timeout=20, check=False, input=json.dumps({
                                    "transcript_path": transcript, "stop_hook_active": False,
                                    "last_assistant_message": self.CLAIM}))
        self.assert_blocks(paired, self.BEFORE)
        self.assertEqual(sorted(p.name for p in hooks.iterdir()), ["claim_check.py", "guard_bash.py"])

    def test_shell_edits_count_and_notes_do_not(self):
        def shell(command, changed, more=0, output=""):
            return self.call("Bash", {"command": command}, output, extra={
                "stdout": output, "stderr": "", "interrupted": False,
                "bashEditDiff": {"changedFiles": changed, "files": [], "moreFiles": more}})
        # A quiet command that changes files is an edit (an unknown one is an edit and then a
        # doubt: test_an_unknown_command_that_changes_files_is_an_edit_then_a_doubt).
        for label, later in (("changed file", shell("cp /tmp/app.py src/app.py", ["/w/src/app.py"])),
                             ("more files", shell("mv build/gen src/gen", [], more=3))):
            with self.subTest(label=label):
                self.assert_blocks(self.check(self.transcript(self.tests(), later)), self.BEFORE)
        # A test run that changes files (snapshots) is a run; a command that changes nothing
        # is not an edit; a failed edit changed nothing.
        for label, parts in (
                ("snapshot run", (self.tests(False), self.edit(),
                                  shell("python3 -m pytest --snapshot-update", ["/w/tests/snap.txt"], output="3 passed"))),
                ("no change", (self.tests(), self.call("Bash", {"command": "ls src"}, "app.py"))),
                ("failed edit", (self.tests(), self.edit(failed=True)))):
            with self.subTest(label=label):
                self.assert_lets_stop(self.check(self.transcript(*parts)))
        # Task notes, temporary files and Claude Code's own files: no test reads them. The
        # scratchpad comes from scratchpad_dir, a common input field of every hook event,
        # Stop included (code.claude.com/docs/en/hooks, Common input fields, 2.1.257 or later).
        notes = self.transcript(self.tests(), self.edit("/w/.private/progress/task.org"),
                                self.edit(str(Path(tempfile.gettempdir()) / "s" / "notes.md"), tool="Write"),
                                self.edit(str(Path.home() / ".claude/projects/p/memory/m.md"), tool="Write"),
                                self.edit("/scratch/plan.md", tool="Write"),
                                shell("echo x >> .private/notes.md", ["/w/.private/notes.md"]))
        self.assert_lets_stop(self.check(notes, scratchpad_dir="/scratch"))


class RepeatedFailure(unittest.TestCase):
    # Claude Code's PostToolUseFailure (code.claude.com/docs/en/hooks): input session_id,
    # tool_name, tool_input, error (for Bash a first line "Exit code N", then the output),
    # is_interrupt; hookSpecificOutput.additionalContext reaches Claude next to the error.
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = {**os.environ, "TMPDIR": str(self.tmp)}

    def report(self, payload) -> subprocess.CompletedProcess:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(HOOKS / "repeated_failure.py")], input=data,
                              capture_output=True, text=True, check=False, env=self.env)

    @staticmethod
    def failure(command: str = "make test", error: str = "Exit code 2\nerror: x.c:3: expected ';'",
                session: str = "s1", **extra) -> dict:
        return {"session_id": session, "transcript_path": "/t.jsonl", "cwd": "/w", "permission_mode": "default",
                "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                "tool_input": {"command": command, "description": "Run"}, "tool_use_id": "toolu_1",
                "error": error, "is_interrupt": False, "duration_ms": 10, **extra}

    def assert_quiet(self, result):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def assert_reminds(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PostToolUseFailure")
        for part in ("failed the same way 3 times", "make test", "After two failed fixes, stop",
                     "restate your assumptions and the evidence", "change approach",
                     "systematic-debugging", "report to the user"):
            self.assertIn(part, output["additionalContext"].replace("4 times", "3 times"))

    def test_the_third_identical_failure_gets_the_reminder(self):
        self.assert_quiet(self.report(self.failure()))
        self.assert_quiet(self.report(self.failure()))
        self.assert_reminds(self.report(self.failure()))
        self.assert_reminds(self.report(self.failure()))  # and every one after it

    def test_timings_and_counts_do_not_matter(self):
        # Timings, counts and dates in the output change between runs of one failure.
        for seconds, when in ((1, "10:02:07"), (2, "10:03:15")):
            self.assert_quiet(self.report(self.failure(
                error=f"Exit code 1\n[{when}] start\nFAIL a\nFAIL b\n\n2 failed in {seconds}.{seconds}5 s")))
        self.assert_reminds(self.report(self.failure(error="Exit code 1\n[11:00:00] start\nFAIL a\nFAIL b\n\n"
                                                           "2 failed in 30.12 s")))

    def test_addresses_hashes_and_temporary_names_do_not_matter(self):
        # Object reprs, Java identity hashes and mkdtemp folders change between runs too.
        runs = [("0x7f3a2c1d9e80", "6d06d69c", "tmpab3x9k2q"), ("0x7f11d0b2c4f0", "7852e922", "tmpq8zr1m0c"),
                ("0x7fe0aa63b1d0", "4e25154f", "tmp9w2k7c4x")]
        for index, (address, java, folder) in enumerate(runs):
            with self.subTest(run=index):
                result = self.report(self.failure(error=(
                    f"Exit code 1\nE AssertionError: <Node object at {address}> != None\n"
                    f"java.lang.IllegalStateException: com.example.Pool@{java}\n/tmp/{folder}/out.txt missing")))
                (self.assert_reminds if index == 2 else self.assert_quiet)(result)

    def test_a_fixed_header_does_not_hide_a_different_failure(self):
        # Test runners start with the same lines on every run (pytest: the session line,
        # the platform, the root folder), so the failure itself comes further down.
        header = ("Exit code 1\n============================= test session starts ==============================\n"
                  "platform linux -- Python 3.13.1, pytest-8.3.4, pluggy-1.5.0\nrootdir: /w\ncollected 12 items\n\n")
        for name in ("test_one", "test_two", "test_three"):
            with self.subTest(name=name):
                self.assert_quiet(self.report(self.failure(
                    command="pytest", error=f"{header}FAILED tests/test_a.py::{name}\n1 failed, 11 passed in 0.52s")))

    def test_different_failures_count_apart(self):
        for payload in (self.failure(), self.failure(error="Exit code 2\nerror: y.c:9: expected ';'"),
                        self.failure(error="Exit code 1\nerror: x.c:3: expected ';'"),
                        self.failure(command="make check"), self.failure(session="s2"),
                        self.failure(), self.failure(command="make check"), self.failure(session="s2")):
            with self.subTest(payload=payload):
                self.assert_quiet(self.report(payload))

    def test_interrupts_other_tools_and_bad_input_are_not_counted(self):
        ignored = [self.failure(is_interrupt=True), self.failure(tool_name="Edit"),
                   self.failure(error=5), self.failure(session=""), self.failure(session=7),
                   {**self.failure(), "tool_input": {"command": 5}}, {**self.failure(), "tool_input": "make test"},
                   "not json", "", DEEP_JSON, [1], {"session_id": "s1"}]
        for payload in ignored * 3:
            with self.subTest(payload=str(payload)[:60]):
                self.assert_quiet(self.report(payload))

    def test_the_counts_stay_in_the_temp_folder_whatever_the_session_id(self):
        for _ in range(3):
            result = self.report(self.failure(session="../../escape/x"))
        self.assert_reminds(result)
        self.assertEqual(sorted(p.parent for p in self.tmp.rglob("*") if p.is_file()), [self.tmp])

    def test_the_count_file_stays_small(self):
        # In-process, so 260 failures do not start 260 interpreters.
        spec = importlib.util.spec_from_file_location("repeated_failure_under_test", HOOKS / "repeated_failure.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module.tempfile, "gettempdir", return_value=str(self.tmp)):
            for index in range(260):
                module.count(self.failure(command=f"make test{index}"))
        (state,) = list(self.tmp.iterdir())
        self.assertEqual(len(json.loads(state.read_text())), module.MAX_KEYS)
        self.assertLess(state.stat().st_size, 20000)
        with mock.patch.object(module.tempfile, "gettempdir", return_value=str(self.tmp)):
            # The oldest keys left: test60 is the oldest kept, test59 the newest dropped.
            self.assertEqual(module.count(self.failure(command="make test60"))[0], 2)
            self.assertEqual(module.count(self.failure(command="make test59"))[0], 1)
        # A file that is not ours or not readable starts the count again instead of failing.
        for junk in ("[1, 2]", "{not json", "x" * 100000, json.dumps({"k": "v"})):
            with self.subTest(junk=junk[:20]):
                state.write_text(junk)
                self.assert_quiet(self.report(self.failure()))


if __name__ == "__main__":
    unittest.main()
