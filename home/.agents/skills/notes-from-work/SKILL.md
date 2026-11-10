---
name: notes-from-work
description: "Turns what a work session found (a bug's cause and fix, a workaround, a technique, a tool's surprising behavior) into short notes in the user's knowledge vault, each confirmed, attacked by an independent agent and landed on the vault's main only after the user approves. Use when the user asks to save, note, keep or harvest what was learned, found or fixed into their notes, vault, knowledge base or memex; prefer it over atomic-notes for findings from work. Not for the state of the work for the next session (close) or for notes on how to work in one project, which stay in its docs."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne, signorenne). See LICENSE.txt"
---

# Notes from work

Goal: what a session found stays findable and true. Each confirmed finding becomes one short note in the user's knowledge vault: the problem in general terms and its fix from start to end. A wrong note costs more than a missing one, so a finding is written only after a check that could have failed and an independent attack, and nothing reaches the vault's main branch before the user approves it.

The vault is the one the user's global instructions name, or the one the user names; when neither names one, or the vault has no AGENTS.md or no documented gates, stop and ask. Its AGENTS.md and the docs it points to own the note rules (kinds, headings, folders, links, evidence, gates); where they say more than this skill, they win. Keep each step, every probe and its output in the working notes its rules name (for example .private/progress/), so they outlive the session.

## 1. Collect

- Take the findings from the current session, or from what the user points at: a plan file, a handoff, an agent memory file.
- Keep a finding that holds beyond this task: a bug's cause and fix, a workaround, a technique, a tool's surprising behavior. Leave out how to work in one project (its paths, what not to touch): that stays in the project's docs.
- State each as one claim in general terms with its conditions: the tool and version, the setup, what was being done.
- Leave out secrets, tokens, internal hostnames and client code. A finding from work under a confidentiality duty is stated only in general terms, and the user decides whether it goes in at all.

## 2. Search the vault

Search titles, aliases and full text for each claim. A note with the same scope is extended instead of repeated. A note that states the fact in a clause keeps the clause and links the new note; correct the clause when the check shows it wrong.

## 3. Confirm

Give each claim a check that could fail:
- a probe that reproduces the behavior, with a control that shows the probe can see the other outcome (for a fix: broken before, working after);
- the primary source for the version in use: the program's source at its release tag, its manual or its man page, opened and read at the relevant place.

Run probes in a throwaway environment (a fresh process with its own name, never the user's running programs) and from a file, so the agent's own command line and settings are not part of what is measured. A claim no check confirms is not written; report it with what is missing.

## 4. Attack

Give the claims, worded as the notes will state them, to a subagent that did not write them, with the sources, the safety rules for its probes and the instruction not to read your probes. Ask it to try to refute each claim and to answer holds, holds only with narrower wording (giving that wording) or refuted, with its evidence. Use the general-purpose subagent in Claude Code on the session's model at effort high (it judges), and the tool's default general agent elsewhere, told to write only in its own scratch folder and to return one line per claim with its evidence; where the tool has no subagents, ask the user before writing claims that no independent agent checked, and say so in step 6. Check each narrowing or refutation yourself before relying on it, then reword: a refuted fix is dropped or moved to the limits, and a claim that does not survive is not written.

## 5. Write on a vault branch

- Make the branch and its worktree from the vault's main as the isolated-work skill does, unless the vault's rules say otherwise.
- Write each finding as the kind the vault's rules give it, usually a failure note for a bug or a workaround and a procedure note for a technique: a sentence or two of background, the problem in general terms, the cause and how to tell it, the fix as numbered steps, the verification (the probe that ran and the output seen, with versions and date), the limits of what was not checked, the connections, and the sources (a reference for each documented fact, and where the finding was observed).
- Keep it clear and concise: one idea per note, each fact in one place, nothing about how the session went.
- Add the links the vault's rules ask for (its folder index, its troubleshooting map), the clause links of step 2 and the outcome line its rules ask for.
- Commit, then run the vault's documented gates through gate-runner and its review through reviewer, giving both the worktree and the commit expected there, and the reviewer the vault's main as base.

## 6. Approve and land

Show the user each note: title, kind and path, the claim in one line, its evidence, and what the attack changed; then the findings left out and why. On a change, edit on the branch, run the gates and the review again, and show it again. On the user's yes, land the branch as isolated-work does; when the user rejects every note, remove the worktree and the branch without landing. Reply with the notes landed, the findings left out, and the gate results with the commit they ran on.
