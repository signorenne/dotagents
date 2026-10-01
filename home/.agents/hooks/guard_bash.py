#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Shell-command guard shared by every coding agent: block commands that bypass git
gates or rewrite published history.

Usage in a hook config: python3 "$HOME/.agents/hooks/guard_bash.py" --tool <claude|codex|gemini|copilot>

Blocks, in every simple command of the text:
  - git ... --no-verify, and git commit -n (skip hooks);
  - *_SKIP_HOOK(S)=<non-zero>, HUSKY=0, SKIP=<ids> assignments (hook skip switches);
  - git config --unset core.hooksPath, git -c core.hooksPath=... (disable hooks);
  - git push --force / -f / --force-with-lease / +refspec (rewrite published history).

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

HOOK_RUNNERS = {"git", "pre-commit"}

COMMIT_VALUE_OPTIONS = {"-m", "-F", "-c", "-C", "-t", "--message", "--file",
                        "--author", "--date", "--template", "--reuse-message",
                        "--reedit-message", "--fixup", "--squash", "--trailer"}
GIT_GLOBAL_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


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


def assignment_reason(name: str, value: str) -> str:
    falsy = value.strip().lower() in {"", "0", "false", "no", "off"}
    if re.search(r"SKIP_HOOKS?$", name) and not falsy:
        return f"{name}={value} skips the repository's git hooks"
    if name == "HUSKY" and value.strip() == "0":
        return "HUSKY=0 skips the repository's git hooks"
    if name == "SKIP" and not falsy:
        return "SKIP= skips pre-commit hooks"
    return ""


def git_reasons(tokens: list) -> list:
    reasons = []
    index, sub = 1, ""
    while index < len(tokens):
        token = tokens[index]
        if token in GIT_GLOBAL_VALUE_OPTIONS and index + 1 < len(tokens):
            value = tokens[index + 1]
            if token == "-c" and value.lower().startswith("core.hookspath="):
                reasons.append("git -c core.hooksPath=... disables the repository's git hooks")
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        sub = token
        break
    args = tokens[index + 1:]

    if "--no-verify" in args:
        reasons.append(f"git {sub} --no-verify skips the repository's git hooks")

    if sub == "commit":
        skip_next = False
        for token in args:
            if skip_next:
                skip_next = False
                continue
            if token in COMMIT_VALUE_OPTIONS:
                skip_next = True
                continue
            if re.fullmatch(r"-[A-Za-z]*n[A-Za-z]*", token):
                reasons.append("git commit -n skips the repository's git hooks")
                break

    if sub == "push":
        for token in args:
            if token.startswith("--force") or re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", token):
                reasons.append("force push rewrites published history")
                break
            if token.startswith("+") and len(token) > 1:
                reasons.append("a +refspec push rewrites published history")
                break

    if sub == "config":
        lowered = [t.lower() for t in args]
        if any(t.startswith("--unset") for t in lowered) and "core.hookspath" in lowered:
            reasons.append("unsetting core.hooksPath disables the repository's git hooks")
    return reasons


def command_reasons(commands: list) -> list:
    reasons = []
    for tokens in commands:
        rest = list(tokens)
        while rest and rest[0] in {"export", "env"}:
            rest = rest[1:]
        while rest:
            match = ASSIGNMENT.match(rest[0])
            if not match:
                break
            reason = assignment_reason(match.group(1), match.group(2))
            if reason:
                reasons.append(reason)
            rest = rest[1:]
        if rest and (rest[0] == "git" or rest[0].endswith("/git")):
            reasons.extend(git_reasons(rest))
    return list(dict.fromkeys(reasons))


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
    reasons = command_reasons(commands)
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
