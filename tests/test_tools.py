# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for the tools in tools/ on a copy of the repository."""

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# git without the user's configuration (signing, hooks, default branch).
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tools(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()) / "repo"
        # Local state stays out: .private notes and .claude (settings, agent worktrees).
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns(
            ".git", "dist", "__pycache__", ".private", ".claude"))
        self.addCleanup(shutil.rmtree, self.repo.parent)

    def run_tool(self, name: str, args=()) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(self.repo / "tools" / name), *map(str, args)],
                              capture_output=True, text=True, check=False)

    def test_validate_passes_on_the_repository(self):
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_validate_rejects_a_toml_end_marker_in_a_subagent(self):
        scout = self.repo / "home/.agents/agents/scout.md"
        scout.write_text(scout.read_text() + "\nA TOML end marker: '''\n")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL home/.agents/agents/scout.md: body contains '''", result.stdout)

    def test_validate_skips_stray_files_and_requires_skill_md(self):
        (self.repo / "home/.agents/skills/.DS_Store").write_bytes(b"\0\1")
        (self.repo / "claude-ai/skills/leftover").mkdir()
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("FAIL claude-ai/skills/leftover: SKILL.md missing", result.stdout.splitlines())
        self.assertNotIn(".DS_Store", result.stdout)

    def test_validate_requires_a_short_description_for_each_override(self):
        overrides = self.repo / "claude-ai/overrides.json"
        cases = {"empty": {"description": ""}, "missing": {}, "not text": {"description": 5},
                 "not an object": "Settles a choice.", "long": {"description": "x" * 201},
                 "angle brackets": {"description": "Settles <choice>."}}
        for label, override in cases.items():
            overrides.write_text(json.dumps({"skills": {"decide": override}}))
            result = self.run_tool("validate.py")
            self.assertEqual(result.returncode, 1, label)
            self.assertNotIn("Traceback", result.stderr, label)
            self.assertIn("FAIL claude-ai/overrides.json: decide: description", result.stdout, label)
        overrides.write_text(json.dumps({"skills": {"no-such-skill": {"description": "Does a thing."}}}))
        self.assertIn("unknown skill 'no-such-skill'", self.run_tool("validate.py").stdout)

    def test_build_refuses_an_override_without_description(self):
        (self.repo / "claude-ai/overrides.json").write_text(json.dumps({"skills": {"decide": {"description": ""}}}))
        result = self.run_tool("build.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("decide", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_validate_rejects_a_skill_in_both_roots(self):
        shutil.copytree(self.repo / "claude-ai/skills/tutor", self.repo / "home/.agents/skills/tutor")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL tutor: skill in both home/.agents/skills and claude-ai/skills", result.stdout)

    def add_skill(self, name: str, description: str = "Does a thing. Use when testing.", body: str = "Body.\n") -> None:
        folder = self.repo / "home/.agents/skills" / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\nlicense: MIT\n---\n{body}",
                                         encoding="utf-8")
        shutil.copy(self.repo / "home/.agents/skills/spec/LICENSE.txt", folder / "LICENSE.txt")

    def test_validate_rejects_a_skill_body_over_20000_bytes(self):
        # After compaction Claude Code keeps about 5,000 tokens of a skill, about 20,000 bytes.
        # The limit counts bytes, not characters: 10,001 two-byte letters are 20,002 bytes.
        self.add_skill("at-limit", body="x" * 20000)
        self.add_skill("over-limit", body="x" * 20001)
        self.add_skill("wide-letters", body="è" * 10001)
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL home/.agents/skills/over-limit/SKILL.md: body of 20001 bytes (limit 20000)", result.stdout)
        self.assertIn("FAIL home/.agents/skills/wide-letters/SKILL.md: body of 20002 bytes (limit 20000)", result.stdout)
        self.assertNotIn("at-limit", result.stdout)

    def test_validate_rejects_reserved_names_and_angle_brackets(self):
        self.add_skill("ok-skill")
        self.assertEqual(self.run_tool("validate.py").returncode, 0, "a plain skill passes")
        for name in ("claude-helper", "my-anthropic-notes", "synced", "anthropic-skills"):
            self.add_skill(name)
        self.add_skill("tagged", "Does <b>a</b> thing. Use when testing.")
        self.add_skill("compared", "Picks a > b. Use when testing.")
        out = self.run_tool("validate.py").stdout
        for name in ("claude-helper", "my-anthropic-notes", "synced", "anthropic-skills"):
            self.assertIn(f"home/.agents/skills/{name}/SKILL.md: reserved name {name!r}", out)
        for name in ("tagged", "compared"):
            self.assertIn(f"home/.agents/skills/{name}/SKILL.md: angle brackets in the description", out)
        self.assertNotIn("ok-skill", out)

    def test_validate_scans_files_of_any_suffix_for_dashes(self):
        palette = self.repo / "home/.agents/skills/plantuml-diagrams/palette.iuml"
        palette.write_text(palette.read_text() + "' a note \u2014 here\n")
        private = self.repo / ".private/notes.md"
        private.parent.mkdir()
        private.write_text("a scratch note \u2014 here\n")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("palette.iuml", result.stdout)
        self.assertNotIn(".private", result.stdout)

    @unittest.skipIf(shutil.which("git") is None, "git is not installed")
    def test_validate_scans_the_files_git_tracks_or_would_track(self):
        git = ["git", "-c", "init.defaultBranch=main"]
        subprocess.run(git + ["init", "-q"], cwd=self.repo, check=True)
        subprocess.run(git + ["add", "-A"], cwd=self.repo, check=True)
        palette = self.repo / "home/.agents/skills/plantuml-diagrams/palette.iuml"
        palette.write_text(palette.read_text() + "' a note \u2014 here\n")
        (self.repo / "docs/new-note.txt").write_text("not added yet \u2013 here\n")
        for ignored in (".private/notes.md", "dist/notes.md"):
            (self.repo / ignored).parent.mkdir(exist_ok=True)
            (self.repo / ignored).write_text("ignored \u2014 here\n")
        out = self.run_tool("validate.py").stdout
        self.assertIn("FAIL home/.agents/skills/plantuml-diagrams/palette.iuml:", out)
        self.assertIn("FAIL docs/new-note.txt:1: em or en dash", out)
        self.assertNotIn(".private", out)
        self.assertNotIn("dist/", out)

    def test_validate_reports_broken_org_links(self):
        # Org links: [[file:path]] and [[file:path][text]] name a file relative to the
        # linking file; ::#id after it, or #id alone, a CUSTOM_ID; ::*Heading or *Heading
        # a heading by its title (orgmode.org/manual, Internal links, Search options).
        (self.repo / "docs/links.org").write_text("""#+TITLE: links
* A real heading :tag:
:PROPERTIES:
:CUSTOM_ID: here
:END:
[[file:no-such.org][missing file]]
[[file:../DESIGN.org::#no-such-rule][missing id]] and [[file:../DESIGN.org::*No such heading]]
[[#nowhere][missing local id]], [[*Nowhere][missing local heading]]
[[file:../DESIGN.org::#one-source][ok]] [[file:../DESIGN.org::*Install   model][ok]]
[[file:diagrams/arch_parts.svg]] [[#here][ok]] [[*A real heading][ok]] [[https://example.com/x][web]]
[[file:../VISION.org::some words][a text search, not checked]]
Verbatim is not a link: write =[[file:...]]= links, or ~[[#id]]~.
#+BEGIN_SRC org
[[file:inside-a-block.org]]
#+END_SRC
""")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        broken = [line for line in result.stdout.splitlines() if "docs/links.org" in line]
        self.assertEqual(broken, [
            "FAIL docs/links.org:6: broken link [[file:no-such.org]]: docs/no-such.org does not exist",
            "FAIL docs/links.org:7: broken link [[file:../DESIGN.org::#no-such-rule]]: "
            "no CUSTOM_ID no-such-rule in DESIGN.org",
            "FAIL docs/links.org:7: broken link [[file:../DESIGN.org::*No such heading]]: "
            "no heading 'No such heading' in DESIGN.org",
            "FAIL docs/links.org:8: broken link [[#nowhere]]: no CUSTOM_ID nowhere in docs/links.org",
            "FAIL docs/links.org:8: broken link [[*Nowhere]]: no heading 'Nowhere' in docs/links.org",
        ])

    def test_validate_reports_hidden_text_in_instruction_files(self):
        # Hermes Agent's context-file scan: a model reads characters and HTML comments that a
        # person reviewing the file does not see. Instruction files: the global and the
        # repository's instructions, the bridges, every text file of a skill, the subagents
        # and the path rules. Characters: zero width (U+200B to U+200D, U+2060), bidirectional
        # controls (U+200E, U+200F, U+202A to U+202E, U+2066 to U+2069), U+FEFF anywhere (a
        # byte order mark too), the soft hyphen U+00AD and the tags U+E0000 to U+E007F. HTML
        # comments: <!-- in Markdown, outside fenced code (shown as code there).
        def prepend(path, text):
            target = self.repo / path
            target.write_text(text + target.read_text(encoding="utf-8"), encoding="utf-8")

        def write(path, text):
            (self.repo / path).write_text(text, encoding="utf-8")

        prepend("home/.agents/AGENTS.md", "\ufeff")
        prepend("AGENTS.md", "<!-- x -->\n")
        prepend("CLAUDE.md", "a\u200db\n")
        prepend("GEMINI.md", "a\u2060b\n")
        prepend(".github/copilot-instructions.md", "ab\u200e\u200f\n")
        prepend("home/.agents/skills/project-setup/templates/AGENTS.md.template", "<!-- t -->\n")
        write("home/.agents/path-rules.json", '{"rules": {"qt-quick": ["**/*.qml\u202c"]}}\n')
        scout = self.repo / "home/.agents/agents/scout.md"
        kept = scout.read_text(encoding="utf-8").rstrip("\n")
        scout.write_text(kept + "\n\nhidden\u2069\n", encoding="utf-8")
        self.add_skill("hidden-text", body="Plain line.\nA soft\u00adhyphen and <!-- note -->.\n```html\n"
                                           "<!-- shown as code -->\n```\n")
        write("home/.agents/skills/spec/reference.txt", "tag\U000e0041s\n"
              "\u200c|\u202a|\u202e|\u2066|\U000e0000|\U000e007f\n"
              "\u00a0|\u200a|\u202f|\u2065|\u206a|\U000e0080|\u2028\n")
        write("home/.agents/skills/spec/extra.md", "<!-- a -->\n")
        write("claude-ai/skills/tutor/notes.org", "x\u202by\n<!-- not markdown -->\n")
        write("docs/notes.md", "not loaded as instructions: \u200b <!-- c -->\n")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        hidden = "invisible or bidirectional character"
        comment = "HTML comment in a Markdown instruction file"
        reported = sorted(line for line in result.stdout.splitlines() if hidden in line or comment in line)
        self.assertEqual(reported, sorted([
            f"FAIL home/.agents/AGENTS.md:1:1: {hidden} U+FEFF",
            f"FAIL AGENTS.md:1:1: {comment}",
            f"FAIL CLAUDE.md:1:2: {hidden} U+200D",
            f"FAIL GEMINI.md:1:2: {hidden} U+2060",
            f"FAIL .github/copilot-instructions.md:1:3: {hidden} U+200E",
            f"FAIL .github/copilot-instructions.md:1:4: {hidden} U+200F",
            f"FAIL home/.agents/skills/project-setup/templates/AGENTS.md.template:1:1: {comment}",
            f"FAIL home/.agents/path-rules.json:1:34: {hidden} U+202C",
            f"FAIL home/.agents/agents/scout.md:{kept.count(chr(10)) + 3}:7: {hidden} U+2069",
            f"FAIL home/.agents/skills/hidden-text/SKILL.md:7:7: {hidden} U+00AD",
            f"FAIL home/.agents/skills/hidden-text/SKILL.md:7:19: {comment}",
            f"FAIL home/.agents/skills/spec/reference.txt:1:4: {hidden} U+E0041",
            f"FAIL home/.agents/skills/spec/reference.txt:2:1: {hidden} U+200C",
            f"FAIL home/.agents/skills/spec/reference.txt:2:3: {hidden} U+202A",
            f"FAIL home/.agents/skills/spec/reference.txt:2:5: {hidden} U+202E",
            f"FAIL home/.agents/skills/spec/reference.txt:2:7: {hidden} U+2066",
            f"FAIL home/.agents/skills/spec/reference.txt:2:9: {hidden} U+E0000",
            f"FAIL home/.agents/skills/spec/reference.txt:2:11: {hidden} U+E007F",
            f"FAIL home/.agents/skills/spec/extra.md:1:1: {comment}",
            f"FAIL claude-ai/skills/tutor/notes.org:1:2: {hidden} U+202B",
        ]))

    def test_validate_reports_selectors_fillers_and_hidden_operators_but_not_emoji(self):
        # Also hidden: the variation selectors U+FE00 to U+FE0F and U+E0100 to U+E01EF (they
        # can carry bytes after a visible character), the Arabic letter mark U+061C, the
        # invisible operators U+2061 to U+2064 and the Hangul filler U+3164; in
        # claude-ai/overrides.json too (its descriptions reach claude.ai). An emoji's own
        # parts pass: U+FE0E or U+FE0F right after a pictographic character, and U+200D
        # joining two (after a presentation selector or a skin tone too).
        (self.repo / "home/.agents/skills/spec/more.txt").write_text(
            "\ufe00|\ufe0f|\U000e0100|\U000e01ef|\u061c|\u2061|\u2064|\u3164\n"
            "\U0001F468\u200d\U0001F469\u200d\U0001F467 \u26a0\ufe0f \U0001F3F3\ufe0f\u200d\U0001F308 "
            "\U0001F469\U0001F3FD\u200d\U0001F4BB \u2764\ufe0e\n"
            "a\u200db \U0001F600\u200d \U0001F600\ufe0f\ufe0f\n", encoding="utf-8")
        (self.repo / "claude-ai/overrides.json").write_text(
            '{"skills": {"decide": {"description": "Settles\u2063 a choice."}}}\n', encoding="utf-8")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        hidden = "invisible or bidirectional character"
        reported = sorted(line for line in result.stdout.splitlines() if hidden in line)
        more = "FAIL home/.agents/skills/spec/more.txt"
        self.assertEqual(reported, sorted([
            f"{more}:1:1: {hidden} U+FE00", f"{more}:1:3: {hidden} U+FE0F", f"{more}:1:5: {hidden} U+E0100",
            f"{more}:1:7: {hidden} U+E01EF", f"{more}:1:9: {hidden} U+061C", f"{more}:1:11: {hidden} U+2061",
            f"{more}:1:13: {hidden} U+2064", f"{more}:1:15: {hidden} U+3164",
            f"{more}:3:2: {hidden} U+200D", f"{more}:3:6: {hidden} U+200D", f"{more}:3:10: {hidden} U+FE0F",
            f"FAIL claude-ai/overrides.json:1:47: {hidden} U+2063",
        ]))

    def test_validate_reads_markdown_code_before_reporting_html_comments(self):
        # CommonMark: a fence may sit in a list item (indented by the item, or right after
        # its marker) or in a blockquote, and closes only with its own character, at least as
        # many times, and nothing after it; a code span shows its text. A <!-- there is
        # shown as code, not hidden: only the two bare comments are reported.
        (self.repo / "home/.agents/skills/spec/fenced.md").write_text(
            "- item\n"
            "    - nested\n"
            "      ```html\n"
            "      <!-- in a nested list fence -->\n"
            "      ```\n"
            "- ```\n"
            "  <!-- in a fence opened on the item line -->\n"
            "  ```\n"
            "> ```\n"
            "> <!-- in a quoted fence -->\n"
            "> ```\n"
            "Inline `<!-- code -->` and ``a `<!--` b`` are shown.\n"
            "But <!-- this --> is hidden.\n"
            "~~~\n"
            "```\n"
            "<!-- a backtick line does not close a tilde fence -->\n"
            "~~~\n"
            "````\n"
            "~~~~\n"
            "```\n"
            "<!-- nor a tilde line or a shorter run a backtick fence -->\n"
            "```` x\n"
            "<!-- nor a fence line with text after it -->\n"
            "````\n"
            "```not a fence``` <!-- after a code span -->\n", encoding="utf-8")
        result = self.run_tool("validate.py")
        comment = "HTML comment in a Markdown instruction file"
        self.assertEqual(sorted(line for line in result.stdout.splitlines() if comment in line), [
            f"FAIL home/.agents/skills/spec/fenced.md:13:5: {comment}",
            f"FAIL home/.agents/skills/spec/fenced.md:25:19: {comment}",
        ])

    def test_validate_does_not_let_a_false_fence_hide_an_html_comment(self):
        # The second review's cases, rebuilt from its description: a fence is indented 0 to 3
        # spaces from its container (4 at the top level make indented code, not a fence); a
        # fence in a blockquote or a list item ends with the container, when a line has no
        # ">" or less indentation than the item; a backslash before a backtick escapes it, so
        # no code span starts there. In each, a comment a reader would not see is reported.
        (self.repo / "home/.agents/skills/spec/false-fences.md").write_text(
            "    ```\n"
            "<!-- a: after indented code, not inside a fence -->\n"
            "    ```\n"
            "> ```\n"
            "> quoted code\n"
            "left the quote <!-- b -->\n"
            "- item\n"
            "  ```\n"
            "  code in the item\n"
            "back at the margin <!-- c -->\n"
            "\\`<!-- d -->\\` is no code span\n"
            "- item\n"
            "\n"
            "  ```\n"
            "\n"
            "  <!-- inside the item's fence, after a blank line -->\n"
            "  ```\n"
            "```\n"
            "    ```\n"
            "<!-- inside: a closing run indented 4 columns does not close the fence -->\n"
            "```\n"
            # Five or more spaces after a list marker: the item's content starts one column
            # after the marker, so the rest is indented code, not a fence (the third review).
            "-     ```\n"
            "  <!-- e: after the item's indented code -->\n", encoding="utf-8")
        result = self.run_tool("validate.py")
        comment = "HTML comment in a Markdown instruction file"
        self.assertEqual(sorted(line for line in result.stdout.splitlines() if comment in line), sorted([
            f"FAIL home/.agents/skills/spec/false-fences.md:2:1: {comment}",
            f"FAIL home/.agents/skills/spec/false-fences.md:6:16: {comment}",
            f"FAIL home/.agents/skills/spec/false-fences.md:10:20: {comment}",
            f"FAIL home/.agents/skills/spec/false-fences.md:11:3: {comment}",
            f"FAIL home/.agents/skills/spec/false-fences.md:23:3: {comment}",
        ]))

    def test_validate_checks_subagent_effort_and_turn_limit(self):
        # Claude Code's effort levels are low, medium, high, xhigh and max; maxTurns is a
        # positive whole number (code.claude.com/docs/en/sub-agents).
        scout = self.repo / "home/.agents/agents/scout.md"
        original = scout.read_text()
        for field, problem in (("effort: extreme", "effort 'extreme'"), ("maxTurns: 0", "maxTurns '0'"),
                               ("maxTurns: many", "maxTurns 'many'")):
            with self.subTest(field=field):
                key = field.split(":")[0]
                lines = [line for line in original.splitlines() if not line.startswith(key + ":")]
                scout.write_text("\n".join(lines[:2] + [field] + lines[2:]) + "\n")
                result = self.run_tool("validate.py")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"FAIL home/.agents/agents/scout.md: {problem}", result.stdout)
        scout.write_text(original)
        self.assertEqual(self.run_tool("validate.py").returncode, 0)

    def test_validate_checks_the_path_rules(self):
        rules = self.repo / "home/.agents/path-rules.json"
        source = json.loads(rules.read_text())
        cases = {"unknown skill": ({"no-such-skill": ["**/*.x"]}, "path rule for unknown skill 'no-such-skill'"),
                 "no globs": ({"qt-quick": []}, "path rule qt-quick: globs must be a non-empty list"),
                 "bad glob": ({"qt-quick": ["**/*.qml", 5]}, "path rule qt-quick: globs must be a non-empty list"),
                 "quote": ({"qt-quick": ['a"b']}, "path rule qt-quick: glob 'a\"b' has a quote, a backslash or a"),
                 "not an object": ([], "home/.agents/path-rules.json: no rules object")}
        for label, (value, problem) in cases.items():
            with self.subTest(label=label):
                rules.write_text(json.dumps({"rules": value} if label != "not an object" else value))
                result = self.run_tool("validate.py")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(problem, result.stdout)
        rules.write_text(json.dumps(source))
        self.assertEqual(self.run_tool("validate.py").returncode, 0)

    def test_validate_catches_broken_skills_and_dashes(self):
        skill = self.repo / "claude-ai/skills/tutor/SKILL.md"
        text = skill.read_text()
        skill.write_text(text.replace("name: tutor", "name: Tutor", 1) + "\nA long pause \u2014 here.\n")
        (self.repo / "home/.agents/skills/spec/LICENSE.txt").unlink()
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid name 'Tutor'", result.stdout)
        self.assertIn("em or en dash", result.stdout)
        self.assertIn("spec/SKILL.md: LICENSE.txt missing", result.stdout)

    def test_build_produces_uploadable_zips(self):
        result = self.run_tool("build.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        dist = self.repo / "dist"
        names = sorted(p.stem for p in (dist / "claude-ai").glob("*.zip"))
        self.assertIn("decide", names)
        self.assertIn("tutor", names)
        with zipfile.ZipFile(dist / "claude-ai/decide.zip") as archive:
            self.assertIn("decide/SKILL.md", archive.namelist())
            head = archive.read("decide/SKILL.md").decode().split("\n---\n", 1)[0]
        description = next(l for l in head.splitlines() if l.startswith("description:"))
        self.assertLessEqual(len(description) - len('description: ""'), 200)
        with zipfile.ZipFile(dist / "project-kit.zip") as kit:
            self.assertIn("project-kit/AGENTS.md.template", kit.namelist())
        first = (dist / "claude-ai/tutor.zip").read_bytes()
        self.run_tool("build.py")
        self.assertEqual((dist / "claude-ai/tutor.zip").read_bytes(), first, "builds must be reproducible")



class CommitMsg(unittest.TestCase):
    """.githooks/commit-msg, the format of CONTRIBUTING.org (Commit messages): one line,
    type(scope): description, lower case, no body, no AI trailer. git runs it with the
    path of the message file and aborts the commit when it exits non-zero."""

    HOOK = ROOT / ".githooks" / "commit-msg"
    GOOD = [
        "feat(hooks): add a stop hook that checks the progress log",
        "docs(design): record that no agent pushes or publishes\n",
        "fix(install): retire the old review copy and its claude code link\r\n",
        "chore(repo): run ci on python 3.12\n\n# Please enter the commit message for your changes.\n#\n",
        "test(hooks): cover the guard\n# ------------------------ >8 ------------------------\n"
        "# Do not modify or remove the line above.\ndiff --git a/x b/x\n+Some Body Text\n",
        "fixup! fix(hooks): block every push and publish in every tool",
        "squash! refactor(skills): rename review to branch-review",
        # Trailer words in the subject are part of the description, not a trailer.
        "fix(install): skip the files generated by the build",
        "docs(project): say why commits carry no co-authored-by trailer",
    ]
    BAD = {
        "Feat(hooks): add x": "type",
        "feature(hooks): add x": "type",
        "feat: add x": "scope",
        "feat(Hooks): add x": "scope",
        "feat(hooks):add x": "type(scope): description",
        "feat(hooks): ": "description",
        "feat(hooks): Add x": "lower case",
        "docs(decisions): correct the cost in D-0010": "lower case",
        "feat(hooks): add x.": "period",
        "feat(hooks): add x \u2014 and y": "dash",
        "feat(hooks): add x\n\nIt also does y.": "body",
        "feat(hooks): add x\n\nCo-Authored-By: Claude <noreply@anthropic.com>": "AI",
        "feat(hooks): add x\n\n\U0001f916 Generated with Claude Code": "AI",
        "Merge branch 'feat/x'": "type",
        "Revert \"feat(hooks): add x\"": "type",
    }

    def check(self, message: str) -> subprocess.CompletedProcess:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        path = folder / "COMMIT_EDITMSG"
        path.write_bytes(message.encode("utf-8"))
        return subprocess.run([str(self.HOOK), str(path)], capture_output=True, text=True, check=False)

    def test_is_an_executable_python_script(self):
        self.assertTrue(os.access(self.HOOK, os.X_OK), "git runs only an executable hook")
        self.assertEqual(self.HOOK.read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env python3")

    def test_accepts_the_documented_format(self):
        for message in self.GOOD:
            with self.subTest(message=message):
                result = self.check(message)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_rejects_other_messages_and_says_what_to_write(self):
        for message, problem in self.BAD.items():
            with self.subTest(message=message):
                result = self.check(message)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(problem, result.stderr)
                self.assertIn("type(scope): description", result.stderr)
                self.assertIn("feat(hooks): add a stop hook", result.stderr)  # an example to follow


class GuardReplay(unittest.TestCase):
    """tools/guard_replay.py on synthetic Claude Code transcripts, in a copy of the
    repository made a git repository whose main branch holds the base guard."""

    setUp_copy, run_tool = Tools.setUp, Tools.run_tool
    GUARD = Path("home/.agents/hooks/guard_bash.py")
    MARKER = "echo replay-marker-5d1c"
    ORG_LINES = "cat <<'X'\n#+end_example\n* not a heading\nX"
    LONG = "echo " + "y" * 395
    # Appended to a guard, it blocks four more commands, as a guard change would.
    PLANT = ("\n\nPLANTED = {'git status', %r, %r, %r}\n_unplanted = decision\n\n\n"
             "def decision(text):\n"
             "    return {'planted block': True} if text in PLANTED else _unplanted(text)\n"
             % (MARKER, ORG_LINES, LONG))

    def setUp(self):
        self.setUp_copy()
        self.git("init", "-q", "-b", "main")
        self.commit("base")
        self.transcripts = self.repo.parent / "projects"
        self.out = self.repo.parent / "report.org"
        self.original = (self.repo / self.GUARD).read_text(encoding="utf-8")
        session = [
            self.call("toolu_1", "git status"), self.call("toolu_3", self.MARKER),
            self.call("toolu_4", "git push origin main"), self.call("toolu_9", self.ORG_LINES),
            self.call("toolu_10", self.LONG),
            # A copy of a call kept by Claude Code, and another record type naming the command.
            {"type": "api-request-blob", "sessionId": "s", "hash": "h",
             "message": {"role": "assistant", "content": [self.block("toolu_1", "git status")]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "git status"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_5", "name": "Bash", "input": {}},
                {"type": "tool_use", "id": "toolu_6", "name": "Bash", "input": {"command": ["git", "push"]}},
                {"type": "tool_use", "id": "toolu_7", "name": "Read", "input": {"file_path": "/x"}}]}},
            self.call("toolu_8", "echo " + "x" * 99_996),  # 100,001 characters
        ]
        self.write(self.transcripts / "-w-repo" / "s1.jsonl", session, malformed="{not json")
        self.write(self.transcripts / "-w-repo" / "s1" / "subagents" / "agent-a.jsonl",
                   [self.call("toolu_2", "git status")])
        # A resumed or forked session repeats earlier calls with their ids in a new file.
        self.write(self.transcripts / "-w-repo" / "s2.jsonl", [self.call("toolu_1", "git status")])

    def git(self, *args, folder=None):
        subprocess.run(["git", "-C", str(folder or self.repo), *args], check=True, capture_output=True, env=GIT_ENV)

    def commit(self, message: str, *paths):
        self.git("add", str(self.GUARD), *paths)
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message)

    @staticmethod
    def block(ident: str, command: str) -> dict:
        return {"type": "tool_use", "id": ident, "name": "Bash", "input": {"command": command}}

    def call(self, ident: str, command: str) -> dict:
        return {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Running it."}, self.block(ident, command)]}}

    @staticmethod
    def write(path: Path, records: list, malformed: str = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(record) for record in records] + ([malformed] if malformed else [])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def plant(self):
        (self.repo / self.GUARD).write_text(self.original + self.PLANT, encoding="utf-8")

    def replay(self, *args) -> subprocess.CompletedProcess:
        return self.run_tool("guard_replay.py", ["--base", "main", "--transcripts", self.transcripts,
                                                 "--out", self.out, *args])

    @staticmethod
    def section(report: str, title: str) -> str:
        return report.split("\n* " + title, 1)[1].split("\n* ", 1)[0]

    def test_an_unchanged_guard_changes_nothing(self):
        result = self.replay()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("newly blocked 0, newly allowed 0", result.stdout)
        report = self.out.read_text(encoding="utf-8")
        self.assertNotIn("#+begin_example", report)
        self.assertIn("- blocked by the base guard: 1\n", report)  # git push origin main
        self.assertIn("- blocked by the head guard: 1\n", report)

    def test_a_new_block_is_listed_once_with_its_calls(self):
        self.plant()
        result = self.replay()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("newly blocked 4, newly allowed 0", result.stdout)
        blocked = self.section(self.out.read_text(encoding="utf-8"), "Newly blocked")
        # Two calls (one in a subagent's transcript), repeated in a resumed session and in an
        # api-request-blob.
        self.assertEqual(blocked.count("#+begin_example\ngit status\n#+end_example"), 1)
        item = blocked.split("#+begin_example\ngit status\n")[0].rstrip("\n").rsplit("\n", 1)[1]
        self.assertIn("2 calls", item)
        self.assertIn("planted block", item)

    def test_a_removed_block_is_listed_under_newly_allowed(self):
        self.plant()
        self.commit("planted base")
        (self.repo / self.GUARD).write_text(self.original, encoding="utf-8")
        result = self.replay()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("newly blocked 0, newly allowed 4", result.stdout)
        report = self.out.read_text(encoding="utf-8")
        self.assertEqual(self.section(report, "Newly allowed").count("#+begin_example\ngit status\n"), 1)
        self.assertNotIn("#+begin_example", self.section(report, "Newly blocked"))

    def test_commands_reach_the_report_only(self):
        self.plant()
        result = self.replay()
        report = self.out.read_text(encoding="utf-8")
        self.assertIn(self.MARKER, report)
        for text in (self.MARKER, "git status", "git push", "yyyy"):
            self.assertNotIn(text, result.stdout + result.stderr)
        self.assertIn(str(self.out), result.stdout)

    def test_report_blocks_stay_valid_org(self):
        self.plant()
        self.replay()
        report = self.out.read_text(encoding="utf-8")
        # Lines that Org would read as a heading or a keyword get a leading comma.
        self.assertIn("#+begin_example\ncat <<'X'\n,#+end_example\n,* not a heading\nX\n#+end_example", report)
        # A command is cut to 300 characters, and the cut is said.
        self.assertIn("#+begin_example\necho " + "y" * 295 + "\n#+end_example", report)
        self.assertIn("cut from 400 characters", report)

    def test_unusable_input_is_counted_not_fatal(self):
        result = self.replay()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.out.read_text(encoding="utf-8")
        for line in ("- transcript files: 3", "- lines that are not JSON: 1", "- records of other types: 2",
                     "- Bash calls: 9", "- Bash calls without a command: 2",
                     "- commands over 100,000 characters (skipped): 1", "- distinct commands judged: 5"):
            self.assertIn(line + "\n", report)

    def test_usage_errors_exit_2_and_write_nothing(self):
        for label, args in (("bad ref", ["--base", "no-such-ref"]),
                            ("missing head", ["--head", self.repo / "no-guard.py"]),
                            ("missing transcripts", ["--transcripts", self.repo / "no-folder"])):
            with self.subTest(label=label):
                result = self.replay(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(self.out.exists())

    def test_the_default_report_goes_to_the_main_checkout(self):
        # Run from a linked worktree, the report lands in the main checkout's .private/,
        # since removing the worktree deletes its ignored files.
        self.commit("tool", "tools/guard_replay.py")
        worktree = self.repo.parent / "repo-wt"
        self.git("worktree", "add", "-q", "-b", "wt", str(worktree))
        result = subprocess.run([sys.executable, "-B", str(worktree / "tools/guard_replay.py"),
                                 "--transcripts", str(self.transcripts)],
                                capture_output=True, text=True, check=False, env=GIT_ENV)
        self.assertEqual(result.returncode, 0, result.stderr)
        reports = list((self.repo / ".private" / "evidence").glob("guard-replay-*.org"))
        self.assertEqual(len(reports), 1)
        self.assertIn(str(reports[0]), result.stdout)
        self.assertFalse((worktree / ".private").exists())

    def test_a_guard_without_decision_gets_the_same_keys(self):
        # A base older than decision() is judged by parse_commands, rough_commands and
        # command_reasons, as main() did before it.
        replay = load(self.repo / "tools" / "guard_replay.py", "guard_replay_under_test")
        battery = load(ROOT / "tests" / "test_hooks.py", "hooks_tests_for_replay").GuardBypassBattery
        text = (ROOT / self.GUARD).read_text(encoding="utf-8")
        node = next(node for node in ast.parse(text).body
                    if isinstance(node, ast.FunctionDef) and node.name == "decision")
        lines = text.split("\n")
        older = self.repo.parent / "guard_without_decision.py"
        older.write_text("\n".join(lines[:node.lineno - 1] + lines[node.end_lineno:]), encoding="utf-8")
        old_guard = replay.load_guard(older, "guard_without_decision")
        self.assertFalse(hasattr(old_guard, "decision"))
        old, new = replay.verdict_of(old_guard), replay.verdict_of(replay.load_guard(ROOT / self.GUARD, "head"))
        for command in battery.BLOCKED + battery.NEAR_MISSES:
            with self.subTest(command=command):
                self.assertEqual(set(old(command)), set(new(command)))


if __name__ == "__main__":
    unittest.main()
