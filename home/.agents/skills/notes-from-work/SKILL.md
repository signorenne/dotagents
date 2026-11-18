---
name: notes-from-work
description: "Turns what a work session found (a bug's cause and fix, a workaround, a technique, a tool's surprising behavior) into short, checked notes in the user's knowledge vault: states each finding in general terms, confirms it with a probe and a primary source, has an independent agent try to break it, writes it on a vault branch by the vault's own rules, runs the vault's gates and lands it after the user approves. Use when the user asks to save, note, keep or harvest what was learned, found or fixed into their notes, vault, knowledge base or memex. Not for the state of the work for the next session (session-close) or for notes on how to work in one project, which stay in its docs."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# Notes from work

Goal: what a session found stays findable and true. Each confirmed finding becomes one short note in the user's knowledge vault: the problem in general terms and its fix from start to end. A wrong note costs more than a missing one, so a finding is written only after a check that could have failed and an independent attack, and nothing reaches the vault's main branch before the user approves it.

The vault is the one the user's global instructions name, or the one the user names. Its AGENTS.md and the docs it points to own the note rules (kinds, headings, folders, links, evidence, gates); where they say more than this skill, they win.

## 1. Collect

- Take the findings from the current session, or from what the user points at: a progress log, a handoff, an agent memory file.
- Keep a finding that holds beyond this task: a bug's cause and fix, a workaround, a technique, a tool's surprising behavior. Leave out how to work in one project (its paths, what not to touch): that stays in the project's docs.
- State each as one claim in general terms with its conditions: the tool and version, the setup, what was being done.
- Leave out secrets, tokens, internal hostnames and client code. A finding from work under a confidentiality duty is stated only in general terms, and the user decides whether it goes in at all.

## 2. Search the vault

Search titles, aliases and full text for each claim. A note with the same scope is extended instead of repeated. A note that states the fact in a clause keeps the clause and links the new note; correct the clause when the check shows it wrong.

## 3. Confirm

Give each claim a check that could fail, and keep its exact commands and output:
- a probe that reproduces the behavior, with a control that shows the probe can see the other outcome (for a fix: broken before, working after);
- the primary source for the version in use: the program's source at its release tag, its manual or its man page, opened and read at the relevant place.

Run probes in a throwaway environment (a fresh process with its own name, never the user's running programs) and from a file, so the agent's own command line and settings are not part of what is measured. A claim no check confirms is not written; report it with what is missing.

## 4. Attack

Give the claims, worded as the notes will state them, to a subagent that did not write them, with the sources, the safety rules for its probes and the instruction not to read your probes. Ask it to try to refute each claim and to answer holds, holds only with narrower wording (giving that wording) or refuted, with its evidence. In Claude Code use the general-purpose subagent, told to write only in its own scratch folder; elsewhere use the reviewer, told that its target is the claims. Check each narrowing or refutation yourself before relying on it, then reword: a refuted fix is dropped or moved to the limits, and a claim that does not survive is not written.

## 5. Write on a vault branch

- Work on a branch in a worktree outside the vault, made from its main, unless the vault's rules say otherwise.
- Write each finding as the kind the vault's rules give it, usually a failure note for a bug or a workaround and a procedure note for a technique: a sentence or two of background, the problem in general terms, the cause and how to tell it, the fix as numbered steps, the verification (the probe that ran and the output seen, with versions and date), the limits of what was not checked, the connections, and the sources (a reference for each documented fact, and where the finding was observed).
- Keep it clear and concise: one idea per note, each fact in one place, nothing about how the session went.
- Add the links the vault's rules ask for (its folder index, its troubleshooting map) and the clause links of step 2, and the outcome line its rules ask for.
- Commit in the vault's convention, run its documented gates (long runs through gate-runner, with the folder and the commit) and the review its rules ask for (reviewer).

## 6. Approve and land

Show the user each note: title, kind and path, the claim in one line, its evidence, and what the attack changed; then the findings left out and why. On the user's yes, rebase the branch on the vault's main if main moved and run the gates again, fast-forward main, then remove the worktree and the branch. On a change, edit on the branch and show it again. Reply with the notes landed, the findings left out, and the gate results with the commit they ran on.
