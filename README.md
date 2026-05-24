# diagram-driven-execution (dde)

A runtime skill that turns a mermaid diagram into a tracked execution
plan: one deterministic parse step extracts nodes and edges, the
session's native SQL store (`todos` + `todo_deps`) tracks progress,
and the agent drives execution by querying for ready nodes one at a
time. The diagram is the frozen contract; instruction discipline
enforces the transition protocol.

## Install

```
apm install -g sergio-sisternes-epam/dde --runtime copilot
```

## Use

Provide a mermaid diagram in v1 grammar (`flowchart LR/TD/RL/BT` or
`stateDiagram-v2`, acyclic only). The skill walks you through:
`parse-diagram.py` (deterministic parse) → SQL load (agent inserts
todos + todo_deps) → loop (query ready nodes → execute → mark done)
→ verify completion (SQL query). The only external dependency is
Python 3 for the initial parse; all state tracking uses the session's
native SQL store.

See `skills/diagram-driven-execution/SKILL.md` for the full process,
`skills/diagram-driven-execution/references/diagram-grammar.md` for the
bounded grammar, and
`skills/diagram-driven-execution/references/transition-protocol.md` for
the lifecycle rules.

## Paired with `sergio-sisternes-epam/genesis`

`genesis` (the agentic-primitives design discipline) mandates dde at
its step 7b. genesis is a developer-time tool; dde is the runtime
contract genesis-designed builds execute against. The two ship as
separate packages so runtime users do not pay the design-discipline
install cost.

## License

Apache-2.0.
