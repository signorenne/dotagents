#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Print where a change stands, in one call: branch, HEAD, base, dirty files, the plan's
state header, the step in progress, the open rulings and the last log lines.

  python3 plan_state.py [--cwd DIR]
  python3 plan_state.py --excerpt [--max-chars 4000]   the bounded form the session hook prints

On a branch that is not a task branch (<type>/<slug>) or has no plan file, it lists the
open plans of the working-notes folder instead. Exit 0, or 2 outside a git repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import planfile  # beside this script

MAP_NOTE = ("Plan file excerpt: a map written by earlier sessions. Check it against git and "
            "the code before relying on it.")


def step_lines(steps: list, state: dict, commits: set) -> list:
    lines = []
    counts = {}
    for row in steps:
        status = row.get("status", "").lower() or "pending"
        counts[status] = counts.get(status, 0) + 1
    if counts:
        lines.append("Steps: " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
    for row in steps:
        if row.get("status", "").lower() != "in progress":
            continue
        name = row.get("nr") or row.get("step", "?")
        lines.append(f"In progress: {name} {row.get('step', '')} (files: {row.get('files', '-')})")
        commit = row.get("commit", "").strip()
        if not commit or commit == "-" or not any(commit.startswith(c) or c.startswith(commit) for c in commits):
            dirty = ", ".join(line[3:] for line in state.get("dirty", [])) or "none"
            lines.append(f"  no commit for it yet; modified files now: {dirty}. Show their diff and "
                         "ask whether to finish or discard the step; discard nothing without an answer.")
    return lines


def describe(cwd, excerpt: bool) -> tuple[int, list]:
    state, private, plan = planfile.locate(cwd)
    if not state:
        return 2, ["Not a git repository."]
    lines = []
    if not excerpt:
        dirty = state["dirty"]
        lines.append(f"Branch: {state['branch'] or '(detached)'}  HEAD: {state['head']}")
        if state.get("unknown"):
            lines.append("Modified tracked files: unknown (git status failed)")
        else:
            lines.append(f"Modified tracked files: {len(dirty)}" + (": " + ", ".join(d[3:] for d in dirty[:10])
                                                                    if dirty else ""))
        if state["untracked"]:
            lines.append(f"Untracked: {len(state['untracked'])}: " + ", ".join(state["untracked"][:10]))
    if plan is None:
        if excerpt:
            return 0, []
        open_plans = []
        for path in planfile.all_plans(private) if private else []:
            header = planfile.read(path)["header"]
            if header.get("Status", "").lower() in planfile.OPEN_STATUSES:
                open_plans.append(f"  {path} ({header.get('Status')}, branch {header.get('Branch', '-')})")
        lines.append("No plan file for this branch." + (" Open plans:" if open_plans else ""))
        return 0, lines + open_plans
    data = planfile.read(plan)
    header = data["header"]
    base = header.get("Base", "")
    commits = set()
    if base:
        commit = planfile.commit_of(base, cwd)
        listed, ok = planfile.git(["log", "--format=%h", f"{commit}..HEAD", "--"], cwd) if commit else ("", False)
        commits = set(listed.split()) if ok else set()
        if not excerpt:
            lines.append(f"Base: {base} ({len(commits)} commits since)" if ok
                         else f"Base: unknown ({base!r} is not a commit)")
    lines.append(f"Plan: {plan}")
    lines.append("  " + ", ".join(f"{key} {header[key]}" for key in planfile.HEADER_KEYS[:-1] if key in header))
    if header.get("Next"):
        lines.append(f"Next: {header['Next']}")
    lines += step_lines(data["steps"], state, commits)
    pending = [row for row in data["rulings"] if row.get("review", "").lower() in ("", "pending")]
    if pending:
        lines.append(f"Open rulings: {len(pending)}: " + "; ".join(
            f"{row.get('nr', '?')} {row.get('ruling', '')[:80]}" for row in pending[:5]))
    log = planfile.log_lines(plan)
    if log:
        lines.append("Last log lines:")
        lines += ["  " + " ".join(row[key] for key in ("step", "kind", "commit", "result", "tests"))
                  for row in log[-3:]]
    if excerpt:
        lines = [MAP_NOTE, f"Branch: {state['branch']}  HEAD: {state['head']}"] + lines
    return 0, lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--excerpt", action="store_true")
    parser.add_argument("--max-chars", type=int, default=4000)
    args = parser.parse_args(argv)
    code, lines = describe(args.cwd, args.excerpt)
    text = "\n".join(lines)
    if args.excerpt and len(text) > args.max_chars:
        text = text[:args.max_chars - 20].rstrip() + "\n... (cut)"
    if text:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
