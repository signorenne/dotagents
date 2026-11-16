---
name: decide-reads-the-named-source-first
description: "A source the user names settles part of the choice; decide reads it before asking."
tags: [behavior]
runs: 1
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
---

Use the decide skill: help me decide the voltage range of the alternator slider in my simulator. The old app's config, old/app.cfg, lists the good and the bad thresholds.
