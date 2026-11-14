#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Replay the shell commands of past Claude Code sessions through two versions of the
guard's decision, without running any of them, and report what a guard change newly
blocks and newly allows, so the maintainer can judge each new block before it lands.

Usage: python3 tools/guard_replay.py [--base REF] [--head PATH] [--transcripts DIR]
                                     [--out FILE]

--base         a git ref whose home/.agents/hooks/guard_bash.py is the old guard
               (default main)
--head         the changed guard file (default this checkout's)
--transcripts  the Claude Code transcripts (default ~/.claude/projects)
--out          the Org report (default .private/evidence/guard-replay-<time>.org in the
               main checkout, also when run from a linked worktree, whose ignored files
               go with it)

Every *.jsonl under --transcripts is read line by line. A shell call is a tool_use block
named Bash with a string input.command in a record of type "assistant"; other records
(api-request-blob copies the same blocks) are counted and skipped. A call counts once per
block id, and each distinct command is judged once by each guard: by its decision() when
it has one, otherwise as main() did before decision() existed (parse_commands, with
rough_commands when the text does not parse, then command_reasons). A non-empty result is
a block. A guard that raises on a command blocks it too, with the error as its reason,
since Claude Code runs the guard with onFailure block.

Stdout gets the counts and the report's path, never a command: commands may hold
secrets, and the report stays in the git-ignored .private/.
Exit: 0 report written, 2 usage error (bad ref, missing file or folder), 1 other error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # loading the guards leaves no cache in hooks/

ROOT = Path(__file__).resolve().parent.parent
GUARD = "home/.agents/hooks/guard_bash.py"
MAX_COMMAND = 100_000
SHOWN = 300
# Org reads these at the start of a line inside a block as a heading or a keyword; a
# leading comma escapes them (Org manual, Literal Examples).
ORG_ESCAPE = re.compile(r"(?m)^([ \t]*)(,*(?:\*|#\+))")


class UsageError(Exception):
    pass


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8",
                            check=False)
    if result.returncode:
        raise UsageError(f"git {' '.join(args)}: {result.stderr.strip() or 'failed'}")
    return result.stdout.strip()


def main_checkout() -> Path:
    """The main checkout's folder, also from a linked worktree."""
    return Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent


def load_guard(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verdict_of(guard):
    """A function from a command line to the guard's reasons ({} lets it through)."""
    if callable(getattr(guard, "decision", None)):
        return guard.decision

    def pipeline(text: str) -> dict:  # a guard older than decision()
        try:
            commands = guard.parse_commands(text)
        except (guard.ParseError, RecursionError):
            commands = guard.rough_commands(text)
        return guard.command_reasons(commands)
    return pipeline


def collect(folder: Path) -> tuple:
    """({command: number of calls}, counts) from every transcript under the folder."""
    counts = dict.fromkeys(("files", "unreadable", "malformed", "other", "calls", "no command", "too long"), 0)
    commands, seen = {}, set()
    for path in sorted(folder.rglob("*.jsonl")):
        counts["files"] += 1
        try:
            with open(path, "rb") as handle:
                for line in handle:
                    if line.strip():
                        read_line(line, commands, seen, counts)
        except OSError:
            counts["unreadable"] += 1
    return commands, counts


def read_line(line: bytes, commands: dict, seen: set, counts: dict) -> None:
    try:
        record = json.loads(line)
    except (ValueError, RecursionError):
        counts["malformed"] += 1
        return
    if not isinstance(record, dict) or record.get("type") != "assistant":
        counts["other"] += 1
        return
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    for block in content if isinstance(content, list) else []:
        if not (isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash"):
            continue
        ident = block.get("id")
        if ident is not None:
            if ident in seen:
                continue
            seen.add(ident)
        counts["calls"] += 1
        given = block.get("input")
        command = given.get("command") if isinstance(given, dict) else None
        if not isinstance(command, str):
            counts["no command"] += 1
        elif len(command) > MAX_COMMAND:
            counts["too long"] += 1
        else:
            commands[command] = commands.get(command, 0) + 1


def judge(verdict, command: str) -> tuple:
    """(reasons, raised): the guard's reasons, or its error as the one reason."""
    try:
        return list(verdict(command)), False
    except Exception as error:  # the hook would fail, and Claude Code blocks then
        return [f"error: {type(error).__name__}"], True


def org_block(command: str) -> str:
    return "#+begin_example\n" + ORG_ESCAPE.sub(r"\1,\2", command[:SHOWN]) + "\n#+end_example"


def entries(title: str, found: list, calls: dict) -> list:
    lines = ["", f"* {title}", ""]
    if not found:
        return lines + ["None."]
    for number, (command, reasons) in enumerate(found, start=1):
        cut = f"; cut from {len(command):,} characters" if len(command) > SHOWN else ""
        count = calls[command]
        lines += ["", f"Command {number} of {len(found)}: {count} call{'s' if count != 1 else ''}{cut}; "
                      f"reasons: {'; '.join(reasons)}.", org_block(command)]
    return lines


def report(args, base_commit: str, head: Path, calls: dict, counts: dict, results: dict) -> tuple:
    blocked = {side: sum(1 for result in results.values() if result[side][0]) for side in ("base", "head")}
    errors = {side: sum(1 for result in results.values() if result[side][1]) for side in ("base", "head")}
    newly_blocked = sorted((command, result["head"][0]) for command, result in results.items()
                           if result["head"][0] and not result["base"][0])
    newly_allowed = sorted((command, result["base"][0]) for command, result in results.items()
                           if result["base"][0] and not result["head"][0])
    digest = hashlib.sha256(head.read_bytes()).hexdigest()
    lines = [
        "#+TITLE: Guard replay", "#+STARTUP: showall", "",
        f"- Base: {args.base} at {base_commit}",
        f"- Head: {head}, SHA-256 {digest}",
        f"- Transcripts: {args.transcripts}",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "", "* Counts", "",
        f"- transcript files: {counts['files']}",
        f"- unreadable files: {counts['unreadable']}",
        f"- lines that are not JSON: {counts['malformed']}",
        f"- records of other types: {counts['other']}",
        f"- Bash calls: {counts['calls']}",
        f"- Bash calls without a command: {counts['no command']}",
        f"- commands over {MAX_COMMAND:,} characters (skipped): {counts['too long']}",
        f"- distinct commands judged: {len(results)}",
        f"- blocked by the base guard: {blocked['base']}",
        f"- blocked by the head guard: {blocked['head']}",
        f"- errors of the base guard: {errors['base']}",
        f"- errors of the head guard: {errors['head']}",
    ]
    lines += entries("Newly blocked (the head guard blocks, the base guard allows)", newly_blocked, calls)
    lines += entries("Newly allowed (the base guard blocks, the head guard allows)", newly_allowed, calls)
    summary = (f"files {counts['files']}, calls {counts['calls']}, distinct commands {len(results)}; "
               f"newly blocked {len(newly_blocked)}, newly allowed {len(newly_allowed)}; "
               f"errors base {errors['base']}, head {errors['head']}")
    return "\n".join(lines) + "\n", summary


def replay(args) -> int:
    head = Path(args.head).resolve()
    transcripts = Path(args.transcripts).expanduser()
    if not head.is_file():
        raise UsageError(f"--head: no such file: {head}")
    if not transcripts.is_dir():
        raise UsageError(f"--transcripts: no such folder: {transcripts}")
    base_commit = git("rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}")
    with tempfile.TemporaryDirectory() as folder:
        base_file = Path(folder) / "guard_base.py"
        base_file.write_text(git("show", f"{base_commit}:{GUARD}") + "\n", encoding="utf-8")
        base = verdict_of(load_guard(base_file, "guard_replay_base"))
    head_verdict = verdict_of(load_guard(head, "guard_replay_head"))
    calls, counts = collect(transcripts)
    results = {command: {"base": judge(base, command), "head": judge(head_verdict, command)} for command in calls}
    text, summary = report(args, base_commit, head, calls, counts, results)
    out = Path(args.out) if args.out else (
        main_checkout() / ".private" / "evidence" / f"guard-replay-{time.strftime('%Y%m%d-%H%M%S')}.org")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(summary)
    print(f"report: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay past shell commands through two guards.")
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default=str(ROOT / GUARD))
    parser.add_argument("--transcripts", default=str(Path.home() / ".claude" / "projects"))
    parser.add_argument("--out")
    args = parser.parse_args()  # exits 2 on a usage error
    try:
        return replay(args)
    except UsageError as error:
        print(f"guard_replay.py: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"guard_replay.py: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
