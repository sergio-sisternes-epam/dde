# diagram-driven-execution (dde)

A runtime skill that turns a mermaid diagram into a tracked execution
plan. Supports two store modes:

- **`store="sql"` (default):** one deterministic parse step extracts
  nodes and edges, the session's native SQL store (`todos` +
  `todo_deps`) tracks progress, and the agent drives execution by
  querying for ready nodes one at a time. Best for DAGs, parallel
  branches, multi-agent coordination, and deterministic completion
  gates.
- **`store="plan"`:** the agent reads the diagram from context, writes
  a plan.md checklist, and updates it per node. No subprocess, no SQL.
  Best for strictly linear workflows of 10 nodes or fewer, single
  agent, where a human-readable checklist is sufficient.

Declare the store mode in your skill's invocation block:

```xml
<skill ref="dde" role="enforcement" store="plan">
```

## Install

```
apm install -g sergio-sisternes-epam/dde --runtime copilot
```

## Use

Provide a mermaid diagram in v1 grammar (`flowchart LR/TD/RL/BT` or
`stateDiagram-v2`, acyclic only). Choose your store mode:

**SQL mode** (default): the skill walks you through:
`parse-diagram.py` (deterministic parse) → SQL load (agent inserts
todos + todo_deps) → loop (query ready nodes → execute → mark done)
→ verify completion (SQL query). The only external dependency is
Python 3 for the initial parse.

**Plan.md mode** (`store="plan"`): the skill creates a plan.md
checklist from the diagram, executes nodes in order updating the
checklist, and verifies completion by reading the file. No Python,
no SQL. Use for linear workflows ≤10 nodes.

See `skills/diagram-driven-execution/SKILL.md` for the full process,
`skills/diagram-driven-execution/references/diagram-grammar.md` for
the bounded grammar,
`skills/diagram-driven-execution/references/transition-protocol.md`
for the SQL mode lifecycle rules, and
`skills/diagram-driven-execution/references/plan-store-protocol.md`
for the plan.md mode lifecycle rules.

## Paired with `sergio-sisternes-epam/genesis`

`genesis` (the agentic-primitives design discipline) mandates dde at
its step 7b. genesis is a developer-time tool; dde is the runtime
contract genesis-designed builds execute against. The two ship as
separate packages so runtime users do not pay the design-discipline
install cost.

## License

Apache-2.0.
