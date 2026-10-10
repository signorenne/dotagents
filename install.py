#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Install dotagents for every coding agent found on this machine.

Installed source of truth: ~/.agents (AGENTS.md, skills/, agents/, hooks/). Edit the
repository, then run this script again to regenerate the per-tool copies.

  python3 install.py              install for the agents detected on this machine
  python3 install.py --dry-run    show what would change, change nothing
  python3 install.py --tools claude,codex,gemini,copilot,cursor   choose explicitly
  python3 install.py --audit      list what in the agents' folders does not come from
                                  this repository, and broken links; changes nothing

Every agent gets every skill from this repository. In Claude Code, the copies that
claude.ai syncs of the same skills are turned off, so each skill loads once, from here.

Every file this script replaces is moved to ~/.agents-backup/<timestamp>/ first.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

PACK = Path(__file__).resolve().parent
SRC = PACK / "home" / ".agents"
ONLINE = PACK / "claude-ai" / "skills"
CLAUDE_FRAGMENT = PACK / "adapters" / "claude" / "settings.json"
UPLOADED_EXTRA = PACK / "claude-ai" / "overrides.json"
SYNCED_PREFIX = "anthropic-skills:"
TOOLS = ("claude", "codex", "gemini", "copilot", "cursor")
HOOK_MARK = "/.agents/hooks/"
OLD_HOOK_MARKS = ("/.claude/hooks/guard_bash.py", "/.claude/hooks/after_edit.py")
OLD_PACK_SKILLS = {"learn": "Tutoring mode.", "handoff": "Close a session:"}
CLAUDE_MD = (
    "@~/.agents/AGENTS.md\n\n"
    "<!-- Global instructions live in ~/.agents/AGENTS.md, shared by every coding agent. "
    "Edit them there. -->\n"
)
GEMINI_TOOLS = {"Read": ["read_file"], "Grep": ["grep_search"],
                "Glob": ["glob", "list_directory"], "Bash": ["run_shell_command"],
                "Edit": ["replace"], "Write": ["write_file"]}
COPILOT_TOOLS = {"Read": "read", "Grep": "search", "Glob": "search",
                 "Bash": "execute", "Edit": "edit", "Write": "edit"}
CODEX_SANDBOX = {"scout": "read-only"}


def hook(cmd: str, **extra) -> dict:
    return {"type": "command", "command": cmd, **extra}


def script(name: str, tool: str) -> str:
    return f'python3 "$HOME/.agents/hooks/{name}" --tool {tool}'


CODEX_HOOKS = {
    "PreToolUse": [{"matcher": "Bash", "hooks": [hook(script("guard_bash.py", "codex"), timeout=10)]}],
    "PostToolUse": [{"matcher": "apply_patch|Edit|Write",
                     "hooks": [hook(script("after_edit.py", "codex"), timeout=60)]}],
}
GEMINI_HOOKS = {
    "BeforeTool": [{"matcher": "run_shell_command",
                    "hooks": [hook(script("guard_bash.py", "gemini"), name="agents-guard", timeout=10000)]}],
    "AfterTool": [{"matcher": "write_file|replace",
                   "hooks": [hook(script("after_edit.py", "gemini"), name="agents-after-edit", timeout=60000)]}],
}
COPILOT_HOOKS = {
    "version": 1,
    "hooks": {
        "PreToolUse": [{"type": "command", "matcher": "Bash", "timeoutSec": 10,
                        "bash": script("guard_bash.py", "copilot")}],
        "PostToolUse": [{"type": "command", "matcher": "Edit|Write", "timeoutSec": 60,
                         "bash": script("after_edit.py", "copilot")}],
    },
}


def parse_agent(text: str) -> tuple[dict, str]:
    """Parse the flat frontmatter of a canonical subagent file."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    head, body = text[4:].split("\n---\n", 1)
    meta = {}
    for line in head.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        meta[key.strip()] = json.loads(value) if value.startswith('"') else value
    return meta, body.lstrip("\n")


def tool_list(meta: dict) -> list[str]:
    return [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]


def gemini_agent(meta: dict, body: str) -> str:
    tools = []
    for tool in tool_list(meta):
        for name in GEMINI_TOOLS.get(tool, []):
            if name not in tools:
                tools.append(name)
    lines = ["---", f"name: {meta['name']}", f"description: {json.dumps(meta['description'])}",
             "kind: local"]
    if tools:
        lines.append("tools:")
        lines += [f"  - {t}" for t in tools]
    return "\n".join(lines + ["---", "", body])


def copilot_agent(meta: dict, body: str) -> str:
    tools = []
    for tool in tool_list(meta):
        alias = COPILOT_TOOLS.get(tool)
        if alias and alias not in tools:
            tools.append(alias)
    lines = ["---", f"name: {meta['name']}", f"description: {json.dumps(meta['description'])}"]
    if tools:
        lines.append(f"tools: {json.dumps(tools)}")
    return "\n".join(lines + ["---", "", body])


def codex_agent(meta: dict, body: str) -> str:
    if "'''" in body:
        raise ValueError(f"{meta['name']}: body contains ''' and cannot be a TOML literal string")
    lines = [f"name = {json.dumps(meta['name'])}",
             f"description = {json.dumps(meta['description'], ensure_ascii=False)}",
             f"sandbox_mode = {json.dumps(CODEX_SANDBOX.get(meta['name'], 'workspace-write'))}"]
    if meta.get("effort") in {"low", "medium", "high"}:
        lines.append(f"model_reasoning_effort = {json.dumps(meta['effort'])}")
    lines.append("developer_instructions = '''")
    lines.append(body.rstrip("\n"))
    lines.append("'''")
    return "\n".join(lines) + "\n"


def is_ours(command: str) -> bool:
    return HOOK_MARK in command or any(mark in command for mark in OLD_HOOK_MARKS)


def merge_event_hooks(existing: dict, ours: dict) -> dict:
    """Remove earlier copies of our hook entries, then append the current ones."""
    result = {}
    for event, entries in (existing or {}).items():
        kept = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            inner = entry.get("hooks")
            if isinstance(inner, list):
                filtered = [h for h in inner if not is_ours(str(h.get("command", "")))]
                if filtered:
                    kept.append({**entry, "hooks": filtered})
            elif not is_ours(str(entry.get("command", "")) + str(entry.get("bash", ""))):
                kept.append(entry)
        if kept:
            result[event] = kept
    for event, entries in ours.items():
        result.setdefault(event, []).extend(json.loads(json.dumps(entries)))
    return result


def merge_values(base, extra):
    """Add keys and list items from extra; existing scalar values win."""
    if isinstance(base, dict) and isinstance(extra, dict):
        for key, value in extra.items():
            base[key] = merge_values(base[key], value) if key in base else value
        return base
    if isinstance(base, list) and isinstance(extra, list):
        return base + [item for item in extra if item not in base]
    return base


class Installer:
    def __init__(self, home: Path, dry_run: bool):
        self.home = home
        self.dry = dry_run
        self.backup_root = home / ".agents-backup" / time.strftime("%Y%m%d-%H%M%S")
        self.agents_home = home / ".agents"
        self.changes = 0
        self.backups = 0
        self.notes = []

    def say(self, action: str, text: str) -> None:
        self.changes += action != "unchanged"
        print(f"{'(dry) ' if self.dry else ''}{action:10} {text}")

    def backup(self, path: Path) -> None:
        try:
            rel = path.relative_to(self.home)
        except ValueError:
            rel = Path(path.name)
        target = self.backup_root / rel
        if not self.dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        self.backups += 1
        self.say("backed up", f"{path} -> {target}")

    def write(self, path: Path, data, executable: bool = False) -> None:
        data = data.encode("utf-8") if isinstance(data, str) else data
        if path.is_symlink():
            self.backup(path)
        elif path.exists():
            if path.read_bytes() == data:
                if executable and not self.dry:
                    path.chmod(0o755)
                return
            self.backup(path)
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if executable:
                path.chmod(0o755)
        self.say("wrote", str(path))

    def link(self, path: Path, target: Path) -> None:
        if path.is_symlink() and os.readlink(path) == str(target):
            return
        if path.exists() or path.is_symlink():
            self.backup(path)
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        self.say("linked", f"{path} -> {target}")

    def merge_json(self, path: Path, mutate) -> None:
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                self.notes.append(f"Could not parse {path} ({error}); merge it by hand.")
                return
        else:
            old = {}
        new = mutate(json.loads(json.dumps(old)))
        if new != old:
            self.write(path, json.dumps(new, indent=2, ensure_ascii=False) + "\n")

    # Shared source --------------------------------------------------------

    def install_source(self) -> None:
        for src in sorted(SRC.rglob("*")):
            if src.is_dir() or "__pycache__" in src.parts or src.suffix == ".pyc":
                continue
            rel = src.relative_to(SRC)
            self.write(self.agents_home / rel, src.read_bytes(),
                       executable=rel.parts[0] == "hooks")
        if ONLINE.is_dir():
            for src in sorted(ONLINE.rglob("*")):
                if src.is_dir() or "__pycache__" in src.parts:
                    continue
                self.write(self.agents_home / "skills" / src.relative_to(ONLINE), src.read_bytes())
        # Files left in our own skill folders by an older version of the pack.
        for skill in [*(SRC / "skills").iterdir(), *(ONLINE.iterdir() if ONLINE.is_dir() else [])]:
            installed = self.agents_home / "skills" / skill.name
            if not installed.is_dir():
                continue
            for stale in sorted(installed.rglob("*")):
                if stale.is_file() and "__pycache__" not in stale.parts \
                        and not (skill / stale.relative_to(installed)).exists():
                    self.backup(stale)

    def subagents(self):
        for path in sorted((SRC / "agents").glob("*.md")):
            meta, body = parse_agent(path.read_text(encoding="utf-8"))
            yield path, meta, body

    def skills(self) -> list[str]:
        return sorted(p.name for p in (SRC / "skills").iterdir() if (p / "SKILL.md").is_file())

    def online_skills(self) -> list[str]:
        if not ONLINE.is_dir():
            return []
        return sorted(p.name for p in ONLINE.iterdir() if (p / "SKILL.md").is_file())

    def uploaded_skills(self) -> list[str]:
        """Skills of this repository that are also uploaded to claude.ai."""
        extra = []
        if UPLOADED_EXTRA.is_file():
            extra = list(json.loads(UPLOADED_EXTRA.read_text(encoding="utf-8"))["skills"])
        return sorted(set(self.online_skills()) | set(extra))

    # Per tool -------------------------------------------------------------

    def install_claude(self) -> None:
        base = self.home / ".claude"
        claude_md = base / "CLAUDE.md"
        if not (claude_md.exists() and "@~/.agents/AGENTS.md" in claude_md.read_text(encoding="utf-8")):
            self.write(claude_md, CLAUDE_MD)
        for name, marker in OLD_PACK_SKILLS.items():
            old = base / "skills" / name / "SKILL.md"
            if old.is_file() and not old.is_symlink() and marker in old.read_text(encoding="utf-8"):
                self.backup(old.parent)
        for name in self.skills() + self.online_skills():
            self.link(base / "skills" / name, self.agents_home / "skills" / name)
        for path, meta, body in self.subagents():
            self.write(base / "agents" / path.name, path.read_text(encoding="utf-8"))
        for old_hook in ("guard_bash.py", "after_edit.py"):
            if (base / "hooks" / old_hook).is_file():
                self.backup(base / "hooks" / old_hook)
        fragment = json.loads(CLAUDE_FRAGMENT.read_text(encoding="utf-8"))
        ours = fragment.pop("hooks")
        # Claude Code lists a synced claude.ai skill next to a local one of the same
        # name instead of replacing it; turn the synced copy off so the repository
        # copy is the only one. A value already set by hand wins (merge_values).
        fragment["skillOverrides"] = {SYNCED_PREFIX + name: "off" for name in self.uploaded_skills()}

        def mutate(settings: dict) -> dict:
            settings = merge_values(settings, fragment)
            settings["hooks"] = merge_event_hooks(settings.get("hooks"), ours)
            return settings
        self.merge_json(base / "settings.json", mutate)
        self.notes.append(
            "Claude Code: every skill comes from this repository; the copies synced from claude.ai "
            "of the same skills are turned off (skillOverrides in ~/.claude/settings.json).")

    def install_codex(self) -> None:
        base = self.home / ".codex"
        self.link(base / "AGENTS.md", self.agents_home / "AGENTS.md")
        for path, meta, body in self.subagents():
            self.write(base / "agents" / f"{meta['name']}.toml", codex_agent(meta, body))
        self.merge_json(base / "hooks.json", lambda s: {**s, "hooks": merge_event_hooks(s.get("hooks"), CODEX_HOOKS)})
        self.notes.append("Codex: review and trust ~/.codex/hooks.json when Codex asks; user hooks run only after review.")

    def install_gemini(self) -> None:
        base = self.home / ".gemini"
        self.link(base / "GEMINI.md", self.agents_home / "AGENTS.md")
        for path, meta, body in self.subagents():
            self.write(base / "agents" / f"{meta['name']}.md", gemini_agent(meta, body))

        def mutate(settings: dict) -> dict:
            settings["hooks"] = merge_event_hooks(settings.get("hooks"), GEMINI_HOOKS)
            context = settings.setdefault("context", {})
            names = context.get("fileName", ["GEMINI.md"])
            names = [names] if isinstance(names, str) else list(names)
            for name in ("AGENTS.md", "GEMINI.md"):
                if name not in names:
                    names.insert(0 if name == "AGENTS.md" else len(names), name)
            context["fileName"] = names
            return settings
        self.merge_json(base / "settings.json", mutate)

    def install_copilot(self) -> None:
        base = self.home / ".copilot"
        self.link(base / "copilot-instructions.md", self.agents_home / "AGENTS.md")
        for path, meta, body in self.subagents():
            self.write(base / "agents" / f"{meta['name']}.agent.md", copilot_agent(meta, body))
        self.write(base / "hooks" / "agents-global.json", json.dumps(COPILOT_HOOKS, indent=2) + "\n")

    def audit(self) -> int:
        """Print what the skill and agent folders hold that this repository does not manage."""
        skills = set(self.skills() + self.online_skills())
        agents = [meta["name"] for _, meta, _ in self.subagents()]
        hooks = {p.name for p in (SRC / "hooks").iterdir() if p.suffix == ".py"}
        folders = {
            self.agents_home / "skills": skills,
            self.agents_home / "agents": {f"{a}.md" for a in agents},
            self.agents_home / "hooks": hooks | {"__pycache__"},
            self.home / ".claude" / "skills": skills | {"synced", ".trash"},
            self.home / ".claude" / "agents": {f"{a}.md" for a in agents},
            self.home / ".codex" / "agents": {f"{a}.toml" for a in agents},
            self.home / ".gemini" / "agents": {f"{a}.md" for a in agents},
            self.home / ".copilot" / "agents": {f"{a}.agent.md" for a in agents},
        }
        foreign, broken = [], []
        for folder, managed in folders.items():
            if not folder.is_dir():
                continue
            for entry in sorted(folder.iterdir()):
                if entry.is_symlink() and not entry.exists():
                    broken.append(entry)
                elif entry.name not in managed:
                    foreign.append(entry)
        print("Not from dotagents (yours, another tool's, or left over; review each):")
        print("\n".join(f"  {p}" for p in foreign) or "  none")
        print("Broken links (safe to delete):")
        print("\n".join(f"  {p}" for p in broken) or "  none")
        return 0

    def install_cursor(self) -> None:
        self.notes.append(
            "Cursor: it reads ~/.agents/skills, ~/.claude/agents and the Claude Code hooks by itself. "
            "It has no global instructions file: paste ~/.agents/AGENTS.md into Settings > Rules > User Rules.")


def detect(home: Path) -> list[str]:
    probes = {
        "claude": (".claude", ["claude"]),
        "codex": (".codex", ["codex"]),
        "gemini": (".gemini", ["gemini"]),
        "copilot": (".copilot", ["copilot"]),
        "cursor": (".cursor", ["cursor-agent", "cursor"]),
    }
    found = []
    for tool, (folder, binaries) in probes.items():
        if (home / folder).is_dir() or any(shutil.which(b) for b in binaries):
            found.append(tool)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tools", help="comma-separated subset of: " + ",".join(TOOLS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--audit", action="store_true",
                        help="list unmanaged entries and broken links in the agents' folders; change nothing")
    args = parser.parse_args()

    home = Path(os.environ.get("HOME", "~")).expanduser()
    tools = [t.strip() for t in args.tools.split(",")] if args.tools else detect(home)
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        parser.error(f"unknown tools: {', '.join(unknown)}")

    installer = Installer(home, args.dry_run)
    if args.audit:
        return installer.audit()
    print(f"Agents: {', '.join(tools) or 'none detected (installing ~/.agents only)'}")
    installer.install_source()
    for tool in tools:
        getattr(installer, f"install_{tool}")()

    backups = f" Replaced files saved in {installer.backup_root}" if installer.backups else ""
    print(f"\n{installer.changes} change(s).{backups}")
    for note in installer.notes:
        print(f"- {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
