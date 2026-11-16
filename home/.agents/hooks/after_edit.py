#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""After-edit hook shared by every coding agent.

Usage in a hook config:
  python3 "$HOME/.agents/hooks/after_edit.py" --tool <claude|codex|gemini|antigravity|copilot>

1. Flags em dash (U+2014) and en dash (U+2013) characters in the text the agent just
   wrote: the new string of an edit, the added lines of a patch, the whole content of a
   file write. Dashes elsewhere in an edited file are not reported; a file write reports
   every dash in the file, since its content is the whole file.
2. Runs clang-format in place on C and C++ files when the project has a .clang-format
   file and a clang-format binary is available (CLANG_FORMAT, clang-format-20, clang-format),
   within a total time budget under the 60 s hook timeout of every agent's config. A file
   written in full (a file write, an added file of a patch) is formatted whole. An edit
   formats only the lines it changed (clang-format --lines), so lines the agent never
   touched keep their formatting. The lines come from the payload when it has them
   (Claude Code's tool_response carries a structuredPatch, also for a write over an
   existing file); otherwise from where the new text stands in the file: a patch hunk
   located by its context, a new string located where it occurs once, or everywhere it
   occurs when the edit replaced every occurrence. An edit whose lines cannot be located
   is not formatted.
3. Checks the syntax of each edited Python, JSON or TOML file, whole, with the standard
   library: compile() for .py (warnings ignored), json for .json (a byte order mark
   allowed; tsconfig*.json, jsconfig*.json, .eslintrc.json, devcontainer.json,
   .devcontainer.json and files under .vscode/ or .devcontainer/ are skipped, since
   those tools allow comments, and a file that parses once its comments outside strings,
   and then its trailing commas, are blanked out is not reported either, since more
   tools read JSON with comments than a list can hold), and tomllib for .toml where the Python is 3.11 or later (skipped before). Files over
   2 MB, and missing ones, are skipped. An error is reported like a dash, with the
   Python version for a .py file, since code for a newer Python may not compile.

Payload shapes understood: Claude Code and Cursor (Write/Edit with file_path, content,
new_string), Gemini CLI (write_file/replace with file_path, content, new_string), Codex
(apply_patch with the patch text in tool_input.command), Copilot (toolArgs as a JSON
string with path, file_text, new_str), Cursor native afterFileEdit (file_path,
edits[].new_string), Antigravity CLI (toolCall.args of write_to_file with TargetFile and
CodeContent, of replace_file_content with ReplacementContent and AllowMultiple; a
relative TargetFile starts at the first workspace path, and a call that reports an error
wrote nothing). Antigravity documents no fields for the chunks of
multi_replace_file_content, so that edit is neither checked nor formatted.

Problems: exit 2 with the report on stderr, which the agent sees; Copilot shows that
only to the user, so there the report goes to the model as additionalContext with exit
0. Unreadable input exits 0 so a broken payload never stops normal work. Gemini CLI
needs JSON on stdout when the hook succeeds. The reformat notice reaches the agent as
additionalContext in each agent's documented format: hookSpecificOutput for Claude
Code and Codex (PostToolUse) and Gemini CLI (AfterTool), a top-level field for Copilot.
Cursor runs the Claude Code hook command and gets its format. Antigravity CLI documents
only {} as the reply and no exit codes, so it gets {} with exit 0, and the report and the
reformat notice go to stderr, where they are not documented to reach the agent.
"""

import argparse
import bisect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import NamedTuple, Optional

try:
    import tomllib  # Python 3.11 or later
except ImportError:
    tomllib = None

DASHES = {"\u2014": "em dash", "\u2013": "en dash"}
CXX_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".ipp", ".tpp", ".inl",
                ".c", ".cc", ".cpp", ".cxx"}
MAX_REPORTED_LINES = 8
PATCH_FILE = re.compile(r"^\*\*\* (Add|Update) File: (.+)$")
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+)$")
# Total budget for clang-format, under the 60 s hook timeout in every agent's config.
DEADLINE_SECONDS = 50
CALL_TIMEOUT_SECONDS = 45
MIN_CALL_SECONDS = 1
SYNTAX_SUFFIXES = {".py", ".json", ".toml"}
MAX_SYNTAX_BYTES = 2_000_000
# JSON files that their tools read with comments allowed (TypeScript, ESLint, VS Code,
# dev containers).
JSONC_NAME = re.compile(r"^((tsconfig|jsconfig)(\..+)?\.json|\.eslintrc\.json|\.?devcontainer\.json)$")
JSONC_FOLDERS = {".vscode", ".devcontainer"}
# A JSON string (to the end of its line when it never closes), a // or /* comment
# outside one (a /* that never closes runs to the end), or a comma before a closing
# bracket. Every part matches without failing, so nothing backtracks.
JSON_STRING = r'"(?:[^"\\\n]|\\.)*"?'
JSON_STRING_OR_COMMENT = re.compile(JSON_STRING + r'|//[^\n]*|/\*(?:[^*]|\*(?!/))*(?:\*/)?')
JSON_STRING_OR_TRAILING_COMMA = re.compile(JSON_STRING + r'|,(?=\s*[\]}])')


def as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, RecursionError):
            return {}
    return {}


class Piece(NamedTuple):
    """New text that an edit put in a file, as it stands there after the edit."""
    text: str
    edited: tuple = ()  # indexes of its lines the edit added; empty: all of them
    full_lines: bool = False  # it starts at the start of a line (a diff hunk)
    everywhere: bool = False  # the edit replaced every occurrence


# What to format in a file: None for all of it, else a list of known line numbers (int)
# and pieces of new text to locate.


def diff_hunk(lines: list) -> tuple[list[str], list[int]]:
    """Return (the new side, indexes of its added lines) of a hunk whose lines start with
    " " (context), "-" or "+". An empty line is an empty context line; others, such as
    "\\ No newline at end of file", are not in the new file."""
    new, added = [], []
    for line in lines:
        mark = line[:1]
        if mark == "+":
            added.append(len(new))
        if mark in ("+", " ", ""):
            new.append(line[1:])
    return new, added


def hunk_piece(lines: list) -> Optional[Piece]:
    new, added = diff_hunk(lines)
    return Piece("\n".join(new), tuple(added), full_lines=True) if added else None


def patch_lines(response) -> Optional[list]:
    """Line numbers of the lines an edit added, from the structuredPatch Claude Code puts in
    tool_response (newStart: the 1-based line of a hunk's first line in the new file), or
    None when the payload has no usable patch (a new file has an empty one)."""
    hunks = as_dict(response).get("structuredPatch")
    if not isinstance(hunks, list) or not hunks:
        return None
    lines = []
    for hunk in hunks:
        start = hunk.get("newStart") if isinstance(hunk, dict) else None
        rows = hunk.get("lines") if isinstance(hunk, dict) else None
        if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(rows, list)
                or not all(isinstance(row, str) for row in rows)):
            return None
        lines.extend(start + index for index in diff_hunk(rows)[1])
    return lines


def parse_patch(patch: str) -> tuple[list[str], str, dict]:
    """Return (files, added text, what to format per file) from an apply_patch body. The
    format has no "+++" file headers, so every line starting with "+" is an added line
    ("+++i;" adds "++i;"). An added file is formatted whole, an updated one where the
    added lines of its hunks stand (in the file it is moved to, if any)."""
    files, added, targets = [], [], {}
    target, hunk = None, []

    def end_hunk():
        if target is not None and targets[target] is not None and hunk:
            piece = hunk_piece(hunk)
            if piece:
                targets[target].append(piece)
        hunk.clear()

    for line in patch.splitlines():
        header, move = PATCH_FILE.match(line), PATCH_MOVE.match(line)
        if line.startswith("*** ") or line.startswith("@@"):
            end_hunk()
        if header:
            target = header.group(2).strip()
            files.append(target)
            targets[target] = None if header.group(1) == "Add" else []
        elif move:
            files.append(move.group(1).strip())
            if target is not None:
                targets[files[-1]] = targets.pop(target)
                target = files[-1]
        elif line.startswith("*** ") and not line.startswith("*** End of File"):
            target = None  # Delete File, End Patch
        elif not line.startswith("*** ") and not line.startswith("@@"):
            hunk.append(line)
            if line.startswith("+"):
                added.append(line[1:])
    end_hunk()
    return files, "\n".join(added), targets


def antigravity_edit(payload: dict, call: dict) -> tuple[list[Path], str, dict]:
    """extract() for Antigravity CLI's toolCall {name, args}."""
    args = as_dict(call.get("args"))
    path, error = args.get("TargetFile"), payload.get("error")
    if not isinstance(path, str) or not path or error:  # a failed call wrote nothing
        return [], "", {}
    roots = payload.get("workspacePaths")
    root = next((r for r in roots if isinstance(r, str) and r), "") if isinstance(roots, list) else ""
    file_path = Path(path) if Path(path).is_absolute() else Path(root or os.getcwd()) / path
    content, new = args.get("CodeContent"), args.get("ReplacementContent")
    if isinstance(content, str):
        return [file_path], content, {file_path: None}
    if isinstance(new, str):
        return [file_path], new, {file_path: [Piece(new, everywhere=args.get("AllowMultiple") is True)]}
    return [file_path], "", {file_path: []}


def extract(payload: dict) -> tuple[list[Path], str, dict]:
    """Return (edited files, new text, what to format in each file) for any supported
    payload shape."""
    call = as_dict(payload.get("toolCall"))
    if call:
        return antigravity_edit(payload, call)
    tool_input = as_dict(payload.get("tool_input")) or as_dict(payload.get("toolArgs"))
    cwd = payload.get("cwd")
    cwd = Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())

    def absolute(name: str) -> Path:
        return Path(name) if Path(name).is_absolute() else cwd / name

    command = tool_input.get("command")
    if isinstance(command, str) and "*** Begin Patch" in command:
        files, text, targets = parse_patch(command)
        return [absolute(f) for f in files], text, {absolute(f): t for f, t in targets.items()}

    candidates = (tool_input.get("file_path"), tool_input.get("path"), payload.get("file_path"))
    path = next((c for c in candidates if isinstance(c, str) and c), "")
    parts, pieces, written = [], [], False
    replace_all = tool_input.get("replace_all") is True
    for key in ("content", "new_string", "file_text", "new_str"):
        if isinstance(tool_input.get(key), str):
            parts.append(tool_input[key])
            if key in ("content", "file_text"):
                written = True
            else:
                pieces.append(Piece(tool_input[key], everywhere=replace_all))
    for edits in (tool_input.get("edits"), payload.get("edits")):
        if isinstance(edits, list):
            for e in edits:
                if isinstance(e, dict) and isinstance(e.get("new_string"), str):
                    parts.append(e["new_string"])
                    pieces.append(Piece(e["new_string"], everywhere=e.get("replace_all") is True))
    if not path:
        return [], "\n".join(parts), {}
    file_path = absolute(path)
    target = patch_lines(payload.get("tool_response"))
    if target is None:
        target = None if written else pieces
    return [file_path], "\n".join(parts), {file_path: target}


def piece_lines(content: str, line_starts: list, piece: Piece) -> set:
    """The line numbers of piece in content; none when it cannot be located (absent, or
    found more than once for an edit made in one place)."""
    text = piece.text.replace("\r\n", "\n")
    if not text:
        return set()
    offsets = []
    at = content.find(text)
    while at >= 0 and (piece.everywhere or len(offsets) < 2):
        if not piece.full_lines or at == 0 or content[at - 1] == "\n":
            offsets.append(at)
        at = content.find(text, at + 1)
    rows = text.split("\n")
    if len(offsets) != 1 and not (offsets and piece.everywhere):
        if piece.edited and len(piece.edited) < len(rows):
            # A hunk whose context does not match as written (apply_patch tolerates
            # whitespace changes there): locate each run of its added lines instead.
            lines, run = set(), []
            for index in list(piece.edited) + [None]:
                if run and index != run[-1] + 1:
                    run_text = "\n".join(rows[run[0]:run[-1] + 1])
                    lines |= piece_lines(content, line_starts, Piece(run_text, full_lines=True))
                    run = []
                if index is not None:
                    run.append(index)
            return lines
        return set()
    span = text.count("\n", 0, len(text) - 1) + 1
    indexes = piece.edited or range(span)
    lines = set()
    for at in offsets:
        first = bisect.bisect_right(line_starts, at)
        lines.update(first + index for index in indexes)
    return lines


def line_ranges(content: str, items: list) -> list[tuple[int, int]]:
    """Merge the known line numbers and the located pieces of items into sorted
    (first, last) ranges of existing lines."""
    content = content.replace("\r\n", "\n")
    line_starts = [0] + [match.end() for match in re.finditer("\n", content)]
    count = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
    lines = set()
    for item in items:
        if isinstance(item, Piece):
            lines |= piece_lines(content, line_starts, item)
        elif isinstance(item, int):
            lines.add(item)
    ranges = []
    for line in sorted(n for n in lines if 1 <= n <= count):
        if ranges and line == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], line)
        else:
            ranges.append((line, line))
    return ranges


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


def blank(match) -> str:
    """A comment or a trailing comma as spaces, newlines kept, so positions stay."""
    text = match.group(0)
    return text if text.startswith('"') else re.sub(r"[^\n]", " ", text)


def without_comments(text: str) -> str:
    """JSON text with its comments outside strings blanked out and, when it had any, its
    trailing commas too (JSON with comments allows them); the same text when it had none."""
    stripped = JSON_STRING_OR_COMMENT.sub(blank, text)
    return text if stripped == text else JSON_STRING_OR_TRAILING_COMMA.sub(blank, stripped)


def syntax_error(path: Path) -> str:
    """A one-line report of a syntax error in a Python, JSON or TOML file, or ""."""
    suffix = path.suffix.lower()
    if suffix not in SYNTAX_SUFFIXES or (suffix == ".toml" and tomllib is None):
        return ""
    if suffix == ".json" and (JSONC_NAME.match(path.name) or JSONC_FOLDERS & set(path.parts)):
        return ""
    if not path.is_file() or path.stat().st_size > MAX_SYNTAX_BYTES:
        return ""
    data = path.read_bytes()
    if suffix == ".py":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                compile(data, str(path), "exec", dont_inherit=True)
        except SyntaxError as error:
            where = f":{error.lineno}" if error.lineno else ""
            version = f"{sys.version_info[0]}.{sys.version_info[1]}"
            return f"Python syntax error in {path}{where}: {error.msg} (checked with Python {version})."
        except (ValueError, RecursionError, MemoryError):  # null bytes, or too deep to check
            pass
        return ""
    kind = suffix[1:].upper()
    try:
        text = data.decode("utf-8-sig" if suffix == ".json" else "utf-8")
    except UnicodeDecodeError as error:
        return f"{kind} file {path} is not valid UTF-8: {error}."
    try:
        if suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError:
                # JSON with comments, read by a tool that allows them, passes once they
                # are blanked out; any other error remains, at the same place.
                json.loads(without_comments(text))
        else:
            tomllib.loads(text)
    except json.JSONDecodeError as error:
        return f"JSON syntax error in {path}:{error.lineno}:{error.colno}: {error.msg}."
    except RecursionError:
        pass
    except ValueError as error:  # tomllib.TOMLDecodeError
        return f"TOML syntax error in {path}: {error}."
    return ""


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


def run_clang_format(file_path: Path, deadline: float, target) -> tuple[str, str]:
    """Return (notice, error) for one file; target says what to format (see extract)."""
    if file_path.suffix.lower() not in CXX_SUFFIXES or not file_path.is_file():
        return "", ""
    if not has_clang_format_config(file_path):
        return "", ""
    binary = clang_format_binary()
    if not binary:
        return "", ""
    before = file_path.read_bytes()
    ranges = []
    if target is not None:
        ranges = line_ranges(before.decode("utf-8", errors="replace"), target)
        if not ranges:
            return "", ""
    left = deadline - time.monotonic()
    if left < MIN_CALL_SECONDS:
        return "", f"clang-format skipped on {file_path}: the hook ran out of time. Formatting not applied."
    lines = [f"--lines={first}:{last}" for first, last in ranges]
    try:
        result = subprocess.run([binary, "-i", "--style=file", *lines, str(file_path)], capture_output=True,
                                text=True, timeout=min(CALL_TIMEOUT_SECONDS, left), check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", f"clang-format did not run on {file_path}: {error}. Formatting not applied."
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:600]
        return "", f"clang-format failed on {file_path} (formatting not applied):\n{detail}"
    if file_path.read_bytes() != before:
        where = ""
        if ranges:
            spans = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)
            where = f" (the edited lines {spans})"
        return f"{binary} reformatted {file_path}{where}. Re-read it before editing it again.", ""
    return "", ""


def finish(tool: str, notices: list[str]) -> int:
    context = "\n".join(notices)
    if tool in ("claude", "codex") and notices:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": context}}))
    elif tool == "gemini":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "AfterTool", "additionalContext": context}}) if notices else "{}")
    elif tool == "copilot" and notices:
        print(json.dumps({"additionalContext": context}))
    elif tool == "antigravity":
        print("{}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", default="claude",
                        choices=["claude", "codex", "gemini", "antigravity", "copilot", "cursor"])
    tool = parser.parse_args().tool
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        payload = json.load(sys.stdin)
    except (ValueError, RecursionError):
        return finish(tool, [])
    if not isinstance(payload, dict):
        return finish(tool, [])

    paths, text, targets = extract(payload)
    problems, notices = [], []
    report = dash_report(paths, text)
    if report:
        problems.append(report)
    for path in paths:
        try:
            error = syntax_error(path)
        except OSError:
            error = ""
        if error:
            problems.append(error)
        try:
            notice, error = run_clang_format(path, deadline, targets.get(path, []))
        except OSError:
            continue
        if notice:
            notices.append(notice)
        if error:
            problems.append(error)

    if problems and tool == "copilot":
        # Copilot shows a postToolUse exit 2 only to the user; the context reaches the model.
        notices = ["\n\n".join(problems + notices)]
    elif tool == "antigravity" and (problems or notices):
        print("\n\n".join(problems + notices), file=sys.stderr)
    elif problems:
        print("\n\n".join(problems + notices), file=sys.stderr)
        return 2
    return finish(tool, notices)


if __name__ == "__main__":
    sys.exit(main())
