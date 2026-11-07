#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Install dotagents for every coding agent found on this machine.

Installed source of truth: ~/.agents (AGENTS.md, skills/, agents/, hooks/). Edit the
repository, then run this script again to regenerate the per-tool copies.

  python3 install.py              install for the agents detected on this machine
  python3 install.py --dry-run    show what would change, change nothing
  python3 install.py --tools claude,codex,gemini,antigravity,copilot,cursor   choose explicitly
  python3 install.py --audit      list what in the agents' folders does not come from
                                  this repository, and broken links; changes nothing

Every agent gets every skill from this repository. In Claude Code, the copies that
claude.ai syncs of the same skills are turned off, so each skill loads once, from here.

Every file this script replaces is moved to ~/.agents-backup/<timestamp>/ first.
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

PACK = Path(__file__).resolve().parent
SRC = PACK / "home" / ".agents"
ONLINE = PACK / "claude-ai" / "skills"
CLAUDE_FRAGMENT = PACK / "adapters" / "claude" / "settings.json"
UPLOADED_EXTRA = PACK / "claude-ai" / "overrides.json"
# Path rules: {skill: [globs]}. In Claude Code each becomes ~/.claude/rules/dotagents-<skill>.md,
# a rule that loads only when Claude works with a matching file (paths globs, relative to
# the session's primary working directory) and points it to the skill.
PATH_RULES = SRC / "path-rules.json"
RULE_PREFIX = "dotagents-"
SYNCED_PREFIX = "anthropic-skills:"
TOOLS = ("claude", "codex", "gemini", "antigravity", "copilot", "cursor")
# Hook scripts this repository installs, and those an older version kept in ~/.claude/hooks.
OUR_HOOK_SCRIPTS = sorted(p.name for p in (SRC / "hooks").glob("*.py"))
OLD_HOOK_SCRIPTS = ("guard_bash.py", "after_edit.py")
OUR_HOOK = re.compile(r"(?:{})(?![\w.-])".format("|".join(
    [re.escape(f"/.agents/hooks/{name}") for name in OUR_HOOK_SCRIPTS]
    + [re.escape(f"/.claude/hooks/{name}") for name in OLD_HOOK_SCRIPTS])))
OLD_PACK_SKILLS = {"learn": "Tutoring mode.", "handoff": "Close a session:"}
# Skills this repository renamed or dropped (review became branch-review): an old copy
# would still load in every tool that reads ~/.agents/skills.
RETIRED_SKILLS = ("review",)
OUR_LICENSE = "Nicolò Plebani (nexenne"  # matches "(nexenne)" before 7 November 2026 and "(nexenne, signorenne)" since
CLAUDE_IMPORT = "@~/.agents/AGENTS.md"
CLAUDE_MD = (
    f"{CLAUDE_IMPORT}\n\n"
    "<!-- Global instructions shared by every coding agent. install.py overwrites "
    "~/.agents/AGENTS.md: edit home/.agents/AGENTS.md in the dotagents repository, "
    "then run install.py again. -->\n"
)
# What an older install.py wrote, replaced because it said to edit ~/.agents/AGENTS.md.
OLD_CLAUDE_MD = (
    f"{CLAUDE_IMPORT}\n\n"
    "<!-- Global instructions live in ~/.agents/AGENTS.md, shared by every coding agent. "
    "Edit them there. -->\n"
)
GEMINI_TOOLS = {"Read": ["read_file"], "Grep": ["grep_search"],
                "Glob": ["glob", "list_directory"], "Bash": ["run_shell_command"],
                "Edit": ["replace"], "Write": ["write_file"]}
COPILOT_TOOLS = {"Read": "read", "Grep": "search", "Glob": "search",
                 "Bash": "execute", "Edit": "edit", "Write": "edit"}
CODEX_SANDBOX = {"scout": "read-only"}
# Gemini CLI stops a subagent after 30 turns or 10 minutes unless its file sets max_turns
# and timeout_mins (docs/core/subagents.md). max_turns comes from the source's maxTurns,
# the one turn limit (Claude Code's); timeout_mins per subagent is here. Builds and test
# suites make the gate-runner the longest. Codex and Copilot CLI agents have no turn limit.
GEMINI_TIMEOUTS = {"gate-runner": 120, "reviewer": 60, "scout": 30}
GEMINI_DEFAULT_TIMEOUT = 30
GEMINI_DEFAULT_TURNS = 80


def hook(cmd: str, **extra) -> dict:
    return {"type": "command", "command": cmd, **extra}


def script(name: str, tool: str) -> str:
    return f'python3 "$HOME/.agents/hooks/{name}" --tool {tool}'


# Codex runs SessionStart with matcher on the source (startup, resume, clear, compact,
# fork) and adds plain stdout as developer context, as Claude Code does.
CODEX_HOOKS = {
    "PreToolUse": [{"matcher": "Bash", "hooks": [hook(script("guard_bash.py", "codex"), timeout=10)]}],
    "PostToolUse": [{"matcher": "apply_patch|Edit|Write",
                     "hooks": [hook(script("after_edit.py", "codex"), timeout=60)]}],
    "SessionStart": [{"matcher": "compact|resume",
                      "hooks": [hook('python3 "$HOME/.agents/hooks/session_refresh.py"', timeout=10)]}],
    # Stop reads stop_hook_active and takes {"decision": "block", "reason"} on exit 0, as in
    # Claude Code; exit 2 also continues, so a missing script must not pass python3's 2 on.
    "Stop": [{"hooks": [hook('python3 "$HOME/.agents/hooks/progress_check.py" || true', timeout=10)]}],
}
GEMINI_HOOKS = {
    "BeforeTool": [{"matcher": "run_shell_command",
                    "hooks": [hook(script("guard_bash.py", "gemini"), name="agents-guard", timeout=10000)]}],
    "AfterTool": [{"matcher": "write_file|replace",
                   "hooks": [hook(script("after_edit.py", "gemini"), name="agents-after-edit", timeout=60000)]}],
}
# Codex rules (experimental in Codex): a forbidden prefix_rule blocks a command that starts
# with its pattern, without prompting. They hold even while Codex skips the hooks, which
# it does until the user trusts them. A pattern part that is a list matches any of its words.
# git: each command that publishes (push, subtree push, send-pack, http-push, lfs push, svn
# dcommit, p4 submit, send-email). gh: the guard runs only read-only or local commands and
# a prefix cannot say "all but these", so the rules forbid every other command of gh
# 2.100.0's tree (gh help, aliases included), gh repo create and new whole, with or without
# --push. The read-only or local commands have no rule (view, list, diff, status
# and checks in any group, repo and gist clone, pr checkout, run watch and download,
# release download, config and variable get, repo read-file and read-dir, ruleset check,
# attestation verify, search, status, browse, completion, licenses, help), nor has gh api
# (not inspected). The gh commands that print the token have their own rules, as far as a
# prefix can say them: gh auth token and git-credential, gh auth status with -t or
# --show-token right after it, gh config get oauth_token without -h. The guard alone covers
# a gh command added later and the forms a prefix cannot see, such as a flag before the
# subcommand (gh -R o/r pr create) or before the token flag (gh auth status -a -t).
CODEX_RULES = (
    (["git", "push"], "git push publishes commits to a remote."),
    (["git", "subtree", "push"], "git subtree push publishes commits to a remote."),
    (["git", ["send-pack", "http-push"]], "git send-pack and git http-push publish commits to a remote."),
    (["git", "lfs", "push"], "git lfs push publishes objects to a remote."),
    (["git", "svn", "dcommit"], "git svn dcommit publishes commits to a Subversion repository."),
    (["git", "p4", "submit"], "git p4 submit publishes commits to a Perforce depot."),
    (["git", "send-email"], "git send-email sends patches by email."),
    *((["gh", groups if len(groups) > 1 else groups[0], *nested, subcommands],
       "Only read-only gh commands run (view, list, diff, status, checks, clone, search); this one is not.")
      for groups, nested, subcommands in (
          (["auth"], [], ["login", "logout", "refresh", "setup-git", "switch"]),
          (["codespace", "cs"], [], ["code", "cp", "create", "delete", "edit", "jupyter", "logs", "ports",
                                     "rebuild", "ssh", "stop"]),
          (["discussion"], [], ["comment", "create", "edit"]),
          (["gist"], [], ["create", "delete", "edit", "new", "rename"]),
          (["issue"], [], ["close", "comment", "create", "delete", "develop", "edit", "lock", "new", "pin",
                           "reopen", "transfer", "unlock", "unpin"]),
          (["pr"], [], ["close", "comment", "create", "edit", "lock", "merge", "new", "ready", "reopen", "revert",
                        "review", "unlock", "update-branch"]),
          (["project"], [], ["close", "copy", "create", "delete", "edit", "field-create", "field-delete",
                             "field-list", "item-add", "item-archive", "item-create", "item-delete", "item-edit",
                             "item-list", "link", "mark-template", "unlink"]),
          (["release"], [], ["create", "delete", "delete-asset", "edit", "new", "upload", "verify", "verify-asset"]),
          (["repo"], [], ["archive", "create", "delete", "edit", "fork", "new", "rename", "set-default", "sync",
                          "unarchive"]),
          (["repo"], ["autolink"], ["create", "delete"]),
          (["repo"], ["deploy-key"], ["add", "delete"]),
          (["skill", "skills"], [], ["add", "install", "preview", "publish", "search", "show", "update"]),
          (["cache"], [], ["delete"]),
          (["run"], [], ["cancel", "delete", "rerun"]),
          (["workflow"], [], ["disable", "enable", "run"]),
          (["agent-task", "agent-tasks", "agent", "agents"], [], ["create"]),
          (["alias"], [], ["delete", "import", "set"]),
          (["attestation", "at"], [], ["download", "trusted-root"]),
          (["config"], [], ["clear-cache", "set"]),
          (["extension", "extensions", "ext"], [], ["browse", "create", "exec", "install", "remove", "search",
                                                     "uninstall", "upgrade"]),
          (["gpg-key"], [], ["add", "delete"]),
          (["label"], [], ["clone", "create", "delete", "edit"]),
          (["secret"], [], ["delete", "remove", "set"]),
          (["ssh-key"], [], ["add", "delete"]),
          (["variable"], [], ["delete", "remove", "set"]))),
    (["gh", ["copilot", "preview"]],
     "Only read-only gh commands run (view, list, diff, status, checks, clone, search); this one is not."),
)
CODEX_RULES_ADVICE = ("Pushing and publishing are the maintainer's, who reviews every change before it "
                      "leaves this machine: stop and tell the user the work is ready for review.")
CODEX_TOKEN_RULES = (
    (["gh", "auth", ["token", "git-credential"]],
     "gh auth token (and gh auth git-credential get) prints the authentication token."),
    (["gh", "auth", "status", ["-t", "--show-token", "-at", "-ta", "-t=true", "--show-token=true"]],
     "gh auth status --show-token prints the authentication token."),
    (["gh", "config", "get", "oauth_token"], "gh config get oauth_token prints the authentication token."),
)
CODEX_TOKEN_ADVICE = ("A token printed here stays in this session's transcript: check the login with gh auth status "
                      "without -t, and ask the user to run any command that needs the token.")
# Antigravity CLI (agy), which replaced Gemini CLI for most users, reads global hooks from
# ~/.gemini/config/hooks.json: an object that maps a hook name to its events. PreToolUse
# and PostToolUse matchers are regexes on the tool name (run_command runs a shell command;
# write_to_file, replace_file_content and multi_replace_file_content edit files); timeout
# is in seconds. It has no event after a compaction or a resume, so no session refresh.
ANTIGRAVITY_HOOKS = {
    "dotagents-guard": {"PreToolUse": [{"matcher": "run_command", "hooks": [
        hook(script("guard_bash.py", "antigravity"), timeout=10)]}]},
    "dotagents-after-edit": {"PostToolUse": [{
        "matcher": "write_to_file|replace_file_content|multi_replace_file_content",
        "hooks": [hook(script("after_edit.py", "antigravity"), timeout=60)]}]},
}
# Copilot CLI's native format: camelCase events send toolName and toolArgs, and a
# matcher is a regex on the whole native tool name (GitHub's hooks reference).
COPILOT_HOOKS = {
    "version": 1,
    "hooks": {
        "preToolUse": [{"type": "command", "matcher": "bash", "timeoutSec": 10,
                        "bash": script("guard_bash.py", "copilot")}],
        "postToolUse": [{"type": "command", "matcher": "edit|create|str_replace_editor|apply_patch",
                         "timeoutSec": 60, "bash": script("after_edit.py", "copilot")}],
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
    turns = int(meta.get("maxTurns", GEMINI_DEFAULT_TURNS))
    if turns < 1:
        raise ValueError(f"maxTurns {meta['maxTurns']!r} is not a positive whole number")
    minutes = GEMINI_TIMEOUTS.get(meta["name"], GEMINI_DEFAULT_TIMEOUT)
    lines += [f"max_turns: {turns}", f"timeout_mins: {minutes}"]
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
        raise ValueError("body contains ''' and cannot be a TOML literal string")
    lines = [f"name = {json.dumps(meta['name'])}",
             f"description = {json.dumps(meta['description'], ensure_ascii=False)}",
             f"sandbox_mode = {json.dumps(CODEX_SANDBOX.get(meta['name'], 'workspace-write'))}"]
    if meta.get("effort") in {"low", "medium", "high"}:
        lines.append(f"model_reasoning_effort = {json.dumps(meta['effort'])}")
    lines.append("developer_instructions = '''")
    lines.append(body.rstrip("\n"))
    lines.append("'''")
    return "\n".join(lines) + "\n"


def codex_rules() -> str:
    """The Starlark rules file that forbids pushing and publishing, and printing the gh
    token, in Codex."""
    lines = ["# Written by dotagents install.py: change the dotagents repository and run it again.",
             "# No agent pushes or publishes (DESIGN.org, no-agent-push)."]
    for rules, advice in ((CODEX_RULES, CODEX_RULES_ADVICE), (CODEX_TOKEN_RULES, CODEX_TOKEN_ADVICE)):
        for pattern, reason in rules:
            lines += ["prefix_rule(",
                      f"    pattern = {json.dumps(pattern)},",
                      '    decision = "forbidden",',
                      f"    justification = {json.dumps(reason + ' ' + advice)},",
                      ")"]
    return "\n".join(lines) + "\n"


def path_rule(skill: str, globs: list) -> str:
    """A Claude Code rule file that sends work on files matching globs to a skill."""
    return "\n".join(["---", "paths:", *[f"  - {json.dumps(glob)}" for glob in globs], "---", "",
                      f"Use the {skill} skill for work on these files. If it is not in your skill list, "
                      f"read ~/.agents/skills/{skill}/SKILL.md and follow it.", ""])


def path_rules() -> dict:
    """The path rules of the repository, {} when it has none."""
    if not PATH_RULES.is_file():
        return {}
    return json.loads(PATH_RULES.read_text(encoding="utf-8"))["rules"]


def copilot_folder(home: Path) -> Path:
    """Copilot CLI's configuration folder: $COPILOT_HOME, which replaces the whole
    ~/.copilot path when it is set, else ~/.copilot."""
    value = os.environ.get("COPILOT_HOME")
    return Path(value).expanduser() if value else home / ".copilot"


def check_source() -> list:
    """Problems in the repository that would stop an install partway, found before it starts."""
    problems = []
    for path in sorted((SRC / "agents").glob("*.md")):
        try:
            meta, body = parse_agent(path.read_text(encoding="utf-8"))
            for render in (codex_agent, gemini_agent, copilot_agent):
                render(meta, body)
        except KeyError as error:
            problems.append(f"{path.relative_to(PACK)}: missing field {error}")
        except ValueError as error:
            problems.append(f"{path.relative_to(PACK)}: {error}")
    for path, key in ((CLAUDE_FRAGMENT, "hooks"), (UPLOADED_EXTRA, "skills"), (PATH_RULES, "rules")):
        if path != CLAUDE_FRAGMENT and not path.is_file():
            continue  # optional: no local skill is uploaded to claude.ai, no path rules
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            problems.append(f"{path.relative_to(PACK)}: {error}")
            continue
        if not (isinstance(data, dict) and isinstance(data.get(key), dict)):
            problems.append(f"{path.relative_to(PACK)}: no {key} object")
        elif path == PATH_RULES:
            for skill, globs in data[key].items():
                if not (isinstance(globs, list) and globs and all(isinstance(g, str) and g for g in globs)):
                    problems.append(f"{path.relative_to(PACK)}: {skill}: globs must be a non-empty list of text")
    return problems


def real_path(path: Path):
    """The path with every link resolved, or None for a link loop."""
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return None


class CannotMerge(ValueError):
    """A settings file holds a value that our entries cannot be merged into."""


def is_ours(hook) -> bool:
    return isinstance(hook, dict) and isinstance(hook.get("command"), str) \
        and bool(OUR_HOOK.search(hook["command"]))


def merge_event_hooks(existing, ours: dict) -> dict:
    """Remove earlier copies of our hook entries, then append the current ones.

    Everything else is kept unchanged; a value that cannot take our entries raises
    CannotMerge, so the caller leaves the file alone.
    """
    existing = existing or {}
    if not isinstance(existing, dict):
        raise CannotMerge("its hooks value is not an object")
    result = {}
    for event, entries in existing.items():
        if not isinstance(entries, list):
            if event in ours:
                raise CannotMerge(f"its {event} hooks are not a list")
            result[event] = entries
            continue
        kept = []
        for entry in entries:
            inner = entry.get("hooks") if isinstance(entry, dict) else None
            if isinstance(inner, list):
                filtered = [h for h in inner if not is_ours(h)]
                if filtered or not inner:  # drop an entry only when it held only ours
                    kept.append({**entry, "hooks": filtered})
            elif not is_ours(entry):
                kept.append(entry)
        if kept or not entries:
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
    def __init__(self, home: Path, dry_run: bool, tools=()):
        self.home = home
        self.dry = dry_run
        self.tools = tuple(tools)
        self.backup_root = home / ".agents-backup" / time.strftime("%Y%m%d-%H%M%S")
        self.agents_home = home / ".agents"
        self.copilot_home = copilot_folder(home)
        self.changes = 0
        self.backups = 0
        self.notes = []
        self.linked = set()  # (link, target) pairs done in this run, which a dry run cannot see on disk

    def say(self, action: str, text: str, change: bool = True) -> None:
        self.changes += change
        print(f"{'(dry) ' if self.dry else ''}{action:10} {text}")

    def backup(self, path: Path, replacing: bool = False) -> Path:
        """Move path to the backup folder; replacing: the caller writes path again and
        counts the change."""
        try:
            rel = path.relative_to(self.home)
        except ValueError:
            rel = Path(path.name)
        target = self.backup_root / rel
        if not self.dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        self.backups += 1
        self.say("backed up", f"{path} -> {target}", change=not replacing)
        return target

    def write(self, path: Path, data, executable: bool = False):
        """Write path, backing up what it replaces; return the backup path, if any."""
        data = data.encode("utf-8") if isinstance(data, str) else data
        saved = None
        if path.is_symlink():
            saved = self.backup(path, replacing=True)
        elif path.exists():
            if path.read_bytes() == data:
                if executable and not self.dry:
                    path.chmod(0o755)
                return None
            saved = self.backup(path, replacing=True)
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if executable:
                path.chmod(0o755)
        self.say("wrote", str(path))
        return saved

    def link(self, path: Path, target: Path) -> None:
        if (path, target) in self.linked or (path.is_symlink() and os.readlink(path) == str(target)):
            return
        self.linked.add((path, target))
        if real_path(path) is not None and real_path(path) == real_path(target):
            # Reached through a linked folder, path is the target itself: replacing it
            # would move the target away and leave a link to itself.
            self.notes.append(f"{path} resolves to {target}; left as it is.")
            return
        if path.exists() or path.is_symlink():
            self.backup(path, replacing=True)
        if not self.dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        self.say("linked", f"{path} -> {target}")

    def merge_json(self, path: Path, mutate) -> bool:
        """Merge our values into a JSON object file; False when it was left alone."""
        old = {}
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except ValueError as error:
                self.notes.append(f"Could not parse {path} ({error}); merge it by hand.")
                return False
        try:
            if not isinstance(old, dict):
                raise CannotMerge("it is not a JSON object")
            new = mutate(json.loads(json.dumps(old)))
        except CannotMerge as error:
            self.notes.append(f"Could not merge {path}: {error}; merge it by hand.")
            return False
        if new != old:
            self.write(path, json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        return True

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
        for name in RETIRED_SKILLS:
            installed = self.agents_home / "skills" / name
            skill_md = installed / "SKILL.md"
            if installed.is_dir() and not installed.is_symlink() and skill_md.is_file():
                text = skill_md.read_text(encoding="utf-8", errors="replace")
                if f"\nname: {name}\n" in text and OUR_LICENSE in text:
                    self.backup(installed)

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
        current = claude_md.read_text(encoding="utf-8", errors="replace") if claude_md.is_file() else ""
        if CLAUDE_IMPORT not in current or current == OLD_CLAUDE_MD:
            saved = self.write(claude_md, CLAUDE_MD)
            if saved and current != OLD_CLAUDE_MD:
                self.notes.append(f"Claude Code: replaced {claude_md}, which did not import "
                                  f"~/.agents/AGENTS.md; the old one {'would be' if self.dry else 'is'} in {saved}.")
        for name in RETIRED_SKILLS:
            retired = base / "skills" / name
            if retired.is_symlink() and os.readlink(retired) == str(self.agents_home / "skills" / name):
                self.backup(retired)
        for name, marker in OLD_PACK_SKILLS.items():
            old = base / "skills" / name / "SKILL.md"
            if old.is_file() and not old.is_symlink() and marker in old.read_text(encoding="utf-8"):
                self.backup(old.parent)
        skills, agents_home = base / "skills", real_path(self.agents_home)
        resolved = real_path(skills)
        if resolved and agents_home and (resolved == agents_home or agents_home in resolved.parents):
            self.notes.append(f"Claude Code: {skills} resolves to {resolved}, inside {self.agents_home}; "
                              "the skills were not linked into it.")
        else:
            for name in self.skills() + self.online_skills():
                self.link(skills / name, self.agents_home / "skills" / name)
        for path, meta, body in self.subagents():
            self.write(base / "agents" / path.name, path.read_text(encoding="utf-8"))
        self.install_path_rules(base / "rules")
        for old_hook in OLD_HOOK_SCRIPTS:
            if (base / "hooks" / old_hook).is_file():
                self.backup(base / "hooks" / old_hook)
        fragment = json.loads(CLAUDE_FRAGMENT.read_text(encoding="utf-8"))
        ours = fragment.pop("hooks")
        # Claude Code lists a synced claude.ai skill next to a local one of the same
        # name instead of replacing it; turn the synced copy off so the repository
        # copy is the only one. A value already set by hand wins (merge_values).
        fragment["skillOverrides"] = {SYNCED_PREFIX + name: "off" for name in self.uploaded_skills()}
        denied = fragment.get("permissions", {}).get("deny", [])

        def mutate(settings: dict) -> dict:
            settings = merge_values(settings, fragment)
            settings["hooks"] = merge_event_hooks(settings.get("hooks"), ours)
            # A rule this repository now denies leaves ask, where an older install put it.
            permissions = settings.get("permissions")
            if isinstance(permissions, dict) and isinstance(permissions.get("ask"), list):
                permissions["ask"] = [rule for rule in permissions["ask"] if rule not in denied]
            return settings
        if self.merge_json(base / "settings.json", mutate):
            self.notes.append(
                "Claude Code: every skill comes from this repository; the copies synced from claude.ai "
                "of the same skills are turned off (skillOverrides in ~/.claude/settings.json).")

    def path_rule_files(self) -> dict:
        return {f"{RULE_PREFIX}{skill}.md": path_rule(skill, globs) for skill, globs in path_rules().items()}

    def install_path_rules(self, rules: Path) -> None:
        """Write a rule per path rule; back up and remove our own (dotagents-*.md) rules that
        the repository no longer has. Every other file in the folder is the user's."""
        wanted = self.path_rule_files()
        for name, text in sorted(wanted.items()):
            self.write(rules / name, text)
        if rules.is_dir():
            for stale in sorted(rules.glob(f"{RULE_PREFIX}*.md")):
                if stale.name not in wanted and (stale.is_file() or stale.is_symlink()):
                    self.backup(stale)

    def install_codex(self) -> None:
        base = self.home / ".codex"
        self.link(base / "AGENTS.md", self.agents_home / "AGENTS.md")
        for path, meta, body in self.subagents():
            self.write(base / "agents" / f"{meta['name']}.toml", codex_agent(meta, body))
        self.merge_json(base / "hooks.json", lambda s: {**s, "hooks": merge_event_hooks(s.get("hooks"), CODEX_HOOKS)})
        # Codex writes default.rules itself (its allow list), so this file has its own name.
        self.write(base / "rules" / "dotagents.rules", codex_rules())
        self.notes.append("Codex: review and trust ~/.codex/hooks.json when Codex asks; user hooks run only after review.")

    def install_gemini(self) -> None:
        base = self.home / ".gemini"
        self.link(base / "GEMINI.md", self.agents_home / "AGENTS.md")
        for path, meta, body in self.subagents():
            self.write(base / "agents" / f"{meta['name']}.md", gemini_agent(meta, body))

        def mutate(settings: dict) -> dict:
            settings["hooks"] = merge_event_hooks(settings.get("hooks"), GEMINI_HOOKS)
            context = settings.setdefault("context", {})
            if not isinstance(context, dict):
                raise CannotMerge("its context value is not an object")
            names = context.get("fileName", ["GEMINI.md"])
            names = [names] if isinstance(names, str) else names
            if not isinstance(names, list):
                raise CannotMerge("its context.fileName is neither a name nor a list")
            names = list(names)
            for name in ("AGENTS.md", "GEMINI.md"):
                if name not in names:
                    names.insert(0 if name == "AGENTS.md" else len(names), name)
            context["fileName"] = names
            return settings
        self.merge_json(base / "settings.json", mutate)

    def install_antigravity(self) -> None:
        base = self.home / ".gemini"
        self.link(base / "GEMINI.md", self.agents_home / "AGENTS.md")

        def hooks(config: dict) -> dict:
            for name, events in ANTIGRAVITY_HOOKS.items():
                old = config.get(name)
                config[name] = json.loads(json.dumps(events))
                if isinstance(old, dict) and isinstance(old.get("enabled"), bool):
                    config[name]["enabled"] = old["enabled"]  # a hook turned off by hand stays off
            return config
        self.merge_json(base / "config" / "hooks.json", hooks)

        # A personal skills manifest adds a folder to the skills Antigravity loads; it does
        # not expand ~, so the path is absolute.
        skills = str(self.agents_home / "skills")

        def manifest(config: dict) -> dict:
            entries = config.setdefault("entries", [])
            if not isinstance(entries, list):
                raise CannotMerge("its entries value is not a list")
            if not any(isinstance(entry, dict) and entry.get("path") == skills for entry in entries):
                entries.append({"path": skills})
            return config
        self.merge_json(base / "config" / "skills.json", manifest)
        self.notes.append(
            "Antigravity CLI: check the hooks with /hooks. It documents no reply that reaches the agent "
            "after an edit, so dash reports stay in the hook's stderr there; it gets no session refresh "
            "and no subagents.")

    def install_copilot(self) -> None:
        base = self.copilot_home
        if not base.is_absolute():
            self.notes.append(f"Copilot CLI: skipped, because COPILOT_HOME ({base}) is a relative path; "
                              "set it to an absolute one and run install.py again.")
            return
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
            self.home / ".claude" / "rules": set(self.path_rule_files()),
            self.home / ".codex" / "agents": {f"{a}.toml" for a in agents},
            self.home / ".gemini" / "agents": {f"{a}.md" for a in agents},
            self.copilot_home / "agents": {f"{a}.agent.md" for a in agents},
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
        if "claude" in self.tools:
            reads = ("Cursor: it reads ~/.agents/skills, ~/.claude/agents and the Claude Code hooks by itself "
                     "(Settings > Agents > Third-Party Imports, on by default).")
        else:
            reads = ("Cursor: this run gave it no subagents and no hooks, because Cursor reads them "
                     "from Claude Code's ~/.claude/agents and ~/.claude/settings.json, which only "
                     "--tools claude writes (run install.py --tools claude,cursor to add them). "
                     "It reads ~/.agents/skills by itself.")
        self.notes.append(
            reads + " It has no global instructions file: paste ~/.agents/AGENTS.md into "
            "Settings > Rules > User Rules.")


def detect(home: Path) -> list[str]:
    probes = {
        "claude": (home / ".claude", ["claude"]),
        "codex": (home / ".codex", ["codex"]),
        "gemini": (home / ".gemini", ["gemini"]),
        "antigravity": (home / ".gemini" / "antigravity-cli", ["agy"]),
        "copilot": (copilot_folder(home), ["copilot"]),
        "cursor": (home / ".cursor", ["cursor-agent", "cursor"]),
    }
    found = []
    for tool, (folder, binaries) in probes.items():
        if folder.is_dir() or any(shutil.which(b) for b in binaries):
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
    if args.tools is None:
        tools = detect(home)
    else:
        tools = list(dict.fromkeys(t.strip() for t in args.tools.split(",") if t.strip()))
        if not tools:
            parser.error("--tools needs at least one of: " + ",".join(TOOLS))
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        parser.error(f"unknown tools: {', '.join(unknown)}")

    problems = check_source()
    if problems:
        print("Nothing installed: fix the repository first (python3 tools/validate.py checks it).",
              file=sys.stderr)
        print("\n".join(f"  {problem}" for problem in problems), file=sys.stderr)
        return 1

    installer = Installer(home, args.dry_run, tools)
    if args.audit:
        return installer.audit()
    print(f"Agents: {', '.join(tools) or 'none detected (installing ~/.agents only)'}")
    installer.install_source()
    for tool in tools:
        getattr(installer, f"install_{tool}")()

    saved = "would be saved" if args.dry_run else "saved"
    backups = f" Replaced files {saved} in {installer.backup_root}" if installer.backups else ""
    print(f"\n{installer.changes} change(s).{backups}")
    for note in installer.notes:
        print(f"- {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
