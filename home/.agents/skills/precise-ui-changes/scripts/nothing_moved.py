#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Prove that a UI change moved nothing outside the areas it was meant to change.

Usage:
  python3 nothing_moved.py noise FIRST.png SECOND.png
      Two renders of the same state with the same code. Prints the largest channel
      difference between them: the rendering noise, to pass as --threshold.

  python3 nothing_moved.py check --before DIR --after DIR --threshold N [--allow L,T,R,B ...]
      Compares each PNG under --after with the PNG at the same relative path under
      --before. A pixel counts as changed when one of its R, G, B or A values differs
      by more than N (0 to 254). Fails when a changed pixel lies outside every --allow
      rectangle, when a frame changed size, or when a frame under --after has no
      reference. A rectangle is left,top,right,bottom in pixels, right and bottom
      excluded. Without --allow, every change counts as outside, which shows where
      frames changed.

Exit status: 0 pass, 1 something changed outside the allowed areas, 2 wrong usage,
unreadable input or missing Pillow. Reading PNG files needs Pillow (pip install pillow).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

Box = tuple  # (left, top, right, bottom), right and bottom excluded


class UsageError(Exception):
    """Wrong usage or input the check cannot judge: exit status 2."""


@dataclass
class Changes:
    inside: int = 0
    outside: int = 0
    outside_box: Box | None = None


def parse_box(text: str) -> Box:
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(f"expected left,top,right,bottom, got {text!r}")
    left, top, right, bottom = (int(p) for p in parts)
    if left >= right or top >= bottom or left < 0 or top < 0:
        raise ValueError(f"empty or negative rectangle {text!r}")
    return (left, top, right, bottom)


def parse_threshold(text: str) -> int:
    value = int(text)
    if not 0 <= value <= 254:
        raise argparse.ArgumentTypeError("threshold must be 0 to 254")
    return value


def grow(box: Box | None, x: int, y: int) -> Box:
    if box is None:
        return (x, y, x + 1, y + 1)
    return (min(box[0], x), min(box[1], y), max(box[2], x + 1), max(box[3], y + 1))


def classify(width: int, height: int, diff: bytes, threshold: int, allowed: list) -> Changes:
    """Count changed pixels inside and outside the allowed boxes.

    diff holds one byte per pixel, row by row: the largest channel difference there.
    """
    if len(diff) != width * height:
        raise ValueError("diff size does not match width and height")
    marks = bytes(0 if level <= threshold else 1 for level in range(256))
    result = Changes()
    for y in range(height):
        row = diff[y * width:(y + 1) * width].translate(marks)
        x = row.find(1)
        while x != -1:
            if any(l <= x < r and t <= y < b for l, t, r, b in allowed):
                result.inside += 1
            else:
                result.outside += 1
                result.outside_box = grow(result.outside_box, x, y)
            x = row.find(1, x + 1)
    return result


def load_pair(first: Path, second: Path):
    """Return (size of first, size of second, per-pixel largest channel difference or None)."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        raise UsageError("reading PNG files needs Pillow: pip install pillow") from None
    with Image.open(first) as a_file, Image.open(second) as b_file:
        for path, image in ((first, a_file), (second, b_file)):
            if image.mode.startswith("I") or image.mode == "F":
                raise UsageError(f"{path}: {image.mode} images (16-bit greyscale or float) are not supported; save 8-bit PNGs")
        a = a_file.convert("RGBA")
        b = b_file.convert("RGBA")
    if a.size != b.size:
        return a.size, b.size, None
    bands = ImageChops.difference(a, b).split()
    largest = bands[0]
    for band in bands[1:]:
        largest = ImageChops.lighter(largest, band)
    return a.size, b.size, largest.tobytes()


def pngs(folder: Path) -> dict:
    """PNG files under folder, by path relative to it, at any depth and in any case."""
    if not folder.is_dir():
        raise UsageError(f"{folder} is not a folder")
    return {p.relative_to(folder).as_posix(): p
            for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".png"}


def noise(args: argparse.Namespace) -> int:
    size_a, size_b, diff = load_pair(Path(args.first), Path(args.second))
    if diff is None:
        print(f"FAIL: sizes differ ({size_a[0]}x{size_a[1]} and {size_b[0]}x{size_b[1]}): not the same state")
        return 1
    level = max(diff) if diff else 0
    count = len(diff) - diff.count(0)
    print(f"noise: largest channel difference {level}, on {count} of {len(diff)} pixels")
    return 0


def check(args: argparse.Namespace) -> int:
    allowed = [parse_box(text) for text in args.allow]
    references = pngs(Path(args.before))
    frames = pngs(Path(args.after))
    if not frames:
        raise UsageError(f"no PNG files under {args.after}")
    failed = 0
    for name in sorted(frames):
        reference = references.get(name)
        if reference is None:
            print(f"FAIL {name}: no reference under {args.before}")
            failed += 1
            continue
        size_ref, size_new, diff = load_pair(reference, frames[name])
        if diff is None:
            print(f"FAIL {name}: size changed from {size_ref[0]}x{size_ref[1]} to {size_new[0]}x{size_new[1]}")
            failed += 1
            continue
        found = classify(size_new[0], size_new[1], diff, args.threshold, allowed)
        if found.outside:
            box = ",".join(str(v) for v in found.outside_box)
            print(f"FAIL {name}: {found.outside} changed pixels outside the allowed areas, within {box}; {found.inside} inside")
            failed += 1
        else:
            print(f"ok   {name}: {found.inside} changed pixels, all inside the allowed areas")
    unmatched = len(set(references) - set(frames))
    if unmatched:
        print(f"note: {unmatched} references have no new frame and were not compared")
    print(f"{'FAIL' if failed else 'PASS'}: {failed} of {len(frames)} frames failed")
    return 1 if failed else 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    p_noise = commands.add_parser("noise", help="largest difference between two renders of one state")
    p_noise.add_argument("first")
    p_noise.add_argument("second")
    p_check = commands.add_parser("check", help="fail on changes outside the allowed areas")
    p_check.add_argument("--before", required=True, help="folder with the reference frames")
    p_check.add_argument("--after", required=True, help="folder with the new frames, same relative paths")
    p_check.add_argument("--threshold", required=True, type=parse_threshold,
                         help="the noise level, 0 to 254; larger differences count")
    p_check.add_argument("--allow", action="append", default=[], help="left,top,right,bottom; repeatable")
    args = parser.parse_args(argv)
    try:
        return noise(args) if args.command == "noise" else check(args)
    except Exception as error:  # any failure to judge is a usage or input error, never a result
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
