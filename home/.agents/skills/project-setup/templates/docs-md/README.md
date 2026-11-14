# <FILL: project name> docs map

Start here to find the right file for the work in front of you, then load only
what the role and the touched area require. Every doc has one job and one
owner. If a concept lives in two places, one of them is stale: keep the floor in
the hub and the full reference in the owning doc.

## Role to doc matrix

An `x` means "load this when working in that role". Load top to bottom, then pull
deeper docs only when the task touches them.

| Doc | scout | planner | impl | review | onboard |
|---|---|---|---|---|---|
| AGENTS.md | x | x | x | x | x |
| README.md (this) | x | x | x | x | x |
| <FILL: the root README, or delete this row> | | | | | x |
| VISION.md | x | x | | | x |
| DESIGN.md | | x | x | x | x |
| STYLE_GUIDE.md | | x | x | x | x |
| CONTRIBUTING.md | | x | x | x | x |
| writing.md | | x | x | x | x |
| decisions.md | | x | x | x | |
| agent-workflows.md | x | x | x | x | |
| <FILL: other docs> | | | | | |

Role names:

- *scout* maps the area of a task and finds the owners.
- *planner* decides scope, sequencing, commands and risk.
- *impl* changes code, tests and docs.
- *review* checks behavior, maintainability and missing coverage.
- *onboard* learns how to build, use and navigate the project.

<FILL: a role this project adds, with its column, or delete this marker.>

## Registry

Every doc, its purpose and the roles that load it.

| Doc | Purpose | Roles |
|---|---|---|
| <FILL: the root README, or delete this row> | Project overview, quick start, build and use | onboard |
| AGENTS.md | Agent guide and working floor | all |
| CLAUDE.md, GEMINI.md | Bridges that import AGENTS.md | tool entrypoints |
| .github/copilot-instructions.md | Copilot bridge to AGENTS.md | tool entrypoint |
| VISION.md | Direction, mission, principles, non-goals | scout, planner, onboard |
| DESIGN.md | Design principles of the public surface | planner, impl, review, onboard |
| STYLE_GUIDE.md | Code style, naming, comments, tooling | planner, impl, review, onboard |
| CONTRIBUTING.md | Workflow, gates, CI, commit messages, docs format | planner, impl, review, onboard |
| README.md (this) | Docs map: role matrix and registry | all |
| writing.md | Prose style and punctuation | planner, impl, review, onboard |
| decisions.md | Decision log | planner, impl, review |
| agent-workflows.md | Multi-step workflows and handoffs | scout, planner, impl, review |
| <FILL: one row per other doc> | | |

## Guidelines for additions

- *Single source per concept.* One doc owns a fact; everywhere else links to
  that doc.
- *Register new docs.* A new doc gets a row in the registry and, when a role
  loads it, a row in the matrix.
- *Header pointer.* Open each doc with a short statement of what it owns and
  links to the related docs.
- *Inline is floor, extract is reference.* A hub (AGENTS.md, this map) keeps
  only the rule an agent must hold; examples and edge cases go to the owning
  doc.
- *Split threshold.* Split a doc only when it is longer than one screen and has
  at least three subtopics that can be loaded independently.

## Known docs gaps

<FILL: docs that are missing or stale, each with what is missing, or "None
currently.">
