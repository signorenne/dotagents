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
  it, no inline backticks outside fenced blocks, and a body of at most 20,000 bytes
  (about the 5,000 tokens of a skill that Claude Code keeps after compaction);
- each override in claude-ai/overrides.json names a local skill and has a description
  of 1 to 200 characters without angle brackets;
- each path rule in home/.agents/path-rules.json names a skill of the repository and
  lists globs without quotes, backslashes or newlines;
- subagents carry name, description, tools and model, the name matches the file, an
  effort is one of Claude Code's levels, a maxTurns is a positive whole number, and the
  body has no ''' (the Codex copy holds it in a TOML literal string);
- no em dash or en dash in any text file git tracks or would track (every file
  outside .git, dist and __pycache__ when git is missing; never .private);
- no unfilled <FILL: ...> marker outside the project templates;
- the files agents load as instructions (home/.agents/AGENTS.md, every text file of a
  skill in either root, the subagents, the path rules, and the repository's AGENTS.md,
  CLAUDE.md, GEMINI.md and .github/copilot-instructions.md) hold no character a reader
  does not see but a model reads: zero width (U+200B to U+200D, U+2060), bidirectional
  controls (U+200E, U+200F, U+202A to U+202E, U+2066 to U+2069), U+FEFF anywhere (a
  byte order mark too: the files are plain UTF-8), the soft hyphen U+00AD and the tags
  U+E0000 to U+E007F; and the Markdown ones hold no HTML comment outside fenced code
  (it hides text from a reader of the rendered file, not from the model);
- the global instructions stay under 200 lines;
- every Python file compiles;
- every Org link in an Org file resolves: [[file:path]] names an existing file
  (relative to the linking file; ~ and absolute paths are not checked), ::#id and #id
  a CUSTOM_ID of the target file, ::*Heading and *Heading one of its headings (title
  without tags, any run of spaces as one); links in src and example blocks or in
  =verbatim= and ~code~ spans, web links and other searches are not checked.
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
PATH_RULES = HOME / "path-rules.json"
TEMPLATES = HOME / "skills" / "project-setup" / "templates"
SKIP_DIRS = {".git", "dist", "__pycache__", ".private"}
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Words Anthropic reserves in skill names, and names Claude Code uses for its own folders.
RESERVED_WORDS = ("anthropic", "claude")
RESERVED_NAMES = {"synced", "anthropic-skills"}
CLAUDE_AI_LIMIT = 200
# After compaction Claude Code keeps the first 5,000 tokens of each invoked skill:
# 20,000 bytes is that budget at about 4 bytes per token.
SKILL_BODY_LIMIT = 20000
SKILL_FIELDS = {"name", "description", "license"}
AGENT_REQUIRED = {"name", "description", "tools", "model"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}  # Claude Code's subagent effort levels
DASHES = ("\u2014", "\u2013")
ORG_LINK = re.compile(r"\[\[([^\[\]\n]+)\](?:\[[^\]]*\])?\]")
ORG_BLOCK = re.compile(r"^[ \t]*#\+begin_(src|example)\b.*?^[ \t]*#\+end_\1\b", re.I | re.M | re.S)
CUSTOM_ID = re.compile(r"^[ \t]*:CUSTOM_ID:[ \t]+(\S+)[ \t]*$", re.M)
ORG_HEADING = re.compile(r"^\*+[ \t]+(.*?)[ \t]*$", re.M)
ORG_TAGS = re.compile(r"[ \t]+:([\w@#%]+:)+$")
# Verbatim and code spans (=...=, ~...~) on one line: their text is not a link.
ORG_VERBATIM = re.compile(r"(?<![^\s(\[{'\"-])([=~])(?=\S)[^\n]*?(?<=\S)\1(?=[\s.,:;!?)\]}'\"-]|$)", re.M)
# Files and folders agents load as instructions, and the characters in them that a reader
# does not see but a model reads (the context-file scan of Hermes Agent).
INSTRUCTION_FILES = {HOME / "AGENTS.md", PATH_RULES, ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / "GEMINI.md",
                     ROOT / ".github" / "copilot-instructions.md"}
INSTRUCTION_FOLDERS = (HOME / "skills", ONLINE, HOME / "agents")
HIDDEN_CHARACTER = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
MARKDOWN_SUFFIXES = (".md", ".md.template")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


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
    size = len(body.encode("utf-8"))
    if size > SKILL_BODY_LIMIT:
        errors.append(f"{rel}: body of {size} bytes (limit {SKILL_BODY_LIMIT})")


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
    if "effort" in fields and fields["effort"] not in EFFORTS:
        errors.append(f"{rel}: effort {fields['effort']!r} is not one of {', '.join(sorted(EFFORTS))}")
    if "maxTurns" in fields and not re.fullmatch(r"[1-9][0-9]*", str(fields["maxTurns"])):
        errors.append(f"{rel}: maxTurns {fields['maxTurns']!r} is not a positive whole number")
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


def check_path_rules(errors: list[str]) -> None:
    """Each path rule names a skill of the repository and lists globs that fit in a
    double-quoted YAML string of the generated rule."""
    rel = PATH_RULES.relative_to(ROOT)
    if not PATH_RULES.is_file():
        return
    try:
        data = json.loads(PATH_RULES.read_text(encoding="utf-8"))
    except ValueError as error:
        errors.append(f"{rel}: {error}")
        return
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, dict):
        errors.append(f"{rel}: no rules object")
        return
    for skill, globs in rules.items():
        if not ((HOME / "skills" / skill / "SKILL.md").is_file() or (ONLINE / skill / "SKILL.md").is_file()):
            errors.append(f"{rel}: path rule for unknown skill {skill!r}")
        if not (isinstance(globs, list) and globs and all(isinstance(g, str) and g.strip() for g in globs)):
            errors.append(f"{rel}: path rule {skill}: globs must be a non-empty list of text")
            continue
        for glob in globs:
            if any(char in glob for char in '"\\\n'):
                errors.append(f"{rel}: path rule {skill}: glob {glob!r} has a quote, a backslash or a newline")


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


def org_title(text: str) -> str:
    return " ".join(ORG_TAGS.sub("", text).split())


def org_anchors(path: Path, cache: dict) -> tuple:
    """(CUSTOM_IDs, heading titles) of an Org file, read once."""
    if path not in cache:
        text = path.read_text(encoding="utf-8", errors="replace")
        cache[path] = (set(CUSTOM_ID.findall(text)), {org_title(h) for h in ORG_HEADING.findall(text)})
    return cache[path]


def org_link_problem(source: Path, target: str, cache: dict) -> str:
    """Why an Org link from source does not resolve, or ""."""
    destination, search = source, target
    if target.startswith("file:"):
        name, _, search = target[len("file:"):].partition("::")
        if name.startswith(("~", "/")):
            return ""
        destination = (source.parent / name).resolve() if name else source
        if not destination.exists():
            return f"{relative(destination)} does not exist"
    elif not target.startswith(("#", "*")):
        return ""  # a web link or another link type
    if not search.startswith(("#", "*")) or not destination.is_file():
        return ""
    ids, headings = org_anchors(destination, cache)
    if search.startswith("#") and search[1:] not in ids:
        return f"no CUSTOM_ID {search[1:]} in {relative(destination)}"
    if search.startswith("*") and org_title(search[1:]) not in headings:
        return f"no heading {org_title(search[1:])!r} in {relative(destination)}"
    return ""


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def check_org_links(path: Path, text: str, cache: dict, errors: list) -> None:
    # Blank out src and example blocks, and verbatim spans, keeping the line numbers.
    scanned = ORG_BLOCK.sub(lambda block: "\n" * block.group(0).count("\n"), text)
    scanned = ORG_VERBATIM.sub("", scanned)
    for link in ORG_LINK.finditer(scanned):
        target = link.group(1).strip()
        problem = org_link_problem(path, target, cache)
        if problem:
            line = scanned.count("\n", 0, link.start()) + 1
            errors.append(f"{relative(path)}:{line}: broken link [[{target}]]: {problem}")


def instruction_file(path: Path) -> bool:
    return path in INSTRUCTION_FILES or any(folder in path.parents for folder in INSTRUCTION_FOLDERS)


def check_hidden_text(rel: Path, text: str, errors: list) -> None:
    """Report each hidden character with its line, column and code point and, in Markdown,
    each HTML comment outside fenced code."""
    markdown = rel.name.endswith(MARKDOWN_SUFFIXES)
    fence = ""
    for number, line in enumerate(text.split("\n"), start=1):
        for match in HIDDEN_CHARACTER.finditer(line):
            errors.append(f"{rel}:{number}:{match.start() + 1}: invisible or bidirectional character "
                          f"U+{ord(match.group()):04X}")
        if not markdown:
            continue
        marker = FENCE.match(line)
        if marker and (not fence or (marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence)
                                     and not line.strip().strip(fence[0]))):
            fence = "" if fence else marker.group(1)
        elif not fence:
            for match in re.finditer("<!--", line):
                errors.append(f"{rel}:{number}:{match.start() + 1}: HTML comment in a Markdown instruction file")


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
    check_path_rules(errors)

    for agent in sorted((HOME / "agents").glob("*.md")):
        check_agent(agent, errors)

    org_cache: dict = {}
    for path, text in text_files():
        rel = path.relative_to(ROOT)
        if path.suffix == ".org":
            check_org_links(path, text, org_cache, errors)
        if instruction_file(path):
            check_hidden_text(rel, text, errors)
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
