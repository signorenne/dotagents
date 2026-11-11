---
name: mechanical-changes
description: "Carries out one mechanical change across many files (a rename, an API migration, moving code between files, replacing a pattern everywhere) without changing behavior: a tested matcher finds every site, a written rulebook drives a re-runnable transformation, a trial on a sample comes first, each unit is checked from the cheapest check to the build, and the change lands in shards that build and revert on their own. Use when the user asks for a codemod, a repository-wide rename, refactor or migration, or the same edit in many files."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Mechanical changes

Goal: one transformation applied at every site, nothing else changed, every step provable. A change that also alters behavior is two changes: make the behavior change in its own commits, before or after.

Run it as an implement task when that skill is available: the rulebook, the site count and the shards are the plan, the trial in section 4 is its first step, each shard is one step and one commit on the task branch (or, split across agents, lands from its agent's branch), and the review in check 6 goes to the reviewer subagent.

## 1. Baseline and rulebook

- Run the project's gates before touching anything and record the result, so failures that already exist are neither blamed on the change nor block it.
- Write the transformation as a rulebook: the rule, examples of input and expected output, and the cases that must stay unchanged. Take the conventions (formatting, attributes, qualifiers, include placement, naming) from code that already follows the target form and write them down; copying an arbitrary example spreads its old habits.
- List what this "mechanical" change can still alter (performance, ABI and linkage, inlining, initialization order, generated code, lookups of a name by string or reflection). Settle with the user each one that touches public API or behavior (decide skill), and record the rest as your decisions.

## 2. Find every site with a tested matcher

- Use a matcher that understands the language: the compiler's tooling (clang-query, clang-tidy), a language server rename, or a structural tool (Coccinelle, OpenRewrite, jscodeshift, Comby). A regex cannot tell two methods with the same name apart and both over- and under-matches; use one only where the syntax is trivial.
- Test the matcher before trusting its count: a file of known cases with traps (sites in comments, strings and macros, templates, look-alike names, multi-line forms) where it must find exactly the expected sites; a real file counted by hand; and an independent count by a different kind of method (the compiler against a text search), with every disagreement explained. A missed site is worse than a false positive. Add each later mistake to the known cases.
- Record the number of sites and files: later checks must bring it to zero.

## 3. Transform with a process you can re-run

- Prefer a script or tool to hand edits. When a rule turns out wrong, fix the rule and run it again from a clean base instead of patching its output; when agents do the edits, fix the rulebook and redo the affected files.
- Fail closed: the script checks every file before it writes any, and refuses a file where the pattern does not match the expected number of times or where two edits overlap. No change is better than a wrong one.
- Run the formatter as a separate last pass, so formatting does not hide the transformation in the diff. Where a hook formats every file an agent edits, make the edits by script through the shell, or apply the formatter to both sides before check 2.
- For an interface change (a rename, a new signature, a moved type), expand and contract: add the new form beside the old one (alias, forwarding function, wrapper), migrate the callers, then remove the old form in a last change.

## 4. Trial, then scale

Run the whole loop on a small sample first (a few files, including the hardest ones), review the result, fix the rules, and only then run it everywhere. To split the rest across agents, use the parallel-agents skill: a shard is a group of files that must change together (a header and its source, a module and its build file), shared files such as build lists get one owner and change after the others, and every shard gets the same rulebook.

## 5. Verify each shard, cheapest check first

Stop at the first failure:

1. the matcher finds no remaining site;
2. the diff holds only the transformation: compare the code before and after, ignoring whitespace (moved code compared byte for byte, or by syntax tree when a tool can);
3. every reference resolves: includes, imports, build file entries;
4. the build with no new warnings compared with the baseline, in every configuration, platform and build option the project supports: a build proves only what it compiled;
5. the affected tests, then the full gates;
6. an independent review of the rule and the tooling output, then of the anomalies the checks reported, rather than of every site.

Checks 1 to 3 run without a build and catch most mistakes cheaply, but they never replace it.

## 6. Land

- Each shard builds, passes and can be reverted on its own; land the shards in an order where every commit builds. Make one atomic change only when the halfway state is itself costly and the whole change can be built and tested at once.
- Add a check to the gates that keeps the old form from coming back (the matcher as a lint or a test).
- Report the rule, the site count before and after, the shards and their commits, the configurations built, and the risks from section 1 that remain.
