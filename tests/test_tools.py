# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for tools/validate.py and tools/build.py on a copy of the repository."""

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


class Tools(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()) / "repo"
        # Local state stays out: .private notes and .claude (settings, agent worktrees).
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns(
            ".git", "dist", "__pycache__", ".private", ".claude"))
        self.addCleanup(shutil.rmtree, self.repo.parent)

    def run_tool(self, name: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(self.repo / "tools" / name)],
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


if __name__ == "__main__":
    unittest.main()
