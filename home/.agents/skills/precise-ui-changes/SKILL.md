---
name: precise-ui-changes
description: "Makes and proves visual UI fixes (layout, spacing, alignment, sizes, icons, visual regressions) in any UI stack: renders the exact state repeatably at device pixels, crops and measures instead of eyeballing, makes the smallest change, proves with a bundled diff check that nothing outside the intended area moved, and only then updates the reference screenshots. Use when the user asks to fix or adjust how a screen or element looks, to align or resize UI elements, or to update screenshot or golden-image tests after a visual change."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Precise UI changes

A visual fix is done when a check that could have failed passes, not when a screenshot looks right. Work in this order.

## 1. Render the exact state, repeatably

- Render through the project's own screenshot or golden-image tests when it has them: a temporary scenario, story or test case gives an exact screenshot of any state. Otherwise grab the window or the item offscreen. Render every state the fix touches (modes, themes, sizes, languages) with the unchanged code into a scratch before folder, one subfolder per state: section 5 compares against it.
- Make the frame repeatable before capturing: fixed data, clock, locale, time zone and random seed; animations finished or disabled, the app's own included; no text cursor, no hover; fonts bundled and loaded; capture once two consecutive frames are identical. Mask only content that changes by itself (a clock, live data), and keep masks small: a mask hides any regression under it.
- Capture device pixels at the target's pixel ratio, not a scaled preview window (in Playwright, scale "device"), and compare only with references made in the same environment (OS or container, renderer, fonts, browser or simulator). Judge final crispness and GPU effects on the real device.

## 2. Look at the right scale

A whole frame scaled down hides the details a layout fix is about, and an image given to a model is downscaled again. Crop the same region from every state and view the crops side by side, at 1:1 or enlarged without smoothing (for example Pillow: Image.crop, then resize with Image.NEAREST).

## 3. Measure instead of eyeballing

- Read the geometry from the UI first: the layout tree or the element's position and size (Qt: mapToItem, x, y, width, height; Playwright: boundingBox; the platform's layout inspector). It is exact and free of rendering noise.
- Measure the pixels when what shows differs from the box (text ascent, padding, soft art): find the rows and columns of a known colour, or, where a gradient has no clean edge, draw a pixel ruler on an enlarged crop and read the edges from it.
- Convert the numbers into the coordinates the code uses and check them against the code that places the element. When they agree, compute the fix from them; when they disagree, something else positions the element: find it first.

## 4. Change the smallest thing, then render again

Change the fewest values that reach the measured target (one offset that fits every state beats a table per state). Render the same states again, crop the same regions and measure again.

## 5. Prove nothing else moved

Run the bundled script with python3; it needs Pillow (ask before installing it): in Claude Code python3 ${CLAUDE_SKILL_DIR}/scripts/nothing_moved.py, elsewhere python3 ~/.agents/skills/precise-ui-changes/scripts/nothing_moved.py. Render the new frames into an after folder with the same subfolders and file names.

1. Measure the noise: render one state twice with unchanged code and run nothing_moved.py noise <first.png> <second.png>. The largest difference it prints is the threshold. Noise is usually 1 or 2 levels; a higher threshold lets real shifts of soft edges and colours through, so above 2 make the frame repeatable first (section 1) and measure again.
2. Set the allowed areas from intent, not from the diff, for each state: the rectangle of each element you meant to change, in the frame's device pixels (the coordinates from section 3 times the pixel ratio, plus the item's offset in the frame), padded by a few pixels for anti-aliasing and soft edges.
3. For each state, run nothing_moved.py check --before <before folder>/<state> --after <after folder>/<state> --threshold <noise> --allow <left,top,right,bottom>, one --allow per area of that state, so a move in one state cannot hide in another state's area. It fails (exit 1) on any changed pixel outside the allowed areas, on a size change, and on a new frame without a reference; exit 2 means wrong usage or unreadable input, not a result. Without --allow it shows where each frame changed.
4. Run it once with an allowed area that leaves out part of the intended change, and see it fail there: then you know it would catch a real move.
5. When it fails, the reported box says where: a change that spread beyond the element, or an allowed area drawn too tight. Find out which before widening anything.

## 6. Update the references last

Only after section 5 passes: predict which references will change, regenerate them with the project's own update command, check that exactly those changed, rerun the whole screenshot suite, look at each changed reference as an image, and commit the references with the fix. Report them as changed expected values, with the request and the check's output as their evidence (trustworthy-tests). Delete the temporary scenarios and frames.

A bug in how something moves or appears over time (it snaps instead of fading, stays empty, arrives late) also needs a behavior test, written and seen failing with the trustworthy-tests skill: a screenshot shows one moment.
