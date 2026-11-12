# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Tests for the scripts bundled with skills."""

import contextlib
import importlib.util
import io
import shutil
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


if __name__ == "__main__":
    unittest.main()
