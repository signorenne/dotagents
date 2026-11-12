#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicolò Plebani (nexenne)
"""Draw numbered markers on a screenshot, for a legend that explains each element.

Usage:
  python3 annotate.py IN.png OUT.png --mark X,Y [--mark X,Y ...] [--crop L,T,R,B] [--radius N]

Each --mark is the centre of one marker in pixels of IN.png; markers are numbered
1, 2, 3 in the order given, so the legend under the picture uses the same numbers.
--crop keeps only the rectangle left,top,right,bottom of IN.png (right and bottom
excluded) before drawing; every marker must fall inside it. --radius sets the marker
size in pixels (default 14).

Exit status: 0 written, 2 wrong usage, unreadable input or missing Pillow.
Drawing needs Pillow (pip install pillow).
"""

from __future__ import annotations

import argparse
import sys


class UsageError(Exception):
    """Wrong usage or input: exit status 2."""


def parse_point(text: str) -> tuple:
    parts = text.split(",")
    if len(parts) != 2:
        raise ValueError(f"expected X,Y, got {text!r}")
    x, y = (int(p) for p in parts)
    if x < 0 or y < 0:
        raise ValueError(f"negative point {text!r}")
    return (x, y)


def parse_box(text: str) -> tuple:
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError(f"expected left,top,right,bottom, got {text!r}")
    left, top, right, bottom = (int(p) for p in parts)
    if left >= right or top >= bottom or left < 0 or top < 0:
        raise ValueError(f"empty or negative rectangle {text!r}")
    return (left, top, right, bottom)


def place(marks: list, size: tuple, crop: tuple | None) -> list:
    """Marker centres in the output picture; every mark must lie inside the picture or the crop."""
    left, top, right, bottom = crop if crop else (0, 0, size[0], size[1])
    if right > size[0] or bottom > size[1]:
        raise UsageError(f"crop {crop} is larger than the picture {size[0]}x{size[1]}")
    placed = []
    for number, (x, y) in enumerate(marks, start=1):
        if not (left <= x < right and top <= y < bottom):
            raise UsageError(f"marker {number} at {x},{y} is outside the picture area {left},{top},{right},{bottom}")
        placed.append((number, x - left, y - top))
    return placed


def draw(source: str, target: str, marks: list, crop: tuple | None, radius: int) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise UsageError("drawing needs Pillow: pip install pillow") from None
    with Image.open(source) as image:
        picture = image.convert("RGBA")
    placed = place(marks, picture.size, crop)
    if crop:
        picture = picture.crop(crop)
    pen = ImageDraw.Draw(picture)
    try:
        font = ImageFont.load_default(size=round(radius * 1.2))
    except TypeError:  # Pillow before 10.1 has one fixed-size default font
        font = ImageFont.load_default()
    for number, x, y in placed:
        box = (x - radius, y - radius, x + radius, y + radius)
        pen.ellipse(box, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255), width=max(2, radius // 6))
        label = str(number)
        left, top, right, bottom = pen.textbbox((0, 0), label, font=font)
        pen.text((x - (right - left) / 2 - left, y - (bottom - top) / 2 - top), label, fill=(20, 20, 20, 255), font=font)
    picture.save(target)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--mark", action="append", default=[], required=True, help="X,Y of a marker; repeatable")
    parser.add_argument("--crop", help="left,top,right,bottom to keep")
    parser.add_argument("--radius", type=int, default=14, help="marker radius in pixels")
    args = parser.parse_args(argv)
    try:
        if args.radius < 4:
            raise UsageError("radius must be at least 4")
        marks = [parse_point(text) for text in args.mark]
        crop = parse_box(args.crop) if args.crop else None
        draw(args.source, args.target, marks, crop, args.radius)
    except Exception as error:  # any failure to draw is a usage or input error
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"wrote {args.target} with {len(marks)} markers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
