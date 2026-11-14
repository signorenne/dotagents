#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
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
- no text file of the dash check holds a character a reader does not see but a model
  reads: zero width (U+200B to U+200D, U+2060), bidirectional controls (U+061C, U+200E,
  U+200F, U+202A to U+202E, U+2066 to U+2069), U+FEFF anywhere (a byte order mark too:
  the files are plain UTF-8), the soft hyphen U+00AD, the invisible operators U+2061 to
  U+2064, the Hangul filler U+3164, the variation selectors U+FE00 to U+FE0F and U+E0100
  to U+E01EF, and the tags U+E0000 to U+E007F, except an emoji's own parts (U+FE0E or
  U+FE0F right after a pictographic character, U+200D between two; tag sequences such as
  subdivision flags are reported);
- the Markdown files (.md, .md.template) agents load as instructions
  (home/.agents/AGENTS.md, those of a skill in either root, the subagents, and the
  repository's AGENTS.md, CLAUDE.md, GEMINI.md and .github/copilot-instructions.md) hold
  no HTML comment outside code (it hides text from a reader of the rendered file, not
  from the model): code is a fenced block, indented 0 to 3 columns from its container
  (the margin, a blockquote, a list item), closed only by its own character at least as
  many times or by a line that leaves the container, or a code span on one line not
  opened by an escaped backtick; a code span over several lines and an indented code
  block are not recognised, so a <!-- in them is reported;
- the global instructions stay under 200 lines;
- every Python file compiles;
- every Org link in an Org file resolves: [[file:path]] names an existing file
  (relative to the linking file; ~ and absolute paths are not checked), ::#id and #id
  a CUSTOM_ID of the target file, ::*Heading and *Heading one of its headings (title
  without tags, any run of spaces as one); links in src and example blocks or in
  =verbatim= and ~code~ spans, web links and other searches are not checked.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import unicodedata
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
# The Claude Code pack injects the global rules through a SessionStart hook, whose output
# Claude Code caps at 10,000 characters (over it the model sees a 2,000-character preview).
GLOBAL_RULES_LIMIT = 9500
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
# Files and folders agents load as instructions (their Markdown files hold no HTML comment),
# and the characters a reader does not see but a model reads, reported in every text file
# (the context-file scan of Hermes Agent, widened beyond the instruction files).
INSTRUCTION_FILES = {HOME / "AGENTS.md", PATH_RULES, OVERRIDES, ROOT / "AGENTS.md", ROOT / "CLAUDE.md",
                     ROOT / "GEMINI.md", ROOT / ".github" / "copilot-instructions.md"}
INSTRUCTION_FOLDERS = (HOME / "skills", ONLINE, HOME / "agents")
HIDDEN_CHARACTER = re.compile("[\u00ad\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\u3164"
                              "\ufe00-\ufe0f\ufeff\U000e0000-\U000e007f\U000e0100-\U000e01ef]")
# An emoji's own parts: a presentation selector right after a pictographic character, and
# the zero width joiner between two (after a selector or a skin tone too).
PRESENTATION_SELECTORS = "\ufe0e\ufe0f"
ZERO_WIDTH_JOINER = "\u200d"
MARKDOWN_SUFFIXES = (".md", ".md.template")
# Markdown containers and code (CommonMark): a blockquote marker, a list item marker, a
# fence run with what follows it, and a code span on one line (a run of backticks not
# escaped by a backslash, its text, and a run of the same length).
QUOTE_MARKER = re.compile(r"[ ]{0,3}>[ ]?")
LIST_MARKER = re.compile(r"([-*+]|\d{1,9}[.)])([ \t]+|$)")
FENCE_RUN = re.compile(r"(`{3,}|~{3,})(.*)$")
CODE_SPAN = re.compile(r"(?<![\\`])(`+)(?!`).+?(?<!`)\1(?!`)")


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


def pictographic(char: str) -> bool:
    """A symbol such as an emoji: Unicode category So, or the planes of emoji, skin tones
    included (a standard-library stand-in for the Extended_Pictographic property)."""
    return unicodedata.category(char) == "So" or 0x1F000 <= ord(char) <= 0x1FFFF


def emoji_part(line: str, index: int) -> bool:
    """True for a presentation selector right after a pictographic character, or a zero
    width joiner between two (the one before it may carry its selector)."""
    char, before = line[index], line[index - 1] if index else ""
    if char in PRESENTATION_SELECTORS:
        return bool(before) and pictographic(before)
    if char != ZERO_WIDTH_JOINER or index + 1 >= len(line) or not before:
        return False
    if before in PRESENTATION_SELECTORS and index >= 2:
        before = line[index - 2]
    return pictographic(before) and pictographic(line[index + 1])


def check_hidden_characters(rel: Path, text: str, errors: list) -> None:
    """Report each hidden character with its line, column and code point."""
    for number, line in enumerate(text.split("\n"), start=1):
        for match in HIDDEN_CHARACTER.finditer(line):
            if emoji_part(line, match.start()):
                continue
            errors.append(f"{rel}:{number}:{match.start() + 1}: invisible or bidirectional character "
                          f"U+{ord(match.group()):04X}")


def strip_quotes(line: str, most: int = -1) -> tuple:
    """(how many blockquote markers open the line, at most most when given; the rest)."""
    depth = 0
    while depth != most and (marker := QUOTE_MARKER.match(line)):
        depth, line = depth + 1, line[marker.end():]
    return depth, line


def indentation(text: str) -> tuple:
    """(the column where the text after its leading blanks starts, that text); a tab moves
    to the next multiple of 4."""
    column = 0
    for index, char in enumerate(text):
        if char not in " \t":
            return column, text[index:]
        column += 1 if char == " " else 4 - column % 4
    return column, ""


def opening_fence(text: str) -> str:
    """The fence run a line opens, or "": a backtick run followed by text that holds a
    backtick is a code span (```a```), not a fence."""
    match = FENCE_RUN.match(text)
    return "" if not match or (match.group(1)[0] == "`" and "`" in match.group(2)) else match.group(1)


def check_html_comments(rel: Path, text: str, errors: list) -> None:
    """Report each <!-- outside code. A fence counts when it is indented 0 to 3 columns from
    its container (the margin, a blockquote, a list item's content, which starts after the
    blanks that follow the marker, or one column after it when 5 or more follow); it ends with a closing
    run of its character, at least as long and with nothing after it, or when a line leaves
    the container (fewer > markers, or less indentation than the item on a line that is
    not blank). Code spans on one line are skipped."""
    fence, fence_quotes, fence_column = "", 0, 0
    items, quotes = [], 0  # content columns of the open list items, outside fences
    for number, line in enumerate(text.split("\n"), start=1):
        if fence:
            depth, body = strip_quotes(line, fence_quotes)
            column, rest = indentation(body)
            if depth == fence_quotes and not (rest and column < fence_column):
                closing = FENCE_RUN.match(rest)
                if (closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence)
                        and not closing.group(2).strip() and column - fence_column <= 3):
                    fence = ""
                continue
            fence = ""  # the line left the fence's container; read it as text
        depth, body = strip_quotes(line)
        if depth != quotes:
            items, quotes = [], depth
        column, rest = indentation(body)
        while rest and items and column < items[-1]:
            items.pop()
        container = items[-1] if items else 0
        item = LIST_MARKER.match(rest) if rest and column - container <= 3 else None
        if item:
            # 1 to 4 blanks after the marker: the content starts after them; 5 or more: one
            # column after the marker, and the text after the blanks is indented code.
            gap = len(item.group(2).expandtabs(4))
            container = column + len(item.group(1)) + (gap if 1 <= gap <= 4 else 1)
            items.append(container)
            column, rest = column + len(item.group(1)) + gap, rest[item.end():]
        if column - container <= 3 and (run := opening_fence(rest)):
            fence, fence_quotes, fence_column = run, depth, container
            continue
        shown = CODE_SPAN.sub(lambda span: " " * len(span.group(0)), line)
        for match in re.finditer("<!--", shown):
            errors.append(f"{rel}:{number}:{match.start() + 1}: HTML comment in a Markdown instruction file")


def check_marketplace(errors: list) -> None:
    """The committed Claude Code marketplace and each pack's links and generated files are what
    tools/build.py writes, every path in it exists, and every skill sits in exactly one pack."""
    spec = importlib.util.spec_from_file_location("dotagents_build", ROOT / "tools" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    rel = build.MARKETPLACE.relative_to(ROOT)
    if not build.MARKETPLACE.is_file() or build.MARKETPLACE.read_text(encoding="utf-8") != build.marketplace_text():
        errors.append(f"{rel}: missing or out of date; run python3 tools/build.py --marketplace")
    wanted = build.pack_links()
    for link, target in sorted(wanted.items()):
        path = ROOT / link
        if not (path.is_symlink() and os.readlink(path) == target and path.exists()):
            errors.append(f"{link}: not a link to {target}; run python3 tools/build.py --marketplace")
    if build.PACKS_DIR.is_dir():
        for path in sorted(build.PACKS_DIR.rglob("*")):
            if path.is_symlink() and path.relative_to(ROOT).as_posix() not in wanted:
                errors.append(f"{path.relative_to(ROOT)}: a link no pack names; run python3 tools/build.py "
                              "--marketplace")
    files = build.pack_files()
    for rel_path, text in sorted(files.items()):
        path = ROOT / rel_path
        if path.is_symlink() or not path.is_file() or path.read_text(encoding="utf-8") != text:
            errors.append(f"{rel_path}: missing or out of date; run python3 tools/build.py --marketplace")
    for path in build.stray_pack_files(files):
        errors.append(f"{path.relative_to(ROOT)}: a generated file no pack names; run python3 tools/build.py "
                      "--marketplace")
    packed = [Path(link).name for link in wanted if "/skills/" in link]
    for folder in skill_folders(HOME / "skills") + skill_folders(ONLINE):
        count = packed.count(folder.name)
        if count != 1:
            errors.append(f"{folder.relative_to(ROOT)}: in {count} packs of tools/build.py (PACKS), not one")


# claude plugin eval (code.claude.com/docs/en/plugin-evals): an unknown key in a case's
# prompt.md is an error, a case needs a grader, and these are the grader types.
EVAL_CASE_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
                  "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}
GRADER_TYPES = {"regex", "tool_used", "tool_order", "file_exists", "llm", "baseline"}


def simple_frontmatter(text: str) -> tuple:
    """({key: raw value}, body) of a "---" block of key: value lines."""
    if not text.startswith("---\n") or "\n---\n" not in text[4:] + "\n":
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith(" "):
            value = value.strip()
            meta[key.strip()] = value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"" else value
    return meta, body


def check_evals(errors: list) -> None:
    """Each eval case under packs/<pack>/evals/ loads as claude plugin eval documents it, and a
    Skill grader names a skill of its pack: a check that runs no model."""
    for case in sorted(ROOT.glob("packs/*/evals/*")):
        if not case.is_dir() or case.name == "results":
            continue
        rel = case.relative_to(ROOT)
        skills = {p.name for p in (case.parent.parent / "skills").iterdir()} if (case.parent.parent / "skills").is_dir() else set()
        prompt = case / "prompt.md"
        if not prompt.is_file():
            if not (case / "case.yaml").is_file():  # the other documented form, which this check does not parse
                errors.append(f"{rel}: no prompt.md or case.yaml")
            continue
        text = prompt.read_text(encoding="utf-8")
        meta, body = simple_frontmatter(text)
        # allowed_tools as a flow list or a block list: the text up to the next top-level key.
        tools = re.search(r"^allowed_tools:(.*?)(?=^(?!- )\S|^---)", text, re.M | re.S)
        meta["allowed_tools"] = tools.group(1) if tools else ""
        for key in sorted(set(meta) - EVAL_CASE_KEYS):
            errors.append(f"{rel}/prompt.md: unknown key {key!r}")
        if not body.strip():
            errors.append(f"{rel}/prompt.md: no prompt")
        graders = sorted((case / "graders").glob("*.md"))
        if not graders:
            errors.append(f"{rel}: no grader")
        for grader in graders:
            g, _ = simple_frontmatter(grader.read_text(encoding="utf-8"))
            name = grader.relative_to(ROOT)
            if g.get("type") not in GRADER_TYPES:
                errors.append(f"{name}: type {g.get('type')!r} is not a grader type")
            if g.get("arm") not in (None, "with-only", "both"):
                errors.append(f"{name}: arm {g.get('arm')!r}")
            if g.get("type") != "tool_used" or g.get("tool") != "Skill":
                continue
            if "Skill" not in meta.get("allowed_tools", ""):
                errors.append(f"{rel}/prompt.md: a Skill grader needs Skill in allowed_tools")
            pattern = g.get("input_match", "")
            try:
                re.compile(pattern)
            except re.error as error:
                errors.append(f"{name}: input_match {error}")
            found = re.search(r"\)\?([\w-]+)", pattern)
            if not found or found.group(1) not in skills:
                errors.append(f"{name}: names no skill of its pack")
            if g.get("max") == "0" and g.get("arm") != "both":
                errors.append(f"{name}: a must-not-fire check needs arm: both, or a two-arm run leaves it out")


SIZE_BASELINE = ROOT / "tools" / "size-baseline.json"
SIZE_GROWTH = 0.10  # a file may grow this share over its baseline before it fails


def sized_files() -> list:
    """The instruction files whose size is held to a baseline: the global rules, every
    SKILL.md and every subagent."""
    files = [HOME / "AGENTS.md"]
    for root in (HOME / "skills", ONLINE):
        files += [folder / "SKILL.md" for folder in skill_folders(root) if (folder / "SKILL.md").is_file()]
    return files + sorted((HOME / "agents").glob("*.md"))


def sizes() -> dict:
    return {path.relative_to(ROOT).as_posix(): len(path.read_bytes()) for path in sized_files()}


def check_sizes(errors: list) -> None:
    """Each instruction file stays within SIZE_GROWTH of its recorded size, so growth is a
    choice made in a commit (python3 tools/validate.py --write-sizes), never drift."""
    try:
        baseline = json.loads(SIZE_BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        errors.append("tools/size-baseline.json: missing or unreadable; run python3 tools/validate.py --write-sizes")
        return
    current = sizes()
    for name, size in sorted(current.items()):
        if name not in baseline:
            errors.append(f"{name}: no size baseline; run python3 tools/validate.py --write-sizes")
        elif size > baseline[name] * (1 + SIZE_GROWTH):
            errors.append(f"{name}: {size} bytes, more than {round(SIZE_GROWTH * 100)}% over its baseline of "
                          f"{baseline[name]}; cut it, or record the new size with --write-sizes in the same commit")
    for name in sorted(set(baseline) - set(current)):
        errors.append(f"tools/size-baseline.json: {name} no longer exists; run python3 tools/validate.py --write-sizes")


def main() -> int:
    if "--write-sizes" in sys.argv[1:]:
        SIZE_BASELINE.write_text(json.dumps(sizes(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {SIZE_BASELINE.relative_to(ROOT)}")
        return 0
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
    check_marketplace(errors)
    check_evals(errors)
    check_sizes(errors)

    for agent in sorted((HOME / "agents").glob("*.md")):
        check_agent(agent, errors)

    org_cache: dict = {}
    for path, text in text_files():
        rel = path.relative_to(ROOT)
        if path.suffix == ".org":
            check_org_links(path, text, org_cache, errors)
        check_hidden_characters(rel, text, errors)
        if instruction_file(path) and path.name.endswith(MARKDOWN_SUFFIXES):
            check_html_comments(rel, text, errors)
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

    rules = (HOME / "AGENTS.md").read_text(encoding="utf-8")
    if len(rules) > GLOBAL_RULES_LIMIT:
        errors.append(f"home/.agents/AGENTS.md: {len(rules)} characters (limit {GLOBAL_RULES_LIMIT}: "
                      "the Claude Code pack injects it at session start)")

    for error in errors:
        print(f"FAIL {error}")
    print(f"{'FAILED' if errors else 'OK'}: {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
