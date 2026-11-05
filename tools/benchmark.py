#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""A/B benchmark of the nexenne method on SWE-bench Verified tasks: the same tasks run by
Claude Code with the method installed (arm "method") and without it (arm "plain").

Usage:
  python3 tools/benchmark.py select --dataset FILE --count N --seed S --out TASKS
  python3 tools/benchmark.py run --tasks TASKS --runs R --arms method,plain --model MODEL
                                 --maintainer-model MODEL --cap-usd TOTAL --out RUNDIR
                                 [--dry-run] [--method-home DIR] [--credentials FILE]
                                 [--hooks-python DIR]
  python3 tools/benchmark.py grade --rundir RUNDIR --swebench-python PY [--gold]
                                   [--tasks TASKS]
  python3 tools/benchmark.py summary --rundir RUNDIR [--org FILE]

select  reads the dataset (JSON lines exported from SWE-bench/SWE-bench_Verified, test
        split), keeps the two longest difficulty buckets ("1-4 hours", ">4 hours"), and
        chooses N tasks with the seed, one per repository before a second from any. TASKS
        holds, per task, the fields the agent may see ("agent": instance_id, repo,
        base_commit, problem_statement, image) apart from every other field ("grading":
        the hidden tests, the evaluation script, the gold patch...), which only grading
        reads.

run     runs each task R times per arm, in an interleaved order, one run at a time. A run
        starts the task's image with podman (fully qualified, SELinux labels off for the
        container), creates the user "agent" owning /testbed, gives it a git identity,
        binds the host's claude read-only at /usr/local/bin/claude, and checks that every
        commit after base_commit keeps base_commit's tree (SWE-bench's images add an empty
        setup commit). The method arm also gets the installed method from --method-home
        (default ~): .claude/CLAUDE.md, skills, agents, rules and .agents with symlinks
        resolved, and .claude/settings.json reduced to the keys install.py writes, its hook
        commands run by the standalone Python in --hooks-python (bound read-only at
        /opt/dotagents-python), since the image's own python3 may be too old; a probe then
        proves the method is live (the guard, run by the settings' own command, exits 2 on
        a push; the skills and the global rules are in place), and a failed probe makes the
        run an error. The plain arm runs claude --safe-mode. Every agent call is claude -p
        in /testbed with the same model, effort high, JSON output, bypassPermissions (the
        container is the boundary), WebFetch and WebSearch off, and --max-budget-usd set to
        the run's remaining share; the first prompt is the problem statement and the same
        instructions in both arms. Each call gets only the Claude access token from
        --credentials (default ~/.claude/.credentials.json), read fresh and through the
        environment, never the refresh token or another service's token, and the token is
        scrubbed from every result and from the prediction before either is kept or shown
        to the maintainer; a token that has expired (the host's claude refreshes it) stops
        the run as "login" before the call. When the agent stops, a simulated maintainer on
        the host (claude -p --safe-mode, no tools, --maintainer-model, an empty folder)
        replies DONE or answers, and an answer resumes the agent's session; at most 6
        replies. The prediction is the change against base_commit in /testbed (committed,
        staged or not), else in the newest other worktree or branch the agent left it on,
        never counting the method's notes (.private/), and without the files the task's
        hidden test patch touches. RUNDIR/runs/<run>/ holds record.json (every call's JSON
        result, the replies, the stop reason, the probe, the costs) and prediction.diff.
        Cost: a run's share is the cap divided by the number of runs; a run's spend is its
        last agent result's total_cost_usd (which holds the earlier calls) plus the
        maintainer's calls; no run starts when the spend so far plus one share would pass
        the cap, and the runs not made go to RUNDIR/not-made.json. A usage limit or a
        failed login stops everything (exit 1), and so does Ctrl-C (exit 130); the stopped
        attempt's spend still counts against the cap. Run again on the same RUNDIR to go
        on: the stopped run starts again from the beginning, and finished runs, errors
        included, are not run again (delete a run's folder to run it again). --dry-run
        prints the plan and the prerequisites and starts nothing.

grade   runs the SWE-bench harness (python -m swebench.harness.run_evaluation, swebench 5)
        with PY, a Python 3.10 or later environment holding the swebench package, from
        RUNDIR/grading/, so its logs stay there, through the Docker API in DOCKER_HOST
        (default podman's socket under XDG_RUNTIME_DIR); when no docker program is on PATH,
        one that runs podman is put there, since the harness stops its containers with it.
        The harness keys predictions by instance id, so each arm and repeat is graded in a
        call of its own; runs that never reached the agent are not graded.
        RUNDIR/grades.json holds per run whether it is resolved and which PASS_TO_PASS
        tests failed (regressions). The harness writes no report for an empty patch, one
        that does not apply, or one whose tests time out: each counts as graded and
        unresolved. A run it failed on otherwise has no grade, and grade exits 1 naming it
        (grade again to retry). With --gold it grades the reference patches of the tasks
        (RUNDIR's tasks.json, or --tasks) into RUNDIR/gold.json instead.

summary writes per arm the runs, errors, graded runs (empty or unapplied predictions among
        them), runs without a report, the resolved rate over the graded runs, median and
        total cost (agent and maintainer apart), median turns, minutes and replies, runs
        with regressions, runs over their share and the stop reasons, then per task both
        arms side by side: an Org fragment of metrics only, no transcript or command text,
        to --org or stdout. It is labeled "pilot: not conclusive" unless both arms finished
        every run of a plan as large as the full run of DESIGN.org's method-measured rule
        (20 tasks, 3 runs per arm). It also gives the total spend, the interrupted
        attempts' share of it and the runs the cap left unmade.

Standard library only. Exit: 0 done, 1 a step failed (reported), 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LONG_BUCKETS = ("1-4 hours", ">4 hours")
AGENT_FIELDS = ("instance_id", "repo", "base_commit", "problem_statement", "image")
ARMS = ("method", "plain")
FIELD_SHAPES = {"instance_id": re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*"), "base_commit": re.compile(r"[0-9a-f]{7,40}"),
                "image": re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*")}
AGENT_INSTRUCTIONS = ("Resolve this issue in the repository in the current folder. Do not push or open pull "
                      "requests. When you need the maintainer, ask and stop: the maintainer answers your messages.")
MAINTAINER_PROMPT = """\
You are the maintainer of a software repository. An AI coding agent is resolving the issue \
below in your repository, and it has stopped. Its last message follows the issue.

Reply with exactly DONE when the agent reports the work finished or asks you nothing. \
Otherwise answer it as the maintainer would, in a few sentences: approve a plan that fits \
the issue, choose the option the agent recommends unless it contradicts the issue, and never \
write code.

<issue>
{issue}
</issue>

<agent_message>
{message}
</agent_message>
"""
DONE_REPLY = re.compile(r"\W*DONE\W*")
MAX_REPLIES = 6
MIN_BUDGET = 0.01  # under a cent, a call cannot do anything useful
AGENT_TIMEOUT = 4 * 3600
MAINTAINER_TIMEOUT = 600
# Errors after which no further call can succeed until the limit resets or the login works.
INTERRUPTIONS = (("usage limit", re.compile(r"(?i)usage limit|limit reached|hit your limit|rate.?limit")),
                 ("login", re.compile(r"(?i)oauth|authenticat|invalid api key|/login\b|\b401\b")))
LOGIN_HINT = "run claude on this machine to refresh the login, then run again"
LOGIN_MARGIN = 300  # seconds of validity the access token needs before a call
METHOD_SETTINGS = ("$schema", "attribution", "enabledPlugins", "hooks", "permissions", "skillOverrides")
HOOKS_PYTHON = "/opt/dotagents-python"
CONTAINER_CLAUDE = "/usr/local/bin/claude"
TESTBED = "/testbed"
NOT_NOTES = ("--", ".", ":(exclude).private")  # a git pathspec: everything but the method's notes
GIT_IDENTITY = (("user.name", "Agent"), ("user.email", "agent@example.invalid"))
PROBE_PAYLOAD = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
PROBE_SCRIPT = """\
# dotagents probe: the guard blocks a push, and the skills and the global rules are in place
printf '%s' "$1" | sh -c "$2" >/dev/null 2>&1; echo "guard=$?"
echo "skills=$(ls -1 "$HOME/.claude/skills" | wc -l)"
echo "claude_md=$(head -n 1 "$HOME/.claude/CLAUDE.md")"
"""
RULES_IMPORT = "@~/.agents/AGENTS.md"


class UsageError(Exception):
    pass


class Failure(Exception):
    """A step that cannot go on: reported, exit 1."""


class Interrupted(Exception):
    """A usage limit or a failed login: no later call can succeed now. str() is its kind."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(kind)
        self.kind, self.detail = kind, detail


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


def read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UsageError(f"cannot read {what} {path}: {error}")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def main_checkout() -> Path:
    """The main checkout's folder, also from a linked worktree; this one without git."""
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return ROOT
    return Path(result.stdout.strip()).parent if result.returncode == 0 else ROOT


# select

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


# run: the plan and the prerequisites

def load_tasks(path: Path) -> list:
    data = read_json(path, "the tasks")
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list) or not tasks or not all(
            isinstance(task, dict) and set(AGENT_FIELDS) <= set(task.get("agent", {})) and "grading" in task
            for task in tasks):
        raise UsageError(f"{path}: not a tasks file written by select")
    for task in tasks:  # they become file names and git or podman arguments
        for field, pattern in FIELD_SHAPES.items():
            value = task["agent"][field]
            if not (isinstance(value, str) and pattern.fullmatch(value)):
                raise UsageError(f"{path}: {field} {value!r} is not the shape SWE-bench uses")
    return tasks


def parse_arms(text: str) -> list:
    arms = [arm.strip() for arm in text.split(",") if arm.strip()]
    if not arms or len(set(arms)) != len(arms) or not set(arms) <= set(ARMS):
        raise UsageError(f"--arms: a comma-separated list of {' and '.join(ARMS)}, each once")
    return arms


def planned(tasks: list, arms: list, runs: int) -> list:
    """(task, arm, repeat, run id) in the order the runs happen: repeat by repeat, task by
    task, the arms alternating which goes first."""
    order = []
    for repeat in range(1, runs + 1):
        for index, task in enumerate(tasks):
            for arm in (arms if (index + repeat) % 2 == 0 else arms[::-1]):
                order.append((task, arm, repeat, f"{task['agent']['instance_id']}.{arm}.{repeat}"))
    return order


def access_token(path: Path) -> str:
    """The Claude access token of the login file, read fresh since the host's claude
    refreshes it; nothing else of the file leaves the host. Interrupted("login") when there
    is none or it expires within LOGIN_MARGIN."""
    login = None
    for attempt in range(3):  # the host's claude may be rewriting the file
        try:
            login = json.loads(path.read_text(encoding="utf-8"))["claudeAiOauth"]
            break
        except (OSError, ValueError, KeyError, TypeError):
            if attempt < 2:
                time.sleep(attempt + 1)
    token = login.get("accessToken") if isinstance(login, dict) else None
    if not isinstance(token, str) or not token:
        raise Interrupted("login", f"no Claude access token in {path}: {LOGIN_HINT}")
    expires = login.get("expiresAt")
    if isinstance(expires, (int, float)) and expires / 1000 < time.time() + LOGIN_MARGIN:
        raise Interrupted("login", f"the Claude access token in {path} has expired: {LOGIN_HINT}")
    return token


def method_files(home: Path) -> list:
    claude = home / ".claude"
    return [claude / "CLAUDE.md", claude / "settings.json", claude / "skills", claude / "agents", home / ".agents"]


def prerequisites(args, arms: list) -> list:
    """(name, ok, detail) for each external thing the run needs; nothing is started."""
    found = []
    for program, hint in (("podman", "install podman (podman.io)"), ("claude", "install Claude Code")):
        path = shutil.which(program)
        found.append((program, bool(path), os.path.realpath(path) if path else hint))
    try:
        access_token(Path(args.credentials))
        found.append(("credentials", True, args.credentials))
    except Interrupted as error:
        found.append(("credentials", False, error.detail))
    if "method" in arms:
        python = Path(args.hooks_python) / "bin" / "python3"
        found.append(("hooks python", python.is_file(), str(python) if python.is_file() else
                      f"unpack a python-build-standalone 3.12 install_only build into {args.hooks_python}"))
        missing = [str(path) for path in method_files(Path(args.method_home)) if not path.exists()]
        found.append(("method files", not missing, args.method_home if not missing else
                      f"missing {', '.join(missing)}: install the method (python3 install.py)"))
    return found


def stage_method(home: Path, staged: Path) -> dict:
    """Copy the installed method into staged/ (its home in the container) and adapt it."""
    temporary = staged.with_name(staged.name + ".partial")
    shutil.rmtree(temporary, ignore_errors=True)
    claude, target = home / ".claude", temporary / ".claude"
    target.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copy2(claude / "CLAUDE.md", target / "CLAUDE.md")
    for folder in ("skills", "agents", "rules"):
        if (claude / folder).is_dir():
            shutil.copytree(claude / folder, target / folder, symlinks=False, ignore=ignore)
    shutil.copytree(home / ".agents", temporary / ".agents", symlinks=False, ignore=ignore)
    settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    kept = {key: value for key, value in settings.items() if key in METHOD_SETTINGS}
    replaced, guard = 0, None
    for groups in kept.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command")
                if isinstance(command, str) and command.startswith("python3 "):
                    hook["command"] = f"{HOOKS_PYTHON}/bin/python3 {command[len('python3 '):]}"
                    replaced += 1
                if isinstance(hook.get("command"), str) and "guard_bash.py" in hook["command"]:
                    guard = hook["command"]
    if guard is None:
        raise Failure(f"{claude / 'settings.json'} runs no guard_bash.py: install the method (python3 install.py)")
    (target / "settings.json").write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256()
    for path in sorted(temporary.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(temporary)).encode() + b"\0" + path.read_bytes())
    temporary.rename(staged)
    return {"digest": digest.hexdigest(), "guard_command": guard,
            "skills": sum(1 for _ in (staged / ".claude" / "skills").iterdir()),
            "adaptations": [f"settings.json keeps {', '.join(sorted(kept))} and leaves out "
                            f"{', '.join(sorted(set(settings) - set(kept))) or 'nothing'}",
                            f"{replaced} hook commands run {HOOKS_PYTHON}/bin/python3 instead of the image's python3"]}


# run: one run

def money(value: float) -> str:
    return f"{max(value, 0):.4f}"


def run_program(argv: list, what: str, data: str = None, env: dict = None, cwd: str = None,
                timeout: float = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=data, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, cwd=cwd, timeout=timeout, check=False)
    except OSError as error:
        raise Failure(f"{what}: {error}")


def checked(argv: list, what: str, data: str = None) -> str:
    result = run_program(argv, what, data)
    if result.returncode:
        raise Failure(f"{what}: exit {result.returncode}: {result.stderr.strip()[-500:]}")
    return result.stdout


def call_json(argv: list, data: str, env: dict, timeout: float, cwd: str = None) -> dict:
    """A claude -p call's JSON result; {"is_error": True, ...} when there is none."""
    try:
        done = run_program(argv, "claude", data, env, cwd, timeout)
    except subprocess.TimeoutExpired:
        return {"is_error": True, "subtype": "timeout"}
    result = None
    for text in [done.stdout] + done.stdout.strip().splitlines()[::-1]:
        try:
            candidate = json.loads(text)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            result = candidate
            break
    if result is None:
        result = {"is_error": True, "subtype": "no_result", "stdout_tail": done.stdout[-2000:]}
    result["exit_code"] = done.returncode
    if done.stderr.strip():
        result["stderr_tail"] = done.stderr[-2000:]
    return result


def interruption(result: dict):
    """"usage limit" or "login" when a failed call reports one, otherwise None."""
    if not (result.get("is_error") or result.get("exit_code")):
        return None
    text = " ".join(str(result.get(key, "")) for key in ("result", "stdout_tail", "stderr_tail", "error"))
    return next((name for name, pattern in INTERRUPTIONS if pattern.search(text)), None)


def cost_of(result: dict):
    value = result.get("total_cost_usd")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def host_environment() -> dict:
    """The host's environment without this session's Claude Code variables, so the
    maintainer's claude starts as a fresh session with its own login."""
    return {name: value for name, value in os.environ.items() if not name.startswith("CLAUDE")}


def qualified(image: str) -> str:
    first = image.split("/", 1)[0]
    return image if "/" in image and ("." in first or ":" in first or first == "localhost") else f"docker.io/{image}"


def container_git(name: str, *args, cwd: str = TESTBED) -> subprocess.CompletedProcess:
    return run_program(["podman", "exec", "-u", "agent", name, "git", "-C", cwd, *args], "git in the container")


def start_container(context, name: str, image: str, arm: str) -> None:
    argv = ["podman", "run", "-d", "--name", name, "--security-opt", "label=disable",
            "-v", f"{context.claude}:{CONTAINER_CLAUDE}:ro"]
    if arm == "method":
        argv += ["-v", f"{context.hooks_python}:{HOOKS_PYTHON}:ro"]
    checked(argv + ["--entrypoint", "sleep", qualified(image), "infinity"], "start the container")
    checked(["podman", "exec", name, "sh", "-c", f"useradd -m -s /bin/bash agent && chown -R agent:agent {TESTBED}"],
            "create the user agent")
    for key, value in GIT_IDENTITY:
        checked(["podman", "exec", "-u", "agent", name, "git", "config", "--global", key, value], "set git's identity")


def commits_after_base(name: str, base: str) -> list:
    listing = container_git(name, "rev-list", "--all", "--not", base)
    if listing.returncode:
        raise Failure(f"list the commits after base_commit: {listing.stderr.strip()[-300:]}")
    commits = listing.stdout.split()
    for commit in commits:
        if container_git(name, "diff", "--quiet", base, commit).returncode:
            raise Failure(f"commit {commit} after base_commit changes the tree: the image may hold the fix")
    return commits


def install_method(context, name: str) -> dict:
    checked(["podman", "cp", f"{context.staged}/.", f"{name}:/home/agent/"], "copy the method")
    checked(["podman", "exec", name, "chown", "-R", "agent:agent", "/home/agent"], "give the method to agent")
    result = run_program(["podman", "exec", "-u", "agent", name, "sh", "-c", PROBE_SCRIPT, "probe", PROBE_PAYLOAD,
                          context.method["guard_command"]], "probe the method")
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    probe = {"guard_exit_on_push": values.get("guard"), "skills": values.get("skills"),
             "expected_skills": context.method["skills"],
             "claude_md_imports_rules": RULES_IMPORT in values.get("claude_md", "")}
    probe["passed"] = (probe["guard_exit_on_push"] == "2" and probe["claude_md_imports_rules"]
                       and probe["skills"] == str(context.method["skills"]))
    return probe


def agent_call(context, name: str, arm: str, prompt: str, budget: float, session) -> dict:
    argv = ["podman", "exec", "-i", "-u", "agent", "-w", TESTBED, "-e", "CLAUDE_CODE_OAUTH_TOKEN", name, "claude", "-p"]
    argv += ["--safe-mode"] if arm == "plain" else []
    argv += ["--model", context.model, "--effort", "high", "--output-format", "json",
             "--permission-mode", "bypassPermissions", "--disallowed-tools", "WebFetch,WebSearch",
             "--max-budget-usd", money(budget)]
    argv += ["--resume", session] if session else []
    # podman exec -e NAME takes the value from podman's own environment: never in argv.
    token = access_token(context.credentials)
    context.tokens.add(token)
    result = call_json(argv, prompt, {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": token}, AGENT_TIMEOUT)
    # An agent that prints its environment would carry the token into the record and the
    # maintainer's prompt.
    return json.loads(scrubbed(json.dumps(result), context.tokens))


def scrubbed(text: str, tokens: set) -> str:
    """The text without any access token a call of this session used (the host's claude
    may have refreshed the login between calls)."""
    for token in tokens:
        text = text.replace(token, "[access token]")
    return text


def maintainer_call(context, issue: str, message: str, budget: float) -> dict:
    argv = ["claude", "-p", "--safe-mode", "--tools", "", "--model", context.maintainer_model,
            "--output-format", "json", "--max-budget-usd", money(budget)]
    with tempfile.TemporaryDirectory() as empty:
        return call_json(argv, MAINTAINER_PROMPT.format(issue=issue, message=message), host_environment(),
                         MAINTAINER_TIMEOUT, cwd=empty)


def spend(record: dict) -> float:
    return record["agent_cost"] + record["maintainer_cost"]


def converse(context, name: str, arm: str, agent: dict, record: dict) -> None:
    """The agent's calls and the maintainer's replies until a stop reason; raises
    Interrupted on a usage limit or a failed login."""
    prompt, session, replies = f"{agent['problem_statement'].rstrip()}\n\n{AGENT_INSTRUCTIONS}", None, 0
    while True:
        if context.share - spend(record) < MIN_BUDGET:
            record["stop"] = "budget"
            return
        result = agent_call(context, name, arm, prompt, context.share - spend(record), session)
        record["calls"].append(result)
        if cost_of(result) is not None:
            # The session's total holds its earlier calls; a resumed call that fails at once
            # may report less, which never lowers what was spent.
            record["agent_cost"] = max(record["agent_cost"], cost_of(result))
        session = result.get("session_id") or session
        stopped = interruption(result)
        if stopped:
            record["stop"] = stopped
            raise Interrupted(stopped, LOGIN_HINT if stopped == "login" else "")
        if result.get("subtype") == "error_max_budget_usd":
            record["stop"] = "budget"
            return
        if result.get("is_error"):
            record["stop"] = "error"
            return
        if replies == MAX_REPLIES:
            record["stop"] = "reply limit"
            return
        if context.share - spend(record) < MIN_BUDGET:
            record["stop"] = "budget"
            return
        answer = maintainer_call(context, agent["problem_statement"], str(result.get("result") or ""),
                                 context.share - spend(record))
        record["maintainer_cost"] += cost_of(answer) or 0.0
        stopped = interruption(answer)
        if stopped:
            record["stop"] = stopped
            raise Interrupted(stopped, LOGIN_HINT if stopped == "login" else "")
        reply = answer.get("result") if isinstance(answer.get("result"), str) and not answer.get("is_error") else None
        record["maintainer"].append({"reply": reply, "cost": cost_of(answer), "subtype": answer.get("subtype")})
        if reply is None or not reply.strip() or DONE_REPLY.fullmatch(reply.strip()):
            record["stop"] = "DONE"  # a maintainer call without a result counts as DONE
            return
        replies += 1
        prompt = reply


def patch_paths(patch: str) -> set:
    paths = set()
    for line in patch.splitlines():
        match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
        if match:
            paths.update(match.groups())
    return paths


def without_paths(diff: str, paths: set) -> tuple:
    """The diff without the file sections that touch one of the paths, and those paths."""
    kept, left_out = [], set()
    for section in re.split(r"(?m)^(?=diff --git )", diff):
        touched = patch_paths(section.split("\n", 1)[0]) & paths
        left_out |= touched
        if not touched:
            kept.append(section)
    return "".join(kept), sorted(left_out)


def predict(name: str, base: str) -> tuple:
    """(diff against base_commit, where it came from): /testbed with every change staged,
    else the newest other worktree or branch that differs from base_commit; the method's
    working notes (.private/, which a task repository does not ignore) never count."""
    def changed(path: str) -> bool:
        container_git(name, "add", "-A", cwd=path)
        return container_git(name, "diff", "--cached", "--quiet", base, *NOT_NOTES, cwd=path).returncode == 1

    if changed(TESTBED):
        return container_git(name, "diff", "--cached", "--binary", base, *NOT_NOTES).stdout, TESTBED
    candidates = []
    for line in container_git(name, "worktree", "list", "--porcelain").stdout.splitlines():
        path = line[len("worktree "):] if line.startswith("worktree ") else None
        if path and path != TESTBED and changed(path):
            when = container_git(name, "log", "-1", "--format=%ct", cwd=path).stdout.strip()
            candidates.append((int(when) if when.isdigit() else 0, f"worktree {path}", path, None))
    refs = container_git(name, "for-each-ref", "--format=%(committerdate:unix) %(refname)", "refs/heads").stdout
    for line in refs.splitlines():
        when, _, ref = line.partition(" ")
        if ref and container_git(name, "diff", "--quiet", base, ref, *NOT_NOTES).returncode == 1:
            candidates.append((int(when) if when.isdigit() else 0, f"branch {ref}", TESTBED, ref))
    if not candidates:
        return "", "none"
    _, source, path, ref = max(candidates)
    if ref:
        return container_git(name, "diff", "--binary", base, ref, *NOT_NOTES).stdout, source
    return container_git(name, "diff", "--cached", "--binary", base, *NOT_NOTES, cwd=path).stdout, source


def one_run(context, task: dict, arm: str, repeat: int, run_id: str, folder: Path) -> dict:
    agent = task["agent"]
    name = "dotagents-bench-" + re.sub(r"[^A-Za-z0-9_.-]", "-", run_id)
    record = {"run": run_id, "instance_id": agent["instance_id"], "arm": arm, "repeat": repeat, "started": now(),
              "finished": False, "stop": None, "error": None, "probe": None, "calls": [], "maintainer": [],
              "agent_cost": 0.0, "maintainer_cost": 0.0, "spend": 0.0, "commits_after_base": [],
              "adaptations": context.method["adaptations"] if arm == "method" else [],
              "prediction_source": None, "left_out": []}
    run_program(["podman", "rm", "-f", "-t", "0", name], "remove an old container")
    try:
        start_container(context, name, agent["image"], arm)
        record["commits_after_base"] = commits_after_base(name, agent["base_commit"])
        if arm == "method":
            record["probe"] = install_method(context, name)
            if not record["probe"]["passed"]:
                raise Failure("the method's probe failed: the method is not live in the container")
        converse(context, name, arm, agent, record)
        diff, record["prediction_source"] = predict(name, agent["base_commit"])
        diff = scrubbed(diff, context.tokens)  # an agent may have written its environment into a file
        diff, record["left_out"] = without_paths(diff, patch_paths(task["grading"].get("test_patch", "")))
        (folder / "prediction.diff").write_text(diff, encoding="utf-8")
        record["finished"] = True
    except Failure as error:
        record.update(stop="error", error=str(error), finished=True)
    except BaseException as stop:  # Interrupted, Ctrl-C or a bug: the attempt's spend still counts
        if isinstance(stop, Interrupted) and record["stop"] is None:
            record["stop"] = stop.kind
        stop.record = record
        raise
    finally:
        run_program(["podman", "rm", "-f", "-t", "0", name], "remove the container")
        record["spend"] = spend(record)
        record["ended"] = now()
    return record


# run: the whole plan

class Context:
    pass


def run(args) -> int:
    tasks = load_tasks(Path(args.tasks))
    arms = parse_arms(args.arms)
    if args.runs < 1 or not args.cap_usd > 0:
        raise UsageError("--runs must be at least 1 and --cap-usd above 0")
    order = planned(tasks, arms, args.runs)
    share = args.cap_usd / len(order)
    args.hooks_python = args.hooks_python or str(main_checkout() / ".private" / "evidence" / "python-3.12")
    rundir = Path(args.out)
    found = prerequisites(args, arms)
    if args.dry_run:
        for _, arm, _, run_id in order:
            print(f"{run_id} share {share:.2f}")
        print(f"{len(order)} runs, cap {args.cap_usd:.2f}, share {share:.2f}")
        for name, ok, detail in found:
            print(f"{name}: {'ok' if ok else 'missing'} ({detail})")
        return 0
    missing = [f"{name}: {detail}" for name, ok, detail in found if not ok]
    if missing:
        raise Failure("; ".join(missing))
    plan = {"tasks": [task["agent"]["instance_id"] for task in tasks], "arms": arms, "runs": args.runs,
            "cap_usd": args.cap_usd, "model": args.model, "maintainer_model": args.maintainer_model}
    if (rundir / "plan.json").exists():
        existing = read_json(rundir / "plan.json", "the plan")
        if {key: existing.get(key) for key in plan} != plan:
            raise UsageError(f"{rundir} holds another plan; use another --out")
        plan = existing
    else:
        plan.update(share=share, order=[run_id for _, _, _, run_id in order], started=now())
        write_json(rundir / "tasks.json", {"tasks": tasks})
    if "method" in arms and "method" not in plan:
        plan["method"] = stage_method(Path(args.method_home), rundir / "method")
    write_json(rundir / "plan.json", plan)
    context = Context()
    context.share, context.model, context.maintainer_model = share, args.model, args.maintainer_model
    context.credentials, context.hooks_python = Path(args.credentials), Path(args.hooks_python).resolve()
    context.claude = os.path.realpath(shutil.which("claude"))
    context.staged, context.method = (rundir / "method").resolve(), plan.get("method", {})
    context.tokens = set()  # every access token an agent call used
    finished = {}
    for path in (rundir / "runs").glob("*/record.json"):
        record = read_json(path, "a run record")
        if record.get("finished"):
            finished[record["run"]] = record
    interrupted = rundir / "interrupted.jsonl"
    spent = sum(record["spend"] for record in finished.values()) + sum(
        json.loads(line)["spend"] for line in (interrupted.read_text(encoding="utf-8").splitlines()
                                               if interrupted.exists() else []) if line.strip())
    waiting = [item for item in order if item[3] not in finished]
    for position, (task, arm, repeat, run_id) in enumerate(waiting):
        if spent + share > args.cap_usd + 1e-9:
            not_made = [item[3] for item in waiting[position:]]
            write_json(rundir / "not-made.json", not_made)
            print(f"cap reached: {len(not_made)} runs not made (listed in {rundir / 'not-made.json'})")
            break
        folder = rundir / "runs" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        try:
            record = one_run(context, task, arm, repeat, run_id, folder)
        except BaseException as stop:
            # Unfinished, so run again later; its spend still counts against the cap.
            if getattr(stop, "record", None) is not None:
                write_json(folder / "record.json", stop.record)
                with open(interrupted, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"run": run_id, "stop": str(stop) if isinstance(stop, Interrupted) else
                                             type(stop).__name__, "spend": stop.record["spend"], "at": now()}) + "\n")
            if not isinstance(stop, Interrupted):
                raise
            print(f"stopped at {run_id}: {stop}" + (f" ({stop.detail})" if stop.detail else "")
                  + f"; run again on {rundir} to go on")
            return 1
        write_json(folder / "record.json", record)
        spent += record["spend"]
        print(f"{run_id}: {record['stop']}, ${record['spend']:.2f}")
    over = f", {spent - args.cap_usd:.2f} over the cap" if spent > args.cap_usd else ""
    print(f"spent {spent:.2f} of {args.cap_usd:.2f}{over}; runs in {rundir / 'runs'}")
    return 0


# grade

def docker_host() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.environ.get("DOCKER_HOST") or f"unix://{runtime}/podman/podman.sock"


APPLY_FAILED = ">>>>> Patch Apply Failed"  # swebench.harness.constants.APPLY_PATCH_FAIL
TIMED_OUT = "Timeout error:"  # what run_evaluation adds to test_output.txt when the tests time out


def harness(python: Path, grading: Path, env: dict, run_id: str, predictions: str, model: str, ids: list) -> dict:
    """Run the SWE-bench harness from grading/ and read back each instance's grade: its
    report, or, without one, a patch that did not apply or tests that timed out (the
    harness logs either and writes no report), both unresolved, or "no report", a harness
    failure that is not graded."""
    logs = grading / "logs" / "run_evaluation" / run_id
    shutil.rmtree(logs, ignore_errors=True)  # the harness skips instances it already reported
    argv = [str(python), "-m", "swebench.harness.run_evaluation", "--dataset_name", "dataset.jsonl",
            "--predictions_path", predictions, "--run_id", run_id, "--instance_ids", *ids,
            "--max_workers", "2", "--timeout", "1800"]
    with open(grading / f"{run_id}.log", "w", encoding="utf-8") as log:
        subprocess.run(argv, cwd=grading, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    reports = {}
    for ident in ids:
        folder = logs / model / ident
        try:
            report = json.loads((folder / "report.json").read_text(encoding="utf-8"))[ident]
        except (OSError, ValueError, KeyError):
            logs_of = {}
            for name in ("run_instance.log", "test_output.txt"):
                try:
                    logs_of[name] = (folder / name).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    logs_of[name] = ""
            outcome = ("patch did not apply" if APPLY_FAILED in logs_of["run_instance.log"] else
                       "tests timed out" if TIMED_OUT in logs_of["test_output.txt"] else "no report")
            reports[ident] = {"graded": outcome != "no report", "resolved": False, "regressions": [],
                              "outcome": outcome}
            continue
        status = report.get("tests_status") or {}
        reports[ident] = {"graded": True, "outcome": "report", "resolved": report.get("resolved") is True,
                          "patch_applied": report.get("patch_successfully_applied") is True,
                          "regressions": sorted((status.get("PASS_TO_PASS") or {}).get("failure") or []),
                          "fail_to_pass_failed": sorted((status.get("FAIL_TO_PASS") or {}).get("failure") or [])}
    return reports


def grade(args) -> int:
    rundir = Path(args.rundir)
    tasks = load_tasks(Path(args.tasks) if args.tasks else rundir / "tasks.json")
    host = docker_host()
    if host.startswith("unix://") and not Path(host[len("unix://"):]).exists():
        raise Failure(f"no Docker API at {host}: start podman's (podman system service --time=0 {host} &, or "
                      f"systemctl --user start podman.socket) and set DOCKER_HOST to it")
    python = Path(args.swebench_python)
    if run_program([str(python), "-c", "import swebench"], "check the SWE-bench Python").returncode:
        raise Failure(f"{python} cannot import swebench: make a Python 3.10 or later virtual environment and "
                      f"pip install swebench in it")
    grading = rundir / "grading"
    grading.mkdir(parents=True, exist_ok=True)
    (grading / "dataset.jsonl").write_text(
        "".join(json.dumps({**task["agent"], **task["grading"]}) + "\n" for task in tasks), encoding="utf-8")
    env = {**os.environ, "DOCKER_HOST": host}
    if not shutil.which("docker"):  # the harness stops and removes its containers with the docker program
        shim = grading / "bin" / "docker"
        shim.parent.mkdir(exist_ok=True)
        shim.write_text('#!/bin/sh\nexec podman "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        env["PATH"] = f"{shim.parent}{os.pathsep}{env.get('PATH', '')}"
    if args.gold:
        ids = [task["agent"]["instance_id"] for task in tasks]
        gold = harness(python, grading, env, f"{rundir.name}-gold", "gold", "gold", ids)
        write_json(rundir / "gold.json", gold)
        print(f"gold: {sum(value['resolved'] for value in gold.values())} of {len(gold)} resolved "
              f"({rundir / 'gold.json'})")
        return unreported(gold, grading)
    # The harness keys predictions by instance id: one call per arm and repeat.
    groups = {}
    for path in sorted((rundir / "runs").glob("*/record.json")):
        record = read_json(path, "a run record")
        prediction = path.parent / "prediction.diff"
        if record.get("finished") and record.get("calls") and prediction.exists():
            groups.setdefault((record["arm"], record["repeat"]), {})[record["instance_id"]] = (
                record["run"], prediction.read_text(encoding="utf-8"))
    grades = {}
    for (arm, repeat), runs in sorted(groups.items()):
        model = f"{arm}-{repeat}"
        # The harness drops an empty patch unreported: it resolves nothing.
        submitted = {ident: run for ident, run in runs.items() if run[1].strip()}
        for run_id, patch in runs.values():
            if not patch.strip():
                grades[run_id] = {"graded": True, "resolved": False, "outcome": "empty prediction", "regressions": []}
        if not submitted:
            continue
        predictions = grading / f"predictions-{model}.jsonl"
        predictions.write_text("".join(json.dumps({"instance_id": ident, "model_name_or_path": model,
                                                   "model_patch": patch}) + "\n"
                                       for ident, (_, patch) in sorted(submitted.items())), encoding="utf-8")
        reports = harness(python, grading, env, f"{rundir.name}-{model}", predictions.name, model, sorted(submitted))
        for ident, (run_id, _) in submitted.items():
            grades[run_id] = reports[ident]
    write_json(rundir / "grades.json", grades)
    for arm in sorted({run_id.split(".")[-2] for run_id in grades}):
        mine = [value for run_id, value in grades.items() if run_id.split(".")[-2] == arm]
        print(f"{arm}: {sum(value['resolved'] for value in mine)} of {len(mine)} resolved")
    print(f"grades: {rundir / 'grades.json'}")
    return unreported(grades, grading)


def unreported(grades: dict, grading: Path) -> int:
    """1, naming them, when the harness failed on some runs; 0 otherwise."""
    missing = sorted(name for name, value in grades.items() if not value["graded"])
    if missing:
        print(f"no report for {len(missing)} (a harness failure; its logs are in {grading}): "
              f"{', '.join(missing)}; grade again to retry", file=sys.stderr)
        return 1
    return 0


# summary

FULL_TASKS, FULL_RUNS = 20, 3  # the full run DESIGN.org's method-measured rule asks for


def median(values: list, form: str) -> str:
    ordered = sorted(values)
    if not ordered:
        return "-"
    middle = len(ordered) // 2
    value = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return format(value, form)


def org_table(rows: list) -> list:
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    line = lambda row: "| " + " | ".join(cell.ljust(width) for cell, width in zip(row, widths)) + " |"  # noqa: E731
    return [line(rows[0]), "|-" + "-+-".join("-" * width for width in widths) + "-|"] + [line(row) for row in rows[1:]]


def replies_of(record: dict) -> int:
    return sum(1 for entry in record.get("maintainer", [])
               if isinstance(entry.get("reply"), str) and entry["reply"].strip()
               and not DONE_REPLY.fullmatch(entry["reply"].strip()))


def arm_row(arm: str, records: list, grades, share: float) -> list:
    mine = [record for record in records if record["arm"] == arm]
    reached = [record for record in mine if record.get("calls")]
    known = grades is not None
    # Graded: a report, an empty prediction or a patch that did not apply (both unresolved);
    # a run the harness failed on is counted apart, outside the rate.
    graded = [grades[record["run"]] for record in reached if known and grades.get(record["run"], {}).get("graded")]
    resolved = sum(1 for value in graded if value["resolved"])
    failed = sum(1 for value in graded if value.get("outcome") in ("empty prediction", "patch did not apply"))
    stops = {}
    for record in mine:
        stops[record["stop"]] = stops.get(record["stop"], 0) + 1
    over = [record["spend"] - share for record in mine if record["spend"] > share + 1e-9]
    return [arm, str(len(mine)), str(sum(1 for record in mine if record["stop"] == "error")),
            str(len(graded)) if known else "-", str(failed) if known else "-",
            str(len(reached) - len(graded)) if known else "-", str(resolved) if known else "-",
            f"{100 * resolved / len(graded):.0f}%" if graded else "-",
            median([record["agent_cost"] for record in reached], ".2f"),
            f"{sum(record['agent_cost'] for record in mine):.2f}",
            median([record["maintainer_cost"] for record in reached], ".2f"),
            f"{sum(record['maintainer_cost'] for record in mine):.2f}",
            median([sum(call.get("num_turns") or 0 for call in record["calls"]) for record in reached], ".1f"),
            median([sum(call.get("duration_ms") or 0 for call in record["calls"]) / 60000 for record in reached],
                   ".1f"),
            str(sum(1 for value in graded if value.get("regressions"))) if known else "-",
            median([replies_of(record) for record in reached], ".1f"),
            str(len(over)), f"{max(over, default=0):.2f}",
            ", ".join(f"{stop} {count}" for stop, count in sorted(stops.items(), key=lambda item: (-item[1], item[0])))]


def summary(args) -> int:
    rundir = Path(args.rundir)
    plan = read_json(rundir / "plan.json", "the plan")
    records = [record for record in (read_json(path, "a run record")
                                     for path in sorted((rundir / "runs").glob("*/record.json")))
               if record.get("finished")]
    grades = read_json(rundir / "grades.json", "the grades") if (rundir / "grades.json").exists() else None
    tasks, runs, arms = plan["tasks"], plan["runs"], plan["arms"]
    # Full only when both arms finished every planned run of a plan as large as the rule's.
    reached = {record["run"] for record in records if record.get("calls")}
    full = (len(tasks) >= FULL_TASKS and runs >= FULL_RUNS and set(arms) == set(ARMS)
            and all(f"{task}.{arm}.{repeat}" in reached
                    for task in tasks for arm in arms for repeat in range(1, runs + 1)))
    path = rundir / "interrupted.jsonl"
    attempts = [json.loads(line) for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else [])
                if line.strip()]
    not_made = read_json(rundir / "not-made.json", "the runs not made") if (rundir / "not-made.json").exists() else []
    finished_spend = sum(record["spend"] for record in records)
    attempts_spend = sum(attempt["spend"] for attempt in attempts)
    lines = [("full run" if full else
              f"pilot: not conclusive (fewer than {FULL_TASKS} tasks or {FULL_RUNS} runs per arm finished in "
              f"both arms)") + ".", "",
             f"{len(tasks)} tasks, {runs} runs per arm, model {plan['model']}, maintainer "
             f"{plan['maintainer_model']}, cap {plan['cap_usd']:.2f}, share {plan['share']:.2f}"
             + ("; not graded." if grades is None else "."),
             f"Spent {finished_spend + attempts_spend:.2f} in all: {finished_spend:.2f} in finished runs and "
             f"{attempts_spend:.2f} in interrupted attempts ({len(attempts)}); planned runs not made: "
             f"{len(not_made)}.", ""]
    lines += org_table([["arm", "runs", "errors", "graded", "empty or not applied", "no report", "resolved",
                         "resolved rate", "median agent cost",
                         "total agent cost", "median maintainer cost", "total maintainer cost", "median turns",
                         "median minutes", "runs with regressions", "median replies", "runs over share",
                         "max over share", "stops"]]
                       + [arm_row(arm, records, grades, plan["share"]) for arm in arms])
    rows = [["task"] + [f"{arm} {what}" for arm in arms for what in ("resolved", "median agent cost")]]
    for ident in tasks:
        row = [ident]
        for arm in arms:
            reached = [record for record in records
                       if record["instance_id"] == ident and record["arm"] == arm and record.get("calls")]
            graded = [grades[record["run"]] for record in reached
                      if grades is not None and grades.get(record["run"], {}).get("graded")]
            row += [f"{sum(1 for value in graded if value['resolved'])}/{len(graded)}" if grades is not None else "-",
                    median([record["agent_cost"] for record in reached], ".2f")]
        rows.append(row)
    lines += [""] + org_table(rows)
    text = "\n".join(lines) + "\n"
    if args.org:
        Path(args.org).write_text(text, encoding="utf-8")
        print(f"summary: {args.org}")
    else:
        print(text, end="")
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
    runner = commands.add_parser("run", help="run the tasks in both arms")
    runner.add_argument("--tasks", required=True)
    runner.add_argument("--runs", type=int, required=True)
    runner.add_argument("--arms", required=True)
    runner.add_argument("--model", required=True)
    runner.add_argument("--maintainer-model", required=True)
    runner.add_argument("--cap-usd", type=float, required=True)
    runner.add_argument("--out", required=True)
    runner.add_argument("--dry-run", action="store_true")
    runner.add_argument("--method-home", default=str(Path.home()))
    runner.add_argument("--credentials", default=str(Path.home() / ".claude" / ".credentials.json"))
    runner.add_argument("--hooks-python")
    runner.set_defaults(handler=run)
    grader = commands.add_parser("grade", help="grade the runs, or the gold patches, with the SWE-bench harness")
    grader.add_argument("--rundir", required=True)
    grader.add_argument("--swebench-python", required=True)
    grader.add_argument("--gold", action="store_true")
    grader.add_argument("--tasks")
    grader.set_defaults(handler=grade)
    summarizer = commands.add_parser("summary", help="summarize the runs per arm")
    summarizer.add_argument("--rundir", required=True)
    summarizer.add_argument("--org")
    summarizer.set_defaults(handler=summary)
    return main_parser


def main() -> int:
    args = parser().parse_args()  # exits 2 on a usage error
    try:
        return args.handler(args)
    except UsageError as error:
        print(f"benchmark.py {args.command}: {error}", file=sys.stderr)
        return 2
    except Failure as error:
        print(f"benchmark.py {args.command}: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"benchmark.py {args.command}: stopped; run again on the same folder to go on", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
