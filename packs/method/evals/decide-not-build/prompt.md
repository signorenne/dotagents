---
name: decide-not-build
description: "A choice that belongs to the user goes to decide, not build."
tags: [trigger]
runs: 3
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

For this project, should we store the data in SQLite or in Postgres? Help me decide.
