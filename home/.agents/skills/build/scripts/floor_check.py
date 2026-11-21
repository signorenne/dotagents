#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Compare a change with its base and report what must never pass unnoticed: removed
tests, added skips, added suppressions, the size of the change and the risk surfaces it
touches. A quick-lane change that outgrew its lane is reported as raised to the full lane.
It also says whether the diff changes only documentation or Python comments, the proof a
docs-only change needs before it runs the lighter gates (METHOD.org, Checks).

  python3 floor_check.py [--base REF] [--cwd DIR] [--lane quick|full] [--quick-limit 100]

The base is --base, else the plan's Base, else the merge base with main (or master). The
diff is the base against the working tree, so uncommitted work counts, and so does each
untracked file git does not ignore (every .private folder left out), read as added lines
and printed as "untracked, counted as added: <paths>"; a binary one (a NUL byte in its
first 8,000 bytes) is printed as "untracked, binary, not scanned: <paths>". Test, skip and suppression patterns cover Python, C and C++ (GoogleTest,
Catch2, Qt Test), JavaScript and TypeScript, Go, Java, Kotlin and Rust; risk surfaces are
path and line patterns, hints for the agent's judgment. The lane is --lane, else the
plan's Lane.

Exit 0: nothing to report. 1: something to report (each item printed). 2: the check
could not run (no repository, unknown base, git failed); it never reads as clean.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import tokenize
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import planfile  # beside this script

TEST_DEFINITIONS = (
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),                                  # Python
    re.compile(r"^\s*class\s+(Test\w*)\b"),                                                  # Python
    re.compile(r"^\s*(?:TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)\s*\(\s*(\w+\s*,\s*\w+)"),   # GoogleTest
    re.compile(r"^\s*(?:TEST_CASE|SCENARIO)\s*\(\s*\"([^\"]+)\""),                           # Catch2
    re.compile(r"^\s*void\s+(test\w*)\s*\(\s*\)\s*;"),                                         # Qt Test slots
    re.compile(r"^\s*(?:it|test)\s*\(\s*['\"`]([^'\"`]+)"),                                   # JS, TS
    re.compile(r"^\s*func\s+(Test\w+)\s*\("),                                                # Go
    re.compile(r"^\s*(?:public\s+)?(?:fun|void)\s+(`[^`]+`|test\w*)\s*\("),                   # Kotlin, Java
    re.compile(r"^\s*#\[(test)\]"),                                                          # Rust (counted)
)
SKIPS = re.compile(
    r"@unittest\.skip|@pytest\.mark\.(?:skip|xfail)|pytest\.skip\(|\.skipTest\(|expectedFailure|"
    r"\bDISABLED_|GTEST_SKIP|\bQSKIP\(|\b(?:it|test|describe)\.(?:skip|todo)\(|\bx(?:it|describe|test)\(|"
    r"\bt\.Skip(?:f|Now)?\(|@Ignore\b|@Disabled\b|#\[ignore\]")
SUPPRESSIONS = re.compile(
    r"#\s*noqa|#\s*type:\s*ignore|#\s*pylint:\s*disable|#\s*pragma:\s*no cover|eslint-disable|"
    r"@ts-(?:ignore|expect-error|nocheck)|\bNOLINT|#\s*pragma\s+warning\s*\(\s*disable|"
    r"#\s*pragma\s+(?:GCC|clang)\s+diagnostic\s+ignored|@SuppressWarnings|#!?\[allow\(|//\s*nolint|-Wno-")
PATH_SURFACES = (
    ("dependency", re.compile(r"(^|/)(package\.json|requirements[^/]*\.txt|pyproject\.toml|setup\.py|setup\.cfg|"
                              r"Pipfile|go\.mod|Cargo\.toml|Gemfile|pom\.xml|build\.gradle(\.kts)?|vcpkg\.json|"
                              r"conanfile\.(txt|py))$")),
    ("build", re.compile(r"(^|/)(CMakeLists\.txt|[^/]+\.cmake|CMakePresets\.json|Makefile|meson\.build|"
                         r"BUILD(\.bazel)?|WORKSPACE|Dockerfile|\.github/workflows/[^/]+)$")),
    ("data migration", re.compile(r"(^|/)(migrations?|migrate)/")),
    ("security", re.compile(r"(^|/)[^/]*(auth(?!or(?!i[sz]|it))|crypt|secret|password|credential|permission|sandbox|guard)"
                            r"[^/]*$",
                            re.I)),
    ("public API", re.compile(r"(^|/)(include|api|public)/")),
)
CODE = re.compile(r"\.(py|c|cc|cpp|cxx|h|hh|hpp|js|jsx|mjs|ts|tsx|go|rs|java|kt|cs|rb|swift|qml|sh)$")
DOCS = re.compile(r"\.(md|markdown|org|rst|adoc)$|(^|/)(README|LICENSE|CHANGELOG|NOTICE|AUTHORS|CONTRIBUTING|COPYING)"
                  r"[^/]*\.txt$|(^|/)docs?/.*\.(txt|puml|svg|png|jpe?g|gif|webp)$", re.I)
TEST_DATA = re.compile(r"(^|/)(tests?|testdata|test_data|fixtures?|__snapshots__|golden)/", re.I)
DIRECTIVE = re.compile(r"#\s*(type:|noqa|pragma|pylint:|fmt:|isort:|mypy:|pyright:|ruff:|nosec)", re.I)
HEADER = re.compile(r"^#!|^[ \t\f]*#.*?coding[:=]")  # a shebang or an encoding line: comments that run
LINE_SURFACES = (
    ("threading", re.compile(r"std::thread|\bpthread_|\bthreading\.|\bThread\(|\bstd::mutex|\bMutex\b|"
                             r"std::atomic|\basyncio\.|\bgo func\b|\bsynchronized\b|\bQThread\b|ThreadPool")),
    ("security", re.compile(r"\beval\(|\bexec\(|\bsubprocess\.|\bos\.system\(|shell\s*=\s*True|pickle\.loads|"
                            r"yaml\.load\(|innerHTML|dangerouslySetInnerHTML|\bstrcpy\(|\bsprintf\(")),
    ("irreversible", re.compile(r"\brm -rf\b|shutil\.rmtree|DROP TABLE|TRUNCATE TABLE|\bgit push\b|--force\b")),
)


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")


def parse_diff(text: str) -> dict:
    """{path: {"added": [lines], "removed": [lines], "numbers": [new line number of each added
    line]}} from a unified diff. The --- and +++ lines name the file only in its header,
    before its first @@, since a hunk line can start with them too (a removed "-- comment");
    a deleted file keeps its old path."""
    files, current, old, header, number = {}, None, None, False, 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current, old, header = None, None, True
        elif header and line.startswith("--- "):
            name = line[4:].strip()
            old = None if name == "/dev/null" else name[2:] if name.startswith("a/") else name
        elif header and line.startswith("+++ "):
            name = line[4:].strip()
            current = old if name == "/dev/null" else name[2:] if name.startswith("b/") else name
            if current is not None:
                files.setdefault(current, {"added": [], "removed": [], "numbers": []})
        elif line.startswith("@@"):
            header = False
            found = HUNK.match(line)
            number = int(found.group(1)) if found else 0
        elif header or current is None:
            continue
        elif line.startswith("+"):
            files[current]["added"].append(line[1:])
            files[current]["numbers"].append(number)
            number += 1
        elif line.startswith("-"):
            files[current]["removed"].append(line[1:])
        elif line == "" or line.startswith(" "):  # a blank context line git prints empty
            number += 1
    return files


def python_spans(text: str) -> tuple[dict, dict] | None:
    """({line: [(start, end)] of comments}, {line: [(start, end)] of strings}) for Python
    source, columns as in the line, or None when it does not tokenize. A string over several
    lines covers each of them."""
    kinds = {tokenize.STRING} | {getattr(tokenize, name) for name in ("FSTRING_START", "FSTRING_MIDDLE",
                                                                       "FSTRING_END") if hasattr(tokenize, name)}
    comments, strings = {}, {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            (row, col), (end_row, end_col) = token.start, token.end
            if token.type == tokenize.COMMENT:
                comments.setdefault(row, []).append((col, end_col))
            elif token.type in kinds:
                for line in range(row, end_row + 1):
                    strings.setdefault(line, []).append((col if line == row else 0,
                                                         end_col if line == end_row else 10 ** 9))
    except (tokenize.TokenError, SyntaxError):
        return None
    return comments, strings


def within(spans: list, column: int) -> bool:
    return any(start <= column < end for start, end in spans)


def test_names(lines: list) -> list:
    names = []
    for line in lines:
        for pattern in TEST_DEFINITIONS:
            match = pattern.match(line)
            if match:
                names.append(re.sub(r"\s+", "", match.group(1)))
                break
    return names


def python_tokens(text: str) -> list | None:
    """Python source as (type, text) tokens without comments and blank lines, or None when it
    does not tokenize. A NEWLINE token counts by its type: a comment added after the last
    line moves the file's final newline without changing code."""
    try:
        return [(token.type, "" if token.type == tokenize.NEWLINE else token.string)
                for token in tokenize.generate_tokens(io.StringIO(text).readline)
                if token.type not in (tokenize.COMMENT, tokenize.NL)]
    except (tokenize.TokenError, SyntaxError):
        return None


def directives(text: str) -> list | None:
    """The comments a linter, type checker or formatter reads (# noqa, # type: ignore and the
    like), in order, or None when the source does not tokenize."""
    try:
        return [token.string for token in tokenize.generate_tokens(io.StringIO(text).readline)
                if token.type == tokenize.COMMENT and DIRECTIVE.search(token.string)]
    except (tokenize.TokenError, SyntaxError):
        return None


def code_change(paths: list, commit: str, cwd) -> str | None:
    """The first changed path that is code, or None when every path is a documentation file or
    a Python file whose tokens other than comments, its shebang, its encoding line and its
    tool directives (# noqa, # type: ignore and the like) are unchanged. A build or
    dependency file, a file under a test data folder, a code file of another language, an
    untracked code file and any other file count as code: the conservative reading, since
    only Python's comments are told apart from code here. Documentation is decided by
    extension (a .txt only when named like README or under docs/), and an image or diagram
    only under docs/."""
    root, ok = planfile.git(["rev-parse", "--show-toplevel"], cwd)
    header = lambda text: [line for line in text.splitlines()[:2] if HEADER.match(line)]
    if not ok:
        return paths[0] if paths else None
    for path in sorted(paths):
        if any(pattern.search(path) for label, pattern in PATH_SURFACES if label in ("build", "dependency")):
            return path
        if path.endswith(".py"):
            old, found = planfile.git(["show", f"{commit}:{path}"], cwd)
            current = Path(root) / path
            if not found or not current.is_file():
                return path
            new = current.read_text(encoding="utf-8", errors="replace").rstrip("\n")
            before, after = python_tokens(old), python_tokens(new)
            if before is None or before != after or header(old) != header(new) or \
                    directives(old) != directives(new):
                return path
        elif CODE.search(path) or TEST_DATA.search(path) or not DOCS.search(path):
            return path
    return None


def untracked_files(cwd) -> tuple[list, bool]:
    """(paths relative to the repository root, ok): every untracked file that is not
    ignored, one by one also inside an untracked folder, with every .private folder left
    out, also where the project does not ignore it."""
    listed, ok = planfile.git(["ls-files", "--others", "--exclude-standard", "--full-name", "-z", "--", ":/",
                               ":(top,exclude,glob)**/.private/**"], cwd, timeout=60)
    return [path for path in listed.split("\0") if path], ok


def read_untracked(root: Path, paths: list) -> tuple[dict, list]:
    """({path: change} with every line of each text file as an added line numbered from 1,
    [binary paths]). A file whose first 8,000 bytes hold a NUL byte is binary, and so is one
    that cannot be read; a symbolic link holds its target, as git diff shows it."""
    files, binary = {}, []
    for path in paths:
        current = root / path
        try:
            data = os.readlink(current).encode() if current.is_symlink() else current.read_bytes()
        except OSError:
            binary.append(path)
            continue
        if b"\0" in data[:8000]:
            binary.append(path)
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        files[path] = {"added": lines, "removed": [], "numbers": list(range(1, len(lines) + 1))}
    return files, binary


def listed(paths: list) -> str:
    return ", ".join(paths[:10]) + (f" and {len(paths) - 10} more" if len(paths) > 10 else "")


def report(files: dict, lane: str, limit: int, spans: dict | None = None) -> tuple[list, list, int]:
    """(problems, surfaces, changed lines). spans maps a Python path to python_spans() of its
    working-tree text: there a suppression written as a comment (# noqa, # type: ignore and
    the like) counts only inside a comment, another form (-Wno- in a build file's string)
    anywhere, and a skip only outside strings and comments. Every match on a line is tested."""
    spans = spans or {}
    problems, surfaces = [], []
    size = 0
    for path, change in sorted(files.items()):
        size += len(change["added"]) + len(change["removed"])
        removed, added = test_names(change["removed"]), test_names(change["added"])
        for name in removed:
            if name in added:
                added.remove(name)
            else:
                problems.append(f"removed test: {path}: {name}")
        comments, strings = spans.get(path) or ({}, {})
        for line, number in zip(change["added"], change.get("numbers") or [0] * len(change["added"])):
            skips, suppressions = list(SKIPS.finditer(line)), list(SUPPRESSIONS.finditer(line))
            if path in spans:
                quoted = strings.get(number, []) + comments.get(number, [])
                skip = any(not within(quoted, hit.start()) for hit in skips)
                suppression = any(within(comments.get(number, []), hit.start()) or not hit.group(0).startswith("#")
                                  for hit in suppressions)
            else:
                skip, suppression = bool(skips), bool(suppressions)
            if skip:
                problems.append(f"added skip: {path}: {line.strip()[:100]}")
            if suppression:
                problems.append(f"added suppression: {path}: {line.strip()[:100]}")
        for label, pattern in PATH_SURFACES:
            if pattern.search(path):
                surfaces.append(f"{label}: {path}")
        if CODE.search(path):
            for label, pattern in LINE_SURFACES:
                hit = next((line for line in change["added"] if pattern.search(line)), None)
                if hit is not None:
                    surfaces.append(f"{label}: {path}: {hit.strip()[:80]}")
    if lane == "quick":
        reasons = ([f"{size} changed lines (quick lane: about {limit})"] if size > limit else []) + \
                  ([f"{len(surfaces)} risk surface(s)"] if surfaces else [])
        if reasons:
            problems.append("raise to the full lane: " + "; ".join(reasons))
    return problems, surfaces, size


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--lane", choices=("quick", "full", "direct"))
    parser.add_argument("--quick-limit", type=int, default=100)
    args = parser.parse_args(argv)
    state, _, plan = planfile.locate(args.cwd, timeout=60)  # a large checkout lists untracked files slowly
    if not state:
        print("floor_check: not a git repository; nothing was checked")
        return 2
    if state.get("unknown"):
        print("floor_check: git status failed; nothing was checked")
        return 2
    header = planfile.read(plan)["header"] if plan else {}
    base = args.base or header.get("Base")
    if not base:
        for target in ("main", "master", "origin/main"):
            base, ok = planfile.git(["merge-base", "HEAD", target], args.cwd)
            if ok and base:
                break
            base = None
    if not base:
        print("floor_check: no base (give --base, or a Base in the plan); nothing was checked")
        return 2
    commit = planfile.commit_of(base, args.cwd)
    if commit is None:
        print(f"floor_check: base {base!r} is not a commit; nothing was checked")
        return 2
    diff, ok = planfile.git(["-c", "diff.suppressBlankEmpty=false", "diff", "--no-color", "--no-ext-diff", "-M",
                             "--src-prefix=a/", "--dst-prefix=b/", commit, "--"], args.cwd, timeout=60)
    if not ok:
        print(f"floor_check: git diff {base} failed; nothing was checked")
        return 2
    names, ok = planfile.git(["diff", "--name-only", "--no-renames", commit, "--"], args.cwd, timeout=60)
    if not ok:
        print(f"floor_check: git diff {base} failed; nothing was checked")
        return 2
    untracked, ok = untracked_files(args.cwd)
    root, root_ok = planfile.git(["rev-parse", "--show-toplevel"], args.cwd)
    if not ok or not root_ok:
        print("floor_check: git ls-files failed; nothing was checked")
        return 2
    lane = (args.lane or header.get("Lane", "")).lower()
    files = parse_diff(diff)
    added, binary = read_untracked(Path(root), untracked)
    files.update(added)
    spans = {}
    for path, change in files.items():
        current = Path(root) / path if root else None
        if path.endswith(".py") and current is not None and current.is_file() and \
                any(SKIPS.search(line) or SUPPRESSIONS.search(line) for line in change["added"]):
            found = python_spans(current.read_text(encoding="utf-8", errors="replace"))
            if found is not None:
                spans[path] = found
    problems, surfaces, size = report(files, lane, args.quick_limit, spans)
    print(f"base {base}, {size} changed lines" + (f", lane {lane}" if lane else ""))
    changed = code_change([name for name in names.splitlines() if name] + untracked, commit, args.cwd)
    print("docs or comments only: " + ("yes" if changed is None else f"no: {changed}"))
    if added:
        print(f"untracked, counted as added: {listed(sorted(added))}")
    if binary:
        print(f"untracked, binary, not scanned: {listed(sorted(binary))}")
    for line in surfaces:
        print(f"risk surface: {line}")
    for line in problems:
        print(line)
    if not problems:
        print("nothing removed, skipped or suppressed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
