#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Compare a change with its base and report what must never pass unnoticed: removed
tests, added skips, added suppressions, the size of the change and the risk surfaces it
touches. A quick-lane change that outgrew its lane is reported as raised to the full lane.

  python3 floor_check.py [--base REF] [--cwd DIR] [--lane quick|full] [--quick-limit 100]

The base is --base, else the plan's Base, else the merge base with main (or master). The
diff is the base against the working tree, so uncommitted work counts; untracked files
are listed apart. Test, skip and suppression patterns cover Python, C and C++ (GoogleTest,
Catch2, Qt Test), JavaScript and TypeScript, Go, Java, Kotlin and Rust; risk surfaces are
path and line patterns, hints for the agent's judgment. The lane is --lane, else the
plan's Lane.

Exit 0: nothing to report. 1: something to report (each item printed). 2: the check
could not run (no repository, unknown base, git failed); it never reads as clean.
"""

from __future__ import annotations

import argparse
import re
import sys
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
    ("security", re.compile(r"(^|/)[^/]*(auth|crypt|secret|password|credential|permission|sandbox|guard)[^/]*$",
                            re.I)),
    ("public API", re.compile(r"(^|/)(include|api|public)/")),
)
CODE = re.compile(r"\.(py|c|cc|cpp|cxx|h|hh|hpp|js|jsx|mjs|ts|tsx|go|rs|java|kt|cs|rb|swift|qml|sh)$")
LINE_SURFACES = (
    ("threading", re.compile(r"std::thread|\bpthread_|\bthreading\.|\bThread\(|\bstd::mutex|\bMutex\b|"
                             r"std::atomic|\basyncio\.|\bgo func\b|\bsynchronized\b|\bQThread\b|ThreadPool")),
    ("security", re.compile(r"\beval\(|\bexec\(|\bsubprocess\.|\bos\.system\(|shell\s*=\s*True|pickle\.loads|"
                            r"yaml\.load\(|innerHTML|dangerouslySetInnerHTML|\bstrcpy\(|\bsprintf\(")),
    ("irreversible", re.compile(r"\brm -rf\b|shutil\.rmtree|DROP TABLE|TRUNCATE TABLE|\bgit push\b|--force\b")),
)


def parse_diff(text: str) -> dict:
    """{path: {"added": [lines], "removed": [lines]}} from a unified diff."""
    files, current = {}, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ "):
            name = line[4:].strip()
            current = None if name == "/dev/null" else name[2:] if name.startswith("b/") else name
            if current is not None:
                files.setdefault(current, {"added": [], "removed": []})
        elif line.startswith("--- "):
            name = line[4:].strip()
            if name != "/dev/null":
                old = name[2:] if name.startswith("a/") else name
                files.setdefault(old, {"added": [], "removed": []})
                current = old
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            files[current]["added"].append(line[1:])
        elif current is not None and line.startswith("-") and not line.startswith("---"):
            files[current]["removed"].append(line[1:])
    return files


def test_names(lines: list) -> list:
    names = []
    for line in lines:
        for pattern in TEST_DEFINITIONS:
            match = pattern.match(line)
            if match:
                names.append(re.sub(r"\s+", "", match.group(1)))
                break
    return names


def report(files: dict, lane: str, limit: int) -> tuple[list, list, int]:
    """(problems, surfaces, changed lines)."""
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
        for line in change["added"]:
            if SKIPS.search(line):
                problems.append(f"added skip: {path}: {line.strip()[:100]}")
            if SUPPRESSIONS.search(line):
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
    state, _, plan = planfile.locate(args.cwd)
    if not state:
        print("floor_check: not a git repository; nothing was checked")
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
    diff, ok = planfile.git(["diff", "--no-color", "--no-ext-diff", "-M", base], args.cwd, timeout=60)
    if not ok:
        print(f"floor_check: git diff {base} failed; nothing was checked")
        return 2
    lane = (args.lane or header.get("Lane", "")).lower()
    problems, surfaces, size = report(parse_diff(diff), lane, args.quick_limit)
    print(f"base {base}, {size} changed lines" + (f", lane {lane}" if lane else ""))
    if state["untracked"]:
        print(f"untracked, not counted: {', '.join(state['untracked'][:10])}")
    for line in surfaces:
        print(f"risk surface: {line}")
    for line in problems:
        print(line)
    if not problems:
        print("nothing removed, skipped or suppressed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
