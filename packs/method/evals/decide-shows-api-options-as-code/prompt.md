---
name: decide-shows-api-options-as-code
description: "An API choice; decide shows each option as a usage snippet in the question's preview."
tags: [behavior]
runs: 1
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
---

Help me decide how components declare their dependencies in my C++ dependency injection module: constructor parameters, a registration macro, or a service locator.
