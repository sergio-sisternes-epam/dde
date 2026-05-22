# diagram-driven-execution (dde)

A runtime skill that turns a mermaid diagram into a deterministic process
contract: the diagram is the frozen state machine, session SQL is the
cursor, and six Python (stdlib-only) scripts are the sole write surface.
Illegal lifecycle transitions are refused at the SQL boundary with audit
rows.

## Install

```
apm install -g sergio-sisternes-epam/dde --runtime copilot
```

## Use

Provide a mermaid diagram in v1 grammar (`flowchart LR/TD/RL/BT` or
`stateDiagram-v2`). The skill walks you through `parse-diagram` ->
`load-plan` -> loop (`next-ready` -> work -> `record-transition`) ->
`verify-completion`. Free-form `todos` mutation is refused; the
scripts are the only state-mutation path.

See `skills/diagram-driven-execution/SKILL.md` for the full process,
`skills/diagram-driven-execution/references/diagram-grammar.md` for the
bounded grammar, and
`skills/diagram-driven-execution/references/transition-protocol.md` for
the lifecycle table.

## Paired with `sergio-sisternes-epam/genesis`

`genesis` (the agentic-primitives design discipline) mandates dde at
its step 7b. genesis is a developer-time tool; dde is the runtime
contract genesis-designed builds execute against. The two ship as
separate packages so runtime users do not pay the design-discipline
install cost.

## License

Apache-2.0.
