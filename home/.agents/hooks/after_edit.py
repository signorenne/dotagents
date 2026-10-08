#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""After-edit hook shared by every coding agent.

Usage in a hook config: python3 "$HOME/.agents/hooks/after_edit.py" --tool <claude|codex|gemini|copilot>

1. Flags em dash (U+2014) and en dash (U+2013) characters in the text the agent just
   wrote. Only the new text is checked, so dashes already in the file are not reported.
2. Runs clang-format in place on C and C++ files when the project has a .clang-format
   file and a clang-format binary is available (CLANG_FORMAT, clang-format-20, clang-format).

Payload shapes understood: Claude Code and Cursor (Write/Edit with file_path, content,
new_string), Gemini CLI (write_file/replace with file_path, content, new_string), Codex
(apply_patch with the patch text in tool_input.command), Copilot (path, file_text,
new_str), Cursor native afterFileEdit (file_path, edits[].new_string).

Problems: exit 2 with the report on stderr, which the agent sees. Unreadable input
exits 0 so a broken payload never stops normal work. Gemini CLI needs JSON on stdout
when the hook succeeds; Claude Code receives the reformat notice as additionalContext.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DASHES = {"\u2014": "em dash", "\u2013": "en dash"}
CXX_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".ipp", ".tpp", ".inl",
                ".c", ".cc", ".cpp", ".cxx"}
MAX_REPORTED_LINES = 8
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$")
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+)$")


def as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def parse_patch(patch: str) -> tuple[list[str], str]:
    """Return (files, added text) from an apply_patch body."""
    files, added = [], []
    for line in patch.splitlines():
        match = PATCH_FILE.match(line) or PATCH_MOVE.match(line)
        if match:
            files.append(match.group(1).strip())
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return files, "\n".join(added)


def extract(payload: dict) -> tuple[list[Path], str]:
    """Return (edited files, new text) for any supported payload shape."""
    tool_input = as_dict(payload.get("tool_input")) or as_dict(payload.get("toolArgs"))
    cwd = Path(payload.get("cwd") or os.getcwd())

    command = tool_input.get("command")
    if isinstance(command, str) and "*** Begin Patch" in command:
        files, text = parse_patch(command)
        return [(cwd / f) if not Path(f).is_absolute() else Path(f) for f in files], text

    path = (tool_input.get("file_path") or tool_input.get("path")
            or payload.get("file_path") or "")
    parts = []
    for key in ("content", "new_string", "file_text", "new_str"):
        if isinstance(tool_input.get(key), str):
            parts.append(tool_input[key])
    for edits in (tool_input.get("edits"), payload.get("edits")):
        if isinstance(edits, list):
            parts.extend(e.get("new_string", "") for e in edits if isinstance(e, dict))
    if not path:
        return [], "\n".join(parts)
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = cwd / file_path
    return [file_path], "\n".join(parts)


def dash_report(paths: list[Path], text: str) -> str:
    hits = []
    for line in text.splitlines():
        kinds = sorted({name for char, name in DASHES.items() if char in line})
        if kinds:
            hits.append(f"  [{', '.join(kinds)}] {line.strip()[:160]}")
    if not hits:
        return ""
    shown = hits[:MAX_REPORTED_LINES]
    more = len(hits) - len(shown)
    tail = f"\n  ... and {more} more line(s)" if more > 0 else ""
    where = ", ".join(str(p) for p in paths) or "the edited file"
    return (
        f"Em/en dash written to {where}. Replace each with a comma, colon, "
        "parentheses, a period, or a plain hyphen. Keep it only if it is required "
        "data (for example a test string), and say so.\n" + "\n".join(shown) + tail
    )


def has_clang_format_config(file_path: Path) -> bool:
    for directory in [file_path.parent, *file_path.parent.parents]:
        if (directory / ".clang-format").is_file() or (directory / "_clang-format").is_file():
            return True
        if (directory / ".git").exists():
            return False
    return False


def clang_format_binary() -> str:
    for candidate in (os.environ.get("CLANG_FORMAT"), "clang-format-20", "clang-format"):
        if candidate and shutil.which(candidate):
            return candidate
    return ""


def run_clang_format(file_path: Path) -> tuple[str, str]:
    """Return (notice, error) for one file."""
    if file_path.suffix.lower() not in CXX_SUFFIXES or not file_path.is_file():
        return "", ""
    if not has_clang_format_config(file_path):
        return "", ""
    binary = clang_format_binary()
    if not binary:
        return "", ""
    before = file_path.read_bytes()
    try:
        result = subprocess.run([binary, "-i", "--style=file", str(file_path)],
                                capture_output=True, text=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", f"clang-format did not run on {file_path}: {error}. Formatting not applied."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:600]
        return "", f"clang-format failed on {file_path} (formatting not applied):\n{detail}"
    if file_path.read_bytes() != before:
        return f"{binary} reformatted {file_path}. Re-read it before editing it again.", ""
    return "", ""


def finish(tool: str, notices: list[str]) -> int:
    if tool == "claude" and notices:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(notices)}}))
    elif tool == "gemini":
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
        return finish(tool, [])
    if not isinstance(payload, dict):
        return finish(tool, [])

    paths, text = extract(payload)
    problems, notices = [], []
    report = dash_report(paths, text)
    if report:
        problems.append(report)
    for path in paths:
        try:
            notice, error = run_clang_format(path)
        except OSError:
            continue
        if notice:
            notices.append(notice)
        if error:
            problems.append(error)

    if problems:
        print("\n\n".join(problems + notices), file=sys.stderr)
        return 2
    return finish(tool, notices)


if __name__ == "__main__":
    sys.exit(main())
