#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Where time and usage go in Claude Code sessions, measured from their transcripts.

  python3 tools/session_stats.py --since 2026-11-08 [--until 2026-11-21] [DIR ...]
  python3 tools/session_stats.py --since 2026-11-08 --json

DIR is a Claude Code project folder (~/.claude/projects/<name>); without one, every
folder under ~/.claude/projects. A session is <DIR>/<id>.jsonl, its subagents
<DIR>/<id>/subagents/agent-*.jsonl with their .meta.json (agentType, model, effort).
A session counts when its first record falls in [since, until]. The report holds
counts and durations only, never transcript text.

Time: each gap between consecutive timestamped records goes to one bucket, or to none
(away). While a tool call is pending: "human" when only AskUserQuestion calls are
pending (up to GAP seconds), else the kind of a pending Agent call ("agent:<kind>"),
else "tools", up to an hour, since a long build or review is work, not absence.
Otherwise, while the turn is open (from a prompt, a task notification or a model
request to an assistant message that ends the turn), and for a gap that ends at an
assistant message: "model", up to GAP (generation and hooks). While the turn is
closed: "agent:<kind>" when a background agent is still running (up to an hour; it
ends at the queue record or notification that names its tool-use id or agent id),
else "human" (reading and typing), up to GAP. Approval waits fall in
"tools": the transcript does not separate them.

Usage: each request (unique assistant message id) has input, cache write, cache read
and output tokens. Weighted usage prices them relative to input tokens with
Anthropic's ratios (cache write 1.25, cache read 0.1, output 5), so it compares cost
across sessions without a price list.

Question rounds: AskUserQuestion calls, plus prompts that answer an assistant text
ending with a question mark. Bookkeeping calls: tool calls that only write task notes
(.private/progress, .private/handoff, .private/plans), and shell commands made only of
read-only git commands, cd and text filters.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAP = 600
PENDING_LIMIT = 3600
WEIGHTS = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25,
           "cache_read_input_tokens": 0.1, "output_tokens": 5.0}
NOTE_PATH = re.compile(r"/\.private/(progress|handoff|plans)/")
GIT_READ = re.compile(r"^git( -C \S+)?( --no-pager| --no-optional-locks)* (status|log|diff|show|rev-parse"
                      r"|merge-base|branch( --show-current| -a| -v| -vv| --list)?$|worktree list)\b")
FILTER = re.compile(r"^(cd \S+|head|tail|wc|sort|uniq|cut|grep)\b")
SEPARATOR = re.compile(r"&&|\|\||;|\|")
METHOD_AGENTS = {"scout", "reviewer", "gate-runner"}
NOTICE = "<task-notification>"


def timestamp(text):
    try:
        value = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def records(path: Path):
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def content_list(record: dict) -> list:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []


def is_prompt(record: dict) -> bool:
    """A message the user typed: not a tool result, a command wrapper, a summary or a meta record."""
    if record.get("type") != "user" or record.get("isMeta") or record.get("isCompactSummary") \
            or record.get("isSidechain"):
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return bool(content.strip()) and not content.lstrip().startswith("<") and NOTICE not in content
    if isinstance(content, list):
        items = [c for c in content if isinstance(c, dict)]
        if any(c.get("type") == "tool_result" for c in items):
            return False
        texts = [str(c.get("text", "")) for c in items if c.get("type") == "text"]
        return bool(texts) and not texts[0].lstrip().startswith("<") and NOTICE not in texts[0]
    return False


def usage(path: Path) -> tuple[Counter, list]:
    """(token totals with a "requests" count, context size of each request)."""
    seen = {}
    for record in records(path):
        message = record.get("message")
        if record.get("type") == "assistant" and isinstance(message, dict) \
                and isinstance(message.get("usage"), dict) and message.get("id"):
            seen[message["id"]] = message["usage"]
    totals, contexts = Counter(), []
    for item in seen.values():
        for key in WEIGHTS:
            value = item.get(key)
            totals[key] += value if isinstance(value, int) else 0
        contexts.append(sum(item.get(k) or 0 for k in
                            ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")))
    totals["requests"] = len(seen)
    return totals, contexts


def weighted(totals: Counter) -> float:
    return sum(totals[key] * factor for key, factor in WEIGHTS.items())


def bookkeeping(name: str, tool_input: dict) -> bool:
    if name in ("Write", "Edit") and NOTE_PATH.search(str(tool_input.get("file_path", ""))):
        return True
    if name != "Bash":
        return False
    parts = [part.strip() for part in SEPARATOR.split(str(tool_input.get("command", "")))]
    return any(GIT_READ.match(part) for part in parts) and all(
        GIT_READ.match(part) or FILTER.match(part) for part in parts)


def subagent_kinds(folder: Path) -> list:
    """(kind, model, effort, totals) for each subagent transcript of a session."""
    found = []
    for path in sorted(folder.glob("agent-*.jsonl")):
        meta = {}
        try:
            meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        meta = meta if isinstance(meta, dict) else {}
        totals, _ = usage(path)
        found.append((str(meta.get("agentType") or "unknown"), str(meta.get("model") or "unknown"),
                      str(meta.get("effort") or "default"), totals))
    return found


def user_text(record: dict) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    return " ".join(str(c.get("text", "")) for c in content or [] if isinstance(c, dict) and c.get("type") == "text")


def bucket(gap: float, pending: dict, background: dict, open_turn: bool, generating: bool):
    """The bucket of one gap (module docstring), or None when it counts as away."""
    if gap <= 0:
        return None
    if pending:
        if {name for name, _, _ in pending.values()} == {"AskUserQuestion"}:
            return "human" if gap < GAP else None
        if gap >= PENDING_LIMIT:
            return None
        kinds = [kind for _, kind, _ in pending.values() if kind]
        return f"agent:{kinds[0]}" if kinds else "tools"
    if open_turn or generating:
        return "model" if gap < GAP else None
    if background and gap < PENDING_LIMIT:
        return f"agent:{next(iter(background.values()))[0]}"
    return "human" if gap < GAP else None


def session(path: Path) -> dict | None:
    """The measures of one main transcript, or None when it has no timestamp."""
    first = prev = None
    pending = {}  # tool_use id -> (name, Agent kind or None, start)
    launched = {}  # tool_use id -> kind, for Agent calls asked to run in the background
    background = {}  # tool_use id -> (kind, launch time, agent id), background agents still running
    open_turn = False
    split = Counter()
    tool_calls, tool_seconds, agent_calls, skills = Counter(), Counter(), Counter(), Counter()
    prompts = questions = notes = 0
    last_text = ""
    for record in records(path):
        when = timestamp(record["timestamp"]) if record.get("timestamp") else None
        prompt = is_prompt(record)
        notice = record.get("type") == "user" and NOTICE in user_text(record)
        if when:
            first = first or when
            if prev:
                gap = (when - prev).total_seconds()
                where = bucket(gap, pending, background, open_turn, record.get("type") == "assistant")
                if where:
                    split[where] += gap
            prev = when
            # A background agent whose notification never came stops counting after an hour.
            background = {key: value for key, value in background.items()
                          if (when - value[1]).total_seconds() < PENDING_LIMIT}
        if prompt or notice or record.get("type") in ("api-request", "assistant"):
            open_turn = True
        if background and (notice or record.get("type") == "queue-operation"):
            text = json.dumps(record)
            background = {key: value for key, value in background.items()
                          if str(key) not in text and not (value[2] and value[2] in text)}
        if prompt:
            prompts += 1
            if last_text.rstrip().endswith("?"):
                questions += 1
            last_text = ""
        message = record.get("message")
        if record.get("type") == "assistant" and isinstance(message, dict) \
                and message.get("stop_reason") in ("end_turn", "stop_sequence"):
            open_turn = False
        for item in content_list(record):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and record.get("type") == "assistant":
                last_text = str(item.get("text", ""))
            elif item.get("type") == "tool_use":
                name = str(item.get("name"))
                tool_input = item.get("input") if isinstance(item.get("input"), dict) else {}
                tool_calls[name] += 1
                kind = None
                if name in ("Agent", "Task"):
                    kind = str(tool_input.get("subagent_type") or "general-purpose")
                    agent_calls[kind] += 1
                    if tool_input.get("run_in_background") in (True, "true"):
                        launched[item.get("id")] = kind
                elif name == "Skill":
                    skills[str(tool_input.get("skill"))] += 1
                elif name == "AskUserQuestion":
                    questions += 1
                notes += bookkeeping(name, tool_input)
                if when:
                    pending[item.get("id")] = (name, kind, when)
            elif item.get("type") == "tool_result":
                key = item.get("tool_use_id")
                started = pending.pop(key, None)
                outcome = record.get("toolUseResult")
                async_launch = isinstance(outcome, dict) and (
                    outcome.get("isAsync") is True or outcome.get("status") == "async_launched")
                asked = launched.pop(key, None)
                kind = asked or (started[1] if started else None)
                if kind and (asked or async_launch) and when:
                    agent_id = outcome.get("agentId") if isinstance(outcome, dict) else None
                    background[key] = (kind, when, str(agent_id) if agent_id else "")
                if started and when:
                    seconds = (when - started[2]).total_seconds()
                    if 0 <= seconds < PENDING_LIMIT:
                        tool_seconds[started[0]] += seconds
    if first is None:
        return None
    totals, contexts = usage(path)
    return {"id": path.stem, "project": path.parent.name, "start": first.isoformat(),
            "active_seconds": sum(split.values()), "split": dict(split), "prompts": prompts,
            "questions": questions, "bookkeeping_calls": notes, "tool_calls": dict(tool_calls),
            "tool_seconds": dict(tool_seconds), "agent_calls": dict(agent_calls), "skills": dict(skills),
            "tokens": dict(totals), "weighted": weighted(totals), "contexts": contexts,
            "subagents": [{"kind": k, "model": m, "effort": e, "tokens": dict(t), "weighted": weighted(t)}
                          for k, m, e, t in subagent_kinds(path.parent / path.stem / "subagents")]}


def collect(folders, since: dt.datetime, until: dt.datetime) -> list:
    found = []
    for folder in folders:
        for path in sorted(Path(folder).glob("*.jsonl")):
            measured = session(path)
            if measured and since <= timestamp(measured["start"]) <= until:
                found.append(measured)
    return found


def percentile(values: list, share: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def summary(sessions: list) -> dict:
    split, tool_calls, agent_calls, skills = Counter(), Counter(), Counter(), Counter()
    tokens, sub_tokens = Counter(), Counter()
    sub_kind = defaultdict(lambda: {"agents": 0, "requests": 0, "weighted": 0.0})
    per_skill = defaultdict(lambda: {"sessions": 0, "active_hours": 0.0, "weighted": 0.0})
    contexts = []
    for item in sessions:
        split.update(item["split"])
        tool_calls.update(item["tool_calls"])
        agent_calls.update(item["agent_calls"])
        skills.update(item["skills"])
        tokens.update(item["tokens"])
        contexts += item["contexts"]
        for sub in item["subagents"]:
            sub_tokens.update(sub["tokens"])
            key = f"{sub['kind']} ({sub['model']}, {sub['effort']})"
            sub_kind[key]["agents"] += 1
            sub_kind[key]["requests"] += sub["tokens"].get("requests", 0)
            sub_kind[key]["weighted"] += sub["weighted"]
        for name in item["skills"]:
            per_skill[name]["sessions"] += 1
            per_skill[name]["active_hours"] += item["active_seconds"] / 3600
            per_skill[name]["weighted"] += item["weighted"] + sum(s["weighted"] for s in item["subagents"])
    active = sum(split.values())
    calls = sum(tool_calls.values())
    main_weight, sub_weight = weighted(tokens), weighted(sub_tokens)
    return {
        "sessions": len(sessions),
        "active_hours": round(active / 3600, 2),
        "prompts": sum(s["prompts"] for s in sessions),
        "question_rounds": sum(s["questions"] for s in sessions),
        "split_hours": {k: round(v / 3600, 2) for k, v in split.most_common()},
        "split_share": {k: round(v / active, 3) for k, v in split.most_common()} if active else {},
        "method_agent_hours": round(sum(v for k, v in split.items()
                                        if k.removeprefix("agent:") in METHOD_AGENTS) / 3600, 2),
        "tool_calls": calls,
        "bookkeeping_calls": sum(s["bookkeeping_calls"] for s in sessions),
        "bookkeeping_share": round(sum(s["bookkeeping_calls"] for s in sessions) / calls, 3) if calls else 0.0,
        "requests_main": tokens["requests"],
        "requests_subagents": sub_tokens["requests"],
        "context_median": int(statistics.median(contexts)) if contexts else 0,
        "context_p90": percentile(contexts, 0.9),
        "weighted_main": round(main_weight),
        "weighted_subagents": round(sub_weight),
        "subagent_share": round(sub_weight / (main_weight + sub_weight), 3) if main_weight + sub_weight else 0.0,
        "agent_calls": dict(agent_calls.most_common()),
        "subagents_by_kind": {k: {**v, "weighted": round(v["weighted"])}
                              for k, v in sorted(sub_kind.items(), key=lambda kv: -kv[1]["weighted"])},
        "skills": dict(skills.most_common()),
        "per_skill": {k: {**v, "active_hours": round(v["active_hours"], 2), "weighted": round(v["weighted"])}
                      for k, v in sorted(per_skill.items(), key=lambda kv: -kv[1]["active_hours"])},
    }


def report(data: dict, sessions: list) -> str:
    lines = [f"sessions {data['sessions']}, active {data['active_hours']} h, prompts {data['prompts']}, "
             f"question rounds {data['question_rounds']}",
             "time split (hours, share of active):"]
    for key, hours in data["split_hours"].items():
        lines.append(f"  {key:32} {hours:8.2f}  {data['split_share'][key]:6.1%}")
    lines += [f"  method subagents (scout, reviewer, gate-runner): {data['method_agent_hours']} h",
              f"tool calls {data['tool_calls']}, bookkeeping {data['bookkeeping_calls']} "
              f"({data['bookkeeping_share']:.1%})",
              f"requests main {data['requests_main']}, subagents {data['requests_subagents']}; "
              f"context per main request median {data['context_median']:,}, p90 {data['context_p90']:,}",
              f"weighted usage main {data['weighted_main']:,}, subagents {data['weighted_subagents']:,} "
              f"({data['subagent_share']:.1%} subagents)",
              "subagents by kind (agents, requests, weighted usage):"]
    for key, value in data["subagents_by_kind"].items():
        lines.append(f"  {key:44} {value['agents']:5} {value['requests']:7} {value['weighted']:>14,}")
    lines.append("per skill (sessions, active hours, weighted usage incl. subagents):")
    for key, value in data["per_skill"].items():
        lines.append(f"  {key:32} {value['sessions']:5} {value['active_hours']:8.2f} {value['weighted']:>14,}")
    lines.append("per session (start, project, active minutes, prompts, questions, requests):")
    for item in sorted(sessions, key=lambda s: s["start"]):
        lines.append(f"  {item['start'][:16]} {item['project'][-30:]:30} {round(item['active_seconds'] / 60):5} "
                     f"{item['prompts']:4} {item['questions']:4} {item['tokens'].get('requests', 0):6}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folders", nargs="*", help="Claude Code project folders (default: all)")
    parser.add_argument("--since", required=True, help="first day, YYYY-MM-DD (UTC)")
    parser.add_argument("--until", help="last day, YYYY-MM-DD (UTC); default: today")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    since = timestamp(args.since)
    until = timestamp(args.until) if args.until else dt.datetime.now(dt.timezone.utc)
    if since is None or until is None:
        parser.error("--since and --until take a date such as 2026-11-08")
    until += dt.timedelta(days=1) if args.until else dt.timedelta()
    folders = args.folders or sorted(p for p in (Path.home() / ".claude" / "projects").glob("*") if p.is_dir())
    sessions = collect(folders, since, until)
    data = summary(sessions)
    print(json.dumps(data, indent=2) if args.json else report(data, sessions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
