# <FILL: project name> style guide

This file owns code mechanics: the language level, naming, layout, error
handling, comments and the tools that enforce them. DESIGN.md owns how the
design feels; writing.md in the docs folder owns prose style.

<FILL: the formatter and the linter, with their configuration files, then: When
this guide and the tooling disagree, the tooling wins; fix both together. Delete
this marker when the project has neither.>

## Language

<FILL: the language standard and the compilers or runtimes the code must build
with, as the build files set them.>

## Naming

<FILL: one line per naming rule the code follows, each with an example: types,
functions, variables, constants, files.>

## Error handling

<FILL: how errors are reported and propagated (exceptions, error codes, result
types), as the code does it.>

## Comments

Comments explain intent, invariants, derivations and references; they do not
narrate syntax. <FILL: the documentation comment format the project uses, or
delete this sentence.>

## Tooling

<FILL: the format and lint commands, exactly as CI runs them.>

```sh
<FILL: format and lint commands>
```
