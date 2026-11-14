#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Stop hook (Claude Code): when the agent's final message says the tests pass, check in
the session's transcript that a test run passed after the last file edit.

It blocks the stop once when last_assistant_message claims that tests pass ("tests pass",
"all tests passed", "the suite is green", "189 tests OK"), the transcript shows a known
test run, and after the last edit either only commands that certainly run no tests came,
or the last known run failed and no command of unknown kind followed it. An edit is an
Edit, Write, MultiEdit or NotebookEdit call that did not fail, or a Bash call whose result
records changed files (bashEditDiff; a command of the third kind below that does is an
edit followed by a run of unknown outcome, as pre-commit run reformatting a file and then
running the tests); edits of task notes (a .private folder), of
temporary files and of Claude Code's own folder (~/.claude) do not count.

Each Bash command after the last edit is of one of three kinds (the maintainer's rule).
(1) A known test run: a test runner (pytest, python -m unittest, ctest, go test, cargo
test, npm test, jest...) or a script or build target named test, gate, check or verify
(./run_tests.sh, sh tools/gates.sh, make check, mvn verify), also behind wrappers (env,
timeout, sudo), launchers (uv run, npx, pnpm exec..., their own options skipped) and
bash -c; its outcome counts. (2) A command
that certainly runs no tests: git status, add, commit, diff, log, show, restore or stash,
cat, ls, head, tail, wc, grep, rg, find (with such -exec commands), echo, printf, mkdir,
cp, mv, sed -n without -i, true, cd; it does not count, unless its output shows a
runner's summary or pre-commit's "hook....Passed" or "Failed" line (git commit's hooks
may run the tests, cat may show a log): then it is a run with that outcome (the
maintainer's decision). (3) Anything else may have run
tests, so its outcome is unknown and the stop goes through. Commands are split with the
shell parser of guard_bash.py, next to this file; without it every stop goes through.
PowerShell commands are read like Bash ones; a subagent or an MCP tool (mcp__...) may have
run tests, so its outcome is unknown; the other built-in tools run none. A run failed when
a runner's summary line says so (a pipe into tail hides the exit status; other lines of
the output, such as a test's own log, are not read), or when the call failed and no
summary says the tests passed; a failed call whose summary says they passed (a later
command of a chain failed) has an unknown outcome.

The transcript format is not documented and the file may lag the conversation, so the
hook reads only its last MAX_BYTES and lets the stop through, printing nothing, on any
doubt: stop_hook_active anything but false (true: the agent already continued because of
a stop hook; missing: Cursor, which runs Claude Code's Stop hooks with its own input and
no cap on follow-ups), no claim, a transcript it cannot read or whose tail does not end
with the final message in the shape it knows, no known test run in that tail, or, after
the last edit, a subagent call, a command of the third kind, or a known test run in the
background, without a result or of unknown outcome.

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

sys.dont_write_bytecode = True  # importing guard_bash leaves no cache in ~/.agents/hooks
try:
    import guard_bash  # its shell parser splits a command line into simple commands
except Exception:  # a missing or broken copy lets every stop through
    guard_bash = None

MAX_BYTES = 4_000_000
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SUBAGENT_TOOLS = {"Agent", "Task"}
# Shell tools: PowerShell takes its command in the same fields as Bash (tools reference).
SHELL_TOOLS = {"Bash", "PowerShell"}
MCP_PREFIX = "mcp__"  # an MCP tool's effect is unknown: it may run tests
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
# What runs tests, read from the program of each simple command (after the guard has
# taken off assignments and wrappers such as env, sudo, timeout or xargs).
RUNNERS = {"pytest", "py.test", "tox", "nox", "ctest", "jest", "vitest", "mocha", "karma", "rspec", "phpunit",
           "bats", "nose2", "trial", "ava", "prove"}
PYTHON_MODULES = {"pytest", "unittest", "nose2", "tox", "nox", "trial"}
# Programs whose test subcommand runs the tests (cargo nextest, npm t and zig build test too).
TEST_SUBCOMMAND = {"go", "cargo", "dotnet", "swift", "mix", "deno", "bun", "flutter", "dart", "bazel", "bazelisk",
                   "sbt", "lein", "stack", "cabal", "meson", "raco", "npm", "pnpm", "yarn", "zig"}
# Build tools whose target names say what runs: make check, mvn verify, cmake --target test.
BUILD_TOOLS = {"make", "gmake", "ninja", "gradle", "gradlew", "mvn", "mvnw", "rake", "just", "task", "cmake"}
# Their options that take the next word as their value, which is not a target: make, ninja
# and cmake --build from their help (make 4.4, ninja 1.13, cmake here); gradle, maven,
# rake, just and task from their manuals as remembered, not checked (none is installed).
MAKE_VALUES = {"-C", "-f", "-I", "-o", "-W", "-E", "--directory", "--file", "--makefile", "--include-dir",
               "--old-file", "--assume-old", "--what-if", "--new-file", "--assume-new", "--eval"}
GRADLE_VALUES = {"-p", "-b", "-c", "-g", "-I", "-x", "-D", "-P", "--project-dir", "--build-file", "--settings-file",
                 "--gradle-user-home", "--init-script", "--exclude-task", "--console", "--warning-mode", "--priority",
                 "--include-build", "--project-cache-dir"}
MAVEN_VALUES = {"-pl", "-f", "-s", "-gs", "-t", "-rf", "-P", "-T", "-l", "-b", "-D", "--projects", "--file",
                "--settings", "--global-settings", "--toolchains", "--resume-from", "--activate-profiles", "--threads",
                "--log-file", "--builder", "--define"}
BUILD_VALUES = {
    "make": MAKE_VALUES, "gmake": MAKE_VALUES, "ninja": {"-C", "-f", "-j", "-k", "-l", "-d", "-t", "-w"},
    "gradle": GRADLE_VALUES, "gradlew": GRADLE_VALUES, "mvn": MAVEN_VALUES, "mvnw": MAVEN_VALUES,
    "rake": {"-f", "-C", "-I", "-r", "-R", "-e", "-E", "-p", "-j", "--rakefile", "--directory", "--libdir", "--require",
             "--rakelibdir", "--execute", "--execute-continue", "--execute-print", "--jobs"},
    "just": {"-f", "-d", "--justfile", "--working-directory", "--shell", "--dotenv-filename", "--dotenv-path",
             "--color", "--chooser"},
    "task": {"-d", "-t", "-o", "-C", "--dir", "--taskfile", "--output", "--concurrency"}}
# make's -j and -l take the next word only when it is a number; just --set takes two.
OPTIONAL_NUMBERS = {"-j", "-l", "--jobs", "--load-average", "--max-load"}
# Programs that run the command after their own words and options: uv run pytest, npx
# jest, pnpm exec vitest. {program: the subcommands that launch (none: the program does)}.
LAUNCHERS = {"uv": ("run",), "poetry": ("run",), "pipenv": ("run",), "pdm": ("run",), "hatch": ("run",),
             "rye": ("run",), "bundle": ("exec",), "npx": (), "bunx": (), "pnpx": (), "npm": ("exec", "x"),
             "pnpm": ("exec", "dlx"), "yarn": ("exec", "dlx"), "bun": ("x",)}
# The launchers' options that take the next word as their value: uv run's
# (docs.astral.sh/uv/reference/cli, uv run, 13 Nov 2026) and npm exec's (npm exec --help);
# other launchers: the common directory and project options.
UV_VALUES = {"--cache-dir", "--color", "--config-file", "--config-setting", "--config-settings", "-C",
             "--config-settings-package", "--default-index", "--directory", "--env-file", "--exclude-newer",
             "--exclude-newer-package", "--extra", "--extra-index-url", "--find-links", "-f", "--fork-strategy",
             "--group", "--index", "--index-strategy", "--index-url", "-i", "--keyring-provider", "--link-mode",
             "--no-binary-package", "--no-build-isolation-package", "--no-build-package", "--no-editable-package",
             "--no-extra", "--no-group", "--no-sources-package", "--only-group", "--package", "--prerelease",
             "--prerelease-package", "--project", "--python", "-p", "--python-platform", "--refresh-package",
             "--reinstall-package", "--resolution", "--upgrade-group", "--upgrade-package", "-P", "--with", "-w",
             "--with-editable", "--with-requirements"}
NPM_EXEC_VALUES = {"--package", "-w", "--workspace", "--allow-scripts"}
LAUNCHER_VALUES = {"uv": UV_VALUES, "npx": NPM_EXEC_VALUES, "npm": NPM_EXEC_VALUES}
OTHER_LAUNCHER_VALUES = {"-C", "--directory", "--project", "--cwd", "--dir"}
LAUNCHER_TEXT = {"-c", "--call"}  # npx -c 'jest --ci' runs its text as a command
INTERPRETERS = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|node|ruby|perl|bash|sh|zsh|dash|ksh)$")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
NAMED = re.compile(r"(?i)test|gate|check|verify")
SCRIPT_SUFFIX = re.compile(r"\.(?:sh|bash|zsh|py|js|mjs|cjs|ts|rb|pl|ps1|bat|cmd)$")
# Commands that certainly run no tests (the maintainer's list): they never count as a run.
# Any other command that is not a known runner may have run tests: its outcome is unknown.
QUIET_PROGRAMS = {"cat", "ls", "head", "tail", "wc", "grep", "rg", "find", "echo", "printf", "mkdir", "cp", "mv",
                  "true", "cd"}
QUIET_GIT = {"status", "add", "commit", "diff", "log", "show", "restore", "stash"}
# The summary lines of common runners, read only in their own shapes, so a test's log
# that mentions failures or errors does not count. Failed: unittest FAILED (failures=1),
# pytest "1 failed, 3 passed in 0.30s", go FAIL, cargo "test result: FAILED", jest and
# vitest "Tests: 1 failed", mocha "1 failing", rspec and bats "1 failure", ctest "1 tests
# failed out of", gradle BUILD FAILED, maven BUILD FAILURE, dotnet "Failed!", phpunit
# FAILURES!, tox "commands failed", make "*** ... Error", pre-commit "hook....Failed".
FAILED_SUMMARY = re.compile(r"""(?mx)
    ^\S.*?\.{3,}Failed\s*$
  | ^FAILED\ \((?:failures|errors|unexpected\ successes)=
  | ^(?:=+\ )?(?:\d+\ \w+,\ )*[1-9]\d*\ (?:failed|errors?)\b[\w\ ,]*\ in\ [\d.]+s\b
  | ^FAIL(?:\t|\ *$) | ^test\ result:\ FAILED\b | ^\s*Tests:?\s+(?:\d+\ \w+,?\s+)*[1-9]\d*\ failed\b
  | ^\s*[1-9]\d*\ failing\s*$ | ^\d+\ (?:examples?|tests?),\ [1-9]\d*\ failures?\b
  | ^\d+%\ tests\ passed,\ [1-9]\d*\ tests?\ failed\ out\ of | ^BUILD\ FAILED\b | ^\[\w+\]\ BUILD\ FAILURE\b
  | ^\s*Failed!\s+-\s+Failed:\s+[1-9] | ^(?:FAILURES|ERRORS)!$ | ^\s*\S+:\ (?:commands\ failed|FAIL\ code\ \d+)
  | ^g?make(?:\[\d+\])?:\ \*\*\*\ .*Error\ \d+""")
# Passed: unittest OK, pytest "4 passed in 0.21s", go ok and PASS, cargo "test result:
# ok", jest "Tests: 4 passed", mocha "4 passing", rspec "0 failures", ctest "100% tests
# passed", gradle BUILD SUCCESSFUL, maven BUILD SUCCESS, dotnet "Passed!", phpunit OK (...),
# pre-commit "hook....Passed" (a skipped hook is neither).
PASSED_SUMMARY = re.compile(r"""(?mx)
    ^\S.*?\.{3,}Passed\s*$
  | ^OK(?:\ \(.*\))?$ | ^(?:=+\ )?(?:\d+\ \w+,\ )*\d+\ passed\b[\w\ ,]*\ in\ [\d.]+s\b | ^ok\s+\S | ^PASS$
  | ^test\ result:\ ok\b | ^\s*Tests:?\s+(?:\d+\ \w+,?\s+)*\d+\ passed\b | ^\s*\d+\ passing\b
  | ^\d+\ (?:examples?|tests?),\ 0\ failures\b | ^100%\ tests\ passed | ^BUILD\ SUCCESSFUL\b
  | ^\[\w+\]\ BUILD\ SUCCESS\b | ^\s*Passed!\s+- | ^OK\ \(\d+\ tests?""")


def outcome(failed: bool, interrupted: bool, output: str) -> str:
    """A run's outcome: "fail" when a runner's summary says so, or the call failed with no
    summary of a pass; "pass" when the call did not fail; "doubt" when it failed although
    a runner's summary says the tests passed (a later command of the chain failed)."""
    if FAILED_SUMMARY.search(output):
        return "fail"
    if not (failed or interrupted):
        return "pass"
    return "doubt" if PASSED_SUMMARY.search(output) else "fail"


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


def operands(words: list) -> list:
    return [word for word in words if not word.startswith("-")]


def named_script(path: str) -> bool:
    """A script file named test, gate, check or verify (./run_tests.sh, tools/gates.sh);
    a bare name such as the shell's own test is a program, not a script."""
    return bool(NAMED.search(os.path.basename(path))) and ("/" in path or bool(SCRIPT_SUFFIX.search(path)))


def launched(program: str, args: list):
    """What a launcher runs: the words of the command after its own options and its launching
    subcommand, the text of npx -c, or None when it launches nothing."""
    steps, values = LAUNCHERS[program], LAUNCHER_VALUES.get(program, OTHER_LAUNCHER_VALUES)
    stepped, index = not steps, 0
    while index < len(args):
        word = args[index]
        if word == "--":
            index += 1
        elif stepped and word in LAUNCHER_TEXT:
            return args[index + 1] if index + 1 < len(args) else None
        elif word.startswith("-"):
            index += 2 if word in values else 1
        elif not stepped:
            if word not in steps:
                return None
            stepped, index = True, index + 1
        else:
            return args[index:]
    return None


def runs_tests(words: list, depth: int = 0) -> bool:
    """True when the simple command executes a test runner, or a script or build target
    named test, gate, check or verify."""
    if not words or depth > 4:
        return False
    program, args = os.path.basename(words[0]), words[1:]
    rest = operands(args)
    if program in RUNNERS:
        return True
    if program in SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
        return command_kind(args[args.index("-c") + 1], depth + 1) == "runner"
    if INTERPRETERS.match(program):
        if program.startswith(("python", "pypy")) and "-m" in args and args.index("-m") + 1 < len(args):
            module = args[args.index("-m") + 1]
            return module in PYTHON_MODULES or bool(NAMED.search(module))
        if "-c" in args or "-e" in args:
            return False  # code given as text (python -c, node -e) is not a script
        return bool(rest) and NAMED.search(os.path.basename(rest[0])) is not None
    launch = launched(program, args) if program in LAUNCHERS else None
    if isinstance(launch, str):
        return command_kind(launch, depth + 1) == "runner"
    if launch:
        return runs_tests(launch, depth + 1)
    if program in TEST_SUBCOMMAND and rest:
        first = rest[0]
        if first in ("test", "t") or (program == "cargo" and first == "nextest") or rest[:2] == ["build", "test"]:
            return True
        if program in ("npm", "pnpm", "yarn", "bun") and first == "run":
            return len(rest) > 1 and NAMED.search(rest[1]) is not None
        if program in ("yarn", "pnpm", "bun"):
            return runs_tests(args, depth + 1)  # yarn vitest runs the package's vitest
        return False
    if program in BUILD_TOOLS:
        return any(NAMED.search(target) for target in build_targets(program, args))
    return named_script(words[0])


def build_targets(program: str, args: list) -> list:
    """The targets a build tool builds: its words that are neither options, nor option
    values, nor VAR=value assignments; for cmake only its --target or -t values; none
    when ninja runs a tool (-t)."""
    if program == "cmake":
        targets, reading = [], False
        for word in args:
            if word in ("--target", "-t") or word.startswith("--target="):
                reading = True
                targets += [word.partition("=")[2]] if "=" in word else []
            elif word.startswith("-"):
                reading = False
            elif reading:
                targets.append(word)
        return targets
    if program == "ninja" and "-t" in args:
        return []
    values, targets, index = BUILD_VALUES[program], [], 0
    while index < len(args):
        word = args[index]
        index += 1
        if word.startswith("-"):
            if "=" in word:
                continue
            if word in values:
                index += 1
            elif word == "--set":
                index += 2
            elif word in OPTIONAL_NUMBERS and index < len(args) and args[index].isdigit():
                index += 1
        elif "=" not in word:
            targets.append(word)
    return targets


def quiet(words: list, depth: int = 0) -> bool:
    """True for a command that certainly runs no tests: QUIET_PROGRAMS (find only with such
    commands after -exec), git with a QUIET_GIT subcommand after its own options, sed -n
    without -i, and a shell's -c text made of such commands."""
    if not words:
        return True
    program, args = os.path.basename(words[0]), words[1:]
    if program in SHELLS and "-c" in args and args.index("-c") + 1 < len(args):
        return depth < 4 and command_kind(args[args.index("-c") + 1], depth + 1) == "quiet"
    if program == "find":
        return all(quiet(guard_bash.split_command(inner)[1], depth + 1) for inner in guard_bash.find_commands(words))
    if program == "git":
        index = 0
        while index < len(args) and args[index].startswith("-"):
            index += 2 if args[index] in guard_bash.GIT_VALUE_OPTIONS else 1
        return index < len(args) and args[index] in QUIET_GIT
    if program == "sed":
        shorts = "".join(arg[1:] for arg in args if arg.startswith("-") and not arg.startswith("--"))
        longs = [arg for arg in args if arg.startswith("--")]
        return (("n" in shorts or "--quiet" in longs or "--silent" in longs) and "i" not in shorts
                and not any(arg.startswith("--in-place") for arg in longs))
    return program in QUIET_PROGRAMS


def command_kind(command: str, depth: int = 0) -> str:
    """"runner" when a simple command of the text runs tests, "quiet" when every one
    certainly runs none, "unknown" otherwise."""
    try:
        commands = guard_bash.parse_commands(command)
    except (guard_bash.ParseError, RecursionError):
        commands = guard_bash.rough_commands(command)
    simple = [guard_bash.split_command(words)[1] for words in commands]
    if any(runs_tests(words, depth) for words in simple):
        return "runner"
    return "quiet" if all(quiet(words, depth) for words in simple) else "unknown"


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
    """"" to let the stop through, or what is missing: "failed" (the last run after the
    last edit failed), "before" (every run came before it) or "none" (no run at all)."""
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
    events = []  # in order: "edit", "pass", "fail", or "doubt" (a run whose outcome is unknown)
    for use in uses:
        name, given = use.get("name"), use.get("input") if isinstance(use.get("input"), dict) else {}
        result = results.get(use.get("id"))
        if name in EDIT_TOOLS:
            if not (result and result[0]) and not ignored_path(given.get("file_path") or given.get("notebook_path"),
                                                               ignored):
                events.append("edit")
        elif name in SUBAGENT_TOOLS or (isinstance(name, str) and name.startswith(MCP_PREFIX)):
            events.append("doubt")
        elif name in SHELL_TOOLS and isinstance(given.get("command"), str):
            kind = command_kind(given["command"])
            if kind == "quiet" and result is not None and (FAILED_SUMMARY.search(result[1])
                                                           or PASSED_SUMMARY.search(result[1])):
                kind = "runner"  # git commit's hooks, or a log it shows, report a test run
            if kind == "runner":
                if result is None or given.get("run_in_background"):
                    events.append("doubt")
                else:
                    failed, output, extra = result
                    interrupted = isinstance(extra, dict) and extra.get("interrupted") is True
                    events.append(outcome(failed, interrupted, output))
            else:
                if result is not None and changed_files(result[2], ignored):
                    events.append("edit")
                if kind == "unknown":
                    events.append("doubt")  # it may have run tests, after the files it changed
    last_edit = max((index for index, event in enumerate(events) if event == "edit"), default=-1)
    after = events[last_edit + 1:]
    if not after:
        if last_edit < 0:
            return ""  # neither an edit nor a run in the tail: nothing to compare the claim with
        return "before" if any(event in ("pass", "fail") for event in events[:last_edit]) else "none"
    return "failed" if after[-1] == "fail" else ""  # the last run after the last edit decides


def reason(missing: str) -> str:
    detail = {"failed": "the last test runs failed",
              "none": "no test ran after your last file edit"}.get(missing,
                                                                   "every test run came before your last file edit")
    return "\n".join([
        f"Your last message says the tests pass, but in this session {detail}.",
        "Run the tests now and report their result, or say plainly that they were not run after the last "
        "edit. Then end the turn.",
    ])


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if guard_bash is None or not isinstance(payload, dict) or payload.get("stop_hook_active") is not False:
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
