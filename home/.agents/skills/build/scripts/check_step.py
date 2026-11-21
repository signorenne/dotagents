#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Run one step's check, keep its whole output in a file, print the tail, and append the
result to the plan's log, so no model turn is spent writing it.

  python3 check_step.py --step S3 -- python3 -m unittest tests.test_x
  python3 check_step.py --step S3 --expect-fail -- python3 -m unittest tests.test_x.T.test_new
  python3 check_step.py --step base --baseline -- <the narrow check>
  python3 check_step.py --step final --gate -- <a documented gate>

A single command argument that holds spaces runs through the shell. The command goes
first to the guard hook beside the skills (../../hooks/guard_bash.py), and one it would
block is not run. --expect-fail records a failing-first run: the call succeeds when the
command fails and fails when it passes, because a pass does not show that the test can
fail. A run with modified or untracked files is logged as "uncommitted(<n>)", never as
the commit's, and as "uncommitted(?)" when git status failed. --tail 0 prints the whole
output (for gate-runner, which searches it).
The logged test count counts failed tests too: unittest's "Ran N tests" summed over runs,
else the last jest "Tests: ... N total" or ctest "failed out of N", else JUnit's "Tests
run: N" after each Maven "Results:" header summed (the last "Tests run: N" without one),
else cargo's passed and failed summed over its "test result:" lines, else pytest's last
summary line (passed, failed and errors), else the last "N passed"; "-" when none.
Without a plan file for the branch the check still runs and the result is not logged.
Exit: the command's code; with --expect-fail 0 when it failed and 1 when it passed; 2
when the command could not start (also exit 126 or 127 from the shell) or the guard
blocked it, and then nothing is logged.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import planfile  # beside this script

UNITTEST = re.compile(r"^Ran (\d+) tests? in ", re.M)                  # summed over runs
LAST_COUNTS = (
    re.compile(r"^Tests:\s+.*?(\d+) total", re.M),                    # jest
    re.compile(r"tests? failed out of (\d+)"),                        # ctest
)
JUNIT = re.compile(r"^(?:\[[A-Z]+\] )?Tests run: (\d+)", re.M)       # Maven prints [INFO] or [ERROR]
RESULTS = re.compile(r"^(?:\[[A-Z]+\] )?Results:\s*$", re.M)        # Maven: one section per module
CARGO = re.compile(r"^test result: .*?(\d+) passed; (\d+) failed", re.M)  # summed over test binaries
PYTEST_LINE = re.compile(r"\bin \d+(?:\.\d+)?s\b")                  # the summary line ends with the time
PYTEST_COUNT = re.compile(r"\b(\d+) (?:passed|failed|errors?)\b")
PASSED = re.compile(r"\b(\d+) passed\b")


GUARD = Path(__file__).resolve().parents[3] / "hooks" / "guard_bash.py"


def guard_refusal(command: str) -> str | None:
    """The guard's reason when it blocks command, or None (also when the guard is not
    installed beside the skills)."""
    if not GUARD.is_file():
        return None
    try:
        result = subprocess.run([sys.executable, str(GUARD), "--tool", "claude"], capture_output=True, text=True,
                                input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
                                timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stderr.strip() or "blocked") if result.returncode == 2 else None


def test_count(output: str) -> str:
    """The number of tests the output reports, failed ones included, or "-"; the first rule
    with a match wins."""
    found = UNITTEST.findall(output)
    if found:
        return str(sum(int(n) for n in found))
    for pattern in LAST_COUNTS:
        found = pattern.findall(output)
        if found:
            return found[-1]
    found = JUNIT.findall(output)
    if found:  # the total after each module's Results header, else the last line
        totals = [int(match.group(1)) for part in RESULTS.split(output)[1:] if (match := JUNIT.search(part))]
        return str(sum(totals)) if totals else found[-1]
    found = CARGO.findall(output)
    if found:
        return str(sum(int(passed) + int(failed) for passed, failed in found))
    for line in reversed(output.splitlines()):
        counts = PYTEST_COUNT.findall(line) if PYTEST_LINE.search(line) else []
        if counts:
            return str(sum(int(n) for n in counts))
    found = PASSED.findall(output)
    return found[-1] if found else "-"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", required=True, help="the plan's step number, or base or final")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--expect-fail", action="store_true", help="a failing-first run")
    kind.add_argument("--baseline", action="store_true", help="the baseline on the base commit")
    kind.add_argument("--gate", action="store_true", help="a full gate")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--tail", type=int, default=30, help="lines of output to print; 0 prints all")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the command after --")
    shell = len(command) == 1 and " " in command[0]
    shown = command[0] if shell else shlex.join(command)
    refusal = guard_refusal(shown)
    if refusal:
        print(f"check_step: blocked by the guard, not run: {refusal}")
        return 2

    state, private, plan = planfile.locate(args.cwd, timeout=60)  # a large checkout lists untracked files slowly
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
    if shell and result.returncode in (126, 127):
        print(output.strip())
        print(f"check_step: could not start {shown} (exit {result.returncode}); not logged")
        return 2
    saved = None
    if folder is not None:
        folder.mkdir(parents=True, exist_ok=True)
        saved = folder / f"{started}-{args.step}.txt"
        saved.write_text(f"$ {shown}\n{output}\nexit {result.returncode}\n", encoding="utf-8")
    lines = output.splitlines()
    print("\n".join(lines[-args.tail:] if args.tail > 0 else lines))
    passed = result.returncode == 0
    count = test_count(output)
    label = "fail-first" if args.expect_fail else "baseline" if args.baseline else "gate" if args.gate else "check"
    untracked = state.get("untracked", []) if state else []  # working notes left out by planfile
    dirty = (state.get("dirty", []) + untracked) if state else []
    commit = f"uncommitted({len(dirty)})" if dirty else (state.get("head") or "-") if state else "-"
    if state and state.get("unknown"):  # git status failed: the tree was not read
        commit = "uncommitted(?)"
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
