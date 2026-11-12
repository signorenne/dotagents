---
name: code-audit
description: "Audits an existing repository or area for problems and writes a local report: security issues, likely bugs and maintainability smells, each confirmed by an independent check and carrying severity, confidence, file:line and evidence, with everything uncertain kept apart as questions for the user. Use when the user asks to audit, inspect or assess code, or to find bugs, code smells, risks or technical debt in a codebase or module. Not for reviewing one change before a commit (review) or documenting code (as-built-docs)."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Code audit

Goal: a short list of problems the owner can act on and trust. A wrong finding costs more than a missed one, because after a few false alarms people stop reading: report only what an independent check confirmed, and turn every doubt into a question.

## 1. Scope

- From the request: the area (whole repository, module, files), the concerns (security, bugs, maintainability, a specific worry), and anything already known (a list for the audit from as-built-docs, a bug report).
- Read the project's AGENTS.md, decision log and conventions: a pattern the project chose on purpose is not a smell.
- Run the project's gates once and record the result, so existing failures are known.
- The report goes to .private/audit/<date>-<scope>.md when .private/ is git-ignored; otherwise ask once where it goes. It is never committed unless the user asks.

## 2. Find candidates

- Map the area with scout (for a large repository, one read-only subagent per area), then read yourself the code each candidate depends on.
- Look in this order:
  - security: input reaching a dangerous call, secrets in code, missing authorization, unsafe parsing or deserialization, each named with its CWE;
  - likely bugs: wrong results, races, resource leaks, unchecked errors, boundary mistakes, undefined behavior, mismatches with a contract or spec;
  - maintainability: named smells (duplicated code, long function, feature envy, shotgun surgery, and the like), each kept only with its concrete cost in this code.
- Use the tools the project has (compiler warnings, sanitizers, static analyzers, linters) and record what they report.
- Before keeping a candidate, check the code's own guards: validation upstream, invariants the callers keep, tests that cover the case.

## 3. Confirm each candidate

Give each candidate a check that could fail: a failing test, a command and its output, a reproduction, or a reviewer subagent given only the code and the claim and told to refute it. What survives becomes a finding. Anything you cannot confirm, that depends on intent, environment or a threat model, or that you do not fully understand, goes to Questions instead. Drop issues that cannot happen in this code and style preferences the project's rules do not back.

## 4. Report

1. Scope and method: what was read, which tools and commands ran with their results, what was left out.
2. Findings, grouped as Security, Likely bugs and Maintainability, strongest first. Each finding has:
   - a title and file:line (with the path from input to the dangerous call when relevant);
   - what happens and when;
   - severity (Blocker, High, Medium, Low), from the worst credible consequence and how likely it is;
   - confidence (High or Medium);
   - the evidence: the check from section 3 and its output;
   - what would prove it wrong;
   - a recommendation in one or two sentences.
3. Questions for the user: what was seen (file:line), why it is unclear, and the answer that would settle it, with no severity.
4. Not checked: areas, configurations and risks left out.

Fix nothing and commit nothing: a finding the user wants fixed goes through the implement skill, starting with a failing test.
