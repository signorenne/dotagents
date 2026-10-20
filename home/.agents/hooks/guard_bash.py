#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Shell-command guard shared by every coding agent: block commands that bypass git
gates, rewrite or delete published history, or push and publish.

Usage in a hook config:
  python3 "$HOME/.agents/hooks/guard_bash.py" --tool <claude|codex|gemini|antigravity|copilot|cursor>

Blocks, in every simple command of the text (also after keywords such as if, do, ! and
wrappers such as sudo, env, xargs, time, nice, timeout, watch, strace, chroot, in a
find -exec, and for a git command run as its own program, such as git-push):
  - git commit|push|merge|rebase|am|pull|cherry-pick --no-verify (or a prefix git accepts
    for it), git commit -n and git am -n (skip hooks);
  - hook skip switches: *_SKIP_HOOK(S)=<non-zero>, HUSKY=0|false, LEFTHOOK=0|false,
    OVERCOMMIT_DISABLE=1, and SKIP=<ids> when the command runs git or pre-commit;
  - hooks disabled through core.hooksPath: git config [--]unset core.hooksPath, git config
    core.hooksPath set to an empty path or /dev/null, git -c or --config-env
    core.hooksPath=..., GIT_CONFIG_KEY_<n> or GIT_CONFIG_PARAMETERS naming core.hooksPath;
  - every git push, git subtree push, git send-pack, git http-push, git lfs push, git svn
    dcommit, git p4 submit, gh pr create (or gh pr new), gh pr merge, gh release create
    (or gh release new), gh repo create --push and gh repo sync, in every agent: the
    maintainer reviews everything before it leaves the machine, so pushing and
    publishing are the maintainer's. A push that also rewrites or deletes
    published history (--force, -f, --force-with-lease, --force-if-includes, +refspec,
    --delete, -d, :ref, --mirror, --prune) and gh pr merge --admin (merges without the
    required checks) are named as such.

The text is split as a shell does: quotes, escapes, comments, newlines, the operators
; & | ( ), redirections, command substitutions, arithmetic ($((...)), ((...)), whose <<
is a shift) and here-documents, whose body is text, not commands. So a commit message that mentions -n or --no-verify is not mistaken for a
flag. Text that does not parse (an unbalanced quote) is checked by a rough split that
ignores quoting, so a parse error never lets a forbidden command through. This guards
the usual forms; it is not a security boundary (commands passed as one string, as to
bash -c, env -S, flock -c or git submodule foreach, and eval, aliases and scripts are
not inspected).

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
    "flock": ("Ew", ("--conflict-exit-code", "--timeout", "--wait"), 1),
    "ionice": ("cnpPu", ("--class", "--classdata", "--pgid", "--pid", "--uid"), 0),
    "nice": ("n", ("--adjustment",), 0),
    "nohup": ("", (), 0),
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
    "watch": ("nqs", ("--equexit", "--interval", "--shotsdir"), 0),
    "xargs": ("adEILnPs", ("--arg-file", "--delimiter", "--max-args", "--max-chars",
                           "--max-procs", "--process-slot-var"), 0),
}
HOOK_RUNNERS = {"git", "pre-commit"}
# find runs the command after each of these up to a ";" or "+" word.
FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir"}
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
}
PUBLISH_REASONS = {PUSH_REASON, SUBTREE_PUSH_REASON, PR_CREATE_REASON, PR_MERGE_REASON,
                   RELEASE_REASON, REPO_SYNC_REASON, REPO_CREATE_PUSH_REASON,
                   *(reason for _, reason in GIT_PUBLISHERS.values())}
PUBLISH_ADVICE = ("Pushing and publishing are the maintainer's: they review every change before "
                  "it leaves this machine. Do not push or publish another way; stop and tell the "
                  "user the work is ready for their review.")
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


def skip_options(words: list, index: int, short_values: str, long_values) -> int:
    """Return the index of the first operand after the options at words[index:]."""
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1
        if not word.startswith("-") or word == "-":
            return index
        index += 1
        if word.startswith("--"):
            if "=" not in word and word in long_values:
                index += 1
            continue
        for position, letter in enumerate(word[1:], start=2):
            if letter in short_values:
                if position == len(word):
                    index += 1  # the value is the next word
                break
    return index


def split_command(words: list) -> tuple:
    """Return (assignments before the program, the program and its arguments)."""
    assignments, index = [], 0
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
            index = skip_options(words, index + 1, short_values, long_values)
            while name == "env" and index < len(words) and words[index] == "-":
                index += 1
            index += operands
        else:
            break
    return assignments, words[index:]


def program_of(words: list) -> str:
    name = os.path.basename(words[0]) if words else ""
    return name[:-4] if name.lower().endswith(".exe") else name  # git.exe from WSL


def as_git(words: list) -> list:
    """A git command run as its own program (git-push, git-subtree, from git --exec-path)
    as the git subcommand it is."""
    program = program_of(words)
    if program.startswith("git-") and len(program) > len("git-"):
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


def gh_reasons(words: list) -> list:
    operands, index = [], 1
    while index < len(words):
        word = words[index]
        index += 1
        if word in ("-R", "--repo"):
            index += 1  # gh takes the repository flag before or after the subcommand
        elif not word.startswith("-"):
            operands.append(word)
    if operands[:2] in (["pr", "create"], ["pr", "new"]):
        return [PR_CREATE_REASON]
    if operands[:2] in (["release", "create"], ["release", "new"]):
        return [RELEASE_REASON]
    if operands[:2] == ["repo", "sync"]:
        return [REPO_SYNC_REASON]
    if operands[:2] in (["repo", "create"], ["repo", "new"]) and any(
            word.partition("=")[0] == "--push" and word.partition("=")[2].lower() not in ("false", "0")
            for word in words[1:]):
        return [REPO_CREATE_PUSH_REASON]
    if operands[:2] != ["pr", "merge"]:
        return []
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
    for words in commands:
        assignments, rest = split_command(words)
        split.append((assignments, as_git(rest)))
        split.extend(([], as_git(split_command(inner)[1])) for inner in find_commands(rest))
    runs_hook_runner = any(program_of(rest) in HOOK_RUNNERS for _, rest in split)
    for assignments, rest in split:
        program = program_of(rest)
        found = [assignment_reason(name, value, program, runs_hook_runner)
                 for name, value in assignments]
        if program == "git":
            found.extend(git_reasons(rest))
        elif program == "gh":
            found.extend(gh_reasons(rest))
        publishes = any(reason in PUBLISH_REASONS for reason in found)
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
    if not all(reasons.values()):
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
