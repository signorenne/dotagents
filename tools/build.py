#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Build the upload and share artifacts into dist/.

Usage: python3 tools/build.py

Produces:
- dist/claude-ai/<skill>.zip   one zip per skill, ready for claude.ai (Customize >
  Skills > Upload a skill): the claude-ai/ skill set plus the local skills listed in
  claude-ai/overrides.json, with their shorter claude.ai description;
- dist/claude-ai-skills.zip    all of the above in one archive;
- dist/project-kit.zip         the project templates, for setting up a repository by hand.

Zip entries get a fixed timestamp so rebuilding unchanged sources gives identical files.
"""

from __future__ import annotations

import json
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


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "claude-ai").mkdir(parents=True)

    overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))["skills"]
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
