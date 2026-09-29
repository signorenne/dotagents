# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for tools/validate.py and tools/build.py on a copy of the repository."""

import json
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
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__"))
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

    def add_skill(self, name: str, description: str = "Does a thing. Use when testing.") -> None:
        folder = self.repo / "home/.agents/skills" / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\nlicense: MIT\n---\nBody.\n")
        shutil.copy(self.repo / "home/.agents/skills/spec/LICENSE.txt", folder / "LICENSE.txt")

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


if __name__ == "__main__":
    unittest.main()
