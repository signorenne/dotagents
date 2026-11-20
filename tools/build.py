#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Build the upload and share artifacts into dist/.

Usage: python3 tools/build.py
       python3 tools/build.py --marketplace   write .claude-plugin/marketplace.json and packs/

Produces:
- dist/claude-ai/<skill>.zip   one zip per skill, ready for claude.ai (Customize >
  Skills > Upload a skill): the claude-ai/ skill set plus the local skills listed in
  claude-ai/overrides.json, with their shorter claude.ai description;
- dist/claude-ai-skills.zip    all of the above in one archive;
- dist/project-kit.zip         the project templates, for setting up a repository by hand.

Zip entries get a fixed timestamp so rebuilding unchanged sources gives identical files.

--marketplace writes the committed Claude Code marketplace and the packs/ folders, the
packs other people install as plugins (claude plugin marketplace add <this repository>,
then /plugin install dotagents-<pack>@dotagents). tools/validate.py fails when either
differs from what this script writes.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "home" / ".agents"
ONLINE = ROOT / "claude-ai" / "skills"
OVERRIDES = ROOT / "claude-ai" / "overrides.json"
TEMPLATES = HOME / "skills" / "project-setup" / "templates"
DIST = ROOT / "dist"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PACKS_DIR = ROOT / "packs"
CLAUDE_FRAGMENT = ROOT / "adapters" / "claude" / "settings.json"
PACK_VERSION = "1.0.0"
OWNER = {"name": "Nicolò Plebani"}
# Each pack is a Claude Code plugin rooted at packs/<pack>/, whose skills/, hooks and
# AGENTS.md are relative links into home/.agents and claude-ai/skills. Its
# .claude-plugin/plugin.json and the method pack's agents/*.md are real files generated
# here (pack_files) and checked by tools/validate.py: a pack loaded in place (claude plugin
# eval packs/<pack>, or a marketplace added from a local folder) resolves only with a
# manifest and reads no subagent through a link (claude plugin details: Agents (0)). An
# install from a git marketplace copies each link's target in (a clone served over HTTP
# on 14 November 2026: Skills (9), Agents (3), Hooks (6)). The hooks stay in the
# marketplace entry.
# Every local skill belongs to exactly one pack and every claude.ai skill to the chat pack
# (tools/validate.py checks it). The method pack also carries the subagents, the hooks and
# the global rules, which a session-start hook prints (Claude Code loads no CLAUDE.md from
# a plugin and caps that output at 10,000 characters).
# depends lists the packs whose subagents or skills a pack's skills call with no fallback
# in their text; the manifest names them as dependencies (bare names, resolved in this
# marketplace), so installing the pack brings them. claude plugin validate checks only the
# form of that list, so tools/validate.py checks that each names another pack here.
PACKS = {
    "method": {
        "description": "The dotagents method: build in lanes from one plan file, design, close, decide, "
                       "review and gates, with the scout, reviewer and gate-runner subagents, the guard "
                       "and session hooks, and the global rules.",
        "skills": ["build", "design", "close", "decide", "branch-review", "gates", "isolated-work",
                   "parallel-agents", "mechanical-changes"],
        "agents": True, "hooks": True},
    "craft": {
        "description": "Craft skills: clean architecture, event-driven UIs, Qt Quick, precise UI changes, "
                       "code audits and notes from work.",
        "skills": ["clean-architecture", "event-driven-ui", "qt-quick", "precise-ui-changes", "code-audit",
                   "notes-from-work"],
        "depends": ["method"]},
    "docs": {
        "description": "Documentation skills: as-built docs, requirements and architecture, project setup "
                       "for agents, and PlantUML diagrams.",
        "skills": ["as-built-docs", "architecture-doc", "project-setup", "plantuml-diagrams"],
        "depends": ["method", "craft"]},
    "chat": {
        "description": "The skills that also run in chat: debugging, tests that can fail, verification, "
                       "research, decisions, prompts, notes, tutoring and handoffs.",
        "skills": "claude-ai"},
}


def add(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def files_of(folder: Path):
    for path in sorted(folder.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def with_description(skill_md: str, description: str) -> str:
    head, body = skill_md[4:].split("\n---\n", 1)
    lines = [f"description: {json.dumps(description, ensure_ascii=False)}"
             if line.startswith("description:") else line
             for line in head.splitlines()]
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def build_skill_zip(folder: Path, out: Path, description: str | None = None) -> None:
    with zipfile.ZipFile(out, "w") as archive:
        for path in files_of(folder):
            data = path.read_bytes()
            if description and path.name == "SKILL.md":
                data = with_description(data.decode("utf-8"), description).encode("utf-8")
            add(archive, f"{folder.name}/{path.relative_to(folder)}", data)


def pack_links() -> dict:
    """{link path relative to the repository: its relative target} for every pack."""
    links = {}
    for name, pack in PACKS.items():
        folder = f"packs/{name}"
        if pack["skills"] == "claude-ai":
            for skill in sorted(p.name for p in ONLINE.iterdir() if (p / "SKILL.md").is_file()):
                links[f"{folder}/skills/{skill}"] = f"../../../claude-ai/skills/{skill}"
        else:
            for skill in pack["skills"]:
                links[f"{folder}/skills/{skill}"] = f"../../../home/.agents/skills/{skill}"
        if pack.get("hooks"):
            links[f"{folder}/hooks"] = "../../home/.agents/hooks"
            links[f"{folder}/AGENTS.md"] = "../../home/.agents/AGENTS.md"
    return links


def pack_hooks() -> dict:
    """Claude Code's hooks from the shared fragment, pointed at the pack's hooks link, after a
    session-start hook that prints the global rules."""
    events = json.loads(CLAUDE_FRAGMENT.read_text(encoding="utf-8"))["hooks"]
    events = json.loads(json.dumps(events).replace("$HOME/.agents/hooks/", "${CLAUDE_PLUGIN_ROOT}/hooks/"))
    rules = {"matcher": "startup|clear|compact", "hooks": [
        {"type": "command", "command": 'cat "${CLAUDE_PLUGIN_ROOT}/AGENTS.md"', "timeout": 10}]}
    events["SessionStart"] = [rules] + events.get("SessionStart", [])
    return events


def marketplace() -> dict:
    plugins = []
    for name, pack in PACKS.items():
        entry = {"name": f"dotagents-{name}", "source": f"./packs/{name}", "description": pack["description"],
                 "version": PACK_VERSION, "license": "MIT"}
        if pack.get("hooks"):
            entry["hooks"] = pack_hooks()
        plugins.append(entry)
    return {"name": "dotagents", "owner": OWNER,
            "description": "A cross-agent method and skill set: plan files, lanes, reviews that can fail, "
                           "and craft, docs and chat skills.",
            "plugins": plugins}


def marketplace_text() -> str:
    return json.dumps(marketplace(), indent=2, ensure_ascii=False) + "\n"


GENERATED = ("*/.claude-plugin/plugin.json", "*/agents/*.md")


def pack_files() -> dict:
    """{generated file path relative to the repository: its text}: each pack's manifest, and
    a copy of each subagent in a pack that carries them."""
    files = {}
    for name, pack in PACKS.items():
        manifest = {"name": f"dotagents-{name}", "description": pack["description"], "version": PACK_VERSION,
                    "author": OWNER}
        if pack.get("depends"):
            manifest["dependencies"] = [f"dotagents-{other}" for other in pack["depends"]]
        files[f"packs/{name}/.claude-plugin/plugin.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        if pack.get("agents"):
            for agent in sorted((HOME / "agents").glob("*.md")):
                files[f"packs/{name}/agents/{agent.name}"] = agent.read_text(encoding="utf-8")
    return files


def stray_pack_files(files: dict) -> list:
    """Real files in a generated place of packs/ that pack_files() does not name."""
    if not PACKS_DIR.is_dir():
        return []
    found = {path for pattern in GENERATED for path in PACKS_DIR.glob(pattern) if not path.is_symlink()}
    return sorted(path for path in found if path.relative_to(ROOT).as_posix() not in files)


def write_packs() -> None:
    """Write the marketplace and make packs/ hold exactly the links pack_links() names and
    the files pack_files() names."""
    MARKETPLACE.parent.mkdir(exist_ok=True)
    MARKETPLACE.write_text(marketplace_text(), encoding="utf-8")
    wanted = pack_links()
    files = pack_files()
    for path in stray_pack_files(files):
        path.unlink()
    if PACKS_DIR.is_dir():
        for path in sorted(PACKS_DIR.rglob("*"), reverse=True):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_symlink() and wanted.get(rel) != os.readlink(path):
                path.unlink()
            elif path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
    for rel, target in sorted(wanted.items()):
        link = ROOT / rel
        if not link.is_symlink():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
    for rel, text in sorted(files.items()):
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    if "--marketplace" in (sys.argv[1:] if argv is None else argv):
        write_packs()
        print(f"wrote {MARKETPLACE.relative_to(ROOT)}, and the links and generated files in {PACKS_DIR.relative_to(ROOT)}/")
        return 0
    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))["skills"]
    for name, override in sorted(overrides.items()):
        description = override.get("description") if isinstance(override, dict) else None
        if not isinstance(description, str) or not description.strip():
            print(f"claude-ai/overrides.json: {name} has no claude.ai description; "
                  "python3 tools/validate.py lists every problem", file=sys.stderr)
            return 1

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "claude-ai").mkdir(parents=True)

    built = []
    for folder in sorted(p for p in ONLINE.iterdir() if (p / "SKILL.md").is_file()):
        out = DIST / "claude-ai" / f"{folder.name}.zip"
        build_skill_zip(folder, out)
        built.append(out)
    for name, override in sorted(overrides.items()):
        out = DIST / "claude-ai" / f"{name}.zip"
        build_skill_zip(HOME / "skills" / name, out, override["description"])
        built.append(out)

    with zipfile.ZipFile(DIST / "claude-ai-skills.zip", "w") as bundle:
        for out in sorted(built):
            add(bundle, f"claude-ai-skills/{out.name}", out.read_bytes())
        add(bundle, "claude-ai-skills/README.md", (ROOT / "claude-ai" / "README.md").read_bytes())

    with zipfile.ZipFile(DIST / "project-kit.zip", "w") as kit:
        for path in files_of(TEMPLATES):
            add(kit, f"project-kit/{path.relative_to(TEMPLATES)}", path.read_bytes())
        add(kit, "project-kit/LICENSE", (ROOT / "LICENSE").read_bytes())

    for path in sorted(DIST.rglob("*.zip")):
        print(f"built {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
