#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Validate the repository: skill and subagent files, text rules, script syntax.

Usage: python3 tools/validate.py     (exit code 1 when anything fails)

Checks:
- skills follow the Agent Skills format: name, description and license fields only,
  name in lowercase kebab case and equal to the folder name, description within the
  limit (1024 characters locally, 200 for the claude.ai set), a LICENSE.txt next to it,
  no inline backticks outside fenced blocks;
- subagents carry name, description, tools and model, and the name matches the file;
- no em dash or en dash in any text file;
- no unfilled <FILL: ...> marker outside the project templates;
- the global instructions stay under 200 lines;
- every Python file compiles.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "home" / ".agents"
ONLINE = ROOT / "claude-ai" / "skills"
OVERRIDES = ROOT / "claude-ai" / "overrides.json"
TEMPLATES = HOME / "skills" / "project-setup" / "templates"
TEXT_SUFFIXES = {".md", ".txt", ".py", ".json", ".yml", ".yaml", ".org", ".template", ".toml", ""}
SKIP_DIRS = {".git", "dist", "__pycache__"}
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
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


def check_skill(folder: Path, limit: int, errors: list[str]) -> None:
    skill = folder / "SKILL.md"
    rel = skill.relative_to(ROOT)
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
    if name != folder.name:
        errors.append(f"{rel}: name {name!r} differs from folder {folder.name!r}")
    description = fields.get("description", "")
    if not description or len(description) > limit:
        errors.append(f"{rel}: description length {len(description)} (limit {limit})")
    if not (folder / "LICENSE.txt").is_file():
        errors.append(f"{rel}: LICENSE.txt missing")
    if inline_backticks(body):
        errors.append(f"{rel}: inline backticks outside fenced blocks")


def check_agent(path: Path, errors: list[str]) -> None:
    rel = path.relative_to(ROOT)
    try:
        fields, _ = frontmatter(path)
    except (ValueError, json.JSONDecodeError) as error:
        errors.append(f"{rel}: {error}")
        return
    missing = AGENT_REQUIRED - set(fields)
    if missing:
        errors.append(f"{rel}: missing fields {sorted(missing)}")
    if fields.get("name") != path.stem:
        errors.append(f"{rel}: name differs from file name")


def text_files():
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not SKIP_DIRS & set(path.relative_to(ROOT).parts):
            if path.suffix in TEXT_SUFFIXES:
                yield path


def main() -> int:
    errors: list[str] = []

    for folder in sorted((HOME / "skills").iterdir()):
        check_skill(folder, 1024, errors)
    for folder in sorted(ONLINE.iterdir()):
        check_skill(folder, 200, errors)
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))["skills"]
    for name, override in overrides.items():
        if not (HOME / "skills" / name / "SKILL.md").is_file():
            errors.append(f"claude-ai/overrides.json: unknown skill {name!r}")
        if len(override.get("description", "")) > 200:
            errors.append(f"claude-ai/overrides.json: {name} description over 200 characters")
    for name in overrides:
        if (ONLINE / name).exists():
            errors.append(f"claude-ai/skills/{name}: also listed in overrides.json")

    for agent in sorted((HOME / "agents").glob("*.md")):
        check_agent(agent, errors)

    for path in text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
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
