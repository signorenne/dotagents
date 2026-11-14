---
name: decide-confirms-each-decision
description: "Confirm several settled choices; decide asks each through the question box, not one yes for a list."
tags: [behavior]
runs: 1
max_turns: 6
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
---

We settled three choices for my command line tool: the config file is TOML, logs go to stderr, and there is no plugin system in version 1. Use decide to confirm and record them.
