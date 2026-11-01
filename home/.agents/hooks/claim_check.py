#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Stop hook (Claude Code): when the agent's final message says the tests pass, check in
the session's transcript that a test run passed after the last file edit.

It blocks the stop once when last_assistant_message claims that tests pass ("tests pass",
"all tests passed", "the suite is green", "189 tests OK") and the transcript shows test
runs but none that passed after the last edit. An edit is an Edit, Write, MultiEdit or
NotebookEdit call that did not fail, or a Bash call whose result records changed files
(bashEditDiff); edits of task notes (a .private folder), of temporary files and of
Claude Code's own folder (~/.claude) do not count. A test run is a Bash command that
runs a known test runner (pytest, unittest, ctest, go test, cargo test, npm test, make
test or check...); it passed when the call did not fail and its output names no failure
(a pipe into tail hides the exit status).

The transcript format is not documented and the file may lag the conversation, so the
hook reads only its last MAX_BYTES and lets the stop through, printing nothing, on any
doubt: stop_hook_active anything but false (true: the agent already continued because of
a stop hook; missing: Cursor, which runs Claude Code's Stop hooks with its own input and
no cap on follow-ups), no claim, a transcript it cannot read or whose tail does not end
with the final message in the shape it knows, no test run in that tail, or, after the
last edit, a subagent call, a test run in the background or of unknown outcome, or
another command that may run tests (one that names tests, a check, gates or verify).

Usage: python3 "$HOME/.agents/hooks/claim_check.py" || true
Blocking: {"decision": "block", "reason": ...} on stdout with exit 0. The "|| true" of
the hook command covers what the script cannot: python3 exits 2 when the script is
missing, and exit 2 from a Stop hook keeps the agent going.
"""

import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 4_000_000
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SUBAGENT_TOOLS = {"Agent", "Task"}
# "tests pass", "all 189 tests passed", "the hook tests are passing", "189 tests OK", "the
# suite is green", "the test suite passes".
CLAIM = re.compile(r"""(?ix)
    \b(?:all\s+)?(?:the\s+)?(?:\d[\d,]*\s+)?(?:[a-z]+\s+)?tests?\s+(?:now\s+|still\s+|all\s+)?
        (?:pass(?:es|ed)?|(?:are|were)\s+(?:all\s+)?(?:passing|green)|ok)\b
  | \b(?:test\s+)?suite\s+(?:(?:is|was|stays|now)\s+)*(?:green|pass(?:es|ed|ing)?)\b""")
# Words that make the clause a negation, a condition or a plan instead of a claim.
HEDGE = re.compile(r"""(?ix)
    \b(?:not|no|never|nor|without|until|unless|if|whether|once|before|should|would|could|will|must|
         might|may|ensure|expect)\b | n't\b | \bso\s+that\b | \bmake\s+sure\b""")
CLAUSE_END = re.compile(r"[.!?;:,\n]")
RUNNER = re.compile(r"""(?ix)
    (?<![\w.-])
    (?: (?:py\.?test|tox|nox|ctest|jest|vitest|mocha|karma|rspec|phpunit|bats|nextest)\b
      | unittest\b
      | (?:go|cargo|dotnet|swift|mix|deno|bun|flutter|dart|bazel|bazelisk|sbt|lein|stack|cabal|meson|raco)
        \s+test\b
      | (?:npm|pnpm|yarn)\s+(?:run\s+)?test\b
      | (?:make|ninja|gradle|gradlew|mvn|mvnw|rake|just)\b[^;&|\n]*?\b(?:test|tests|check)\b)""")
# A command that may run tests without a known runner's name (a gates script, a check).
MAYBE_RUNNER = re.compile(r"(?i)test|gate|\bcheck\b|verify")
# Failure lines of common runners: unittest FAILED (...), pytest "1 failed", go FAIL,
# cargo "test result: FAILED", jest "1 failed", mocha "1 failing", rspec "1 failure",
# ctest "1 tests failed", gradle BUILD FAILED, maven "Failures: 1".
FAILURE = re.compile(r"""(?mx)
    ^(?:FAILED|FAIL)\b | ---\ FAIL\b | test\ result:\ FAILED | BUILD\ FAIL(?:ED|URE)
  | \b[1-9]\d*\ (?:tests?\ )?(?:failed|failing|failures?|errors?)\b | \b(?:Failures|Errors):\ [1-9]
  | \btests\ FAILED\b""")


def tail_records(path: str) -> list:
    """The JSON objects on the lines of the file's last MAX_BYTES; [] when it is not a
    regular file. Opened without blocking, so a FIFO cannot hold the hook."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            return []
        start = max(0, info.st_size - MAX_BYTES)
        handle.seek(start)
        data = handle.read(MAX_BYTES)
    if start:
        data = data[data.find(b"\n") + 1:] if b"\n" in data else b""
    records = []
    for line in data.split(b"\n"):
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, RecursionError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def blocks_of(record: dict) -> list:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block["text"] for block in content
                         if isinstance(block, dict) and isinstance(block.get("text"), str))
    return ""


def normalized(text: str) -> str:
    return " ".join(text.split())


def claims_tests_pass(message: str) -> bool:
    for match in CLAIM.finditer(message):
        clause = CLAUSE_END.split(message[max(0, match.start() - 80):match.start()])[-1]
        if not HEDGE.search(clause + match.group(0)):
            return True
    return False


def ignored_path(path, ignored: list) -> bool:
    """Task notes, temporary files and Claude Code's own files: no test reads them."""
    if not isinstance(path, str) or not path:
        return False
    path = os.path.normpath(path)
    return ".private" in Path(path).parts or any(path == root or path.startswith(root + os.sep)
                                                 for root in ignored)


def changed_files(result, ignored: list) -> bool:
    """True when a Bash result records a changed file that counts (bashEditDiff)."""
    diff = result.get("bashEditDiff") if isinstance(result, dict) else None
    if not isinstance(diff, dict):
        return False
    changed, files, more = diff.get("changedFiles"), diff.get("files"), diff.get("moreFiles")
    paths = (changed if isinstance(changed, list) else []) + [
        entry.get("filePath") for entry in (files if isinstance(files, list) else []) if isinstance(entry, dict)]
    return any(not ignored_path(path, ignored) for path in paths if path) or (isinstance(more, int) and more > 0)


def verdict(records: list, message: str, ignored: list) -> str:
    """"" to let the stop through, or what is missing: "failed" (the runs after the last
    edit failed) or "before" (every run came before it)."""
    uses, results = [], {}
    last_tool = final_at = -1
    final = ""
    for position, record in enumerate(records):
        role = record.get("type")
        for block in blocks_of(record):
            kind = block.get("type")
            if role == "assistant" and kind == "tool_use":
                uses.append(block)
                last_tool = position
            elif role == "assistant" and kind == "text" and isinstance(block.get("text"), str):
                final_at, final = position, block["text"]
            elif role == "user" and kind == "tool_result":
                results[block.get("tool_use_id")] = (block.get("is_error") is True,
                                                    result_text(block.get("content")), record.get("toolUseResult"))
                last_tool = position
    # The transcript may lag: go on only when its tail ends with the final message.
    final, message = normalized(final), normalized(message)
    if final_at <= last_tool or not final or (final not in message and message not in final):
        return ""
    events = []  # ("edit" | "pass" | "fail" | "doubt", None)
    for use in uses:
        name, given = use.get("name"), use.get("input") if isinstance(use.get("input"), dict) else {}
        result = results.get(use.get("id"))
        if name in EDIT_TOOLS:
            if not (result and result[0]) and not ignored_path(given.get("file_path") or given.get("notebook_path"),
                                                               ignored):
                events.append("edit")
        elif name in SUBAGENT_TOOLS:
            events.append("doubt")
        elif name == "Bash" and isinstance(given.get("command"), str):
            command = given["command"]
            if RUNNER.search(command):
                if result is None or given.get("run_in_background"):
                    events.append("doubt")
                else:
                    failed, output, extra = result
                    interrupted = isinstance(extra, dict) and extra.get("interrupted") is True
                    events.append("fail" if failed or interrupted or FAILURE.search(output) else "pass")
            elif result is not None and changed_files(result[2], ignored):
                events.append("edit")
            elif MAYBE_RUNNER.search(command):
                events.append("maybe" if result is None or not result[0] else "other")
    if not any(event in ("pass", "fail") for event in events):
        return ""  # no test run to match the claim to
    last_edit = max((index for index, event in enumerate(events) if event == "edit"), default=-1)
    after = events[last_edit + 1:]
    if any(event in ("pass", "doubt", "maybe") for event in after):
        return ""
    return "failed" if "fail" in after else "before"


def reason(missing: str) -> str:
    detail = ("the last test runs failed" if missing == "failed"
              else "every test run came before your last file edit")
    return "\n".join([
        f"Your last message says the tests pass, but in this session {detail}.",
        "Run the tests now and report their result, or say plainly that they were not run after the last "
        "edit. Then end the turn.",
    ])


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("stop_hook_active") is not False:
            return 0
        message, path = payload.get("last_assistant_message"), payload.get("transcript_path")
        if not (isinstance(message, str) and isinstance(path, str) and path and claims_tests_pass(message)):
            return 0
        ignored = [os.path.normpath(tempfile.gettempdir()), os.path.normpath(Path.home() / ".claude")]
        if isinstance(payload.get("scratchpad_dir"), str) and payload["scratchpad_dir"]:
            ignored.append(os.path.normpath(payload["scratchpad_dir"]))
        missing = verdict(tail_records(path), message, ignored)
        if missing:
            print(json.dumps({"decision": "block", "reason": reason(missing)}))
    except Exception:  # never keep the agent going because of a broken hook
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
