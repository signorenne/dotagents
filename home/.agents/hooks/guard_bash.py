#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Shell-command guard shared by every coding agent: block commands that bypass git
gates or rewrite published history.

Usage in a hook config: python3 "$HOME/.agents/hooks/guard_bash.py" --tool <claude|codex|gemini|copilot>

Blocks, per shell segment:
  - git ... --no-verify, and git commit -n (skip hooks);
  - *_SKIP_HOOK(S)=<non-zero>, HUSKY=0, SKIP=<ids> assignments (hook skip switches);
  - git push --force / -f / --force-with-lease / +refspec (rewrite published history);
  - git config --unset core.hooksPath, git -c core.hooksPath=... (disable hooks).

The command is tokenized with shlex, so text inside quotes (a commit message that
mentions -n or --no-verify) is not mistaken for a flag. This guards the usual forms;
it is not a security boundary (a command hidden in bash -c "..." or a script is not
inspected).

Blocking: exit 2 with the reason on stderr (Claude Code, Codex, Gemini CLI, Cursor;
Copilot denies on any non-zero exit). Unreadable input exits 0 so a broken payload
never stops normal work. Gemini CLI needs JSON on stdout when the hook succeeds.
"""

import argparse
import json
import re
import shlex
import sys

OPERATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", "\n"}
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
COMMIT_VALUE_OPTIONS = {"-m", "-F", "-c", "-C", "-t", "--message", "--file",
                        "--author", "--date", "--template", "--reuse-message",
                        "--reedit-message", "--fixup", "--squash", "--trailer"}
GIT_GLOBAL_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def extract_command(payload: dict) -> str:
    """Find the shell command in any supported agent's payload shape."""
    for container in (payload.get("tool_input"), payload.get("toolArgs"), payload):
        if isinstance(container, str):
            try:
                container = json.loads(container)
            except (json.JSONDecodeError, ValueError):
                continue
        if isinstance(container, dict) and isinstance(container.get("command"), str):
            return container["command"]
    return ""


def segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    result, current = [], []
    for token in lexer:
        if token in OPERATORS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def assignment_reason(name: str, value: str) -> str:
    falsy = value.strip().lower() in {"", "0", "false", "no", "off"}
    if re.search(r"SKIP_HOOKS?$", name) and not falsy:
        return f"{name}={value} skips the repository's git hooks"
    if name == "HUSKY" and value.strip() == "0":
        return "HUSKY=0 skips the repository's git hooks"
    if name == "SKIP" and not falsy:
        return "SKIP= skips pre-commit hooks"
    return ""


def git_reasons(tokens: list[str]) -> list[str]:
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


def command_reasons(command: str) -> list[str]:
    reasons = []
    for tokens in segments(command):
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
    except (json.JSONDecodeError, ValueError):
        return allow(tool)
    if not isinstance(payload, dict):
        return allow(tool)
    command = extract_command(payload)
    if not command:
        return allow(tool)
    try:
        reasons = command_reasons(command)
    except ValueError:  # unbalanced quotes: the shell would reject the command anyway
        return allow(tool)
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
