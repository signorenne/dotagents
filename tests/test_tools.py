# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Tests for the tools in tools/ on a copy of the repository."""

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
        write("docs/notes.md", "not loaded as instructions: <!-- c -->\n")
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

    def test_validate_reports_hidden_characters_in_every_text_file(self):
        # Not only the instruction files: a zero width or bidirectional character in code,
        # tests or docs is reported too (a bidirectional control can make code read
        # differently from how it runs). The HTML comment check stays on the Markdown
        # instruction files, so the comment in docs/notes.md passes.
        (self.repo / "docs/notes.md").write_text("a\u200bb <!-- c -->\n", encoding="utf-8")
        (self.repo / "tools/helper.py").write_text("x = 1  # a\u2067b\u2069\n", encoding="utf-8")
        readme = self.repo / "README.org"
        readme.write_text("zero\u200dwidth\n" + readme.read_text(encoding="utf-8"), encoding="utf-8")
        result = self.run_tool("validate.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        hidden = "invisible or bidirectional character"
        reported = sorted(line for line in result.stdout.splitlines() if hidden in line or "HTML comment" in line)
        self.assertEqual(reported, sorted([
            f"FAIL docs/notes.md:1:2: {hidden} U+200B",
            f"FAIL tools/helper.py:1:11: {hidden} U+2067",
            f"FAIL tools/helper.py:1:13: {hidden} U+2069",
            f"FAIL README.org:1:5: {hidden} U+200D",
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
        # The battery parses; an unclosed quote takes the rough split in both.
        for command in battery.BLOCKED + battery.NEAR_MISSES + ["git push 'origin"]:
            with self.subTest(command=command):
                self.assertEqual(set(old(command)), set(new(command)))
        self.assertTrue(old("git push 'origin"))


class Benchmark(unittest.TestCase):
    """tools/benchmark.py on a synthetic dataset; its run and grade meet only fake claude,
    podman and harness programs, never the real ones."""

    TOOL = ROOT / "tools" / "benchmark.py"
    AGENT_FIELDS = {"instance_id", "repo", "base_commit", "problem_statement", "image"}
    LONG = {"1-4 hours", ">4 hours"}

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        self.dataset = self.folder / "dataset.jsonl"
        repos, buckets = ["a/one", "b/two", "c/three"], ["1-4 hours", ">4 hours", "15 min - 1 hour", "<15 min fix"]
        # Every field only grading may use carries a HIDDEN marker, so a leak shows.
        self.rows = [{
            "instance_id": f"{repos[index % 3].split('/')[1]}__{index}", "repo": repos[index % 3],
            "base_commit": f"{index:040x}", "problem_statement": f"Problem {index}: the widget breaks.",
            "image": f"swebench/sweb.eval.x86_64.task_{index}:latest", "difficulty": buckets[index % 4],
            "patch": f"HIDDEN-GOLD-{index}", "hints_text": f"HIDDEN-HINT-{index}",
            "test_patch": f"diff --git a/tests/test_{index}.py b/tests/test_{index}.py\n+HIDDEN-TEST-{index}\n",
            "eval_script": f"HIDDEN-EVAL-{index}", "log_parser": f"HIDDEN-PARSER-{index}",
            "FAIL_TO_PASS": json.dumps([f"HIDDEN-F2P-{index}"]), "PASS_TO_PASS": json.dumps([f"HIDDEN-P2P-{index}"]),
        } for index in range(16)]
        self.dataset.write_text("".join(json.dumps(row) + "\n" for row in self.rows), encoding="utf-8")

    def tool(self, *args, env=None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(self.TOOL), *map(str, args)],
                              capture_output=True, text=True, check=False, env=env)

    def select(self, count: int, seed: int, name: str = "tasks.json") -> dict:
        out = self.folder / name
        result = self.tool("select", "--dataset", self.dataset, "--count", count, "--seed", seed, "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_select_is_seeded_and_keeps_the_longest_buckets(self):
        first, again = self.select(4, 7), self.select(4, 7, "again.json")
        ids = [task["agent"]["instance_id"] for task in first["tasks"]]
        self.assertEqual(ids, [task["agent"]["instance_id"] for task in again["tasks"]])
        self.assertEqual(len(set(ids)), 4)
        rows = {row["instance_id"]: row for row in self.rows}
        self.assertTrue(all(rows[ident]["difficulty"] in self.LONG for ident in ids), ids)
        # One task per repository before a second from any (the long tasks span 3 repositories).
        self.assertEqual(len({rows[ident]["repo"] for ident in ids[:3]}), 3)
        # Another seed draws from the same 8 long tasks in another order.
        others = {task["agent"]["instance_id"] for seed in range(1, 6) for task in self.select(4, seed, "o.json")["tasks"]}
        self.assertTrue(others <= {row["instance_id"] for row in self.rows if row["difficulty"] in self.LONG})

    def test_select_keeps_the_grading_fields_apart(self):
        for task in self.select(8, 3)["tasks"]:
            self.assertEqual(set(task["agent"]), self.AGENT_FIELDS)
            self.assertNotIn("HIDDEN", json.dumps(task["agent"]))
            for field in ("patch", "test_patch", "eval_script", "log_parser", "FAIL_TO_PASS", "PASS_TO_PASS"):
                self.assertIn("HIDDEN", task["grading"][field])

    def test_select_refuses_more_tasks_than_the_buckets_hold(self):
        result = self.tool("select", "--dataset", self.dataset, "--count", 9, "--seed", 1, "--out", self.folder / "t.json")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.folder / "t.json").exists())


# Fake programs for benchmark.py run: each logs its call (argv, stdin, environment facts)
# to BENCH_FAKE_LOG and answers from the scenario in BENCH_FAKE_SCENARIO. claude answers
# as the agent, or as the maintainer when called with --tools; a None answer prints nothing.
FAKE_CLAUDE = r'''
import json, os, sys
DEFAULTS = {
    "agent": {"type": "result", "subtype": "success", "is_error": False, "result": "I fixed the issue.",
              "session_id": "sess-1", "num_turns": 5, "duration_ms": 1000, "total_cost_usd": 0.5,
              "modelUsage": {"claude-opus-5-5": {}}, "permission_denials": []},
    "maintainer": {"type": "result", "subtype": "success", "is_error": False, "result": "DONE",
                   "total_cost_usd": 0.01},
}
argv, data = sys.argv[1:], sys.stdin.read()
role = "maintainer" if "--tools" in argv else "agent"
path = os.environ["BENCH_FAKE_SCENARIO"]
with open(path) as handle:
    scenario = json.load(handle)
queue = scenario.setdefault(role, [])
response = queue.pop(0) if queue else DEFAULTS[role]
with open(path, "w") as handle:
    json.dump(scenario, handle)
secrets = [name for name, value in os.environ.items() if "REFRESH-SECRET" in value or "MCP-SECRET" in value]
entry = {"program": "claude", "role": role, "argv": argv, "stdin": data, "cwd_files": sorted(os.listdir(".")),
         "container": os.environ.get("BENCH_FAKE_CONTAINER"), "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
         "secrets_in_env": secrets}
with open(os.environ["BENCH_FAKE_LOG"], "a") as handle:
    handle.write(json.dumps(entry) + "\n")
expire, refresh = scenario.pop("expire_login", None), scenario.pop("refresh_login", None)
if role == "agent" and (expire or refresh):  # the host's login expires, or is refreshed, meanwhile
    with open(path, "w") as handle:
        json.dump(scenario, handle)
    with open(os.environ["BENCH_FAKE_CREDENTIALS"]) as handle:
        login = json.load(handle)
    if expire:
        login["claudeAiOauth"]["expiresAt"] = 0
    else:
        login["claudeAiOauth"]["accessToken"] = refresh
    with open(os.environ["BENCH_FAKE_CREDENTIALS"], "w") as handle:
        json.dump(login, handle)
if response is None:
    sys.exit(1)
print(json.dumps(response))
'''
FAKE_PODMAN = r'''
import json, os, re, subprocess, sys
argv = sys.argv[1:]
data = sys.stdin.read() if "-i" in argv else ""
with open(os.environ["BENCH_FAKE_SCENARIO"]) as handle:
    scenario = json.load(handle)
with open(os.environ["BENCH_FAKE_LOG"], "a") as handle:
    handle.write(json.dumps({"program": "podman", "argv": argv, "stdin": data}) + "\n")
if argv[0] == "run":
    print("c0ffee")
    sys.exit(0)
if argv[0] != "exec":
    sys.exit(0)
index, passed, user = 1, {}, "root"
while argv[index].startswith("-"):
    if argv[index] == "-e":  # -e NAME takes the value from podman's environment, -e NAME=VALUE gives it
        name, _, value = argv[index + 1].partition("=")
        passed[name] = value if "=" in argv[index + 1] else os.environ.get(name, "")
    if argv[index] == "-u":
        user = argv[index + 1]
    index += 2 if argv[index] in ("-u", "-w", "-e") else 1
container, command = argv[index], argv[index + 1:]
# A task image has no user agent until a run creates it (users: the containers that have it).
if "useradd" in " ".join(command):
    scenario["users"] = scenario.get("users", []) + [container]
    with open(os.environ["BENCH_FAKE_SCENARIO"], "w") as handle:
        json.dump(scenario, handle)
elif user == "agent" and container not in scenario.get("users", []):
    print("Error: unable to find user agent: no matching entries in passwd file", file=sys.stderr)
    sys.exit(255)
if command[0] == "claude":
    # interrupt_at: the agent call (1, 2...) at which the user presses Ctrl-C in the tool.
    scenario["agent_calls"] = scenario.get("agent_calls", 0) + 1
    with open(os.environ["BENCH_FAKE_SCENARIO"], "w") as handle:
        json.dump(scenario, handle)
    if scenario["agent_calls"] == scenario.get("interrupt_at"):
        os.kill(os.getppid(), 2)  # SIGINT to benchmark.py
        sys.exit(130)
    # A container sees only the variables podman exec passes with -e.
    env = {name: value for name, value in os.environ.items() if name == "PATH" or name.startswith("BENCH_FAKE_")}
    env.update(passed, BENCH_FAKE_CONTAINER=container)
    sys.exit(subprocess.run(["claude", *command[1:]], input=data, text=True, env=env).returncode)
if command[0] in ("find", "cat"):
    # transcripts: {path: text}, the session files Claude Code wrote in the container; without
    # the key, its projects folder does not exist, as when no session was saved.
    files = scenario.get("transcripts")
    target = command[1]
    if files is None or (command[0] == "cat" and target not in files):
        print("%s: '%s': No such file or directory" % (command[0], target), file=sys.stderr)
        sys.exit(1)
    if command[0] == "cat":
        sys.stdout.write(files[target])
    else:
        print("\n".join(path for path in files if path.startswith(target + "/")))
elif "# dotagents probe" in " ".join(command):
    print("guard=%d" % scenario.get("probe_guard", 2))
    print("skills=%d" % scenario.get("skills", 2))
    print("claude_md=%s" % scenario.get("claude_md", "@~/.agents/AGENTS.md"))
elif command[0] == "git":
    # trees: each worktree's change against head, the commit the image starts on;
    # branches: {ref: [time, change against head]}; after_base: {commit: [the files it
    # changes against base_commit]}, the image's own; setup_diff: head's change against
    # base_commit, which a diff against any commit but head shows too; prunable: worktrees
    # whose folder is gone, which git lists as prunable and cannot change into; fail:
    # {words: message or [exit, message]}, a git call holding every word of a key fails with
    # that message and exit (128, git's fatal exit, unless given).
    path = command[command.index("-C") + 1] if "-C" in command else "/testbed"
    prunable = scenario.get("prunable", [])
    if path in prunable:
        print("fatal: cannot change to '%s': No such file or directory" % path, file=sys.stderr)
        sys.exit(128)
    for words, failure in scenario.get("fail", {}).items():
        if all(word in command for word in words.split()):
            code, message = failure if isinstance(failure, list) else (128, failure)
            print(message, file=sys.stderr)
            sys.exit(code)
    # unborn: worktrees on a branch with no commits yet (git checkout --orphan), where
    # rev-parse -q --verify HEAD exits 1 with no output and log exits 128.
    if path in scenario.get("unborn", []) and "rev-parse" in command:
        sys.exit(1)
    if path in scenario.get("unborn", []) and "log" in command:
        print("fatal: your current branch 'orphan' does not have any commits yet", file=sys.stderr)
        sys.exit(128)
    trees = scenario.get("trees", {"/testbed": scenario.get("diff", "")})
    branches = scenario.get("branches", {})
    after_base = scenario.get("after_base", {})
    head = scenario.get("head", "HEAD-COMMIT")
    setup = "" if head in command else scenario.get("setup_diff", "")
    def visible(text):  # git's exclude pathspec for the notes
        if ":(exclude).private" not in command:
            return text
        return "".join(section for section in re.split(r"(?m)^(?=diff --git )", text)
                       if not section.startswith("diff --git a/.private/"))
    refs = [word for word in command if word in branches]
    commits = [word for word in command if word in after_base]
    if "rev-list" in command:
        # off_head: commits after base_commit on another branch, which only --all reaches.
        print("\n".join(commit for commit in after_base if "--all" in command
                        or commit not in scenario.get("off_head", [])))
    elif "--name-only" in command and commits:
        # [old, new] is a rename, which git lists by its new name alone without --no-renames.
        names = [name for entry in after_base[commits[0]] for name in
                 ((entry if "--no-renames" in command else entry[1:]) if isinstance(entry, list) else [entry])]
        sys.stdout.write("".join(name + ("\0" if "-z" in command else "\n") for name in names))
    elif "rev-parse" in command:
        print(head)
    elif "worktree" in command:
        for tree in list(trees) + prunable:
            print("worktree %s\nHEAD %s" % (tree, head))
            if tree in prunable:
                print("prunable gitdir file points to non-existent location")
            print()
    elif "for-each-ref" in command:
        print("\n".join("%d %s" % (when, ref) for ref, (when, _) in branches.items()))
    elif "log" in command:
        print(scenario.get("times", {}).get(path, 0))
    elif "diff" in command:
        if refs:  # base then ref; the other order is a reversed change
            reversed_order = command[command.index(refs[0]) - 1] in ("--binary", "--quiet")
            text = "REVERSED\n" if reversed_order else visible(setup + branches[refs[0]][1])
        else:
            text = visible(setup + trees.get(path, ""))
        if "--quiet" in command:
            sys.exit(1 if text else 0)
        sys.stdout.write(text)
'''


class BenchmarkRun(unittest.TestCase):
    """benchmark.py run against fake claude and podman programs (FAKE_CLAUDE, FAKE_PODMAN)."""

    setUp_dataset, tool, select = Benchmark.setUp, Benchmark.tool, Benchmark.select
    TOOL = Benchmark.TOOL
    TOKEN = "TOKEN-SECRET-123"
    INSTRUCTIONS = "Resolve this issue in the repository in the current folder."

    def setUp(self):
        self.setUp_dataset()
        self.select(2, 5)
        self.tasks = self.folder / "tasks.json"
        self.select(1, 5, "one.json")
        self.one = self.folder / "one.json"
        programs = self.folder / "bin"
        programs.mkdir()
        for name, body in (("claude", FAKE_CLAUDE), ("podman", FAKE_PODMAN)):
            (programs / name).write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
            (programs / name).chmod(0o755)
        self.scenario, self.log = self.folder / "scenario.json", self.folder / "calls.jsonl"
        self.set_scenario({})
        self.env = {**os.environ, "PATH": str(programs), "BENCH_FAKE_SCENARIO": str(self.scenario),
                    "BENCH_FAKE_LOG": str(self.log), "BENCH_FAKE_CREDENTIALS": str(self.folder / "credentials.json")}
        # An installed method: the files install.py writes, and a personal setting.
        self.home = self.folder / "home"
        settings = {"model": "personal", "theme": "dark", "permissions": {"deny": ["Bash(git push *)"]},
                    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command":
                              'python3 "$HOME/.agents/hooks/guard_bash.py" --tool claude'}]}],
                              "Stop": [{"hooks": [{"type": "command", "command":
                                        'python3 "$HOME/.agents/hooks/claim_check.py" || true'}]}]}}
        for name, text in ((".claude/CLAUDE.md", "@~/.agents/AGENTS.md\n"), (".claude/skills/one/SKILL.md", "one"),
                           (".claude/skills/two/SKILL.md", "two"), (".claude/agents/scout.md", "scout"),
                           (".claude/rules/dotagents-gates.md", "rule"), (".agents/AGENTS.md", "rules"),
                           (".agents/hooks/guard_bash.py", "# guard"), (".claude/settings.json", json.dumps(settings))):
            (self.home / name).parent.mkdir(parents=True, exist_ok=True)
            (self.home / name).write_text(text, encoding="utf-8")
        # The login file: only the Claude access token may reach a container.
        self.credentials = self.folder / "credentials.json"
        self.credentials.write_text(json.dumps({
            "claudeAiOauth": {"accessToken": self.TOKEN, "refreshToken": "REFRESH-SECRET",
                              "expiresAt": int((time.time() + 86400) * 1000)},
            "mcpOAuth": {"plugin:x:slack|1": {"accessToken": "MCP-SECRET"}}}), encoding="utf-8")
        self.python = self.folder / "python"
        (self.python / "bin").mkdir(parents=True)
        (self.python / "bin" / "python3").write_text("", encoding="utf-8")
        self.rundir = self.folder / "run"

    def set_scenario(self, scenario: dict):
        self.scenario.write_text(json.dumps(scenario), encoding="utf-8")

    def run_bench(self, *extra, tasks=None, arms="method,plain", runs=1, cap=4, rundir=None, env=None):
        return self.tool("run", "--tasks", tasks or self.tasks, "--runs", runs, "--arms", arms,
                         "--model", "claude-opus-5-5", "--maintainer-model", "claude-sonnet-5-5", "--cap-usd", cap,
                         "--out", rundir or self.rundir, "--method-home", self.home, "--credentials", self.credentials,
                         "--hooks-python", self.python, *extra, env=env or self.env)

    def calls(self, program: str, role: str = None) -> list:
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        return [entry for entry in entries if entry["program"] == program and role in (None, entry.get("role"))]

    def records(self, rundir=None) -> dict:
        return {path.parent.name: json.loads(path.read_text(encoding="utf-8"))
                for path in ((rundir or self.rundir) / "runs").glob("*/record.json")}

    @staticmethod
    def option(argv: list, name: str):
        return argv[argv.index(name) + 1] if name in argv else None

    def test_both_arms_get_the_same_call_except_safe_mode(self):
        result = self.run_bench()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        agent = self.calls("claude", "agent")
        self.assertEqual(len(agent), 4)  # 2 tasks x 2 arms x 1 run
        for call in agent:
            argv = call["argv"]
            self.assertEqual(("--safe-mode" in argv), ".plain." in call["container"], call["container"])
            self.assertEqual([self.option(argv, name) for name in ("--model", "--effort", "--permission-mode",
                                                                   "--disallowed-tools", "--output-format")],
                             ["claude-opus-5-5", "high", "bypassPermissions", "WebFetch,WebSearch", "json"])
            self.assertIn(self.INSTRUCTIONS, call["stdin"])
            self.assertNotIn("method", call["stdin"].lower())
            self.assertEqual(call["token"], self.TOKEN)
            self.assertEqual(call["secrets_in_env"], [])
        prompts = {}
        for call in agent:
            prompts.setdefault(call["stdin"], set()).add(call["container"].split(".")[1])
        self.assertEqual(list(prompts.values()), [{"method", "plain"}] * 2)  # one prompt per task, both arms
        # No field only grading may use, and no secret, reaches a program's arguments or input.
        logged = self.log.read_text(encoding="utf-8")
        self.assertNotIn("HIDDEN", logged)
        for secret in ("REFRESH-SECRET", "MCP-SECRET"):
            self.assertNotIn(secret, logged)
        self.assertNotIn(self.TOKEN, json.dumps([entry["argv"] for entry in self.calls("podman") + agent]))
        self.assertNotIn(self.TOKEN, result.stdout + result.stderr)
        # The simulated maintainer: on the host, no tools, its own model, an empty folder, its own login.
        for call in self.calls("claude", "maintainer"):
            self.assertIn("--safe-mode", call["argv"])
            self.assertEqual(self.option(call["argv"], "--tools"), "")
            self.assertEqual(self.option(call["argv"], "--model"), "claude-sonnet-5-5")
            self.assertEqual((call["cwd_files"], call["token"], call["container"]), ([], None, None))
        records = self.records()
        self.assertEqual(len(records), 4)
        for name, record in records.items():
            self.assertEqual((record["stop"], record["finished"]), ("DONE", True), name)
            self.assertEqual(record["probe"]["passed"] if record["arm"] == "method" else record["probe"],
                             True if record["arm"] == "method" else None)
            self.assertTrue((self.rundir / "runs" / name / "prediction.diff").exists())

    def test_the_method_arm_gets_the_method_files_and_an_adapted_python(self):
        self.run_bench(tasks=self.one, arms="method")
        staged = self.rundir / "method"
        settings = json.loads((staged / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertNotIn("model", settings)  # the maintainer's own settings stay out
        commands = [hook["command"] for groups in settings["hooks"].values() for group in groups
                    for hook in group["hooks"]]
        self.assertTrue(all(command.startswith('/opt/dotagents-python/bin/python3 "$HOME/.agents/hooks/')
                            for command in commands), commands)
        for name in (".claude/CLAUDE.md", ".claude/skills/two/SKILL.md", ".claude/agents/scout.md",
                     ".claude/rules/dotagents-gates.md", ".agents/hooks/guard_bash.py"):
            self.assertTrue((staged / name).is_file(), name)
        run = [entry["argv"] for entry in self.calls("podman") if entry["argv"][0] == "run"][0]
        self.assertIn(f"{self.python}:/opt/dotagents-python:ro", run)
        self.assertEqual(run[-4:-2], ["--entrypoint", "sleep"])
        self.assertTrue(run[-2].startswith("docker.io/swebench/"), run[-2])  # the image, fully qualified
        record = next(iter(self.records().values()))
        self.assertIn("python3", " ".join(record["adaptations"]))

    def test_dry_run_starts_nothing(self):
        empty = self.folder / "empty"
        empty.mkdir()
        result = self.run_bench("--dry-run", env={**self.env, "PATH": str(empty)})
        self.assertEqual(result.returncode, 0, result.stderr)
        for task in json.loads(self.tasks.read_text(encoding="utf-8"))["tasks"]:
            for arm in ("method", "plain"):
                self.assertIn(f"{task['agent']['instance_id']}.{arm}.1 share 1.00", result.stdout)
        self.assertIn("podman: missing", result.stdout)
        self.assertIn("claude: missing", result.stdout)
        self.assertIn("images: not checked (podman missing)", result.stdout)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.rundir / "runs").exists())

    def test_dry_run_checks_each_image_with_podman_only(self):
        # The check a run makes before its first call, once per task: a task whose image
        # would stop its runs shows before any run spends money.
        tasks = json.loads(self.tasks.read_text(encoding="utf-8"))["tasks"]
        tasks[0]["grading"]["patch"] = ("diff --git a/pyproject.toml b/pyproject.toml\n--- a/pyproject.toml\n"
                                        "+++ b/pyproject.toml\n@@ -1 +1 @@\n-a\n+b\n")
        stops, passes = (task["agent"]["instance_id"] for task in tasks)
        checked = self.folder / "checked.json"
        checked.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        self.set_scenario({"after_base": {"4b48727": ["pyproject.toml"]}})
        result = self.run_bench("--dry-run", tasks=checked)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"{stops} image: a run would stop: commit 4b48727 after base_commit changes pyproject.toml",
                      result.stdout)
        self.assertIn(f"{passes} image: ok, commits after base_commit: 1", result.stdout)
        self.assertEqual(self.calls("claude"), [])
        self.assertFalse(self.rundir.exists())
        podman = [entry["argv"] for entry in self.calls("podman")]
        started = [argv for argv in podman if argv[0] == "run"]
        self.assertEqual([argv[-2] for argv in started], [f"docker.io/{task['agent']['image']}" for task in tasks])
        for argv in started:  # nothing bound in, and every container removed at the end
            self.assertNotIn("-v", argv)
            name = argv[argv.index("--name") + 1]
            self.assertEqual([call for call in podman if name in call][-1], ["rm", "-f", "-t", "0", name])
        # The bare image, as a run finds it before its setup: no user agent created, git as root.
        execs = [argv for argv in podman if argv[0] == "exec"]
        self.assertEqual(([argv for argv in execs if "useradd" in " ".join(argv)],
                          sorted({argv[2] for argv in execs if argv[1] == "-u"})), ([], ["root"]))

    def test_dry_run_reports_a_non_empty_prediction_from_an_untouched_image(self):
        # A run's prediction step, taken on the image before any agent: a change it finds
        # there (a prediction base that does not match the image, files git add -A sweeps
        # in) would ride in every run's prediction. The bare image has no user agent, so a
        # git that ran as agent would fail and find nothing.
        ident = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]["agent"]["instance_id"]
        image = {"head": "4b48727", "after_base": {"4b48727": ["pyproject.toml"]}, "setup_diff": self.PIN,
                 "branches": {"refs/heads/main": [100, ""]}}
        stops = f"{ident} image: a run would stop: the untouched image gives a non-empty prediction from "
        for label, scenario, line in (
                ("setup commit only", {}, f"{ident} image: ok, commits after base_commit: 1, prediction: empty"),
                ("untracked file", {"trees": {"/testbed": self.FIX}}, stops + "/testbed (src/widget.py)"),
                ("branch", {"branches": {"refs/heads/main": [100, ""], "refs/heads/old": [50, self.OLD]}},
                 stops + "branch refs/heads/old (src/old.py)")):
            with self.subTest(label=label):
                self.log.unlink(missing_ok=True)
                self.set_scenario({**image, **scenario})
                result = self.run_bench("--dry-run", tasks=self.one)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(line + "\n", result.stdout)
                self.assertEqual(self.calls("claude"), [])
                self.assertFalse(self.rundir.exists())

    def test_the_cap_stops_runs_before_the_total_passes_it(self):
        # A share of 1 (4 runs under 4): the first run overshoots to 3.5, its share used up
        # before the maintainer is asked, so a second share would pass the cap.
        self.set_scenario({"agent": [{"subtype": "success", "is_error": False, "result": "Fixed.",
                                      "session_id": "s", "num_turns": 9, "total_cost_usd": 3.5}]})
        result = self.run_bench()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("claude", "agent")), 1)
        self.assertEqual(self.calls("claude", "maintainer"), [])
        self.assertIn("3 runs not made", result.stdout)
        self.assertEqual(len(json.loads((self.rundir / "not-made.json").read_text(encoding="utf-8"))), 3)
        record = next(iter(self.records().values()))
        self.assertEqual((record["stop"], record["spend"]), ("budget", 3.5))

    def test_each_call_gets_the_remaining_share(self):
        self.set_scenario({
            "agent": [{"subtype": "success", "is_error": False, "result": "A or B? I recommend A.",
                       "session_id": "sess-9", "num_turns": 3, "total_cost_usd": 0.5},
                      {"subtype": "success", "is_error": False, "result": "Done with A.",
                       "session_id": "sess-9", "num_turns": 4, "total_cost_usd": 1.2}],
            "maintainer": [{"result": "Use A.", "total_cost_usd": 0.1}, {"result": "DONE", "total_cost_usd": 0.1}]})
        self.run_bench(tasks=self.one, arms="method", cap=2)  # one run, a share of 2
        first, second = self.calls("claude", "agent")
        self.assertAlmostEqual(float(self.option(first["argv"], "--max-budget-usd")), 2.0)
        self.assertNotIn("--resume", first["argv"])
        self.assertEqual(self.option(second["argv"], "--resume"), "sess-9")
        self.assertEqual(second["stdin"], "Use A.")
        self.assertAlmostEqual(float(self.option(second["argv"], "--max-budget-usd")), 1.4)  # 2 - 0.5 - 0.1
        asked = [float(self.option(call["argv"], "--max-budget-usd")) for call in self.calls("claude", "maintainer")]
        self.assertEqual([round(value, 4) for value in asked], [1.5, 0.7])
        record = next(iter(self.records().values()))
        # The last agent result already holds the earlier call's cost.
        self.assertAlmostEqual(record["spend"], 1.4)
        self.assertAlmostEqual(record["agent_cost"], 1.2)
        self.assertAlmostEqual(record["maintainer_cost"], 0.2)

    def test_the_maintainer_loop_stops(self):
        reply = {"result": "Go ahead.", "total_cost_usd": 0.01}
        for label, maintainer, agent_calls, stop in (
                ("reply limit", [reply] * 10, 7, "reply limit"), ("done", [], 1, "DONE"),
                ("done inside a reply", [{"result": "Not DONE yet: add a test.", "total_cost_usd": 0.01}], 2, "DONE"),
                ("no result", [None], 1, "DONE"),
                ("budget stop", [{"subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 0.02}], 1,
                 "DONE")):
            with self.subTest(label=label):
                self.log.unlink(missing_ok=True)
                self.set_scenario({"maintainer": maintainer})
                rundir = self.folder / label.replace(" ", "-")
                result = self.run_bench(tasks=self.one, arms="plain", rundir=rundir)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(self.calls("claude", "agent")), agent_calls)
                record = next(iter(self.records(rundir).values()))
                self.assertEqual(record["stop"], stop)
                self.assertEqual(len(record["maintainer"]), min(agent_calls, 6))

    def test_a_failed_probe_is_an_error_not_a_run(self):
        # The guard lets a push through, a skill is missing, or CLAUDE.md lost its import.
        for label, scenario in (("guard", {"probe_guard": 0}), ("skills", {"skills": 1}),
                                ("rules", {"claude_md": "# empty"})):
            with self.subTest(label=label):
                self.log.unlink(missing_ok=True)
                self.set_scenario(scenario)
                rundir = self.folder / f"probe-{label}"
                result = self.run_bench(tasks=self.one, rundir=rundir)
                self.assertEqual(result.returncode, 0, result.stderr)
                containers = [call["container"] for call in self.calls("claude", "agent")]
                self.assertEqual([name.split(".")[1] for name in containers], ["plain"])
                method = next(record for record in self.records(rundir).values() if record["arm"] == "method")
                self.assertEqual((method["stop"], method["probe"]["passed"], method["calls"]), ("error", False, []))

    def test_a_commit_after_base_may_change_only_files_no_hidden_patch_changes(self):
        # A SWE-bench setup commit may pin the environment (astropy-13398's pins setuptools
        # in pyproject.toml); one that changes a file of the gold patch or of the hidden test
        # patch may hold the fix or the tests, so the run stops before the agent starts.
        task = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]
        task["grading"]["patch"] = ("diff --git a/src/widget.py b/src/widget.py\n--- a/src/widget.py\n"
                                    "+++ b/src/widget.py\n@@ -1 +1 @@\n-a\n+b\n")
        test_path = task["grading"]["test_patch"].split(" b/", 1)[1].split("\n", 1)[0]
        tasks = self.folder / "gold-paths.json"
        tasks.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
        # A rename's old side is a changed file too; a commit on another branch counts as well.
        for label, after_base, off_head, commit, touched in (
                ("pin", {"4b48727": ["pyproject.toml"]}, [], "4b48727", None),
                ("gold", {"4b48727": ["pyproject.toml", "src/widget.py"]}, [], "4b48727", "src/widget.py"),
                ("test", {"4b48727": [test_path]}, [], "4b48727", test_path),
                ("rename", {"4b48727": [["src/widget.py", "src/gadget.py"]]}, [], "4b48727", "src/widget.py"),
                ("other branch", {"4b48727": ["pyproject.toml"], "5d1e0aa": ["src/widget.py"]}, ["5d1e0aa"],
                 "5d1e0aa", "src/widget.py")):
            with self.subTest(label=label):
                self.log.unlink(missing_ok=True)
                self.set_scenario({"after_base": after_base, "off_head": off_head})
                rundir = self.folder / f"after-base-{label}"
                result = self.run_bench(tasks=tasks, arms="plain", rundir=rundir)
                self.assertEqual(result.returncode, 0, result.stderr)
                [record] = self.records(rundir).values()
                agent = self.calls("claude", "agent")
                if touched is None:
                    self.assertEqual((record["stop"], record["error"]), ("DONE", None))
                    self.assertEqual(record["commits_after_base"], ["4b48727"])
                    self.assertEqual(len(agent), 1)
                else:
                    self.assertEqual((record["stop"], record["calls"], agent), ("error", [], []))
                    self.assertIn(commit, record["error"])
                    self.assertIn(touched, record["error"])
                    self.assertNotIn("pyproject.toml", record["error"])

    def test_a_git_failure_before_the_agent_stops_the_run_as_an_error(self):
        # Each git step before the first call (the commits after base_commit, the files each
        # changes, the commit the image starts on) that fails would otherwise pass for "no
        # commit" or "no file": the run stops as an error, and the dry run shows the stop.
        ident = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]["agent"]["instance_id"]
        bad = "fatal: bad object"
        for label, fail, error in (
                ("rev-list", {"rev-list": bad}, f"list the commits after base_commit: {bad}"),
                ("name-only diff", {"--name-only": bad}, f"compare commit 4b48727 with base_commit: {bad}"),
                ("rev-parse", {"rev-parse": bad}, f"read the commit the image starts on: {bad}")):
            scenario = {"after_base": {"4b48727": ["pyproject.toml"]}, "fail": fail}
            with self.subTest(label=label):
                self.log.unlink(missing_ok=True)
                self.set_scenario(scenario)
                rundir = self.folder / f"before-{label.replace(' ', '-')}"
                result = self.run_bench(tasks=self.one, arms="plain", rundir=rundir)
                self.assertEqual(result.returncode, 0, result.stderr)
                [record] = self.records(rundir).values()
                self.assertEqual((record["stop"], record["error"], record["calls"]), ("error", error, []))
                self.assertEqual(self.calls("claude"), [])
                self.set_scenario(scenario)
                result = self.run_bench("--dry-run", tasks=self.one, rundir=self.folder / "dry")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"{ident} image: a run would stop: {error}\n", result.stdout)

    NOTES = ("diff --git a/.private/progress/fix.org b/.private/progress/fix.org\nnew file mode 100644\n"
             "--- /dev/null\n+++ b/.private/progress/fix.org\n@@ -0,0 +1 @@\n+notes\n")
    FIX = "diff --git a/src/widget.py b/src/widget.py\n--- a/src/widget.py\n+++ b/src/widget.py\n@@ -1 +1 @@\n-a\n+b\n"
    OLD = "diff --git a/src/old.py b/src/old.py\n--- a/src/old.py\n+++ b/src/old.py\n@@ -1 +1 @@\n-a\n+c\n"

    def test_the_prediction_finds_the_change_outside_the_notes(self):
        # The method's notes in /testbed/.private are not the change; the change may sit in
        # /testbed, in another worktree, or on the newest branch that differs from base_commit.
        for label, scenario, source, prediction in (
                ("testbed", {"trees": {"/testbed": self.NOTES + self.FIX}}, "/testbed", self.FIX),
                ("worktree", {"trees": {"/testbed": self.NOTES, "/home/agent/fix": self.NOTES + self.FIX},
                              "times": {"/home/agent/fix": 100}}, "worktree /home/agent/fix", self.FIX),
                ("branch", {"trees": {"/testbed": self.NOTES},
                            "branches": {"refs/heads/old": [100, self.OLD],
                                         "refs/heads/fix": [200, self.NOTES + self.FIX]}},
                 "branch refs/heads/fix", self.FIX),
                ("notes only", {"trees": {"/testbed": self.NOTES}}, "none", ""),
                # A worktree whose folder the agent deleted holds no change; its commits stay on its branch.
                ("deleted worktree", {"trees": {"/testbed": self.NOTES}, "prunable": ["/home/agent/fix"],
                                      "branches": {"refs/heads/fix": [200, self.FIX]}}, "branch refs/heads/fix",
                 self.FIX),
                # A worktree on a branch with no commits yet (checkout --orphan) has no commit time.
                ("unborn worktree", {"trees": {"/testbed": self.NOTES, "/home/agent/new": self.FIX},
                                     "unborn": ["/home/agent/new"]}, "worktree /home/agent/new", self.FIX)):
            with self.subTest(label=label):
                self.set_scenario(scenario)
                rundir = self.folder / f"prediction-{label.replace(' ', '-')}"
                self.run_bench(tasks=self.one, arms="method", rundir=rundir)
                [(name, record)] = self.records(rundir).items()
                self.assertEqual(record["prediction_source"], source)
                self.assertEqual((rundir / "runs" / name / "prediction.diff").read_text(encoding="utf-8"), prediction)

    PIN = ("diff --git a/pyproject.toml b/pyproject.toml\n--- a/pyproject.toml\n+++ b/pyproject.toml\n"
           "@@ -1 +1 @@\n-setuptools\n+setuptools==68.0.0\n")

    def test_the_prediction_leaves_out_the_image_s_setup_commit(self):
        # The harness applies the prediction on the commit the image starts on, the setup
        # commit after base_commit (astropy-13398's pins setuptools): the setup change is the
        # image's, not the agent's, so an agent that changes nothing leaves an empty prediction.
        for label, scenario, source, prediction in (
                ("testbed", {"trees": {"/testbed": self.FIX}}, "/testbed", self.FIX),
                ("branch", {"branches": {"refs/heads/fix": [200, self.FIX]}}, "branch refs/heads/fix", self.FIX),
                ("nothing", {}, "none", "")):
            with self.subTest(label=label):
                self.set_scenario({**scenario, "head": "4b48727", "after_base": {"4b48727": ["pyproject.toml"]},
                                   "setup_diff": self.PIN})
                rundir = self.folder / f"setup-{label}"
                self.run_bench(tasks=self.one, arms="plain", rundir=rundir)
                [(name, record)] = self.records(rundir).items()
                self.assertEqual((record["stop"], record.get("start_commit"), record["prediction_source"]),
                                 ("DONE", "4b48727", source))
                self.assertEqual((rundir / "runs" / name / "prediction.diff").read_text(encoding="utf-8"), prediction)

    def test_the_prediction_leaves_out_the_hidden_test_files(self):
        task = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]
        test_path = task["grading"]["test_patch"].split(" b/", 1)[1].split("\n", 1)[0]
        source = ("diff --git a/src/widget.py b/src/widget.py\n--- a/src/widget.py\n+++ b/src/widget.py\n"
                  "@@ -1 +1 @@\n-old\n+new\n")
        agent_test = (f"diff --git a/{test_path} b/{test_path}\nnew file mode 100644\n--- /dev/null\n"
                      f"+++ b/{test_path}\n@@ -0,0 +1 @@\n+agent test\n")
        self.set_scenario({"diff": source + agent_test})
        self.run_bench(tasks=self.one, arms="plain")
        name = next(iter(self.records()))
        self.assertEqual((self.rundir / "runs" / name / "prediction.diff").read_text(encoding="utf-8"), source)
        self.assertEqual(self.records()[name]["prediction_source"], "/testbed")

    def test_a_run_keeps_the_agent_s_whole_change_and_its_transcripts(self):
        # Kept to judge the quality of the work, never graded: the change with the tests the
        # prediction leaves out, and Claude Code's session files (the main session and each
        # subagent), the token scrubbed as from a prediction. Without session files the run
        # still counts, and the record says what is missing.
        task = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]
        test_path = task["grading"]["test_patch"].split(" b/", 1)[1].split("\n", 1)[0]
        agent_test = (f"diff --git a/{test_path} b/{test_path}\nnew file mode 100644\n--- /dev/null\n"
                      f"+++ b/{test_path}\n@@ -0,0 +1 @@\n+agent test\n")
        home = "/home/agent/.claude/projects"
        sessions = {f"{home}/-testbed/sess-1.jsonl": f'{{"tool": "Bash", "output": "TOKEN={self.TOKEN}"}}\n',
                    f"{home}/-testbed/sess-1/subagents/agent-a.jsonl": '{"role": "reviewer"}\n'}
        for label, scenario, saved, kept in (
                ("sessions", {"transcripts": sessions}, {"saved": 2, "errors": []},
                 {"-testbed/sess-1.jsonl": '{"tool": "Bash", "output": "TOKEN=[access token]"}\n',
                  "-testbed/sess-1/subagents/agent-a.jsonl": '{"role": "reviewer"}\n'}),
                ("no session folder", {}, {"saved": 0, "errors": [
                    f"list the transcripts: find: '{home}': No such file or directory"]}, {})):
            with self.subTest(label=label):
                self.set_scenario({"diff": self.FIX + agent_test, **scenario})
                rundir = self.folder / f"keep-{label.replace(' ', '-')}"
                result = self.run_bench(tasks=self.one, arms="plain", rundir=rundir)
                self.assertEqual(result.returncode, 0, result.stderr)
                [(name, record)] = self.records(rundir).items()
                folder = rundir / "runs" / name
                self.assertEqual((record["stop"], record["transcripts"]), ("DONE", saved))
                self.assertEqual((folder / "prediction.diff").read_text(encoding="utf-8"), self.FIX)
                self.assertEqual((folder / "agent.diff").read_text(encoding="utf-8"), self.FIX + agent_test)
                found = {str(path.relative_to(folder / "transcripts")): path.read_text(encoding="utf-8")
                         for path in (folder / "transcripts").rglob("*.jsonl")}
                self.assertEqual(found, kept)

    def test_a_git_failure_in_the_prediction_is_an_error_not_an_empty_prediction(self):
        # A git call of the prediction step that fails (a stale index.lock, a bad revision)
        # would otherwise read as "no change", graded unresolved; a run that cannot take its
        # prediction is an error, and the dry run shows it as a run that would stop.
        ident = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]["agent"]["instance_id"]
        lock = "fatal: Unable to create '/testbed/.git/index.lock': File exists."
        bad = "fatal: bad object"
        worktree = {"trees": {"/testbed": "", "/home/agent/fix": self.FIX}, "times": {"/home/agent/fix": 100}}
        branch = {"branches": {"refs/heads/fix": [200, self.FIX]}}
        for label, scenario, step, where in (
                ("add", {"fail": {"add -A": lock}}, "add", "/testbed"),
                # Not every failure is git's fatal 128: a plain error exits 1, a usage error 129.
                ("add exit 1", {"fail": {"add -A": [1, "error: unable to index file 'src/widget.py'"]}}, "add",
                 "/testbed"),
                ("diff --quiet exit 129", {"fail": {"diff --cached --quiet": [129, "usage: git diff [<options>]"]}},
                 "diff", "/testbed"),
                ("diff --quiet", {"fail": {"diff --cached --quiet": bad}}, "diff", "/testbed"),
                ("diff", {"trees": {"/testbed": self.FIX}, "fail": {"diff --cached --binary": bad}}, "diff",
                 "/testbed"),
                ("worktree list", {"fail": {"worktree list": bad}}, "worktree", "/testbed"),
                ("worktree list exit 1", {"fail": {"worktree list": [1, "error: unable to read worktrees"]}},
                 "worktree", "/testbed"),
                ("worktree add", {**worktree, "fail": {"/home/agent/fix add -A": lock}}, "add", "/home/agent/fix"),
                ("worktree rev-parse", {**worktree, "fail": {"/home/agent/fix rev-parse": bad}}, "rev-parse",
                 "/home/agent/fix"),
                ("worktree log", {**worktree, "fail": {"log": bad}}, "log", "/home/agent/fix"),
                ("worktree diff --quiet", {**worktree, "fail": {"/home/agent/fix diff --cached --quiet": bad}}, "diff",
                 "/home/agent/fix"),
                ("worktree diff", {**worktree, "fail": {"/home/agent/fix diff --cached --binary": bad}}, "diff",
                 "/home/agent/fix"),
                ("for-each-ref", {"fail": {"for-each-ref": bad}}, "for-each-ref", "/testbed"),
                ("branch diff --quiet", {**branch, "fail": {"diff --quiet refs/heads/fix": bad}}, "diff", "/testbed"),
                ("branch diff", {**branch, "fail": {"diff --binary refs/heads/fix": bad}}, "diff", "/testbed")):
            [failure] = scenario["fail"].values()
            code, message = failure if isinstance(failure, list) else (128, failure)
            error = f"take the prediction: git {step} in {where} exited {code}: {message}"
            with self.subTest(label=label):
                self.log.unlink(missing_ok=True)
                self.set_scenario(scenario)
                rundir = self.folder / f"predict-{label.replace(' ', '-')}"
                result = self.run_bench(tasks=self.one, arms="plain", rundir=rundir)
                self.assertEqual(result.returncode, 0, result.stderr)
                [(name, record)] = self.records(rundir).items()
                self.assertEqual((record["stop"], record["error"], record["prediction_source"]),
                                 ("error", error, None))
                self.assertEqual(len(record["calls"]), 1)  # the agent ran; its spend still counts
                self.assertFalse((rundir / "runs" / name / "prediction.diff").exists())
                self.set_scenario(scenario)
                result = self.run_bench("--dry-run", tasks=self.one, rundir=self.folder / "dry")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"{ident} image: a run would stop: {error}\n", result.stdout)

    def test_task_fields_that_reach_paths_and_commands_are_checked(self):
        task = json.loads(self.one.read_text(encoding="utf-8"))["tasks"][0]
        for field, value in (("instance_id", "../escape"), ("base_commit", "--output=/tmp/x"),
                             ("image", "--privileged")):
            with self.subTest(field=field):
                bad = self.folder / f"bad-{field}.json"
                bad.write_text(json.dumps({"tasks": [{**task, "agent": {**task["agent"], field: value}}]}),
                               encoding="utf-8")
                result = self.run_bench("--dry-run", tasks=bad)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(field, result.stderr)

    def test_a_finished_run_is_not_run_again(self):
        self.assertEqual(self.run_bench(tasks=self.one).returncode, 0)
        self.log.unlink()
        result = self.run_bench(tasks=self.one)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("claude"), [])

    ASKS = {"subtype": "success", "is_error": False, "result": "A or B? I recommend A.", "session_id": "s",
            "num_turns": 3, "total_cost_usd": 3.0}

    def interrupted(self) -> list:
        path = self.rundir / "interrupted.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_a_failed_resumed_call_keeps_the_session_s_cost(self):
        # A resumed call that fails at once may report a total of 0: the $3 already spent stays.
        self.set_scenario({"agent": [self.ASKS, {"subtype": "success", "is_error": True, "total_cost_usd": 0,
                                                 "result": "Claude AI usage limit reached|1786600000"}],
                           "maintainer": [{"result": "Use A.", "total_cost_usd": 0.1}]})
        result = self.run_bench(tasks=self.one, arms="method", cap=8)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertAlmostEqual(self.interrupted()[0]["spend"], 3.1)

    def test_ctrl_c_keeps_the_attempt_and_its_spend(self):
        self.set_scenario({"agent": [self.ASKS], "maintainer": [{"result": "Use A.", "total_cost_usd": 0.1}],
                           "interrupt_at": 2})
        result = self.run_bench(tasks=self.one, arms="method", cap=8)
        self.assertEqual(result.returncode, 130, result.stderr)
        self.assertIn("run again", result.stderr)
        [record] = self.records().values()
        self.assertEqual(record["finished"], False)
        [attempt] = self.interrupted()
        self.assertAlmostEqual(attempt["spend"], 3.1)
        self.assertEqual(attempt["stop"], "KeyboardInterrupt")

    def test_a_share_under_a_cent_is_spent(self):
        self.set_scenario({"agent": [dict(self.ASKS, total_cost_usd=1.996)]})
        self.run_bench(tasks=self.one, arms="method", cap=2)  # one run, a share of 2
        self.assertEqual(self.calls("claude", "maintainer"), [])
        self.assertEqual(next(iter(self.records().values()))["stop"], "budget")

    def expire_login(self):
        login = json.loads(self.credentials.read_text(encoding="utf-8"))
        login["claudeAiOauth"]["expiresAt"] = int((time.time() - 60) * 1000)
        self.credentials.write_text(json.dumps(login), encoding="utf-8")

    def test_an_expired_login_is_a_missing_prerequisite(self):
        self.expire_login()
        dry = self.run_bench("--dry-run")
        self.assertIn("credentials: missing", dry.stdout)
        self.assertIn("expired", dry.stdout)
        result = self.run_bench()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("run claude on this machine", result.stderr)
        self.assertEqual(self.calls("claude"), [])

    def test_a_login_that_expires_during_a_run_stops_it_until_refreshed(self):
        self.set_scenario({"agent": [self.ASKS], "maintainer": [{"result": "Use A.", "total_cost_usd": 0.1}],
                           "expire_login": True})
        result = self.run_bench(tasks=self.one, arms="method", cap=8)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("login", result.stdout)
        self.assertIn("run claude on this machine", result.stdout)
        self.assertEqual(len(self.calls("claude", "agent")), 1)  # no call made with an expired token
        [record] = self.records().values()
        self.assertEqual((record["stop"], record["finished"]), ("login", False))
        self.assertAlmostEqual(self.interrupted()[0]["spend"], 3.1)

    def test_a_refreshed_login_leaves_neither_token_in_the_prediction(self):
        # Call 1 runs with the token the agent writes into a file; the host then refreshes
        # the login, and call 2 runs with another.
        change = f"diff --git a/.env b/.env\nnew file mode 100644\n--- /dev/null\n+++ b/.env\n@@ -0,0 +1 @@\n+{self.TOKEN}\n"
        self.set_scenario({"agent": [self.ASKS], "maintainer": [{"result": "Use A.", "total_cost_usd": 0.1}],
                           "refresh_login": "TOKEN-REFRESHED-456", "diff": change})
        self.run_bench(tasks=self.one, arms="plain", cap=8)
        self.assertEqual([call["token"] for call in self.calls("claude", "agent")], [self.TOKEN, "TOKEN-REFRESHED-456"])
        [name] = self.records()
        self.assertNotIn(self.TOKEN, (self.rundir / "runs" / name / "prediction.diff").read_text(encoding="utf-8"))

    def test_the_token_never_reaches_a_record_or_the_maintainer(self):
        # An agent that prints its environment puts the token in its answer and in the other
        # fields of its result; one that writes it to a file puts it in the change.
        denial = {"tool_name": "Bash", "tool_input": {"command": f"echo {self.TOKEN}"}}
        change = f"diff --git a/.env b/.env\nnew file mode 100644\n--- /dev/null\n+++ b/.env\n@@ -0,0 +1 @@\n+{self.TOKEN}\n"
        self.set_scenario({"agent": [dict(self.ASKS, result=f"env: CLAUDE_CODE_OAUTH_TOKEN={self.TOKEN}",
                                          permission_denials=[denial])], "diff": change})
        self.run_bench(tasks=self.one, arms="plain")
        [maintainer] = self.calls("claude", "maintainer")
        self.assertNotIn(self.TOKEN, maintainer["stdin"])
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN=", maintainer["stdin"])
        [name] = self.records()
        for kept in ("record.json", "prediction.diff"):
            self.assertNotIn(self.TOKEN, (self.rundir / "runs" / name / kept).read_text(encoding="utf-8"), kept)
        self.assertIn("+++ b/.env", (self.rundir / "runs" / name / "prediction.diff").read_text(encoding="utf-8"))

    def test_a_usage_limit_stops_the_whole_run_until_started_again(self):
        self.set_scenario({"agent": [{"subtype": "success", "is_error": True, "total_cost_usd": 0,
                                      "result": "Claude AI usage limit reached|1786600000"}]})
        result = self.run_bench()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("usage limit", result.stdout)
        self.assertEqual(len(self.calls("claude", "agent")), 1)
        self.assertEqual([record for record in self.records().values() if record.get("finished")], [])
        result = self.run_bench()  # started again on the same folder, the limit gone
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len([record for record in self.records().values() if record["finished"]]), 4)


# A fake SWE-bench Python: -c (the import check) passes; -m swebench.harness.run_evaluation
# logs its call and writes a report per instance, resolved when the patch holds RESOLVE and
# with a failing PASS_TO_PASS test when it holds REGRESS. Like swebench 5.0.2, it writes no
# report for an empty patch (dropped before evaluation), nor for one that does not apply
# (UNAPPLIABLE: it logs ">>>>> Patch Apply Failed" in run_instance.log), nor when the tests
# time out (HANG: "Timeout error" in test_output.txt), nor when it fails (CRASH). Duplicate
# instance ids exit 3.
FAKE_HARNESS = r'''
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
if args[:1] == ["-c"]:
    sys.exit(0)
def option(name):
    return args[args.index(name) + 1]
ids = []
for word in args[args.index("--instance_ids") + 1:]:
    if word.startswith("--"):
        break
    ids.append(word)
run_id, predictions = option("--run_id"), option("--predictions_path")
with open(option("--dataset_name")) as handle:
    dataset = [json.loads(line) for line in handle]
with open(os.environ["BENCH_FAKE_LOG"], "a") as handle:
    handle.write(json.dumps({"program": "harness", "python": sys.argv[0], "argv": args, "cwd": os.getcwd(), "ids": ids,
                             "docker_host": os.environ.get("DOCKER_HOST"), "docker": shutil.which("docker"),
                             "dataset_fields": sorted(dataset[0])}) + "\n")
if predictions == "gold":
    model, patches = "gold", {ident: "RESOLVE" for ident in ids}
else:
    with open(predictions) as handle:
        rows = [json.loads(line) for line in handle]
    model, patches = rows[0]["model_name_or_path"], {row["instance_id"]: row["model_patch"] for row in rows}
    if len(patches) != len(rows):
        sys.exit(3)
for ident in ids:
    folder = Path("logs/run_evaluation") / run_id / model / ident
    patch = patches[ident]
    if not patch:
        continue
    folder.mkdir(parents=True, exist_ok=True)
    if "UNAPPLIABLE" in patch:
        (folder / "run_instance.log").write_text(">>>>> Patch Apply Failed:\nerror: patch failed: x:1\n")
        continue
    if "HANG" in patch:
        (folder / "test_output.txt").write_text("running...\n\nTimeout error: 1800 seconds exceeded.")
        continue
    if "QUOTE" in patch:  # the tests ran and printed the phrase; then the harness failed
        (folder / "test_output.txt").write_text("test_retry ... Timeout error: retrying\nok\n")
        continue
    if "CRASH" in patch:
        continue
    failing = ["test_old"] if "REGRESS" in patch else []
    (folder / "report.json").write_text(json.dumps({ident: {
        "patch_exists": bool(patch), "patch_successfully_applied": bool(patch), "resolved": "RESOLVE" in patch,
        "tests_status": {"FAIL_TO_PASS": {"success": [], "failure": []},
                         "PASS_TO_PASS": {"success": [], "failure": failing}}}}))
'''


class BenchmarkResults(unittest.TestCase):
    """benchmark.py grade (against FAKE_HARNESS) and summary, on a synthetic run folder:
    2 tasks x 2 arms x 2 runs; the method's patches resolve, the plain arm's regress, and the
    plain arm's fourth run is a setup error that never reached the agent."""

    setUp_dataset, tool, select = Benchmark.setUp, Benchmark.tool, Benchmark.select
    TOOL = Benchmark.TOOL
    # Skewed, so a mean and a median differ.
    AGENT_COSTS = {"method": [1.0, 1.0, 1.0, 9.0], "plain": [0.5, 0.5, 2.0, 0.0]}
    TURNS, MINUTES = [10, 10, 10, 30], [1, 1, 1, 9]

    def setUp(self):
        self.setUp_dataset()
        tasks = self.select(2, 5)["tasks"]
        self.ids = [task["agent"]["instance_id"] for task in tasks]
        self.rundir = self.folder / "run"
        (self.rundir / "runs").mkdir(parents=True)
        (self.rundir / "tasks.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        (self.rundir / "plan.json").write_text(json.dumps({
            "tasks": self.ids, "arms": ["method", "plain"], "runs": 2, "cap_usd": 16, "share": 2.0,
            "model": "claude-opus-5-5", "maintainer_model": "claude-sonnet-5-5"}), encoding="utf-8")
        for repeat in (1, 2):
            for index, ident in enumerate(self.ids):
                for arm in ("method", "plain"):
                    number = (repeat - 1) * 2 + index
                    error = arm == "plain" and number == 3
                    cost = self.AGENT_COSTS[arm][number]
                    calls = [] if error else [{"result": "TRANSCRIPT-TEXT: ran git push",
                                               "num_turns": self.TURNS[number],
                                               "duration_ms": 60000 * self.MINUTES[number], "total_cost_usd": cost}]
                    # One reply, then DONE (which is not a reply).
                    replies = ([{"reply": "TRANSCRIPT-REPLY", "cost": 0.01}, {"reply": "DONE", "cost": 0.0}]
                               if arm == "method" else [])
                    run_id = f"{ident}.{arm}.{repeat}"
                    folder = self.rundir / "runs" / run_id
                    folder.mkdir()
                    (folder / "record.json").write_text(json.dumps({
                        "run": run_id, "instance_id": ident, "arm": arm, "repeat": repeat, "finished": True,
                        "stop": "error" if error else "DONE", "calls": calls, "maintainer": replies,
                        "agent_cost": cost, "maintainer_cost": sum(entry["cost"] for entry in replies),
                        "spend": cost + sum(entry["cost"] for entry in replies)}), encoding="utf-8")
                    if not error:
                        (folder / "prediction.diff").write_text(
                            f"diff --git a/x b/x\n+{'RESOLVE' if arm == 'method' else 'REGRESS'}\n", encoding="utf-8")
        programs = self.folder / "bin"
        programs.mkdir()
        self.python = programs / "swebench-python"
        self.python.write_text(f"#!{sys.executable}\n{FAKE_HARNESS}", encoding="utf-8")
        self.python.chmod(0o755)
        self.socket = self.folder / "podman.sock"
        self.socket.write_text("", encoding="utf-8")
        self.log = self.folder / "calls.jsonl"
        self.env = {**os.environ, "PATH": str(programs), "DOCKER_HOST": f"unix://{self.socket}",
                    "BENCH_FAKE_LOG": str(self.log)}

    def harness_calls(self) -> list:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def grade(self, *extra, env=None) -> subprocess.CompletedProcess:
        return self.tool("grade", "--rundir", self.rundir, "--swebench-python", self.python, *extra,
                         env=env or self.env)

    def test_grade_gold_grades_the_reference_patches(self):
        result = self.grade("--gold")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        [call] = self.harness_calls()
        self.assertEqual(call["argv"][call["argv"].index("--predictions_path") + 1], "gold")
        self.assertEqual(sorted(call["ids"]), sorted(self.ids))
        self.assertIn("patch", call["dataset_fields"])  # the gold patch comes from the dataset
        # From RUNDIR/grading, through podman's socket, with a docker program for the cleanup.
        self.assertEqual(Path(call["cwd"]), (self.rundir / "grading").resolve())
        self.assertEqual(call["docker_host"], f"unix://{self.socket}")
        self.assertTrue(call["docker"] and Path(call["docker"]).read_text().endswith('exec podman "$@"\n'))
        gold = json.loads((self.rundir / "gold.json").read_text(encoding="utf-8"))
        self.assertEqual({ident: gold[ident]["resolved"] for ident in self.ids}, dict.fromkeys(self.ids, True))
        self.assertIn("gold: 2 of 2 resolved", result.stdout)

    def test_grade_calls_the_harness_once_per_arm_and_repeat(self):
        result = self.grade()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.harness_calls()
        self.assertEqual(len(calls), 4)  # the harness keys predictions by instance id
        for call in calls:
            self.assertEqual(len(call["ids"]), len(set(call["ids"])))
        graded = sorted(ident for call in calls for ident in call["ids"])
        self.assertEqual(len(graded), 7)  # the setup error never reached the agent
        grades = json.loads((self.rundir / "grades.json").read_text(encoding="utf-8"))
        self.assertEqual(len(grades), 7)
        for run_id, grade in grades.items():
            arm = run_id.split(".")[1]
            self.assertEqual((grade["resolved"], grade["regressions"]),
                             (True, []) if arm == "method" else (False, ["test_old"]), run_id)

    def test_grade_counts_empty_and_unapplied_patches_and_reports_harness_failures(self):
        empty, unapplied, crashed = (f"{self.ids[0]}.method.1", f"{self.ids[1]}.method.1", f"{self.ids[0]}.method.2")
        hung, quoted = f"{self.ids[1]}.plain.1", f"{self.ids[0]}.plain.2"
        for run_id, patch in ((empty, ""), (unapplied, "diff --git a/x b/x\n+UNAPPLIABLE\n"),
                              (crashed, "diff --git a/x b/x\n+CRASH\n"), (hung, "diff --git a/x b/x\n+HANG\n"),
                              (quoted, "diff --git a/x b/x\n+QUOTE\n")):
            (self.rundir / "runs" / run_id / "prediction.diff").write_text(patch, encoding="utf-8")
        result = self.grade()
        self.assertEqual(result.returncode, 1, result.stdout)  # a run the harness did not report on
        self.assertIn(crashed, result.stderr)
        grades = json.loads((self.rundir / "grades.json").read_text(encoding="utf-8"))
        self.assertEqual({run_id: (grades[run_id]["graded"], grades[run_id]["resolved"], grades[run_id]["outcome"])
                          for run_id in (empty, unapplied, crashed, hung, quoted)},
                         {empty: (True, False, "empty prediction"), unapplied: (True, False, "patch did not apply"),
                          crashed: (False, False, "no report"), hung: (True, False, "tests timed out"),
                          quoted: (False, False, "no report")})
        self.assertNotIn(hung, result.stderr)  # a timeout is the patch's failure, not the harness's
        # Empty and unapplied predictions are failures to resolve; a harness failure stays
        # apart, outside the rate: 1 resolved of 3 graded, not of the 4 that reached the agent.
        summary = self.tool("summary", "--rundir", self.rundir)
        self.assertEqual(self.table(summary.stdout, "method")[3:9], ["3", "2", "0", "1", "1", "33%"])
        # plain: one report, one timeout, and the run whose output only quotes a timeout.
        self.assertEqual(self.table(summary.stdout, "plain")[3:9], ["2", "0", "1", "1", "0", "0%"])

    def test_a_run_that_failed_after_the_agent_counts_as_an_error_only(self):
        # A run whose prediction step failed reached the agent, whose cost counts, but has no
        # prediction: an error, not a run the harness failed to report on. A run whose agent
        # call ended in an error still has its prediction, which grade grades, and which the
        # harness may fail on like any other (grade exits 1).
        run_id = f"{self.ids[0]}.method.1"
        path = self.rundir / "runs" / run_id / "record.json"
        prediction = path.parent / "prediction.diff"
        fix, crash = prediction.read_text(encoding="utf-8"), "diff --git a/x b/x\n+CRASH\n"
        # runs, errors, graded, empty or not applied, tests timed out, no report, resolved, rate
        for label, error, source, patch, exit_code, row in (
                ("prediction failed", "take the prediction: git add in /testbed exited 128: fatal: lock", None, None,
                 0, ["4", "1", "3", "0", "0", "0", "3", "100%"]),
                ("agent error", None, "/testbed", fix, 0, ["4", "1", "4", "0", "0", "0", "4", "100%"]),
                ("agent error, harness failed", None, "/testbed", crash, 1,
                 ["4", "1", "3", "0", "0", "1", "3", "100%"])):
            with self.subTest(label=label):
                record = json.loads(path.read_text(encoding="utf-8"))
                record.update(stop="error", error=error, prediction_source=source)
                path.write_text(json.dumps(record), encoding="utf-8")
                prediction.unlink(missing_ok=True)
                if patch:
                    prediction.write_text(patch, encoding="utf-8")
                result = self.grade()
                self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
                grades = json.loads((self.rundir / "grades.json").read_text(encoding="utf-8"))
                self.assertEqual(run_id in grades, bool(source))
                summary = self.tool("summary", "--rundir", self.rundir)
                self.assertEqual(self.table(summary.stdout, "method")[1:9], row)

    def test_a_run_grades_json_does_not_hold_counts_as_no_report(self):
        # grades.json holds the runs graded so far; a run that finished later has no entry,
        # like a run the harness failed on has no report: both call for grading again.
        self.assertEqual(self.grade().returncode, 0)
        path = self.rundir / "grades.json"
        grades = json.loads(path.read_text(encoding="utf-8"))
        del grades[f"{self.ids[0]}.method.1"]
        path.write_text(json.dumps(grades), encoding="utf-8")
        summary = self.tool("summary", "--rundir", self.rundir)
        # runs, errors, graded, empty or not applied, tests timed out, no report, resolved, rate
        self.assertEqual(self.table(summary.stdout, "method")[1:9], ["4", "0", "3", "0", "0", "1", "3", "100%"])

    def test_a_run_made_again_after_grade_counts_as_no_report_until_graded_again(self):
        # Deleting a run's folder and running again gives a new prediction under the same id;
        # the old grade would count a result the new run never had. A grade file written
        # before grade recorded what it graded is still trusted.
        run_id = f"{self.ids[0]}.method.1"
        self.assertEqual(self.grade().returncode, 0)
        path = self.rundir / "grades.json"
        graded = path.read_text(encoding="utf-8")
        # runs, errors, graded, empty or not applied, tests timed out, no report, resolved, rate
        for label, prediction, legacy, row in (
                ("new prediction", "diff --git a/x b/x\n+REGRESS\n", False, ["4", "0", "3", "0", "0", "1", "3", "100%"]),
                ("prediction gone", None, False, ["4", "0", "3", "0", "0", "1", "3", "100%"]),
                ("grade file without hashes", None, True, ["4", "0", "4", "0", "0", "0", "4", "100%"])):
            with self.subTest(label=label):
                folder = self.rundir / "runs" / run_id
                (folder / "prediction.diff").write_text("diff --git a/x b/x\n+RESOLVE\n", encoding="utf-8")
                grades = json.loads(graded)
                if legacy:
                    grades = {key: {name: value for name, value in grade.items() if name != "prediction_sha256"}
                              for key, grade in grades.items()}
                elif prediction is None:
                    (folder / "prediction.diff").unlink()
                else:
                    (folder / "prediction.diff").write_text(prediction, encoding="utf-8")
                path.write_text(json.dumps(grades), encoding="utf-8")
                summary = self.tool("summary", "--rundir", self.rundir)
                self.assertEqual(self.table(summary.stdout, "method")[1:9], row)
        # The same for a grade of an empty prediction, which grade writes without the harness.
        with self.subTest(label="empty prediction made again"):
            prediction = self.rundir / "runs" / run_id / "prediction.diff"
            prediction.write_text("", encoding="utf-8")
            self.assertEqual(self.grade().returncode, 0)
            prediction.write_text("diff --git a/x b/x\n+RESOLVE\n", encoding="utf-8")
            summary = self.tool("summary", "--rundir", self.rundir)
            self.assertEqual(self.table(summary.stdout, "method")[1:9], ["4", "0", "3", "0", "0", "1", "3", "100%"])

    def test_grade_takes_a_relative_swebench_python_and_keeps_its_symlink(self):
        # The harness runs in RUNDIR/grading/, so a relative path must still reach the
        # Python; a venv's python is a symlink that must not be resolved, or it loses the venv.
        # ./NAME is a path too, never looked up on PATH (whose swebench-python is another file).
        (self.folder / "bin" / "venv-python").symlink_to("swebench-python")
        local = self.folder / "local"
        local.mkdir()
        (local / "swebench-python").symlink_to(self.python)
        for cwd, argument, expected in ((self.folder, "bin/venv-python", self.folder / "bin" / "venv-python"),
                                        (local, "./swebench-python", local / "swebench-python")):
            with self.subTest(argument=argument):
                self.log.unlink(missing_ok=True)
                result = subprocess.run([sys.executable, "-B", str(self.TOOL), "grade", "--rundir",
                                         str(self.rundir), "--swebench-python", argument], cwd=cwd, env=self.env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = self.harness_calls()
                self.assertEqual(len(calls), 4)
                self.assertEqual({call["python"] for call in calls},
                                 {str(expected.parent.resolve() / expected.name)})

    def test_grade_finds_a_bare_swebench_python_name_on_path(self):
        # A name without a folder (python3, or a venv's python on PATH) is looked up on PATH,
        # as before the relative path fix, not taken as a file in the current folder.
        result = subprocess.run([sys.executable, "-B", str(self.TOOL), "grade", "--rundir", str(self.rundir),
                                 "--swebench-python", "swebench-python"], cwd=self.folder, env=self.env,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.harness_calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual({call["python"] for call in calls}, {str(self.python)})

    def test_grade_needs_podman_s_socket(self):
        result = self.grade(env={**self.env, "DOCKER_HOST": f"unix://{self.folder / 'no.sock'}"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("podman system service", result.stderr)
        self.assertFalse(self.log.exists())

    def table(self, text: str, first: str) -> list:
        line = next(line for line in text.splitlines() if line.startswith(f"| {first} "))
        return [cell.strip() for cell in line.strip("|").split("|")]

    def test_summary_gives_medians_per_arm_and_no_transcript(self):
        self.grade()
        org = self.folder / "summary.org"
        result = self.tool("summary", "--rundir", self.rundir, "--org", org)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = org.read_text(encoding="utf-8")
        self.assertIn("pilot: not conclusive", text)  # 2 tasks and 2 runs per arm, under the full run's
        self.assertEqual(self.table(text, "arm")[:9], ["arm", "runs", "errors", "graded", "empty or not applied",
                                                         "tests timed out", "no report", "resolved", "resolved rate"])
        # Medians over the runs that reached the agent, totals over all runs.
        self.assertEqual(self.table(text, "method"),
                         ["method", "4", "0", "4", "0", "0", "0", "4", "100%", "1.00", "12.00", "0.01", "0.04", "10.0", "1.0", "0",
                          "1.0", "1", "7.01", "DONE 4"])  # 9.01 passes the share of 2
        self.assertEqual(self.table(text, "plain"),
                         ["plain", "4", "1", "3", "0", "0", "0", "0", "0%", "0.50", "3.00", "0.00", "0.00", "10.0", "1.0", "3",
                          "0.0", "0", "0.00", "DONE 3, error 1"])
        self.assertEqual(self.table(text, self.ids[0]), [self.ids[0], "2/2", "1.00", "0/2", "1.25"])
        self.assertEqual(self.table(text, self.ids[1]), [self.ids[1], "2/2", "5.00", "0/1", "0.50"])  # its setup error never reached the agent
        for transcript in ("TRANSCRIPT", "git push"):
            self.assertNotIn(transcript, text)

    def test_summary_counts_interrupted_attempts_and_runs_not_made(self):
        (self.rundir / "interrupted.jsonl").write_text(
            json.dumps({"run": f"{self.ids[0]}.method.1", "stop": "usage limit", "spend": 0.5}) + "\n",
            encoding="utf-8")
        (self.rundir / "not-made.json").write_text(json.dumps(["x.method.3", "x.plain.3"]), encoding="utf-8")
        result = self.tool("summary", "--rundir", self.rundir)
        self.assertEqual(result.returncode, 0, result.stderr)
        # 12.04 (method) + 3.00 (plain) in finished runs, 0.50 in the interrupted attempt.
        self.assertIn("Spent 15.54 in all: 15.04 in finished runs and 0.50 in interrupted attempts (1); "
                      "planned runs not made: 2.", result.stdout)

    def test_summary_calls_a_run_full_only_when_every_planned_run_finished(self):
        def summarize(arms: list, missing: int = 0) -> str:
            rundir = self.folder / f"full-{len(arms)}-{missing}"
            tasks = [f"t{index}" for index in range(20)]
            (rundir / "runs").mkdir(parents=True)
            (rundir / "plan.json").write_text(json.dumps({
                "tasks": tasks, "arms": arms, "runs": 3, "cap_usd": 120, "share": 1.0, "model": "m",
                "maintainer_model": "s"}), encoding="utf-8")
            planned = [f"{task}.{arm}.{repeat}" for task in tasks for arm in arms for repeat in (1, 2, 3)]
            for run_id in planned[missing:]:
                task, arm, repeat = run_id.split(".")
                (rundir / "runs" / run_id).mkdir()
                (rundir / "runs" / run_id / "record.json").write_text(json.dumps({
                    "run": run_id, "instance_id": task, "arm": arm, "repeat": int(repeat), "finished": True,
                    "stop": "DONE", "calls": [{"num_turns": 1}], "maintainer": [], "agent_cost": 0.5,
                    "maintainer_cost": 0.0, "spend": 0.5}), encoding="utf-8")
            result = self.tool("summary", "--rundir", rundir)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.splitlines()[0]
        self.assertEqual(summarize(["method", "plain"]), "full run.")
        self.assertIn("pilot: not conclusive", summarize(["method", "plain"], missing=1))  # cut by the cap
        self.assertIn("pilot: not conclusive", summarize(["method"]))  # one arm compares nothing

    def test_summary_without_grades_says_so(self):
        result = self.tool("summary", "--rundir", self.rundir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not graded", result.stdout)
        self.assertEqual(self.table(result.stdout, "method")[3:9], ["-"] * 6)


if __name__ == "__main__":
    unittest.main()
