#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Shell-command guard shared by every coding agent: block commands that bypass git
gates, rewrite or delete published history, or push and publish.

Usage in a hook config:
  python3 "$HOME/.agents/hooks/guard_bash.py" --tool <claude|codex|gemini|antigravity|copilot|cursor>

Blocks, in every simple command of the text (also after keywords such as if, do, ! and
wrappers such as sudo, env, xargs, time, nice, timeout, watch, strace, chroot, parallel,
systemd-run, firejail, unshare, nsenter, in a find -exec, also nested, in the remote
command of an ssh, and for a git command run as its own program, such as git-push):
  - git commit|push|merge|rebase|am|pull|cherry-pick --no-verify (or a prefix git accepts
    for it), git commit -n and git am -n (skip hooks);
  - hook skip switches: *_SKIP_HOOK(S)=<non-zero>, HUSKY=0|false, LEFTHOOK=0|false,
    OVERCOMMIT_DISABLE=1, and SKIP=<ids> when the command runs git or pre-commit;
  - hooks disabled through core.hooksPath: git config [--]unset core.hooksPath, git config
    core.hooksPath set to an empty path or /dev/null, git -c or --config-env
    core.hooksPath=..., GIT_CONFIG_KEY_<n> or GIT_CONFIG_PARAMETERS naming core.hooksPath;
  - every git push, git subtree push, git send-pack, git http-push, git lfs push, git svn
    dcommit, git p4 submit and git send-email, and every gh command but the read-only or
    local ones (view, list, diff, status and checks in any group, repo and gist clone, pr
    checkout, run watch and download, release download, config and variable get, repo
    read-file and read-dir, ruleset check, attestation verify, search, status, browse,
    completion, licenses, help; gh api is not inspected; a flag other than -R or --repo
    before the subcommand makes a command unknown, since gh takes the flag's next word as
    its value), so a write command gh adds later is blocked too, in every agent: the
    maintainer reviews everything before it leaves the
    machine, so pushing and publishing are the maintainer's; the text of a post (a comment,
    review, issue, discussion, gist or patch) goes to the user instead. A push that also rewrites or deletes
    published history (--force, -f, --force-with-lease, --force-if-includes, +refspec,
    --delete, -d, :ref, --mirror, --prune) and gh pr merge --admin (merges without the
    required checks) are named as such;
  - the gh commands that print the authentication token, which would stay in the session's
    transcript: gh auth token, gh auth git-credential, gh auth status with -t or
    --show-token (in any position, also in a cluster such as -at or as -t=true, the last
    value winning), and gh config get oauth_token, the subcommand found among all the
    operands after the group.

The text is split as a shell does: quotes, escapes, comments, newlines, the operators
; & | ( ), redirections, command substitutions, arithmetic ($((...)), ((...)), whose <<
is a shift) and here-documents, whose body is text, not commands. So a commit message that mentions -n or --no-verify is not mistaken for a
flag. Text that does not parse (an unbalanced quote) is checked by a rough split that
ignores quoting, so a parse error never lets a forbidden command through. This guards
the usual forms; it is not a security boundary (commands passed as one string, as to
bash -c, env -S, flock -c, git submodule foreach or after parallel's :::, and eval,
aliases and scripts are not inspected).

Blocking: exit 2 with the reason on stderr (Claude Code, Codex, Gemini CLI, Cursor).
Copilot denies on exit 2 but shows stderr only to the user, so it also gets
{"permissionDecision": "deny", "permissionDecisionReason": ...} on stdout, the reason
it shows to the agent. Antigravity CLI documents a JSON decision on stdout and no exit
codes, so it gets {"decision": "deny", "reason": ...} or {"decision": "allow"}, always
with exit 0. Unreadable input exits 0 so a broken payload never stops normal work.
Gemini CLI needs JSON on stdout when the hook succeeds.
"""

import argparse
import json
import os
import re
import sys

BLANKS = " \t\r"
OPERATOR_CHARS = ";&|()\n"
WORD_END = BLANKS + OPERATOR_CHARS + "<>"
REDIRECTION = re.compile(r"&>>?|<<<|<<-?|<>|<&|>>|>&|>\||<|>")
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
FALSY = {"", "0", "false", "no", "off"}
OFF = {"0", "false", "no", "off"}

KEYWORDS = {"!", "{", "if", "then", "elif", "else", "while", "until", "do", "coproc"}
DECLARATIONS = {"export", "declare", "typeset", "local", "readonly"}
# Commands that run the command after them: (short options taking a value, long options
# taking the next word as value, operands before the command).
WRAPPERS = {
    "builtin": ("", (), 0),
    "command": ("", (), 0),
    "doas": ("Cu", (), 0),
    "env": ("CSu", ("--chdir", "--split-string", "--unset"), 0),
    "exec": ("a", (), 0),
    # firejail takes every option value glued (--net=none).
    "firejail": ("", (), 0),
    "flock": ("Ew", ("--conflict-exit-code", "--timeout", "--wait"), 1),
    "ionice": ("cnpPu", ("--class", "--classdata", "--pgid", "--pid", "--uid"), 0),
    "nice": ("n", ("--adjustment",), 0),
    "nohup": ("", (), 0),
    "nsenter": ("NtW", ("--net-socket", "--target", "--wdns"), 0),
    # GNU parallel (option table of parallel 20261022, src/parallel: bundling, require_order)
    # runs the command up to its first argument separator; a command given as one of the
    # arguments is a string and is not inspected.
    "parallel": ("BCDEHIJLNPSUWadjns", (
        "--arg-file", "--arg-file-sep", "--arg-sep", "--argfile", "--argfilesep", "--argsep",
        "--basefile", "--basenameextensionreplace", "--basenamereplace", "--bf", "--bin",
        "--block", "--block-size", "--block-timeout", "--blocksize", "--blocktimeout", "--bner",
        "--bnr", "--bt", "--col-sep", "--colsep", "--combine-exec", "--combine-executable",
        "--combineexec", "--combineexecutable", "--compress-program", "--compressprogram",
        "--ctag-string", "--ctagstring", "--debug", "--decompress-program",
        "--decompressprogram", "--delay", "--delimiter", "--dirnamereplace", "--dnr", "--env",
        "--er", "--extensionreplace", "--filter", "--group-by", "--groupby", "--halt",
        "--halt-on-error", "--haltonerror", "--header", "--id", "--jl", "--joblog", "--jobs",
        "--limit", "--linkinputsource", "--load", "--match", "--max-args", "--max-chars",
        "--max-procs", "--max-replace-args", "--maxargs", "--maxchars", "--maxprocs",
        "--maxreplaceargs", "--memfree", "--memsuspend", "--milestone", "--min-version",
        "--minversion", "--ms", "--nice", "--parens", "--process-slot-var", "--processslotvar",
        "--profile", "--recend", "--recstart", "--res", "--result", "--results", "--retries",
        "--return", "--rpl", "--rsync-opts", "--rsyncopts", "--semaphore-name",
        "--semaphore-timeout", "--semaphorename", "--semaphoretimeout", "--seqreplace",
        "--shard", "--shell-completion", "--shellcompletion", "--slf", "--slotreplace", "--sql",
        "--sql-and-worker", "--sql-master", "--sql-worker", "--sqlandworker", "--sqlmaster",
        "--sqlworker", "--ssh", "--ssh-delay", "--sshdelay", "--sshlogin", "--sshloginfile",
        "--st", "--tag-string", "--tagstring", "--tempdir", "--template", "--term-seq",
        "--termseq", "--tf", "--timeout", "--tmpdir", "--tmpl", "--total", "--total-jobs",
        "--totaljobs", "--transfer-file", "--transfer-files", "--transferfile",
        "--transferfiles", "--trc", "--trim", "--use-compress-program",
        "--use-decompress-program", "--usecompressprogram", "--usedecompressprogram", "--wd",
        "--work-dir", "--workdir", "--xapplyinputsource"), 0),
    "pkexec": ("", ("--user",), 0),
    "proxychains": ("f", (), 0),
    "proxychains4": ("f", (), 0),
    "runuser": ("cgGsuw", ("--command", "--group", "--shell", "--supp-group", "--user",
                           "--whitelist-environment"), 0),
    "chroot": ("", ("--groups", "--userspec"), 1),
    "ltrace": ("aADeFlnopsuwx", ("--align", "--config", "--debug", "--indent", "--library",
                                 "--output", "--where"), 0),
    "setsid": ("", (), 0),
    "stdbuf": ("eio", ("--error", "--input", "--output"), 0),
    "systemd-run": ("CEHMpu", (
        "--background", "--capsule", "--description", "--expand-environment", "--gid", "--host",
        "--job-mode", "--json", "--machine", "--nice", "--on-active", "--on-boot", "--on-calendar",
        "--on-startup", "--on-unit-active", "--on-unit-inactive", "--output", "--path-property",
        "--property", "--root-directory", "--service-type", "--setenv", "--slice", "--socket-property",
        "--timer-property", "--uid", "--unit", "--working-directory"), 0),
    "strace": ("abeEIoOpPsSuUX", ("--attach", "--columns", "--env", "--output", "--string-limit",
                                  "--summary-sort-by", "--trace", "--trace-path", "--user"), 0),
    "sudo": ("CDghpRrTtUu", ("--chdir", "--chroot", "--close-from", "--command-timeout",
                             "--group", "--host", "--other-user", "--prompt", "--role",
                             "--type", "--user"), 0),
    "taskset": ("", (), 1),
    "time": ("fo", ("--format", "--output"), 0),
    "timeout": ("ks", ("--kill-after", "--signal"), 1),
    "torsocks": ("aPpu", ("--address", "--pass", "--port", "--user"), 0),
    "unbuffer": ("", (), 0),
    "unshare": ("GlRSw", ("--boottime", "--load-interp", "--map-group", "--map-groups", "--map-user",
                          "--map-users", "--monotonic", "--owner", "--propagation", "--root",
                          "--setgid", "--setgroups", "--setuid", "--wd"), 0),
    "watch": ("nqs", ("--equexit", "--interval", "--shotsdir"), 0),
    "xargs": ("adEILnPs", ("--arg-file", "--delimiter", "--max-args", "--max-chars",
                           "--max-procs", "--process-slot-var"), 0),
}
# Wrapper options whose value is optional: they take the next word as their value only
# when it is a number (nsenter -S and -G, glued and optional in util-linux 2.42, a
# separate uid or gid before it).
NUMERIC_VALUES = {"nsenter": ("GS", ("--setgid", "--setuid"))}
# GNU parallel's argument separators: its command ends before the first one.
PARALLEL_SEPARATORS = {":::", "::::", ":::+", "::::+"}
HOOK_RUNNERS = {"git", "pre-commit"}
# find runs the command after each of these up to a ";" or "+" word.
FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir"}
# ssh's short options that take a value (OpenSSH has no long options).
SSH_VALUE_OPTIONS = "BbcDEeFIiJLlmOoPpQRSWw"
# Commands that other commands run (a find -exec in a find -exec, an ssh's remote
# command) are followed this many levels deep; the text below that level gets the rough
# split, which still finds git and gh, so nesting costs linear time and hides nothing.
MAX_NESTING = 8
# The remote commands of ssh calls are parsed in full up to this many characters in all;
# past that they get the rough split, so nested ssh calls also cost linear time.
MAX_REMOTE_TEXT = 100_000
ROUGH_PROGRAMS = HOOK_RUNNERS | {"gh"}

GIT_VALUE_OPTIONS = {"-C", "-c", "--attr-source", "--config-env", "--git-dir", "--namespace",
                     "--work-tree"}
HOOK_SUBCOMMANDS = {"am", "cherry-pick", "commit", "merge", "pull", "push", "rebase"}
# Per subcommand: (short options taking a value, short options whose optional value can
# only be glued, long options taking the next word as value).
GIT_OPTIONS = {
    "am": ("Cp", "S", set()),
    "commit": ("CcFmtU", "Su", {"--author", "--cleanup", "--date", "--file", "--fixup",
                                "--message", "--pathspec-from-file", "--reedit-message",
                                "--reuse-message", "--squash", "--template", "--trailer",
                                "--unified"}),
    "push": ("o", "", {"--exec", "--push-option", "--receive-pack", "--repo"}),
}
FORCE_OPTIONS = ("--force", "--force-with-lease", "--force-if-includes")
# git subtree: (short options taking a value, long options taking the next word as value).
SUBTREE_OPTIONS = ("Pbm", ("--annotate", "--branch", "--message", "--onto", "--prefix"))
PUSH_REASON = "git push publishes commits to a remote"
SUBTREE_PUSH_REASON = "git subtree push publishes commits to a remote"
PR_CREATE_REASON = "gh pr create publishes a branch as a pull request"
PR_MERGE_REASON = "gh pr merge merges into a published branch"
RELEASE_REASON = "gh release create publishes a release"
REPO_SYNC_REASON = "gh repo sync pushes to a repository"
REPO_CREATE_PUSH_REASON = "gh repo create --push pushes commits to a new repository"
# git commands that publish other than push: {subcommand: (its action, reason)}; an action
# of None means the subcommand itself publishes.
GIT_PUBLISHERS = {
    "send-pack": (None, "git send-pack publishes commits to a remote"),
    "http-push": (None, "git http-push publishes commits to a remote"),
    "lfs": ("push", "git lfs push publishes objects to a remote"),
    "svn": ("dcommit", "git svn dcommit publishes commits to a Subversion repository"),
    "p4": ("submit", "git p4 submit publishes commits to a Perforce depot"),
    "send-email": (None, "git send-email sends patches by email"),
}
GIST_REASON = "gh gist create publishes a gist"
ISSUE_REASON = "gh issue create publishes an issue"
# gh commands that publish, other than gh pr merge and gh repo create --push:
# {(command, subcommand): reason}; gh's alias new shares the reason of create.
GH_PUBLISHERS = {
    ("pr", "create"): PR_CREATE_REASON, ("pr", "new"): PR_CREATE_REASON,
    ("pr", "ready"): "gh pr ready changes the review state of a pull request",
    ("pr", "comment"): "gh pr comment posts on a pull request",
    ("pr", "review"): "gh pr review posts a review on a pull request",
    ("pr", "edit"): "gh pr edit changes a published pull request",
    ("release", "create"): RELEASE_REASON, ("release", "new"): RELEASE_REASON,
    ("release", "upload"): "gh release upload publishes files on a release",
    ("release", "edit"): "gh release edit changes a published release",
    ("repo", "sync"): REPO_SYNC_REASON,
    ("gist", "create"): GIST_REASON, ("gist", "new"): GIST_REASON,
    ("issue", "create"): ISSUE_REASON, ("issue", "new"): ISSUE_REASON,
    ("issue", "comment"): "gh issue comment posts on an issue",
    ("discussion", "create"): "gh discussion create publishes a discussion",
    ("discussion", "comment"): "gh discussion comment posts on a discussion",
    ("workflow", "run"): "gh workflow run starts a workflow on GitHub",
}
# The publish forms that post text, whose text the user can post instead.
POST_REASONS = {GIST_REASON, ISSUE_REASON, GIT_PUBLISHERS["send-email"][1],
                *(GH_PUBLISHERS[key] for key in (("pr", "comment"), ("pr", "review"), ("pr", "edit"),
                                                 ("release", "edit"), ("issue", "comment"),
                                                 ("discussion", "create"), ("discussion", "comment")))}
# GitHub: only read-only or local gh commands run (gh 2.100.0's command tree), and every
# other gh command is blocked, so a write command gh adds later is blocked too; gh api is
# not inspected. Read-only or local: the subcommands below in any group (ls is gh's alias
# of list), the top-level commands below, the group and subcommand pairs below (gh label
# clone copies labels into a repository, so only repo and gist clone; co is pr's alias of
# checkout, rs and at the group aliases of ruleset and attestation; gh co is a user alias,
# so it is not one), the read subcommands of repo's nested groups, and help.
GH_READ_SUBCOMMANDS = {"checks", "diff", "list", "ls", "status", "view"}
GH_READ_COMMANDS = {"api", "browse", "completion", "help", "licenses", "search", "status", "version"}
GH_READ_PAIRS = {("repo", "clone"), ("gist", "clone"), ("pr", "checkout"), ("pr", "co"), ("run", "watch"),
                 ("run", "download"), ("release", "download"), ("config", "get"), ("variable", "get"),
                 ("repo", "read-file"), ("repo", "read-dir"), ("ruleset", "check"), ("rs", "check"),
                 ("attestation", "verify"), ("at", "verify")}
GH_READ_GROUPS = {("repo", "autolink"), ("repo", "deploy-key"), ("repo", "gitignore"), ("repo", "license")}
GH_NOT_READ_ONLY = "is not one of the read-only gh commands (view, list, diff, status, checks, clone, search)"
GH_ADVICE = "Run only read-only gh commands, and ask the user to run any other."
# gh commands that print the authentication token (gh auth git-credential get prints it as
# the password; gh config get oauth_token prints one stored in plain text). A token in the
# output stays in the transcript, which leaves the machine with every model request.
TOKEN_PRINTS = "prints the authentication token"
TOKEN_ADVICE = ("A token printed here stays in this session's transcript. Check the login with gh auth "
                "status without -t, and ask the user to run any command that needs the token.")
FALSE_VALUES = {"0", "f", "false"}  # what Go's strconv.ParseBool reads as false, lower-cased
# git's own programs that the guard inspects, run by their own name (git-push from git
# --exec-path, git-lfs); other git-* programs (git-cliff, git-crypt) are not git.
GIT_PROGRAMS = HOOK_SUBCOMMANDS | {"config", "subtree"} | set(GIT_PUBLISHERS)
PUBLISH_REASONS = {PUSH_REASON, SUBTREE_PUSH_REASON, PR_MERGE_REASON, REPO_CREATE_PUSH_REASON,
                   *GH_PUBLISHERS.values(), *(reason for _, reason in GIT_PUBLISHERS.values())}
PUBLISH_ADVICE = ("Pushing and publishing are the maintainer's: they review every change before "
                  "it leaves this machine. Do not push or publish another way; stop and tell the "
                  "user the work is ready for their review.")
POST_ADVICE = ("To post a comment, review, issue, gist, description or patch, write its text in "
               "your reply for the user to post.")
GATE_ADVICE = ("Gates and published history are the maintainer's call. Fix the failing check, "
               "or stop and ask the user to run this command themselves.")
CONFIG_VALUE_OPTIONS = {"-f", "--blob", "--comment", "--default", "--file", "--type",
                        "--url", "--value"}
CONFIG_ACTIONS = {"edit", "get", "list", "remove-section", "rename-section", "set", "unset"}


class ParseError(ValueError):
    """The text is not a complete shell command (an unbalanced quote, for example)."""


class Parser:
    """Split shell text into simple commands, each a list of words without quotes.

    Commands inside $(...), backticks and <(...) are listed too. Redirections are
    dropped; here-document bodies and arithmetic are skipped, except the substitutions
    in them that the shell runs."""

    def __init__(self, text: str, commands: list):
        self.text = text
        self.pos = 0
        self.commands = commands
        self.heredocs = []  # (delimiter, strip tabs, expands) opened on the current line

    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.text[index] if index < len(self.text) else ""

    def parse(self, nested: bool = False) -> None:
        """Read commands to the end of the text or, when nested, to the ) closing $(."""
        words, depth = [], 0
        while True:
            self.skip_blanks()
            char = self.peek()
            if not char:
                if nested:
                    raise ParseError("unterminated $(")
                break
            if char == "#":
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end
            elif char == "&" and self.peek(1) == ">":
                self.redirection()
            elif char == "(" and self.peek(1) == "(" and (
                    end := self.arithmetic_end(self.pos + 2, "(", "))")) > 0:
                self.skip_arithmetic(self.pos + 2, end, "))")  # a command such as (( x = 1 << 2 ))
            elif char in OPERATOR_CHARS:
                self.pos += 1
                if words:
                    self.commands.append(words)
                words = []
                if char == "\n":
                    self.read_heredocs()
                elif char == "(":
                    depth += 1
                elif char == ")" and nested:
                    if depth == 0:
                        return
                    depth -= 1
            elif char in "<>":
                self.redirection()
            else:
                word, quoted = self.read_word()
                next_char = self.peek()
                if next_char and next_char in "<>" and word.isdigit() and not quoted:
                    continue  # the file descriptor of a redirection, as in 2>&1
                words.append(word)
        if words:
            self.commands.append(words)

    def skip_blanks(self) -> None:
        while True:
            char = self.peek()
            if char and char in BLANKS:
                self.pos += 1
            elif char == "\\" and self.peek(1) == "\n":
                self.pos += 2
            else:
                return

    def read_word(self) -> tuple:
        """Return (the word at pos without quotes, whether any part of it was quoted)."""
        parts, quoted = [], False
        while True:
            char = self.peek()
            if not char or char in WORD_END:
                return "".join(parts), quoted
            if char == "\\":
                escaped = self.peek(1)
                self.pos += 2
                if escaped != "\n":
                    parts.append(escaped)
                    quoted = True
            elif char == "'":
                end = self.text.find("'", self.pos + 1)
                if end < 0:
                    raise ParseError("unterminated '")
                parts.append(self.text[self.pos + 1:end])
                self.pos = end + 1
                quoted = True
            elif char == '"':
                self.pos += 1
                parts.append(self.expansions('"'))
                quoted = True
            elif char == "$" and self.peek(1) == "'":
                parts.append(self.ansi_c_quoted())
                quoted = True
            elif char == "$" and self.peek(1) in ("(", "["):
                parts.append(self.substitution())
            elif char == "`":
                parts.append(self.backticks())
            else:
                parts.append(char)
                self.pos += 1

    def expansions(self, closing: str) -> str:
        """Read text in which only backslashes, $(...) and backticks are special, as in
        double quotes, up to closing or, when closing is empty, to the end."""
        parts = []
        while True:
            char = self.peek()
            if not char:
                if closing:
                    raise ParseError("unterminated " + closing)
                return "".join(parts)
            if char == closing:
                self.pos += 1
                return "".join(parts)
            if char == "\\":
                escaped = self.peek(1)
                self.pos += 2
                if escaped != "\n":
                    parts.append(escaped if escaped in '$`"\\' else "\\" + escaped)
            elif char == "$" and self.peek(1) in ("(", "["):
                parts.append(self.substitution())
            elif char == "`":
                parts.append(self.backticks())
            else:
                parts.append(char)
                self.pos += 1

    def ansi_c_quoted(self) -> str:
        start = index = self.pos + 2
        while index < len(self.text) and self.text[index] != "'":
            index += 2 if self.text[index] == "\\" else 1
        if index >= len(self.text):
            raise ParseError("unterminated $'")
        self.pos = index + 1
        return re.sub(r"\\(.)", r"\1", self.text[start:index], flags=re.DOTALL)

    def substitution(self) -> str:
        """Read $(...), or the arithmetic $((...)) or $[...], at pos; return its text."""
        start = self.pos
        if self.peek(1) == "[":
            end = self.arithmetic_end(start + 2, "[", "]")
            if end < 0:
                raise ParseError("unterminated $[")
            return self.skip_arithmetic(start + 2, end, "]")
        if self.peek(2) == "(":
            end = self.arithmetic_end(start + 3, "(", "))")
            if end > 0:
                return self.skip_arithmetic(start + 3, end, "))")
        self.pos += 2
        self.parse(nested=True)
        return self.text[start:self.pos]

    def arithmetic_end(self, start: int, opening: str, closing: str) -> int:
        """Index just past the closing ("))" or "]") of arithmetic whose expression starts
        at start, or -1. A ")" that is not followed by another closes a subshell instead,
        as in ((cd a) ) or $((cd a) )."""
        depth = 0
        for index in range(start, len(self.text)):
            char = self.text[index]
            if char == opening:
                depth += 1
            elif char == closing[0]:
                if depth:
                    depth -= 1
                elif self.text.startswith(closing, index):
                    return index + len(closing)
                else:
                    return -1
        return -1

    def skip_arithmetic(self, start: int, end: int, closing: str) -> str:
        """Move from pos to end, past arithmetic whose < and << are operators, not
        redirections; list the commands of any $(...) or backticks in its expression
        text[start:end - len(closing)]. Return the text skipped."""
        Parser(self.text[start:end - len(closing)], self.commands).expansions("")
        skipped = self.text[self.pos:end]
        self.pos = end
        return skipped

    def backticks(self) -> str:
        start = index = self.pos + 1
        while index < len(self.text) and self.text[index] != "`":
            index += 2 if self.text[index] == "\\" else 1
        if index >= len(self.text):
            raise ParseError("unterminated `")
        self.pos = index + 1
        Parser(re.sub(r"\\([`$\\])", r"\1", self.text[start:index]), self.commands).parse()
        return self.text[start - 1:self.pos]

    def redirection(self) -> None:
        """Skip a redirection and its target; note a here-document for the next newline."""
        operator = REDIRECTION.match(self.text, self.pos).group(0)
        self.pos += len(operator)
        self.skip_blanks()
        start = self.pos
        target, quoted = self.read_word()
        if operator in ("<<", "<<-"):
            if self.pos == start:
                raise ParseError("here-document without a delimiter")
            self.heredocs.append((target, operator == "<<-", not quoted))

    def read_heredocs(self) -> None:
        """Skip the bodies of the here-documents opened on the line that just ended."""
        for delimiter, strip_tabs, expands in self.heredocs:
            body = []
            while self.pos < len(self.text):
                end = self.text.find("\n", self.pos)
                end = len(self.text) if end < 0 else end
                line = self.text[self.pos:end]
                self.pos = end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
                body.append(line)
            if expands:
                Parser("\n".join(body), self.commands).expansions("")
        self.heredocs = []


def parse_commands(text: str) -> list:
    commands = []
    Parser(text, commands).parse()
    return commands


def rough_commands(text: str) -> list:
    """Split text that does not parse while ignoring quotes and backticks, and start a
    new command at every git, gh or pre-commit word, so a forbidden command is still
    found (words inside quotes may then read as flags)."""
    text = re.sub(r"\\\n", "", text)
    text = re.sub(r"&>|[<>]&", " > ", text)
    text = re.sub(r"[\"'\\]", "", text).replace("`", " ")
    commands = []
    for piece in re.split(r"[;&|()\n]+", text):
        command = []
        for word in piece.split():
            if command and os.path.basename(word) in ROUGH_PROGRAMS:
                commands.append(command)
                command = []
            command.append(word)
        if command:
            commands.append(command)
    return commands


def skip_options(words: list, index: int, short_values: str, long_values, numeric=("", ())) -> int:
    """Return the index of the first operand after the options at words[index:].
    numeric holds the (short, long) options whose value is optional: glued, or the next
    word when that is a number."""
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1
        if not word.startswith("-") or word == "-":
            return index
        index += 1
        number_follows = index < len(words) and words[index].isdigit()
        if word.startswith("--"):
            if "=" not in word and (word in long_values or (word in numeric[1] and number_follows)):
                index += 1
            continue
        for position, letter in enumerate(word[1:], start=2):
            if letter in short_values or letter in numeric[0]:
                if position == len(word) and (letter in short_values or number_follows):
                    index += 1  # the value is the next word
                break
    return index


def split_command(words: list) -> tuple:
    """Return (assignments before the program, the program and its arguments)."""
    assignments, index, end = [], 0, len(words)
    while index < len(words):
        word = words[index]
        match = ASSIGNMENT.match(word)
        name = os.path.basename(word)
        if match:
            assignments.append((match.group(1), match.group(2)))
            index += 1
        elif word in KEYWORDS:
            index += 1
        elif word == "function":
            index += 2  # and the function name; the body follows
        elif word in DECLARATIONS:
            index = skip_options(words, index + 1, "", ())
        elif name in WRAPPERS:
            short_values, long_values, operands = WRAPPERS[name]
            index = skip_options(words, index + 1, short_values, long_values,
                                 NUMERIC_VALUES.get(name, ("", ())))
            while name == "env" and index < len(words) and words[index] == "-":
                index += 1
            index += operands
            if name == "parallel":
                end = next((at for at in range(index, end) if words[at] in PARALLEL_SEPARATORS), end)
        else:
            break
    return assignments, words[index:end]


def program_of(words: list) -> str:
    name = os.path.basename(words[0]) if words else ""
    return name[:-4] if name.lower().endswith(".exe") else name  # git.exe from WSL


def as_git(words: list) -> list:
    """One of git's own programs that the guard inspects (git-push, git-subtree, from git
    --exec-path) as the git subcommand it is."""
    program = program_of(words)
    if program.startswith("git-") and program[len("git-"):] in GIT_PROGRAMS:
        return ["git", program[len("git-"):], *words[1:]]
    return words


def find_commands(words: list) -> list:
    """The commands a find runs with -exec, -execdir, -ok or -okdir."""
    if program_of(words) != "find":
        return []
    found, current = [], None
    for word in words[1:]:
        if current is None:
            if word in FIND_ACTIONS:
                current = []
        elif word in (";", "+"):
            found.append(current)
            current = None
        else:
            current.append(word)
    return found + ([current] if current else [])


def remote_command(words: list) -> str:
    """The command line an ssh runs on the remote host, or "": its words after the
    destination, joined with spaces as ssh sends them to the remote shell. ssh reads
    options after the destination too, unless -- came before it."""
    if program_of(words) != "ssh":
        return ""
    index = skip_options(words, 1, SSH_VALUE_OPTIONS, ())
    terminated = index > 1 and words[index - 1] == "--"
    index += 1  # the destination
    if not terminated:
        index = skip_options(words, index, SSH_VALUE_OPTIONS, ())
    return " ".join(words[index:])


def abbreviates(name: str, option: str, shortest: int) -> bool:
    """True when name is option or a prefix of it at least shortest characters long
    (git accepts any unique prefix of a long option)."""
    return len(name) >= shortest and option.startswith(name)


def assignment_reason(name: str, value: str, program: str, runs_hook_runner: bool) -> str:
    setting = value.strip().lower()
    if re.search(r"SKIP_HOOKS?$", name) and setting not in FALSY:
        return f"{name}={value} skips the repository's git hooks"
    if name in ("HUSKY", "LEFTHOOK") and setting in OFF:
        return f"{name}={value} skips the repository's git hooks"
    if name == "OVERCOMMIT_DISABLE" and setting not in FALSY:
        return f"{name}={value} skips the repository's git hooks"
    if name == "SKIP" and setting not in FALSY:
        # A bare or exported SKIP= reaches the git or pre-commit run later in the text.
        if program in HOOK_RUNNERS or (not program and runs_hook_runner):
            return "SKIP= skips pre-commit hooks"
    if re.fullmatch(r"GIT_CONFIG_KEY_\d+", name) and setting == "core.hookspath":
        return f"{name}=core.hooksPath overrides the repository's git hooks"
    if name == "GIT_CONFIG_PARAMETERS" and "core.hookspath" in setting:
        return "GIT_CONFIG_PARAMETERS with core.hooksPath overrides the repository's git hooks"
    return ""


def parse_git_options(args: list, short_values: str, short_optional: str, long_values) -> tuple:
    """Return (short option letters, long option names, operands) of a git subcommand."""
    shorts, longs, operands = set(), [], []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        if word == "--":
            operands.extend(args[index:])
            break
        if word.startswith("--"):
            name = word.split("=", 1)[0]
            longs.append(name)
            if "=" not in word and name in long_values:
                index += 1
        elif word.startswith("-") and len(word) > 1:
            # A cluster such as -anm: scan left to right up to the first option with a value.
            for position, letter in enumerate(word[1:], start=2):
                if letter in short_values:
                    if position == len(word):
                        index += 1
                    break
                if letter in short_optional:
                    break
                shorts.add(letter)
        else:
            operands.append(word)
    return shorts, longs, operands


def push_reasons(shorts: set, longs: list, operands: list) -> list:
    reasons = [PUSH_REASON]
    if "f" in shorts or any(abbreviates(n, o, 3) for n in longs for o in FORCE_OPTIONS):
        reasons.append("force push rewrites published history")
    if any(o.startswith("+") and len(o) > 1 for o in operands):
        reasons.append("a +refspec push rewrites published history")
    if ("d" in shorts or any(abbreviates(n, "--delete", 3) for n in longs)
            or any(o.startswith(":") and len(o) > 1 for o in operands)):
        reasons.append("deleting a remote ref destroys published history")
    if any(abbreviates(n, "--mirror", 3) for n in longs):
        reasons.append("git push --mirror overwrites and deletes remote refs")
    if any(abbreviates(n, "--prune", 3) for n in longs):
        reasons.append("git push --prune deletes remote refs")
    return reasons


def config_reason(args: list) -> str:
    options, operands = [], []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        if word.startswith("-") and len(word) > 1:
            options.append(word.split("=", 1)[0])
            if "=" not in word and word in CONFIG_VALUE_OPTIONS:
                index += 1
        else:
            operands.append(word)
    action = operands.pop(0) if operands and operands[0] in CONFIG_ACTIONS else ""
    if not operands or operands[0].lower() != "core.hookspath":
        return ""
    if action == "unset" or any(abbreviates(o, "--unset-all", 4) for o in options):
        return "unsetting core.hooksPath disables the repository's git hooks"
    reading = action in ("get", "list") or any(o.startswith("--get") or o in ("-l", "--list")
                                               for o in options)
    value = operands[1].strip() if len(operands) > 1 else None
    if not reading and value is not None and (not value or os.path.normpath(value) == "/dev/null"):
        return "core.hooksPath set to an empty path or /dev/null disables the repository's git hooks"
    return ""


def git_reasons(words: list) -> list:
    reasons = []
    index = 1
    while index < len(words) and words[index].startswith("-"):
        word = words[index]
        name, _, value = word.partition("=")
        if word in GIT_VALUE_OPTIONS:
            value = words[index + 1] if index + 1 < len(words) else ""
            index += 1
        if name in ("-c", "--config-env") and value.split("=", 1)[0].strip().lower() == "core.hookspath":
            reasons.append(f"git {name} core.hooksPath=... disables the repository's git hooks")
        index += 1
    sub = words[index] if index < len(words) else ""
    args = words[index + 1:]
    shorts, longs, operands = parse_git_options(args, *GIT_OPTIONS.get(sub, ("", "", ())))
    if sub in HOOK_SUBCOMMANDS:
        if any(abbreviates(name, "--no-verify", len("--no-v")) for name in longs):
            reasons.append(f"git {sub} --no-verify skips the repository's git hooks")
        if sub in ("am", "commit") and "n" in shorts:
            reasons.append(f"git {sub} -n skips the repository's git hooks")
    if sub == "push":
        reasons.extend(push_reasons(shorts, longs, operands))
    if sub == "subtree":
        command = skip_options(args, 0, *SUBTREE_OPTIONS)
        if command < len(args) and args[command] == "push":
            reasons.append(SUBTREE_PUSH_REASON)
    if sub == "config":
        reasons.append(config_reason(args))
    if sub in GIT_PUBLISHERS:
        action, reason = GIT_PUBLISHERS[sub]
        first = skip_options(args, 0, "", ())
        if action is None or (first < len(args) and args[first] == action):
            reasons.append(reason)
    return [reason for reason in reasons if reason]


def gh_help(words: list, operands: list) -> bool:
    """gh alone, gh --version and help. -h is help only as the last word, since gh auth and
    gh config get read it as --hostname; after "--", --help and -h are arguments."""
    if "--" in words:
        return not operands or "--help" in words[:words.index("--")]
    return not operands or "--help" in words or words[-1] == "-h"


def repository_flag(word: str) -> bool:
    """-R or --repo with its value glued (-Ro/r, --repo=o/r)."""
    return word.startswith("--repo=") or (word.startswith("-R") and len(word) > 2)


def gh_read_only(operands: list) -> bool:
    """True for a gh command that only reads or works locally (see GH_READ_SUBCOMMANDS)."""
    if operands[0] in GH_READ_COMMANDS:
        return True
    if len(operands) > 1 and (operands[1] in GH_READ_SUBCOMMANDS or tuple(operands[:2]) in GH_READ_PAIRS):
        return True
    return tuple(operands[:2]) in GH_READ_GROUPS and len(operands) > 2 and operands[2] in GH_READ_SUBCOMMANDS


def shows_token(words: list) -> bool:
    """True when gh auth status gets -t or --show-token: also in a cluster of short flags
    (-at), with a value (-t=true, --show-token=1; a false value turns it off, the last one
    wins); in a cluster, -h takes the rest of the word as its value (-ht names host t)."""
    shown = False
    for word in words:
        if word == "--":
            break
        name, equals, value = word.partition("=")
        if name == "--show-token":
            shown = not equals or value.lower() not in FALSE_VALUES
        elif word.startswith("-") and not word.startswith("--"):
            for position, letter in enumerate(word[1:], start=2):
                if letter == "t":
                    rest = word[position:]
                    shown = not rest.startswith("=") or rest[1:].lower() not in FALSE_VALUES
                if letter != "a":
                    break  # -t=value or -h value ends the cluster; -a is the other flag
    return shown


def gh_token_reason(words: list, operands: list) -> str:
    """Why a gh command prints the authentication token, or "". The subcommand is looked
    for in every operand after the group, since a flag before it can move it along."""
    group, rest = operands[0], operands[1:]
    for name in ("token", "git-credential"):
        if group == "auth" and name in rest:
            return f"gh auth {name} {TOKEN_PRINTS}"
    if group == "auth" and "status" in rest and shows_token(words):
        return f"gh auth status --show-token {TOKEN_PRINTS}"
    if group == "config" and "get" in rest and "oauth_token" in rest:
        return f"gh config get oauth_token {TOKEN_PRINTS}"
    return ""


def gh_reasons(words: list) -> list:
    # flag_at: how many operands came before the first flag other than the repository
    # flag. gh's parser takes an unknown flag's next word as its value while it looks for
    # the subcommand, so a flag before the subcommand hides which command runs.
    operands, flag_at, index = [], None, 1
    while index < len(words):
        word = words[index]
        index += 1
        if word in ("-R", "--repo"):
            index += 1  # gh takes the repository flag before or after the subcommand
        elif word.startswith("-") and not repository_flag(word):
            flag_at = len(operands) if flag_at is None else flag_at
        elif not word.startswith("-"):
            operands.append(word)
    if gh_help(words, operands):
        return []
    token = gh_token_reason(words, operands)
    if token:
        return [token]
    # The operands that make a command read-only: a top-level command, a group and its
    # subcommand, or repo, a nested group and its subcommand.
    named = 1 if operands[0] in GH_READ_COMMANDS else 3 if tuple(operands[:2]) in GH_READ_GROUPS else 2
    if flag_at is not None and flag_at < named:
        return [f"gh {operands[0]} with a flag before its subcommand {GH_NOT_READ_ONLY}"]
    if gh_read_only(operands):
        return []
    if tuple(operands[:2]) in GH_PUBLISHERS:
        return [GH_PUBLISHERS[tuple(operands[:2])]]
    if operands[:2] in (["repo", "create"], ["repo", "new"]) and any(
            word.partition("=")[0] == "--push" and word.partition("=")[2].lower() not in ("false", "0")
            for word in words[1:]):
        return [REPO_CREATE_PUSH_REASON]
    if operands[:2] != ["pr", "merge"]:
        return [f"gh {' '.join(operands[:2])} {GH_NOT_READ_ONLY}"]
    reasons = [PR_MERGE_REASON]
    for word in words[1:]:
        name, _, value = word.partition("=")
        if name == "--admin" and value.lower() not in ("false", "0"):
            reasons.append("gh pr merge --admin merges without the required checks and reviews")
            break
    return reasons


def command_reasons(commands: list) -> dict:
    """Return {reason: True when only commands that push or publish gave it}."""
    reasons = {}
    split = []
    # Each command, then the commands it runs: those of a find -exec, and the remote
    # command of an ssh, split as the remote shell splits it. Past MAX_NESTING levels or
    # MAX_REMOTE_TEXT characters, the rest of the text gets the rough split, which shows
    # every git and gh word in it, and its pieces are not followed further.
    rough = MAX_NESTING + 1
    queue = [(words, 0) for words in commands]
    index = remote_text = 0
    while index < len(queue):  # grows with the commands that the commands run
        words, depth = queue[index]
        index += 1
        assignments, rest = split_command(words)
        rest = as_git(rest)
        split.append((assignments, rest))
        if depth == rough:
            continue
        inner = find_commands(rest)
        remote = remote_command(rest)
        if (inner or remote) and (depth == MAX_NESTING or remote_text + len(remote) > MAX_REMOTE_TEXT):
            queue.extend((command, rough) for command in rough_commands(" ".join(rest)))
            continue
        remote_text += len(remote)
        if remote:
            try:
                inner.extend(parse_commands(remote))
            except (ParseError, RecursionError):
                queue.extend((command, rough) for command in rough_commands(remote))
        queue.extend((command, depth + 1) for command in inner)
    runs_hook_runner = any(program_of(rest) in HOOK_RUNNERS for _, rest in split)
    for assignments, rest in split:
        program = program_of(rest)
        found = [assignment_reason(name, value, program, runs_hook_runner)
                 for name, value in assignments]
        if program == "git":
            found.extend(git_reasons(rest))
        elif program == "gh":
            found.extend(gh_reasons(rest))
        publishes = any(reason in PUBLISH_REASONS or reason.endswith(GH_NOT_READ_ONLY) for reason in found)
        for reason in found:
            if reason:
                reasons[reason] = reasons.get(reason, True) and publishes
    return reasons


def extract_command(payload: dict) -> str:
    """Find the shell command in any supported agent's payload shape."""
    call = payload.get("toolCall")  # Antigravity CLI: run_command's args hold CommandLine
    args = call.get("args") if isinstance(call, dict) else None
    if isinstance(args, dict) and isinstance(args.get("CommandLine"), str):
        return args["CommandLine"]
    for container in (payload.get("tool_input"), payload.get("toolArgs"), payload):
        if isinstance(container, str):
            try:
                container = json.loads(container)
            except (ValueError, RecursionError):
                continue
        if isinstance(container, dict) and isinstance(container.get("command"), str):
            return container["command"]
    return ""


def allow(tool: str) -> int:
    if tool == "gemini":
        print("{}")
    elif tool == "antigravity":
        print(json.dumps({"decision": "allow"}))  # defers to the next hook or the default policy
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", default="claude",
                        choices=["claude", "codex", "gemini", "antigravity", "copilot", "cursor"])
    tool = parser.parse_args().tool
    try:
        payload = json.load(sys.stdin)
    except (ValueError, RecursionError):
        return allow(tool)
    if not isinstance(payload, dict):
        return allow(tool)
    command = extract_command(payload)
    if not command:
        return allow(tool)
    try:
        commands = parse_commands(command)
    except (ParseError, RecursionError):
        commands = rough_commands(command)
    reasons = command_reasons(commands)
    if not reasons:
        return allow(tool)
    advice = []
    if any(reasons.values()):
        advice.append(PUBLISH_ADVICE)
    if POST_REASONS & set(reasons):
        advice.append(POST_ADVICE)
    if any(reason.endswith(GH_NOT_READ_ONLY) for reason in reasons):
        advice.append(GH_ADVICE)
    if any(reason.endswith(TOKEN_PRINTS) for reason in reasons):
        advice.append(TOKEN_ADVICE)
    if not all(publishes or reason.endswith(TOKEN_PRINTS) for reason, publishes in reasons.items()):
        advice.append(GATE_ADVICE)
    message = "Blocked: " + "; ".join(reasons) + ". " + " ".join(advice)
    if tool == "antigravity":
        print(json.dumps({"decision": "deny", "reason": message}))
        return 0
    print(message, file=sys.stderr)
    if tool == "copilot":
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": message}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
