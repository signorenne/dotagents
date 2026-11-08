---
name: trustworthy-tests
description: "Writes and reviews automated tests that can fail: expected values from the spec, each test seen failing for the right reason, never weakened to pass. Use when writing, changing or reviewing tests."
license: "MIT, Copyright (c) 2026 Nicolò Plebani (nexenne). See LICENSE.txt"
---

# Trustworthy tests

A test is a claim that the code does what its contract says, and it is evidence only if it could have failed. A false-positive test is worse than no test: it reports green, so nobody looks, and the bug ships with a certificate. The usual way to write one is to test the code against itself: take the expected value from what the code returns, mock the logic under test, or edit the test until it passes. Each of these turns a refutation into a formality.

These rules apply to every automated test you write, change or review: unit tests first, and the same rules for integration and end-to-end tests. They work the same whether the user asked for tests directly or a caller (the implement skill, a workflow, an orchestrating agent) gave you a step: the caller names the behavior to pin (a spec section, an acceptance criterion, a bug report), the files and the project's test command, and gets back the report described in Output.

## 1. Start from the contract, not from the code

- Before writing a test, state in one sentence the behavior it pins: the input or state, the action, the observable outcome. Take it from the spec, the documentation, the bug report or the user, not from what the code does today.
- Derive every expected value independently of the code under test: by hand, from an example in the spec, from a reference implementation or another trusted oracle. Never run the code and paste its output as the expectation: that freezes current behavior, bugs included. A snapshot or golden file is fine only for output meant to stay fixed, and its first version is checked against the contract like any other expected value.
- When the contract does not settle a case and the answer would change the test, ask (or, inside a caller's step, report it as an open question); otherwise leave that case untested and list it in the report. Never encode a guess as the truth.

## 2. Write tests that a wrong implementation fails

- Assert the observable outcome: the return value, the state change, the output, the error type and message, the call that crosses a real boundary. Every test has at least one assertion that a plausible wrong implementation would violate.
- Be specific: exact values, the specific exception, the expected order. "Is not None", "raises nothing", "length above zero" or "was called" are enough only when they are the whole contract. Wrap only the call that should raise in the block that expects an exception, so an exception from the setup cannot pass the test.
- Mock only boundaries you cannot run in a test or do not own (network, clock, randomness, external services, and the filesystem when a temporary directory will not do). Never mock the unit under test or the logic the test is about; an assertion on a value the mock itself returns tests the mock. Call a mock's assertion methods by their exact names: a misspelled one can pass silently and check nothing (unittest.mock catches only some misspellings, such as called_once_with from Python 3.12, and none with unsafe=True).
- Make sure every assertion executes: await asynchronous code in a runner that awaits it, return or await promises, check that callbacks were called, and do not rely on assertions the build can compile out (NDEBUG, python -O).
- Cover where implementations go wrong: boundaries (zero, one, the limit and its neighbors, empty input), invalid input and error paths, the exact case from a bug report, a second run of an operation meant to be idempotent (a retry, rerun or migration), and a caller without permission being refused. One behavior per test, named for that behavior, so a failure says what broke.
- Keep tests deterministic and independent: seed randomness, inject or fix the clock, wait on conditions rather than sleeping, share no mutable state, and pass in any order. A flaky test is not evidence.

## 3. See every new or changed test fail for the right reason

This step is what separates a test from a decoration. Before trusting a test, watch it fail, and read the failure: it must name the behavior the test pins, not an import error, a typo, a missing fixture or a test that was never collected. Do it once per behavior, not once per case: a table of cases for one behavior needs one failing run, and a test moved or renamed without changing what it asserts needs only a check that it still runs.

- New behavior: run the test before the implementation exists or is wired in.
- Bug fix: run it on the unfixed code; it must fail on the bug.
- A test for code that already exists: break the code on purpose with one small change to the behavior the test pins (flip a comparison, move a boundary, return a constant, drop a call, revert the fix), run the test, see it fail, then undo exactly that change. First check that the broken code built: a change that does not compile leaves the old binary to run, or a build error to read as the test's failure. Undo it by editing it back, never with git checkout, git restore or git stash on a file that holds other uncommitted work, and confirm with git diff that only the intended changes remain. If the test still passes, first confirm that it ran the code you changed (not a stale build, an installed copy or a cached binary). If it did, the test pins nothing: strengthen it, remove it if you added it in this change, and otherwise report it.
- If the project documents a mutation testing tool, run it on the touched code as well; do not install one without asking.

Record each observation: the command and the failing line of its output. Then make the test pass and run it again together with the suite it belongs to, and check that the runner counts the new tests among those it ran. When a script rewrites part of a test file, list the file's test functions before and after the edit and check that only the intended ones changed.

When you cannot run the tests (for example in a chat without code execution), say so, mark every test as not yet seen failing, and give the user the command and the change to the code that should make each one fail.

## 4. When a test fails, find out which side is wrong

A failing test says that the code, the test or the contract is wrong. Decide which from the contract, never from which side is easier to change.

- The test matches the contract: fix the code.
- The expected value is wrong: correct it only when the spec, the documentation or a fact established independently of the code under test proves the old value wrong, and cite that evidence in the report as a test change. What the code under test returns is never that evidence.
- The contract itself changed (in the spec, the plan or the user's request): update the test in the same change as the contract, and name it in the report. Delete the test of a behavior the contract dropped only when the approved spec or plan says that behavior goes; otherwise ask.
- Anything else that makes a failing test pass without fixing the code (deleting it, skipping it, marking it as an expected failure, loosening a tolerance, widening a matcher, catching the exception, asserting less) needs the user's approval: ask with the evidence instead of making the edit.
- A flaky test gets diagnosed (systematic-debugging skill, if available), not retried until it passes.

## 5. Reviewing tests

Attack each new or changed test: name a plausible wrong implementation, or a small change to the code, that would still pass it. If you can name one, the test is a false positive for that behavior; report it with that implementation or change. When you review without permission to edit, name the change and do not apply it. Then check for:

- expected values taken from the code's own output;
- tests with no assertion, assertions that cannot fail (asserting true, comparing a value with itself), and assertions inside a branch or loop that may not run;
- assertions that never execute: an asynchronous test in a runner that does not await it, a promise neither returned nor awaited, a callback never called, an assertion compiled out;
- mocks of the unit under test, assertions on what a mock was told to return, and misspelled mock assertion methods;
- blocks that expect an exception around more than the call that should raise;
- tests that never run: a file or function name the runner does not collect, a filter, a skip, or a missing registration (compare the runner's count or list with the tests in the diff);
- deleted or skipped tests, loosened tolerances or matchers, weakened assertions, regenerated snapshots, and changed expected values without cited evidence;
- behaviors in the contract, boundaries and error paths with no test.

Say which findings you confirmed by running something and which you inferred from reading.

## Red flags

- "The test passes" about a test you never saw fail.
- An expected value obtained by running the code under test.
- Editing the test until the suite goes green.
- A mock configured to return X, then an assertion that the result is X.
- skip, xfail, only, a commented-out test or a deleted test in the diff.
- Snapshots regenerated with an update flag (for example jest -u) and accepted unread.
- The runner reports the same number of tests as before you added some.
- Coverage rises while no assertion checks the new lines.

## Rationalizations

| Excuse | Reality |
|---|---|
| "The code is obviously right, the test just confirms it" | Then seeing the test fail on a broken version costs a minute and proves the test works. |
| "I'll take the expected value from the output" | That tests the code against itself; its bugs become the specification. |
| "The test was wrong, so I relaxed it" | Wrong according to what evidence? Cite it, or ask. |
| "Mocking everything makes it fast and isolated" | It also makes it test the mocks. Mock the boundary, not the logic. |
| "It's flaky, a retry fixes it" | A flaky test is hiding a race, an order dependence or a hidden input. |
| "Coverage is at 100%" | Coverage counts lines executed, not behaviors checked. |
| "The suite is green" | Green means something only if the new tests ran and were seen failing first. |

## Output

For each test written or changed:

- the behavior it pins, in one sentence, with its source in the contract;
- the evidence that it can fail: the command and the failing line, or the change to the code that made it fail;
- the final passing run, with the number of tests the runner reported.

Then list the test changes that alter an expectation (with their evidence), anything that needs the user's approval under section 4, and the behaviors left untested with the reason. A review lists the false positives found, each with the wrong implementation or change that passes it. A caller (implement, a workflow, an orchestrator) copies this evidence into its progress log or report.

## Example

The contract: a username is valid when it has 3 to 16 characters.

Weak: one test asserts that valid_username("alice") is true. It passes, and it would still pass with any limits around 5 characters, or with a function that accepts everything.

Strong: tests at each limit and its neighbors, with expected values read from the contract: 2 characters invalid, 3 valid, 16 valid, 17 invalid, and the empty string invalid. The 16-character test failed when the comparison was changed from less than or equal to less than, and the 17-character name from the bug report failed on the unfixed code.

## Related

For a failing or flaky test whose cause is unclear, use systematic-debugging. Before saying the work is done, apply verifying-before-claiming-done.
