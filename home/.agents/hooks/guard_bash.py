#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Shell-command guard shared by every coding agent: block commands that bypass git
gates or rewrite or delete published history.

Usage in a hook config: python3 "$HOME/.agents/hooks/guard_bash.py" --tool <claude|codex|gemini|copilot|cursor>

Blocks, in every simple command of the text (also after keywords such as if, do, ! and
wrappers such as sudo, env, xargs, time, nice, timeout):
  - git commit|push|merge|rebase|am|pull|cherry-pick --no-verify (or a prefix git accepts
    for it), git commit -n and git am -n (skip hooks);
  - hook skip switches: *_SKIP_HOOK(S)=<non-zero>, HUSKY=0|false, LEFTHOOK=0|false,
    OVERCOMMIT_DISABLE=1, and SKIP=<ids> when the command runs git or pre-commit;
  - hooks disabled through core.hooksPath: git config [--]unset core.hooksPath, git config
    core.hooksPath set to an empty path or /dev/null, git -c or --config-env
    core.hooksPath=..., GIT_CONFIG_KEY_<n> or GIT_CONFIG_PARAMETERS naming core.hooksPath;
  - git push that rewrites or deletes published history: --force, -f, --force-with-lease,
    --force-if-includes, +refspec, --delete, -d, :ref, --mirror, --prune;
  - every git push when the agent is not Claude Code, since Claude Code asks the user
    before a push and the others do not. Cursor runs the Claude Code hook command as
    well; it is told apart by its documented CURSOR_VERSION variable or the
    cursor_version payload field.

The text is split as a shell does: quotes, escapes, comments, newlines, the operators
; & | ( ), redirections, command substitutions and here-documents, whose body is text,
not commands. So a commit message that mentions -n or --no-verify is not mistaken for a
flag. Text that does not parse (an unbalanced quote) is checked by a rough split that
ignores quoting, so a parse error never lets a forbidden command through. This guards
the usual forms; it is not a security boundary (bash -c "...", eval, aliases and
scripts are not inspected).

Blocking: exit 2 with the reason on stderr (Claude Code, Codex, Gemini CLI, Cursor;
Copilot denies on any non-zero exit). Unreadable input exits 0 so a broken payload
never stops normal work. Gemini CLI needs JSON on stdout when the hook succeeds.
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

KEYWORDS = {"!", "{", "if", "then", "elif", "else", "while", "until", "do"}
DECLARATIONS = {"export", "declare", "typeset", "local", "readonly"}
# Commands that run the command after them: (short options taking a value, long options
# taking the next word as value, operands before the command).
WRAPPERS = {
    "builtin": ("", (), 0),
    "command": ("", (), 0),
    "doas": ("Cu", (), 0),
    "env": ("CSu", ("--chdir", "--split-string", "--unset"), 0),
    "exec": ("a", (), 0),
    "nice": ("n", ("--adjustment",), 0),
    "nohup": ("", (), 0),
    "sudo": ("CDghpRrTtUu", ("--chdir", "--chroot", "--close-from", "--command-timeout",
                             "--group", "--host", "--other-user", "--prompt", "--role",
                             "--type", "--user"), 0),
    "time": ("fo", ("--format", "--output"), 0),
    "timeout": ("ks", ("--kill-after", "--signal"), 1),
    "xargs": ("adEILnPs", ("--arg-file", "--delimiter", "--max-args", "--max-chars",
                           "--max-procs", "--process-slot-var"), 0),
}
HOOK_RUNNERS = {"git", "pre-commit"}

GIT_VALUE_OPTIONS = {"-C", "-c", "--config-env", "--git-dir", "--namespace", "--work-tree"}
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
CONFIG_VALUE_OPTIONS = {"-f", "--blob", "--comment", "--default", "--file", "--type",
                        "--url", "--value"}
CONFIG_ACTIONS = {"edit", "get", "list", "remove-section", "rename-section", "set", "unset"}


class ParseError(ValueError):
    """The text is not a complete shell command (an unbalanced quote, for example)."""


class Parser:
    """Split shell text into simple commands, each a list of words without quotes.

    Commands inside $(...), backticks and <(...) are listed too. Redirections are
    dropped; here-document bodies are skipped, except the substitutions an unquoted
    delimiter lets the shell run."""

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
            elif char == "$" and self.peek(1) == "(":
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
            elif char == "$" and self.peek(1) == "(":
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
        start = self.pos
        self.pos += 2
        self.parse(nested=True)
        return self.text[start:self.pos]

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
    new command at every git or pre-commit word, so a forbidden command is still
    found (words inside quotes may then read as flags)."""
    text = re.sub(r"\\\n", "", text)
    text = re.sub(r"&>|[<>]&", " > ", text)
    text = re.sub(r"[\"'\\]", "", text).replace("`", " ")
    commands = []
    for piece in re.split(r"[;&|()\n]+", text):
        command = []
        for word in piece.split():
            if command and os.path.basename(word) in HOOK_RUNNERS:
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
    return os.path.basename(words[0]) if words else ""


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


def push_reasons(shorts: set, longs: list, operands: list, plain_push_allowed: bool) -> list:
    reasons = []
    if not plain_push_allowed:
        reasons.append("git push runs only in Claude Code, which asks the user before each push")
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
    if not reading and len(operands) > 1 and operands[1].strip() in ("", "/dev/null"):
        return "core.hooksPath set to an empty path or /dev/null disables the repository's git hooks"
    return ""


def git_reasons(words: list, plain_push_allowed: bool) -> list:
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
        reasons.extend(push_reasons(shorts, longs, operands, plain_push_allowed))
    if sub == "config":
        reasons.append(config_reason(args))
    return [reason for reason in reasons if reason]


def command_reasons(commands: list, plain_push_allowed: bool) -> list:
    reasons = []
    split = [split_command(words) for words in commands]
    runs_hook_runner = any(program_of(rest) in HOOK_RUNNERS for _, rest in split)
    for assignments, rest in split:
        program = program_of(rest)
        for name, value in assignments:
            reasons.append(assignment_reason(name, value, program, runs_hook_runner))
        if program == "git":
            reasons.extend(git_reasons(rest, plain_push_allowed))
    return list(dict.fromkeys(reason for reason in reasons if reason))


def extract_command(payload: dict) -> str:
    """Find the shell command in any supported agent's payload shape."""
    for container in (payload.get("tool_input"), payload.get("toolArgs"), payload):
        if isinstance(container, str):
            try:
                container = json.loads(container)
            except (ValueError, RecursionError):
                continue
        if isinstance(container, dict) and isinstance(container.get("command"), str):
            return container["command"]
    return ""


def running_in_cursor(payload: dict) -> bool:
    """Cursor runs the Claude Code hook command too; it sets CURSOR_VERSION for every
    hook process and sends cursor_version in every payload (cursor.com/docs/agent/hooks)."""
    return bool(os.environ.get("CURSOR_VERSION")) or "cursor_version" in payload


def allow(tool: str) -> int:
    if tool == "gemini":
        print("{}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", default="claude",
                        choices=["claude", "codex", "gemini", "copilot", "cursor"])
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
    plain_push_allowed = tool == "claude" and not running_in_cursor(payload)
    reasons = command_reasons(commands, plain_push_allowed)
    if not reasons:
        return allow(tool)
    print(
        "Blocked: " + "; ".join(reasons) + ". "
        "Gates and published history are the maintainer's call. Fix the failing "
        "check, or stop and ask the user to run this command themselves.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
