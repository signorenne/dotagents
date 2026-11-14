#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""A/B benchmark of the nexenne method on SWE-bench Verified tasks: the same tasks run by
Claude Code with the method installed (arm "method") and without it (arm "plain").

Usage:
  python3 tools/benchmark.py select --dataset FILE --count N --seed S --out TASKS

select  reads the dataset (JSON lines exported from SWE-bench/SWE-bench_Verified, test
        split), keeps the two longest difficulty buckets ("1-4 hours", ">4 hours"), and
        chooses N tasks with the seed, one per repository before a second from any. TASKS
        holds, per task, the fields the agent may see ("agent": instance_id, repo,
        base_commit, problem_statement, image) apart from every other field ("grading":
        the hidden tests, the evaluation script, the gold patch...), which only grading
        reads.

Standard library only. Exit: 0 done, 1 a step failed (reported), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

LONG_BUCKETS = ("1-4 hours", ">4 hours")
AGENT_FIELDS = ("instance_id", "repo", "base_commit", "problem_statement", "image")


class UsageError(Exception):
    pass


def read_lines(path: Path) -> list:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise UsageError(f"cannot read {path}: {error.strerror}")
    rows = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                raise UsageError(f"{path}:{number}: not a JSON line")
    return rows


def choose(rows: list, count: int, seed: int) -> list:
    """count rows of the longest buckets, shuffled by the seed, taken in rounds of one per
    repository."""
    pool = sorted((row for row in rows if row.get("difficulty") in LONG_BUCKETS), key=lambda row: row["instance_id"])
    if count < 1 or count > len(pool):
        raise UsageError(f"--count must be between 1 and {len(pool)}, the tasks of the buckets "
                         f"{' and '.join(LONG_BUCKETS)}")
    random.Random(seed).shuffle(pool)
    chosen = []
    while len(chosen) < count:
        repositories = set()
        for row in pool:
            if row not in chosen and row["repo"] not in repositories and len(chosen) < count:
                chosen.append(row)
                repositories.add(row["repo"])
        if not repositories:
            break  # the pool is used up
    return chosen


def select(args) -> int:
    rows = read_lines(Path(args.dataset))
    missing = [field for field in AGENT_FIELDS + ("difficulty",) if rows and field not in rows[0]]
    if missing:
        raise UsageError(f"{args.dataset}: no field {', '.join(missing)}")
    tasks = [{"agent": {field: row[field] for field in AGENT_FIELDS},
              "grading": {field: value for field, value in row.items() if field not in AGENT_FIELDS}}
             for row in choose(rows, args.count, args.seed)]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"dataset": str(args.dataset), "seed": args.seed, "tasks": tasks}, indent=1) + "\n",
                   encoding="utf-8")
    for task in tasks:
        print(task["agent"]["instance_id"], task["agent"]["repo"], task["grading"]["difficulty"])
    print(f"tasks: {out}")
    return 0


def parser() -> argparse.ArgumentParser:
    main_parser = argparse.ArgumentParser(description="A/B benchmark of the nexenne method.")
    commands = main_parser.add_subparsers(dest="command", required=True)
    chooser = commands.add_parser("select", help="choose the tasks")
    chooser.add_argument("--dataset", required=True)
    chooser.add_argument("--count", type=int, required=True)
    chooser.add_argument("--seed", type=int, required=True)
    chooser.add_argument("--out", required=True)
    chooser.set_defaults(handler=select)
    return main_parser


def main() -> int:
    args = parser().parse_args()  # exits 2 on a usage error
    try:
        return args.handler(args)
    except UsageError as error:
        print(f"benchmark.py {args.command}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
