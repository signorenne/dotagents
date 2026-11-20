# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne)
"""Tests for the scripts bundled with skills."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "home/.agents/skills/precise-ui-changes/scripts/nothing_moved.py"

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


nothing_moved = load("nothing_moved", SCRIPT)
annotate = load("annotate", ROOT / "home/.agents/skills/as-built-docs/scripts/annotate.py")

try:
    from PIL import Image
except ImportError:
    Image = None


def diff_with(width, height, changes):
    """A diff map of width x height with the given {(x, y): level} values."""
    data = bytearray(width * height)
    for (x, y), level in changes.items():
        data[y * width + x] = level
    return bytes(data)


class Classify(unittest.TestCase):
    def test_no_difference_counts_nothing(self):
        found = nothing_moved.classify(10, 10, diff_with(10, 10, {}), 0, [])
        self.assertEqual((found.inside, found.outside, found.outside_box), (0, 0, None))

    def test_a_difference_equal_to_the_threshold_is_noise(self):
        found = nothing_moved.classify(10, 10, diff_with(10, 10, {(3, 3): 2}), 2, [])
        self.assertEqual(found.outside, 0)

    def test_a_difference_above_the_threshold_counts(self):
        found = nothing_moved.classify(10, 10, diff_with(10, 10, {(3, 3): 3}), 2, [])
        self.assertEqual(found.outside, 1)

    def test_change_inside_an_allowed_box_passes(self):
        found = nothing_moved.classify(10, 10, diff_with(10, 10, {(5, 5): 50}), 1, [(4, 4, 8, 8)])
        self.assertEqual((found.inside, found.outside), (1, 0))

    def test_right_and_bottom_edges_are_outside_the_box(self):
        diff = diff_with(10, 10, {(8, 5): 50, (5, 8): 50})
        found = nothing_moved.classify(10, 10, diff, 1, [(4, 4, 8, 8)])
        self.assertEqual((found.inside, found.outside), (0, 2))

    def test_outside_box_spans_every_outside_change(self):
        diff = diff_with(10, 10, {(1, 2): 9, (7, 6): 9, (5, 5): 9})
        found = nothing_moved.classify(10, 10, diff, 1, [(4, 4, 6, 6)])
        self.assertEqual(found.outside_box, (1, 2, 8, 7))
        self.assertEqual(found.inside, 1)

    def test_a_row_with_changes_inside_and_outside_counts_both(self):
        diff = diff_with(10, 10, {(5, 5): 9, (9, 5): 9})
        found = nothing_moved.classify(10, 10, diff, 1, [(4, 4, 8, 8)])
        self.assertEqual((found.inside, found.outside), (1, 1))

    def test_every_allowed_box_counts(self):
        diff = diff_with(10, 10, {(1, 1): 9, (8, 8): 9})
        found = nothing_moved.classify(10, 10, diff, 1, [(0, 0, 3, 3), (7, 7, 10, 10)])
        self.assertEqual((found.inside, found.outside), (2, 0))

    def test_parse_box_rejects_malformed_and_empty_rectangles(self):
        self.assertEqual(nothing_moved.parse_box("1,2,3,4"), (1, 2, 3, 4))
        for text in ("1,2,3", "4,2,3,5", "1,5,3,5", "a,b,c,d"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                nothing_moved.parse_box(text)


class CommandCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.before = self.root / "before"
        self.after = self.root / "after"
        self.before.mkdir()
        self.after.mkdir()

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            status = nothing_moved.main(list(argv))
        return status, out.getvalue()

    def check(self, *extra, before=None, threshold="1"):
        return self.run_main("check", "--before", str(before or self.before), "--after", str(self.after),
                             "--threshold", threshold, *extra)


class Folders(CommandCase):
    """Command behaviour that reads no image, so it runs without Pillow."""

    def test_new_frame_without_reference_fails(self):
        (self.after / "b.png").write_bytes(b"")
        status, out = self.check()
        self.assertEqual(status, 1, out)
        self.assertIn("b.png: no reference", out)

    def test_reference_without_a_new_frame_fails(self):
        # A state not rendered again is not shown unmoved; the frame that was rendered still passes.
        for name in ("a.png", "b.png"):
            (self.before / name).write_bytes(b"")
        (self.after / "a.png").write_bytes(b"")
        with mock.patch.object(nothing_moved, "load_pair", return_value=((2, 2), (2, 2), bytes(4))):
            status, out = self.check()
        self.assertEqual(status, 1, out)
        self.assertIn(f"FAIL b.png: no new frame under {self.after}", out)
        self.assertIn("ok   a.png: 0 changed pixels", out)
        self.assertIn("FAIL: 1 of 2 frames failed", out)

    def test_bad_rectangle_is_a_usage_error(self):
        (self.after / "a.png").write_bytes(b"")
        self.assertEqual(self.check("--allow", "8,8,4,4")[0], 2)

    def test_missing_folder_is_a_usage_error(self):
        (self.after / "a.png").write_bytes(b"")
        self.assertEqual(self.check(before=self.root / "nowhere")[0], 2)

    def test_empty_frames_folder_is_a_usage_error(self):
        self.assertEqual(self.check()[0], 2)

    def test_unreadable_image_is_a_usage_error(self):
        (self.before / "a.png").write_bytes(b"")
        (self.after / "a.png").write_bytes(b"")
        self.assertEqual(self.check()[0], 2)

    def test_unexpected_error_is_a_usage_error(self):
        (self.before / "a.png").write_bytes(b"")
        (self.after / "a.png").write_bytes(b"")
        with mock.patch.object(nothing_moved, "load_pair", side_effect=RuntimeError("boom")):
            self.assertEqual(self.check()[0], 2)

    def test_threshold_zero_is_accepted(self):
        (self.after / "b.png").write_bytes(b"")
        self.assertEqual(self.check(threshold="0")[0], 1)

    def test_negative_threshold_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stderr(io.StringIO()):
            nothing_moved.main(["check", "--before", str(self.before), "--after", str(self.after),
                                "--threshold", "-1"])
        self.assertEqual(stop.exception.code, 2)

    def test_threshold_out_of_range_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stderr(io.StringIO()):
            nothing_moved.main(["check", "--before", str(self.before), "--after", str(self.after),
                                "--threshold", "255"])
        self.assertEqual(stop.exception.code, 2)


@unittest.skipIf(Image is None, "Pillow is not installed")
class Images(CommandCase):
    def frame(self, folder, name, size=(20, 20), dots=(), mode="RGBA"):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", size, (30, 30, 30, 255))
        for x, y, colour in dots:
            image.putpixel((x, y), colour)
        image.convert(mode).save(path)

    def test_change_inside_the_allowed_area_passes(self):
        self.frame(self.before, "a.png")
        self.frame(self.after, "a.png", dots=[(5, 5, (90, 30, 30, 255))])
        status, out = self.check("--allow", "4,4,8,8")
        self.assertEqual(status, 0, out)

    def test_change_outside_the_allowed_area_fails_with_its_box(self):
        self.frame(self.before, "a.png")
        self.frame(self.after, "a.png", dots=[(5, 5, (90, 30, 30, 255)), (15, 12, (90, 30, 30, 255))])
        status, out = self.check("--allow", "4,4,8,8")
        self.assertEqual(status, 1, out)
        self.assertIn("within 15,12,16,13", out)

    def test_a_change_in_green_or_alpha_alone_counts(self):
        for colour in ((30, 90, 30, 255), (30, 30, 30, 100)):
            with self.subTest(colour=colour):
                self.frame(self.before, "a.png")
                self.frame(self.after, "a.png", dots=[(15, 12, colour)])
                self.assertEqual(self.check()[0], 1)

    def test_noise_level_changes_pass(self):
        self.frame(self.before, "a.png")
        self.frame(self.after, "a.png", dots=[(15, 12, (31, 30, 30, 255))])
        self.assertEqual(self.check()[0], 0)

    def test_frames_in_subfolders_and_upper_case_names_are_compared(self):
        self.frame(self.before, "spec/a.PNG")
        self.frame(self.after, "spec/a.PNG", dots=[(15, 12, (90, 30, 30, 255))])
        status, out = self.check()
        self.assertEqual(status, 1, out)
        self.assertIn("spec/a.PNG", out)

    def test_size_change_fails(self):
        self.frame(self.before, "a.png")
        self.frame(self.after, "a.png", size=(20, 21))
        status, out = self.check()
        self.assertEqual(status, 1, out)
        self.assertIn("size changed", out)

    def test_16_bit_images_are_refused(self):
        self.frame(self.before, "a.png", mode="I;16")
        self.frame(self.after, "a.png", mode="I;16")
        self.assertEqual(self.check()[0], 2)

    def test_noise_on_different_sizes_fails(self):
        self.frame(self.before, "a.png")
        self.frame(self.after, "a.png", size=(20, 21))
        status, out = self.run_main("noise", str(self.before / "a.png"), str(self.after / "a.png"))
        self.assertEqual(status, 1, out)

    def test_noise_reports_the_largest_difference(self):
        self.frame(self.before, "a.png", dots=[(1, 1, (32, 30, 30, 255))])
        self.frame(self.after, "a.png", dots=[(1, 1, (35, 30, 30, 255)), (2, 2, (31, 30, 30, 255))])
        status, out = self.run_main("noise", str(self.before / "a.png"), str(self.after / "a.png"))
        self.assertEqual(status, 0, out)
        self.assertIn("largest channel difference 3, on 2 of 400 pixels", out)


class AnnotatePlace(unittest.TestCase):
    def test_points_and_boxes_are_parsed_strictly(self):
        self.assertEqual(annotate.parse_point("3,4"), (3, 4))
        for text in ("3", "3,4,5", "-1,2", "a,b"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                annotate.parse_point(text)
        self.assertEqual(annotate.parse_box("1,2,3,4"), (1, 2, 3, 4))
        with self.assertRaises(ValueError):
            annotate.parse_box("4,2,3,5")

    def test_markers_are_numbered_in_order_and_moved_by_the_crop(self):
        placed = annotate.place([(15, 25), (30, 40)], (100, 100), (10, 20, 50, 60))
        self.assertEqual(placed, [(1, 5, 5), (2, 20, 20)])

    def test_a_marker_outside_the_crop_is_refused(self):
        with self.assertRaises(annotate.UsageError):
            annotate.place([(5, 25)], (100, 100), (10, 20, 50, 60))
        with self.assertRaises(annotate.UsageError):
            annotate.place([(100, 5)], (100, 100), None)

    def test_a_crop_larger_than_the_picture_is_refused(self):
        with self.assertRaises(annotate.UsageError):
            annotate.place([(5, 5)], (100, 100), (0, 0, 120, 50))

    def test_unreadable_input_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(annotate.main(["/nonexistent/in.png", "/nonexistent/out.png", "--mark", "1,1"]), 2)


@unittest.skipIf(Image is None, "Pillow is not installed")
class AnnotateDraw(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.source = self.root / "in.png"
        Image.new("RGB", (200, 120), (40, 40, 40)).save(self.source)
        self.target = self.root / "out.png"

    def run_main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return annotate.main([str(self.source), str(self.target), *argv])

    def test_markers_are_drawn_where_asked_and_nowhere_else(self):
        self.assertEqual(self.run_main("--mark", "30,30", "--mark", "150,80"), 0)
        with Image.open(self.target) as out:
            out = out.convert("RGB")
            ring = (30 + 13, 30)  # on the marker, away from its number
            self.assertNotEqual(out.getpixel(ring), (40, 40, 40))
            self.assertNotEqual(out.getpixel((150 + 13, 80)), (40, 40, 40))
            self.assertEqual(out.getpixel((100, 5)), (40, 40, 40))

    def test_crop_keeps_only_the_rectangle(self):
        self.assertEqual(self.run_main("--mark", "60,50", "--crop", "50,40,150,100"), 0)
        with Image.open(self.target) as out:
            self.assertEqual(out.size, (100, 60))
            self.assertNotEqual(out.convert("RGB").getpixel((10 + 13, 10)), (40, 40, 40))

    def test_bad_markers_and_radius_are_usage_errors(self):
        self.assertEqual(self.run_main("--mark", "500,5"), 2)
        self.assertEqual(self.run_main("--mark", "5,5", "--radius", "2"), 2)
        self.assertFalse(self.target.exists())


BUILD = ROOT / "home/.agents/skills/build/scripts"
# git without the user's configuration (signing, hooks, default branch).
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
PLAN = """#+TITLE: Plan: widget

- Status: in progress
- Lane: {lane}
- Risk: low
- Base: {base}
- Branch: feat/widget
- Review: quick
- Next: S2 add the widget's test

* Intent
Make the widget.

* Steps
| Nr | Step        | Files    | Check | Status      | Commit |
|----+-------------+----------+-------+-------------+--------|
| S1 | scaffold    | a.py     | unit  | done        | {base} |
| S2 | widget test | test_a.py | unit | in progress |        |

* Rulings
| Nr | Ruling              | Why | Alternative | Cost if wrong | Review  |
|----+---------------------+-----+-------------+---------------+---------|
| R1 | name it widget      | x   | gadget      | a rename      | pending |
| R2 | keep the old helper | y   | drop it     | none          | kept    |
"""


class PlanScripts(unittest.TestCase):
    """plan_state, check_step and floor_check on a temporary repository whose working
    notes hold a plan, as METHOD.org (The plan file, Checks) defines them."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / ".gitignore").write_text(".private/\n")
        (self.repo / "test_a.py").write_text("def test_one():\n    pass\n\n\ndef test_two():\n    pass\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "--short", "HEAD")
        self.git("switch", "-q", "-c", "feat/widget")
        self.plan = self.repo / ".private" / "plans" / "widget.org"
        self.plan.parent.mkdir(parents=True)
        self.write_plan("full")

    def write_plan(self, lane):
        self.plan.write_text(PLAN.format(base=self.base, lane=lane))

    def git(self, *args, cwd=None) -> str:
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=GIT_ENV, capture_output=True,
                              text=True, check=True).stdout.strip()

    def run_script(self, name, *args, cwd=None):
        return subprocess.run([sys.executable, "-B", str(BUILD / name), *args], cwd=cwd or self.repo,
                              env=GIT_ENV, capture_output=True, text=True, check=False)

    def log(self) -> list:
        path = self.plan.with_suffix(".log")
        return [line.split("\t") for line in path.read_text().splitlines()] if path.exists() else []

    def test_plan_state_prints_the_header_the_step_in_progress_and_open_rulings(self):
        result = self.run_script("plan_state.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Status in progress, Lane full, Risk low", result.stdout)
        self.assertIn("Next: S2 add the widget's test", result.stdout)
        self.assertIn("In progress: S2 widget test (files: test_a.py)", result.stdout)
        self.assertIn("no commit for it yet", result.stdout)
        self.assertIn("Open rulings: 1: R1 name it widget", result.stdout)
        self.assertNotIn("R2", result.stdout)

    def test_the_excerpt_is_marked_as_a_map_and_bounded(self):
        result = self.run_script("plan_state.py", "--excerpt", "--max-chars", "200")
        self.assertTrue(result.stdout.startswith("Plan file excerpt: a map"), result.stdout)
        self.assertLessEqual(len(result.stdout.rstrip("\n")), 200)
        self.assertTrue(result.stdout.rstrip().endswith("(cut)"))

    def test_a_linked_worktree_reads_the_main_checkouts_plan(self):
        worktree = self.root / "wt"
        self.git("switch", "-q", "main")
        self.git("worktree", "add", "-q", str(worktree), "feat/widget")
        result = self.run_script("plan_state.py", cwd=worktree)
        self.assertIn(f"Plan: {self.plan.resolve()}", result.stdout)

    def test_off_a_task_branch_it_lists_the_open_plans_only(self):
        landed = self.plan.parent / "old.md"
        landed.write_text("# Plan: old\n\n- Status: landed\n- Branch: feat/old\n")
        self.git("switch", "-q", "main")
        result = self.run_script("plan_state.py")
        self.assertIn("No plan file for this branch. Open plans:", result.stdout)
        self.assertIn("widget.org (in progress, branch feat/widget)", result.stdout)
        self.assertNotIn("old.md", result.stdout)
        self.assertEqual(self.run_script("plan_state.py", "--excerpt").stdout, "")

    def test_plan_state_never_lists_working_notes_as_untracked(self):
        (self.repo / ".gitignore").write_text("")
        self.git("commit", "-q", "-am", "track nothing ignored")
        (self.repo / "new.txt").write_text("x\n")
        result = self.run_script("plan_state.py")
        self.assertIn("Untracked: 1: new.txt", result.stdout)
        self.assertNotIn(".private", result.stdout.split("Untracked:")[1].splitlines()[0])

    def test_outside_a_repository_plan_state_exits_2(self):
        outside = self.root / "plain"
        outside.mkdir()
        self.assertEqual(self.run_script("plan_state.py", cwd=outside).returncode, 2)

    def test_check_step_logs_a_pass_with_the_commit_and_the_test_count(self):
        result = self.run_script("check_step.py", "--step", "S2", "--",
                                 sys.executable, "-c", "print('Ran 3 tests in 0.1s')")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.log()[-1][1:6], ["S2", "check", self.base, "pass", "3"])
        saved = list(self.plan.with_suffix(".runs").iterdir())
        self.assertEqual(len(saved), 1)
        self.assertIn("Ran 3 tests", saved[0].read_text())

    def test_check_step_counts_the_tests_of_each_runner(self):
        # A count that drops when a test fails, or reads only the last of several summaries,
        # hides a lost test when the gates are compared with the baseline.
        check_step = load("check_step", BUILD / "check_step.py")
        maven = ("Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.1 s - in a.FooTest\n"
                 "Tests run: 4, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.2 s - in a.BarTest\n"
                 "\nResults:\n\nTests run: 7, Failures: 1, Errors: 0, Skipped: 0\n")
        cargo = ("test result: ok. 12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n"
                 "   Doc-tests widget\n"
                 "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n")
        samples = (
            ("Ran 3 tests in 0.1s\n\nOK\n", "3"),
            ("Ran 3 tests in 0.1s\n\nOK\nRan 4 tests in 0.2s\n\nOK\n", "7"),
            ("Tests:       1 failed, 3 passed, 4 total\n", "4"),
            ("Test Suites: 1 passed, 1 total\nTests:       1 failed, 3 passed, 4 total\nSnapshots:   0 total\n", "4"),
            ("100% tests passed, 0 tests failed out of 12\n", "12"),
            ("75% tests passed, 1 tests failed out of 4\n", "4"),
            (maven, "7"),
            ("".join(f"[INFO] {line}\n" if line else "\n" for line in maven.splitlines()), "7"),
            (cargo, "12"),
            ("test result: FAILED. 2 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s\n", "3"),
            ("==================== 2 failed in 0.30s ====================\n", "2"),
            ("collected 9 items\n\n=== 3 failed, 5 passed, 1 skipped in 0.12s ===\n", "8"),
            ("1 passed, 2 errors in 0.50s\n", "3"),
            ("widgets: 5 passed\n", "5"),
            ("all good\n", "-"),
        )
        for output, expected in samples:
            with self.subTest(output=output):
                self.assertEqual(check_step.test_count(output), expected)

    def test_check_step_logs_a_dirty_tree_as_uncommitted_and_passes_the_exit_code_on(self):
        (self.repo / "test_a.py").write_text("changed\n")
        result = self.run_script("check_step.py", "--step", "S2", "--", sys.executable, "-c", "raise SystemExit(3)")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.log()[-1][2:5], ["check", "uncommitted(1)", "fail"])

    def test_expect_fail_succeeds_only_when_the_command_fails(self):
        failing = self.run_script("check_step.py", "--step", "S2", "--expect-fail", "--",
                                  sys.executable, "-c", "raise SystemExit(1)")
        self.assertEqual(failing.returncode, 0, failing.stdout)
        self.assertEqual(self.log()[-1][2:5:2], ["fail-first", "fail"])
        passing = self.run_script("check_step.py", "--step", "S2", "--expect-fail", "--",
                                  sys.executable, "-c", "pass")
        self.assertEqual(passing.returncode, 1)
        self.assertIn("does not show the test can fail", passing.stdout)
        self.assertEqual(self.log()[-1][2:5:2], ["fail-first", "pass"])

    def test_check_step_runs_without_a_plan_and_logs_nothing(self):
        self.git("switch", "-q", "main")
        result = self.run_script("check_step.py", "--step", "x", "--", sys.executable, "-c", "pass")
        self.assertEqual(result.returncode, 0)
        self.assertIn("not logged: no plan file", result.stdout)
        self.assertEqual(self.log(), [])

    def test_floor_check_reports_removed_tests_skips_suppressions_and_surfaces(self):
        (self.repo / "test_a.py").write_text(
            "import unittest\n\n\n@unittest.skip('later')\ndef test_one():\n    x = 1  # noqa: F841\n")
        (self.repo / "CMakeLists.txt").write_text("project(x)\n")
        self.git("add", "CMakeLists.txt")
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("removed test: test_a.py: test_two", result.stdout)
        self.assertNotIn("removed test: test_a.py: test_one", result.stdout)  # kept, only decorated
        self.assertIn("added skip: test_a.py: @unittest.skip('later')", result.stdout)
        self.assertIn("added suppression: test_a.py: x = 1  # noqa: F841", result.stdout)
        self.assertIn("risk surface: build: CMakeLists.txt", result.stdout)

    def test_floor_check_raises_a_quick_change_that_outgrew_its_lane(self):
        self.write_plan("quick")
        (self.repo / "test_a.py").write_text((self.repo / "test_a.py").read_text() + "x = 1\n" * 101)
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("raise to the full lane: 101 changed lines", result.stdout)
        (self.repo / "test_a.py").write_text((self.repo / "test_a.py").read_text().replace("x = 1\n" * 101, "x = 1\n"))
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("nothing removed, skipped or suppressed", result.stdout)

    def test_floor_check_sees_a_deleted_test_file_and_hunk_lines_that_look_like_headers(self):
        (self.repo / "q.sql").write_text("-- old comment\nselect 1;\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_x.py").write_text("def test_one():\n    pass\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "more")
        self.base = self.git("rev-parse", "--short", "HEAD")
        self.write_plan("full")
        self.git("rm", "-q", "tests/test_x.py")
        (self.repo / "q.sql").write_text("select 1;\n")
        (self.repo / "test_a.py").write_text("def test_one():\n    pass\n")
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("removed test: tests/test_x.py: test_one", result.stdout)
        self.assertIn("removed test: test_a.py: test_two", result.stdout)
        self.assertNotIn("old comment", result.stdout)
        # 2 lines of the deleted file, 1 in q.sql, 4 in test_a.py (two blank lines and test_two)
        self.assertIn(f"base {self.base}, 7 changed lines", result.stdout)

    def test_floor_check_says_whether_a_diff_changes_only_docs_or_python_comments(self):
        # A docs-only diff runs lighter gates (METHOD.org, Checks), so "yes" needs proof that no
        # code changed: documentation files (by extension, images only under docs/), or Python
        # edits whose tokens other than comments are unchanged. A line inside a string that
        # starts with #, a shebang, an untracked code file and any other file are code. The line
        # informs, it never changes the exit code.
        lib = '"""Doc."""\nX = """\n# data\n"""\nY = 2  # noqa: E501\nZ = 3  # type: ignore\n\n\ndef f():\n    return 1  # one\n'
        (self.repo / "docs").mkdir()
        (self.repo / "docs/guide.org").write_text("* Guide\n")
        (self.repo / "docs/Makefile").write_text("all:\n\techo 1\n")
        (self.repo / "docs/diagram.svg").write_text("<svg>1</svg>\n")
        (self.repo / "docs/notes.txt").write_text("notes\n")
        (self.repo / "docs/authoring.org").write_text("* Authoring\n")
        (self.repo / "docs/CMakeLists.txt").write_text("project(docs)\n")
        (self.repo / "requirements").mkdir()
        (self.repo / "requirements/base.txt").write_text("requests==2.0\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/data").mkdir()
        (self.repo / "tests/data/golden.md").write_text("expected\n")
        (self.repo / "lib.py").write_text(lib)
        (self.repo / "a.c").write_text("int x; /* c */\n")
        (self.repo / "app.json").write_text('{"a": 1}\n')
        (self.repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "more")
        self.base = self.git("rev-parse", "--short", "HEAD")
        self.write_plan("full")
        cases = (
            ({"docs/guide.org": "* Guide\n\nMore prose.\n"}, "yes"),
            ({"lib.py": lib.replace("\n\ndef f", "\n# added\ndef f").replace("# one", "# uno")}, "yes"),
            ({"docs/guide.org": "* Guide 2\n", "lib.py": lib + "# trailing\n"}, "yes"),
            ({"lib.py": lib.replace("# data", "# other")}, "no: lib.py"),
            ({"lib.py": lib.replace("return 1", "return 2")}, "no: lib.py"),
            ({"a.c": "int x; /* changed */\n"}, "no: a.c"),
            ({"app.json": '{"a": 2}\n'}, "no: app.json"),
            ({"logo.png": b"\x89PNG\r\n\x1a\n\x01"}, "no: logo.png"),
            ({"docs/diagram.svg": "<svg>2</svg>\n", "notes.md": "* Notes\n"}, "yes"),
            ({"docs/Makefile": "all:\n\techo 2\n"}, "no: docs/Makefile"),
            ({"new.py": "print(1)\n"}, "no: new.py"),
            ({"lib.py": "#!/usr/bin/env python3\n" + lib}, "no: lib.py"),
            ({"lib.py": "# -*- coding: latin-1 -*-\n" + lib}, "no: lib.py"),
            ({"lib.py": lib.replace("  # noqa: E501", "")}, "no: lib.py"),
            ({"lib.py": lib.replace("# type: ignore", "# typed")}, "no: lib.py"),
            ({"lib.py": None}, "no: lib.py"),
            ({"docs/notes.txt": "more notes\n", "docs/authoring.org": "* Authoring 2\n"}, "yes"),
            ({"docs/CMakeLists.txt": "project(docs2)\n"}, "no: docs/CMakeLists.txt"),
            ({"requirements/base.txt": "requests==3.0\n"}, "no: requirements/base.txt"),
            ({"tests/data/golden.md": "changed\n"}, "no: tests/data/golden.md"),
        )
        for files, verdict in cases:
            with self.subTest(files=sorted(files), verdict=verdict):
                self.git("checkout", "-q", "HEAD", "--", ".")
                self.git("clean", "-fdq")
                for name, content in files.items():
                    path = self.repo / name
                    if content is None:
                        path.unlink()
                    else:
                        path.write_bytes(content) if isinstance(content, bytes) else path.write_text(content)
                result = self.run_script("floor_check.py")
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(f"docs or comments only: {verdict}\n", result.stdout)

    def test_floor_check_counts_python_suppressions_and_skips_only_outside_strings(self):
        # A Python line that only mentions a suppression inside a string or a docstring adds
        # none, nor does one that names a skip in a string or a comment; a real comment or
        # decorator still does.
        (self.repo / "test_a.py").write_text(
            (self.repo / "test_a.py").read_text()
            + "S = \"# noqa: E501 and @unittest.skip('x')\"\n"
            + '"""Doc mentioning # type: ignore\nand @pytest.mark.skip here."""\n'
            + "# a comment naming @unittest.skip\ny = 1  # noqa: E501\n\n\n@unittest.skip('later')\ndef test_three():\n    pass\n")
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        flagged = [line for line in result.stdout.splitlines() if line.startswith(("added skip", "added suppression"))]
        self.assertEqual(flagged, ["added suppression: test_a.py: y = 1  # noqa: E501",
                                   "added skip: test_a.py: @unittest.skip('later')"])

    def test_floor_check_misses_no_real_python_suppression_or_skip(self):
        # Every match on a line is tested, a string-form flag (-Wno-) counts in a string, a
        # file that does not tokenize keeps the line patterns, and line numbers survive deleted
        # lines and blank context lines that git prints empty (diff.suppressBlankEmpty).
        (self.repo / "setup.py").write_text("import os\n\n\nKEEP = 1\nGONE = 2\n\nEND = 3\n")
        (self.repo / "broken.py").write_text("ok = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "more")
        self.base = self.git("rev-parse", "--short", "HEAD")
        self.write_plan("full")
        self.git("config", "diff.suppressBlankEmpty", "true")
        (self.repo / "setup.py").write_text(
            "import os\n\n\nKEEP = 1\n\nEND = 3\n"
            "x = \"# noqa\"; y = 1  # noqa: E501\n"
            "z = \"pytest.skip(\"; pytest.skip(\"real\")\n"
            "ARGS = [\"-Wno-unused-function\"]\n")
        (self.repo / "broken.py").write_text("ok = 1\ns = \"never closed  # noqa\n")
        result = self.run_script("floor_check.py")
        flagged = sorted(line.split(": ", 2)[1] + ": " + line.split(": ", 2)[2]
                         for line in result.stdout.splitlines() if line.startswith(("added skip", "added suppression")))
        self.assertEqual(flagged, sorted([
            'setup.py: x = "# noqa"; y = 1  # noqa: E501',
            'setup.py: z = "pytest.skip("; pytest.skip("real")',
            'setup.py: ARGS = ["-Wno-unused-function"]',
            'broken.py: s = "never closed  # noqa']), result.stdout)

    def test_floor_check_reads_auth_as_a_word_in_security_paths(self):
        # author, authors and authoring are not security; auth, oauth, authorize and
        # authorization are.
        for name in ("docs/skill-authoring.org", "AUTHORS", "auth.py", "oauth.py", "authorize.go", "authorization.py",
                     "cert_authority.go"):
            path = self.repo / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("x\n")
        self.git("add", "-A")
        surfaces = [line for line in self.run_script("floor_check.py").stdout.splitlines()
                    if line.startswith("risk surface: security")]
        self.assertEqual(sorted(surfaces), [f"risk surface: security: {name}"
                                            for name in sorted(("auth.py", "oauth.py", "authorize.go", "authorization.py",
                                                                "cert_authority.go"))])

    def status_line(self, payload, cwd=None):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, "-B", str(BUILD / "status_line.py")], cwd=cwd or self.repo,
                              env=GIT_ENV, input=text, capture_output=True, text=True, check=False)

    def test_the_status_line_shows_the_branch_the_plan_and_the_context_used(self):
        result = self.status_line({"workspace": {"current_dir": str(self.repo)},
                                   "context_window": {"used_percentage": 42.4}}, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
        for part in ("feat/widget", "in progress", "next: S2 add the widget's test", "ctx 42%"):
            self.assertIn(part, result.stdout)

    def test_the_status_line_without_a_plan_shows_the_branch_and_reads_cwd(self):
        self.git("switch", "-q", "main")
        result = self.status_line({"cwd": str(self.repo), "context_window": {"used_percentage": None}}, cwd=self.root)
        self.assertEqual((result.returncode, result.stdout), (0, "main\n"))

    def test_the_status_line_names_a_detached_head(self):
        self.git("switch", "-q", "--detach", "HEAD")
        result = self.status_line({"cwd": str(self.repo)})
        self.assertEqual((result.returncode, result.stdout), (0, "detached\n"))

    def test_the_status_line_never_fails_on_bad_input(self):
        for payload in ("", "not json", "[1, 2]", {"workspace": {"current_dir": str(self.root / "missing")}}):
            with self.subTest(payload=payload):
                result = self.status_line(payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
                self.assertTrue(result.stdout.strip())

    def test_a_base_that_is_not_a_commit_never_reaches_git_as_an_option(self):
        target = self.root / "written-by-git"
        self.plan.write_text(PLAN.format(base=f"--output={target}", lane="full"))
        self.assertEqual(self.run_script("floor_check.py").returncode, 2)
        self.assertIn("Base: unknown", self.run_script("plan_state.py").stdout)
        self.assertFalse(target.exists())
        self.assertFalse(any(p.name.endswith("..HEAD") for p in self.repo.iterdir()))

    def test_check_step_counts_an_untracked_file_as_uncommitted(self):
        (self.repo / "test_new.py").write_text("def test_new():\n    pass\n")
        self.run_script("check_step.py", "--step", "S2", "--", sys.executable, "-c", "pass")
        self.assertEqual(self.log()[-1][3], "uncommitted(1)")

    def test_the_working_notes_never_make_a_run_uncommitted(self):
        (self.repo / ".gitignore").write_text("")  # a project that does not ignore .private
        self.git("commit", "-q", "-am", "track nothing ignored")
        for _ in range(2):  # the second run sees the first run's output and log in .private
            self.run_script("check_step.py", "--step", "S2", "--", sys.executable, "-c", "pass")
        self.assertEqual(self.log()[-1][3], self.git("rev-parse", "--short", "HEAD"))

    def test_nested_working_notes_never_make_a_run_uncommitted_either(self):
        (self.repo / ".gitignore").write_text("")
        sub = self.repo / "sub"
        (sub / ".private" / "plans").mkdir(parents=True)
        (sub / "keep.txt").write_text("x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "sub")
        plan = sub / ".private/plans/widget.org"
        plan.write_text(PLAN.format(base=self.base, lane="full"))
        for _ in range(2):
            self.run_script("check_step.py", "--step", "S2", "--", sys.executable, "-c", "pass", cwd=sub)
        last = plan.with_suffix(".log").read_text().splitlines()[-1].split("\t")
        self.assertEqual(last[3], self.git("rev-parse", "--short", "HEAD"))

    def test_a_notes_folder_in_an_untracked_folder_is_left_out_too(self):
        (self.repo / ".gitignore").write_text("")
        self.git("commit", "-q", "-am", "track nothing ignored")
        sub = self.repo / "sub"  # holds nothing tracked: git lists only "?? sub/"
        (sub / ".private" / "plans").mkdir(parents=True)
        plan = sub / ".private/plans/widget.org"
        plan.write_text(PLAN.format(base=self.base, lane="full"))
        self.run_script("check_step.py", "--step", "S2", "--", sys.executable, "-c", "pass", cwd=sub)
        last = plan.with_suffix(".log").read_text().splitlines()[-1].split("\t")
        self.assertEqual(last[3], self.git("rev-parse", "--short", "HEAD"))
        (sub / "real.txt").write_text("x\n")  # a real untracked file beside it still counts
        self.run_script("check_step.py", "--step", "S2", "--", sys.executable, "-c", "pass", cwd=sub)
        self.assertEqual(plan.with_suffix(".log").read_text().splitlines()[-1].split("\t")[3], "uncommitted(1)")

    def test_a_command_that_never_started_is_no_failing_run(self):
        result = self.run_script("check_step.py", "--step", "S2", "--expect-fail", "--", "no-such-program-xyz --flag")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(self.log(), [])

    def test_check_step_refuses_what_the_guard_blocks(self):
        for command in (["git push origin main"], ["git", "commit", "--no-verify", "-m", "x"]):
            with self.subTest(command=command):
                result = self.run_script("check_step.py", "--step", "S2", "--", *command)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("blocked by the guard", result.stdout)
        self.assertEqual(self.log(), [])
        self.assertEqual(self.git("log", "--oneline").count("\n"), 0)  # nothing was committed

    def test_tail_0_prints_the_whole_output_for_gate_runner(self):
        result = self.run_script("check_step.py", "--step", "final", "--gate", "--tail", "0", "--",
                                 sys.executable, "-c", "print('\\n'.join(map(str, range(50))))")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("0\n1\n2\n"), result.stdout[:40])

    def test_floor_check_that_cannot_run_exits_2(self):
        self.assertEqual(self.run_script("floor_check.py", "--base", "no-such-ref").returncode, 2)

    def test_an_escaped_pipe_in_a_table_cell_keeps_the_later_columns(self):
        # A Check cell holds a command; markdown writes a pipe inside a cell as \|.
        self.plan.write_text(self.plan.read_text().replace(
            "| S2 | widget test | test_a.py | unit | in progress |",
            "| S2 | widget test | test_a.py | unit 2>&1 \\| tail -3 | in progress |"))
        result = self.run_script("plan_state.py")
        self.assertIn("Steps: 1 done, 1 in progress", result.stdout)
        self.assertIn("In progress: S2 widget test (files: test_a.py)", result.stdout)

    def test_floor_check_reads_untracked_files_as_added_lines(self):
        # A new file not yet added is part of the change: its skips, suppressions and risk
        # surfaces count, and so do its lines, one by one inside an untracked folder; a binary
        # file is listed and not scanned.
        (self.repo / "test_new.py").write_text(
            "import unittest\n\n\n@unittest.skip('later')\ndef test_new():\n    x = 1  # noqa: F841\n")
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg/auth.py").write_text("TOKEN = 1\n")
        (self.repo / "pkg/blob.bin").write_bytes(b"\x00\x01")
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"base {self.base}, 7 changed lines", result.stdout)
        self.assertIn("added skip: test_new.py: @unittest.skip('later')", result.stdout)
        self.assertIn("added suppression: test_new.py: x = 1  # noqa: F841", result.stdout)
        self.assertIn("risk surface: security: pkg/auth.py", result.stdout)
        self.assertIn("untracked, counted as added: pkg/auth.py, test_new.py\n", result.stdout)
        self.assertIn("untracked, binary, not scanned: pkg/blob.bin\n", result.stdout)
        # A name with a space and an accent stays whole; a link counts its target as one line.
        (self.repo / "dir é").mkdir()
        (self.repo / "dir é/nota.md").write_text("Nota.\n")
        (self.repo / "link.py").symlink_to("pkg")  # a folder: read through the link, it would fail
        result = self.run_script("floor_check.py")
        self.assertIn(f"base {self.base}, 9 changed lines", result.stdout)
        self.assertIn("untracked, counted as added: dir é/nota.md, link.py, pkg/auth.py, test_new.py\n", result.stdout)

    def test_floor_check_leaves_working_notes_out_also_when_they_are_not_ignored(self):
        (self.repo / ".gitignore").write_text("")
        self.git("commit", "-q", "-am", "track nothing ignored")
        self.base = self.git("rev-parse", "--short", "HEAD")
        self.write_plan("full")
        (self.repo / "sub/.private").mkdir(parents=True)
        (self.repo / "sub/.private/notes.md").write_text("# noqa\n" * 50)
        (self.repo / "extra.py").write_text("y = 1  # type: ignore\n")
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"base {self.base}, 1 changed lines", result.stdout)
        self.assertIn("added suppression: extra.py: y = 1  # type: ignore", result.stdout)
        self.assertIn("untracked, counted as added: extra.py\n", result.stdout)
        self.assertNotIn(".private", result.stdout)

    def test_plan_state_warns_of_a_row_with_more_cells_than_its_header(self):
        # An unescaped pipe in a cell shifts the later columns: the Status read is the wrong cell.
        result = self.run_script("plan_state.py")
        self.assertNotIn("Malformed row", result.stdout)
        self.plan.write_text(self.plan.read_text().replace(
            "| S2 | widget test | test_a.py | unit | in progress |",
            "| S2 | widget test | test_a.py | unit 2>&1 | tail -3 | in progress |"))
        warning = ("Malformed row in Steps: S2 has 7 cells, the header has 6; write a pipe inside a cell "
                   "as \\| in markdown and \\vert in org")
        lines = self.run_script("plan_state.py").stdout.splitlines()
        self.assertIn(warning, lines)
        steps = next(number for number, line in enumerate(lines) if line.startswith("Steps:"))
        self.assertLess(lines.index(warning), steps)
        self.assertNotIn("Malformed row", self.run_script("plan_state.py", "--excerpt").stdout)

    def with_failing_git_status(self) -> dict:
        """An environment whose git fails on status and is the real one otherwise."""
        folder = self.root / "bin"
        folder.mkdir()
        fake = folder / "git"
        fake.write_text('#!/bin/sh\nfor arg in "$@"; do [ "$arg" = status ] && exit 1; done\n'
                        f'exec "{shutil.which("git")}" "$@"\n')
        fake.chmod(0o755)
        return {**GIT_ENV, "PATH": f"{folder}{os.pathsep}{GIT_ENV['PATH']}"}

    def test_a_git_status_that_fails_never_reads_as_a_clean_tree(self):
        # check_step: a run on a tree it could not read is never logged as the commit's;
        # floor_check: exit 2 when git failed, it never reads as clean; plan_state says so.
        (self.repo / "test_a.py").write_text("changed\n")
        env = self.with_failing_git_status()

        def run(name, *args):
            return subprocess.run([sys.executable, "-B", str(BUILD / name), *args], cwd=self.repo, env=env,
                                  capture_output=True, text=True, check=False)

        result = run("check_step.py", "--step", "S2", "--", sys.executable, "-c", "pass")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.log()[-1][2:5], ["check", "uncommitted(?)", "pass"])
        result = run("floor_check.py")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("git status failed; nothing was checked", result.stdout)
        result = run("plan_state.py")
        self.assertIn("Modified tracked files: unknown (git status failed)", result.stdout)
        self.assertNotIn("Modified tracked files: 0", result.stdout)

    def test_floor_check_reads_the_same_paths_under_a_git_diff_prefix_setting(self):
        (self.repo / "test_a.py").write_text("def test_one():\n    pass\n")
        self.git("config", "diff.mnemonicPrefix", "true")  # git then writes c/ and w/, not a/ and b/
        result = self.run_script("floor_check.py")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("removed test: test_a.py: test_two", result.stdout)


if __name__ == "__main__":
    unittest.main()
