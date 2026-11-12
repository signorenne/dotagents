#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Validate the repository: skill and subagent files, text rules, script syntax.

Usage: python3 tools/validate.py     (exit code 1 when anything fails)

Checks:
- every folder in a skills root holds a SKILL.md, and no skill name is in both roots;
- skills follow the Agent Skills format: name, description and license fields only,
  name in lowercase kebab case, equal to the folder name, without the reserved words
  anthropic and claude and not synced, description within the limit (1024 characters
  locally, 200 for the claude.ai set) and without angle brackets, a LICENSE.txt next to
  it, no inline backticks outside fenced blocks;
- each override in claude-ai/overrides.json names a local skill and has a description
  of 1 to 200 characters without angle brackets;
- subagents carry name, description, tools and model, the name matches the file, and
  the body has no ''' (the Codex copy holds it in a TOML literal string);
- no em dash or en dash in any text file git tracks or would track (every file
  outside .git, dist and __pycache__ when git is missing; never .private);
- no unfilled <FILL: ...> marker outside the project templates;
- the global instructions stay under 200 lines;
- every Python file compiles.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "home" / ".agents"
ONLINE = ROOT / "claude-ai" / "skills"
OVERRIDES = ROOT / "claude-ai" / "overrides.json"
TEMPLATES = HOME / "skills" / "project-setup" / "templates"
SKIP_DIRS = {".git", "dist", "__pycache__", ".private"}
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Words Anthropic reserves in skill names, and names Claude Code uses for its own folders.
RESERVED_WORDS = ("anthropic", "claude")
RESERVED_NAMES = {"synced", "anthropic-skills"}
CLAUDE_AI_LIMIT = 200
SKILL_FIELDS = {"name", "description", "license"}
AGENT_REQUIRED = {"name", "description", "tools", "model"}
DASHES = ("\u2014", "\u2013")


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing frontmatter")
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"unparsable frontmatter line: {line!r}")
        value = value.strip()
        fields[key.strip()] = json.loads(value) if value.startswith('"') else value
    return fields, body


def inline_backticks(body: str) -> bool:
    without_fences = re.sub(r"```.*?```", "", body, flags=re.S)
    return "`" in without_fences


def skill_folders(root: Path) -> list:
    """Every folder in a skills root; stray files such as .DS_Store are not skills."""
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS)


def angle_brackets(text: str) -> bool:
    return "<" in text or ">" in text


def check_skill(folder: Path, limit: int, errors: list[str]) -> None:
    skill = folder / "SKILL.md"
    rel = skill.relative_to(ROOT)
    if not skill.is_file():
        errors.append(f"{folder.relative_to(ROOT)}: SKILL.md missing")
        return
    try:
        fields, body = frontmatter(skill)
    except (ValueError, json.JSONDecodeError) as error:
        errors.append(f"{rel}: {error}")
        return
    extra = set(fields) - SKILL_FIELDS
    if extra:
        errors.append(f"{rel}: fields outside the standard set: {sorted(extra)}")
    name = fields.get("name", "")
    if not NAME.match(name) or len(name) > 64:
        errors.append(f"{rel}: invalid name {name!r}")
    elif name in RESERVED_NAMES or any(word in name for word in RESERVED_WORDS):
        errors.append(f"{rel}: reserved name {name!r}")
    if name != folder.name:
        errors.append(f"{rel}: name {name!r} differs from folder {folder.name!r}")
    description = fields.get("description", "")
    if not description or len(description) > limit:
        errors.append(f"{rel}: description length {len(description)} (limit {limit})")
    if angle_brackets(description):
        errors.append(f"{rel}: angle brackets in the description")
    if not (folder / "LICENSE.txt").is_file():
        errors.append(f"{rel}: LICENSE.txt missing")
    if inline_backticks(body):
        errors.append(f"{rel}: inline backticks outside fenced blocks")


def check_agent(path: Path, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    try:
        fields, body = frontmatter(path)
    except (ValueError, json.JSONDecodeError) as error:
        errors.append(f"{rel}: {error}")
        return
    missing = AGENT_REQUIRED - set(fields)
    if missing:
        errors.append(f"{rel}: missing fields {sorted(missing)}")
    if fields.get("name") != path.stem:
        errors.append(f"{rel}: name differs from file name")
    if "'''" in body:
        errors.append(f"{rel}: body contains ''', which ends the TOML literal string of the Codex copy")


def check_overrides(errors: list[str]) -> None:
    rel = OVERRIDES.relative_to(ROOT)
    if not OVERRIDES.is_file():
        return
    try:
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except ValueError as error:
        errors.append(f"{rel}: {error}")
        return
    skills = overrides.get("skills") if isinstance(overrides, dict) else None
    if not isinstance(skills, dict):
        errors.append(f"{rel}: no skills object")
        return
    for name, override in skills.items():
        if not (HOME / "skills" / name / "SKILL.md").is_file():
            errors.append(f"{rel}: unknown skill {name!r}")
        if (ONLINE / name).exists():
            errors.append(f"claude-ai/skills/{name}: also listed in overrides.json")
        description = override.get("description") if isinstance(override, dict) else None
        if not isinstance(description, str) or not description.strip() \
                or len(description) > CLAUDE_AI_LIMIT:
            errors.append(f"{rel}: {name}: description must be a string of 1 to "
                          f"{CLAUDE_AI_LIMIT} characters")
        elif angle_brackets(description):
            errors.append(f"{rel}: {name}: description has angle brackets")


def git_files():
    """Files git tracks or would track (untracked, not ignored); None without git."""
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        if Path(top).resolve() != ROOT.resolve():  # ROOT is a plain folder inside another repository
            return None
        listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return sorted({ROOT / name for name in os.fsdecode(listed).split("\0") if name})


def walked_files():
    for folder, dirs, files in os.walk(ROOT):
        here = Path(folder)
        # A folder with its own .git (a nested repository or worktree) is not part of this one.
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (here / d / ".git").exists())
        for name in sorted(files):
            yield here / name


def text_files():
    """Every text file of the repository, as (path, text); binary files are skipped."""
    paths = git_files()
    for path in walked_files() if paths is None else paths:
        if SKIP_DIRS & set(path.relative_to(ROOT).parts) or path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" not in data:
            yield path, data.decode("utf-8", errors="replace")


def main() -> int:
    errors: list[str] = []

    local, online = skill_folders(HOME / "skills"), skill_folders(ONLINE)
    for folder in local:
        check_skill(folder, 1024, errors)
    for folder in online:
        check_skill(folder, CLAUDE_AI_LIMIT, errors)
    for name in sorted({p.name for p in local} & {p.name for p in online}):
        errors.append(f"{name}: skill in both home/.agents/skills and claude-ai/skills")
    check_overrides(errors)

    for agent in sorted((HOME / "agents").glob("*.md")):
        check_agent(agent, errors)

    for path, text in text_files():
        rel = path.relative_to(ROOT)
        for number, line in enumerate(text.splitlines(), start=1):
            if any(dash in line for dash in DASHES):
                errors.append(f"{rel}:{number}: em or en dash")
        if "<FILL" in text and TEMPLATES not in path.parents and path.parent != ROOT / "tools":
            if path.name != "SKILL.md" or path.parent.name != "project-setup":
                errors.append(f"{rel}: unfilled <FILL marker outside the templates")
        if path.suffix == ".py":
            try:
                compile(text, str(path), "exec")
            except SyntaxError as error:
                errors.append(f"{rel}: {error}")

    lines = len((HOME / "AGENTS.md").read_text(encoding="utf-8").splitlines())
    if lines > 200:
        errors.append(f"home/.agents/AGENTS.md: {lines} lines (limit 200)")

    for error in errors:
        print(f"FAIL {error}")
    print(f"{'FAILED' if errors else 'OK'}: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
