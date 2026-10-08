# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for tools/validate.py and tools/build.py on a copy of the repository."""

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
