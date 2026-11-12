---
name: build-on-resume
description: "Ask to resume work on a branch; build resumes from the plan file."
tags: [trigger]
runs: 3
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Continue the work on this branch from where the last session stopped.
