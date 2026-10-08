# Decision log

Owns the decision log: what was decided, why, who proposed it, who accepted it,
and which doc now holds the rule. The rule text itself stays in its owning doc;
this file keeps the context those docs leave out, so nobody reopens a settled
question.

## Authority

- The maintainer decides. An entry becomes Accepted only through the maintainer's
  explicit acceptance, and Decided by then records it.
- Agents add entries as Proposed. An agent writes Accepted only to record a
  decision the maintainer explicitly accepted in the same session.
- A Proposed entry binds nobody and changes no owning doc. Changing a rule in an
  owning doc needs the maintainer's explicit approval of that change.
- An Accepted entry binds later work. A task that conflicts with one stops and
  states the conflict; the maintainer either changes the task or supersedes the
  entry.
- Supersede, do not rewrite: a changed decision gets a new entry, and the old
  entry's status becomes "Superseded by D-NNNN".

## When to record

Record a choice when reversing it later would cost real work, or when someone is
likely to propose the rejected option again: a module boundary, a dependency, an
exception to the error model, a public API shape, a tooling or workflow rule. Do
not record what an owning doc already states and explains.

## Entry format

```text
### D-NNNN: short title

- Status: Proposed | Accepted | Superseded by D-NNNN
- Proposed by: maintainer | contributor | agent
- Decided by: maintainer (only once accepted)
- Date: YYYY-MM-DD
- Rule in: owning doc, or none
- Decision: one or two sentences.
- Why: the constraint or evidence that settled it.
- Rejected: the options considered and why not.
- Revisit if: the condition that would reopen it.
```

Number entries in order and never reuse a number.

## Decisions

None recorded yet.
