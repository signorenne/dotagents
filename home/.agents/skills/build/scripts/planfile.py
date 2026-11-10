# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""The plan file of a change and its log, as METHOD.org defines them (standard library only).

A plan is .private/plans/<slug>.<ext> (org or md) in the working-notes folder: the
nearest .private in the working folder or a parent, up to the repository root; in a
linked worktree, the main checkout's. <slug> comes from a task branch <type>/<slug>.
Its state header is the "- Key: value" list before the first section; its tables are
org or markdown tables. The log <slug>.log beside it is tab-separated and written only
by scripts and hooks.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

HEADER_KEYS = ("Status", "Lane", "Risk", "Base", "Branch", "Review", "Next")
STATUSES = ("draft", "approved", "in progress", "in review", "built", "landed", "blocked", "dropped")
OPEN_STATUSES = ("draft", "approved", "in progress", "in review", "built", "blocked")
TASK_BRANCH = re.compile(r"^[a-z]+/([A-Za-z0-9._-]+)$")
HEADER_LINE = re.compile(r"^- (" + "|".join(HEADER_KEYS) + r"): *(.*)$")
SECTION = re.compile(r"^(?:\* +|## +)(.+?)\s*$")
SEPARATOR_ROW = re.compile(r"^\|[-+:| ]+\|?$")
LOG_FIELDS = ("time", "step", "kind", "commit", "result", "tests", "command")
PLAN_SUFFIXES = (".org", ".md")
# Seconds per git call; a hook with a time limit lowers it before calling in.
GIT_TIMEOUT = 5.0


def git(args, cwd, timeout: float | None = None) -> tuple[str, bool]:
    """(stdout without trailing newlines, ok); a call slower than the timeout is not ok."""
    try:
        result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                                timeout=timeout or GIT_TIMEOUT, check=False)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "", False
    return result.stdout.rstrip("\n"), result.returncode == 0


def private_folder(cwd) -> Path | None:
    """The working-notes folder for cwd: .private in cwd or a parent up to the repository
    root; in a linked worktree, the main checkout's .private."""
    start = Path(cwd).absolute()
    for directory in (start, *start.parents):
        if (directory / ".private").is_dir():
            return directory / ".private"
        dot_git = directory / ".git"
        if dot_git.is_file():  # a linked worktree
            common, ok = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], directory)
            main = Path(common).parent / ".private" if ok and common else None
            return main if main is not None and main.is_dir() else None
        if dot_git.exists():
            return None
    return None


def slug_of(branch: str) -> str | None:
    match = TASK_BRANCH.match(branch or "")
    return match.group(1) if match else None


def plan_for(private: Path, slug: str) -> Path | None:
    """The newest .private/plans/<slug>.org or .md."""
    found = [private / "plans" / f"{slug}{suffix}" for suffix in PLAN_SUFFIXES]
    found = [p for p in found if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def all_plans(private: Path) -> list:
    folder = private / "plans"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix in PLAN_SUFFIXES and p.is_file())


def log_of(plan: Path) -> Path:
    return plan.with_suffix(".log")


def sections(text: str) -> tuple[dict, dict]:
    """(header {key: value}, {section title: body text}). The title line (org #+TITLE or a
    markdown "# " heading) is not a section."""
    header, bodies, current = {}, {}, None
    for line in text.splitlines():
        match = SECTION.match(line)
        if match:
            current = match.group(1)
            bodies[current] = []
            continue
        if current is None:
            found = HEADER_LINE.match(line)
            if found and found.group(1) not in header:
                header[found.group(1)] = found.group(2).strip()
        else:
            bodies[current].append(line)
    return header, {title: "\n".join(lines) for title, lines in bodies.items()}


def table(body: str) -> list:
    """The rows of the first table in a section body, as dicts keyed by the lower-case
    header cells."""
    rows = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        if SEPARATOR_ROW.match(stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return []
    keys = [cell.lower() for cell in rows[0]]
    return [dict(zip(keys, cells + [""] * (len(keys) - len(cells)))) for cells in rows[1:]]


def read(plan: Path) -> dict:
    text = plan.read_text(encoding="utf-8", errors="replace")
    header, bodies = sections(text)
    found = {"header": header, "sections": bodies}
    for name in ("Steps", "Rulings", "Review", "Assumptions"):
        found[name.lower()] = table(bodies.get(name, ""))
    return found


def append_log(plan: Path, **fields) -> str:
    """Append one line to the plan's log; return it."""
    fields.setdefault("time", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    line = "\t".join(str(fields.get(key, "-")).replace("\t", " ").replace("\n", " ") or "-"
                     for key in LOG_FIELDS)
    with log_of(plan).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return line


def log_lines(plan: Path) -> list:
    path = log_of(plan)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = line.split("\t")
        if len(cells) == len(LOG_FIELDS):
            rows.append(dict(zip(LOG_FIELDS, cells)))
    return rows


def head_state(cwd) -> dict:
    """Branch, short HEAD and the modified tracked files of the repository at cwd; {} outside one."""
    branch, ok = git(["branch", "--show-current"], cwd)
    if not ok:
        return {}
    head, _ = git(["rev-parse", "--short", "HEAD"], cwd)
    status, _ = git(["--no-optional-locks", "status", "--porcelain", "--untracked-files=no"], cwd)
    untracked, _ = git(["--no-optional-locks", "status", "--porcelain", "--untracked-files=normal"], cwd)
    return {"branch": branch, "head": head, "dirty": [line for line in status.splitlines() if line],
            "untracked": [line[3:] for line in untracked.splitlines() if line.startswith("??")]}


def locate(cwd) -> tuple[dict, Path | None, Path | None]:
    """(head state, working-notes folder, plan file of the current task branch)."""
    state = head_state(cwd)
    if not state:
        return {}, None, None
    private = private_folder(cwd)
    slug = slug_of(state["branch"])
    plan = plan_for(private, slug) if private and slug else None
    return state, private, plan
