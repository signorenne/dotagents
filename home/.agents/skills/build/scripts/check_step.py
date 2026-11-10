#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Run one step's check, keep its whole output in a file, print the tail, and append the
result to the plan's log, so no model turn is spent writing it.

  python3 check_step.py --step S3 -- python3 -m unittest tests.test_x
  python3 check_step.py --step S3 --expect-fail -- python3 -m unittest tests.test_x.T.test_new
  python3 check_step.py --step base --baseline -- <the narrow check>
  python3 check_step.py --step final --gate -- <a documented gate>

A single command argument that holds spaces runs through the shell. --expect-fail
records a failing-first run: the call succeeds when the command fails and fails when it
passes, because a pass does not show that the test can fail. A run with modified tracked
files is logged as "uncommitted(<n>)", never as the commit's. Without a plan file for the
branch the check still runs and the result is not logged. Exit: the command's code; with
--expect-fail 0 when it failed and 1 when it passed; 2 when the command could not start.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import planfile  # beside this script

COUNTS = (
    re.compile(r"^Ran (\d+) tests? in ", re.M),                       # unittest
    re.compile(r"\b(\d+) passed\b"),                                  # pytest
    re.compile(r"tests? failed out of (\d+)"),                        # ctest
    re.compile(r"^Tests run: (\d+)", re.M),                           # JUnit
    re.compile(r"^Tests:\s+.*?(\d+) total", re.M),                    # jest
)


def test_count(output: str) -> str:
    for pattern in COUNTS:
        found = pattern.findall(output)
        if found:
            return str(found[-1])
    return "-"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", required=True, help="the plan's step number, or base or final")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--expect-fail", action="store_true", help="a failing-first run")
    kind.add_argument("--baseline", action="store_true", help="the baseline on the base commit")
    kind.add_argument("--gate", action="store_true", help="a full gate")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--tail", type=int, default=30)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command after --")
    shell = len(command) == 1 and " " in command[0]
    shown = command[0] if shell else " ".join(command)

    state, private, plan = planfile.locate(args.cwd)
    # The whole output stays in the working notes: beside the plan, else in .private/runs.
    folder = plan.with_suffix(".runs") if plan else private / "runs" if private else None
    started = time.strftime("%Y%m%d-%H%M%S")
    try:
        result = subprocess.run(command[0] if shell else command, shell=shell, cwd=args.cwd,
                                capture_output=True, text=True, errors="replace", check=False)
    except OSError as error:
        print(f"check_step: could not start {shown}: {error}", file=sys.stderr)
        return 2
    output = result.stdout + result.stderr
    saved = None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        saved = folder / f"{started}-{args.step}.txt"
        saved.write_text(f"$ {shown}\n{output}\nexit {result.returncode}\n", encoding="utf-8")
    lines = output.splitlines()
    print("\n".join(lines[-args.tail:]))
    passed = result.returncode == 0
    count = test_count(output)
    label = "fail-first" if args.expect_fail else "baseline" if args.baseline else "gate" if args.gate else "check"
    dirty = state.get("dirty", []) if state else []
    commit = f"uncommitted({len(dirty)})" if dirty else (state.get("head") or "-") if state else "-"
    print(f"exit {result.returncode}, {'pass' if passed else 'fail'}, tests {count}, {commit}"
          + (f", output {saved}" if saved else ""))
    if plan is not None:
        planfile.append_log(plan, step=args.step, kind=label, commit=commit,
                            result="pass" if passed else "fail", tests=count, command=shown)
    else:
        print("not logged: no plan file for this branch")
    if args.expect_fail:
        if passed:
            print("expected a failure, but the command passed: this run does not show the test can fail")
            return 1
        return 0
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
