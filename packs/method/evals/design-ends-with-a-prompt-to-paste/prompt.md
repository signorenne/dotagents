---
name: design-ends-with-a-prompt-to-paste
description: "A design-only request; the reply opens with Done: yes or Done: no and gives the next step as a prompt to paste in a fenced block."
tags: [behavior]
runs: 1
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
---

Use the design skill: design a tags feature for my notes app: tagging a note, filtering by tag, renaming a tag. Every choice is yours: decide them yourself.
