# transition-protocol (rule)

Auto-attach: any thread that holds the `diagram-driver` persona.

This rule defines the agent contract for interacting with the
session SQL store. The store is shared substrate (concept 6
TODO/STATUS). This skill imposes a discipline on top of it.

## Permitted operations

You may invoke ONLY these scripts (relative to the skill root):

| Script                          | Purpose                                                 |
|---------------------------------|---------------------------------------------------------|
| `scripts/parse-diagram.py`      | parse mermaid into structured JSON                      |
| `scripts/load-plan.py`          | apply schema + insert design rows (idempotent)          |
| `scripts/next-ready.py`         | query current ready / done / stuck state                |
| `scripts/record-transition.py`  | apply a status transition (validated, audited)          |
| `scripts/verify-completion.py`  | check whether all terminals are reached                 |

Every script reads `DDE_DB_PATH` from the environment (SQLite
file path; defaults to `.copilot-dde.sqlite` in cwd). The scripts
use only the Python standard library and run identically on
macOS, Linux, and Windows. See the SKILL.md "Platform and
runtime" section.

## Forbidden operations

- Direct `UPDATE todos SET status = ...` queries against design
  rows (composite ids of shape `<design_id>::<node_id>`).
- Direct `INSERT` or `DELETE` against `dde_designs`, `dde_nodes`,
  `dde_edges`, `dde_history`.
- Pruning `dde_history` rows. The audit trail is append-only.
- Loading a second diagram with the same `design_id` -- the load
  script refuses, and you must not try to "force" it by mutating
  rows directly.

A future harness may enforce these forbids at the capability
level. Until then, the persona enforces them.

## Per-node lifecycle

This is the per-node STATE MACHINE, distinct from the diagram's
edges. Diagram edges define which OTHER nodes can be `ready`;
the lifecycle below defines what each node's status may become.

```
       pending
          |
          v
        ready  -----------------+
          |                     |
          v                     |
     in_progress  -------> failed
          |
          v
         done
```

- `pending`: created by `load-plan.py`; predecessors not yet
  `done`. Cannot transition directly to `in_progress` or `done`.
- `ready`: promoted automatically by `record-transition.py` when
  every predecessor reaches `done`. The agent picks from this
  set and only this set.
- `in_progress`: the agent is executing this node's work. The
  next legal transition is `done` (success) or `failed`.
- `done`: terminal success. Triggers re-evaluation of children's
  `ready` status atomically inside `record-transition.py`.
- `failed`: terminal failure. Triggers `verify-completion.py`
  to flag the design as incomplete; an operator decision is
  required (B10 HUMAN CHECKPOINT).

Any other transition (e.g. `pending -> done`, `done -> ready`,
`failed -> in_progress`) exits 4 and writes a rejection row to
`dde_history`. Rejection is structural; do not interpret it as
"can be worked around".

## Exit-code dictionary

| Exit | Meaning                                            | Agent response                        |
|------|----------------------------------------------------|---------------------------------------|
| 0    | accepted                                           | continue loop                         |
| 2    | grammar reject (parse-diagram only)                | return diagram to operator with diag  |
| 3    | design_id already exists (load-plan only)          | B10 RE-PLAN checkpoint                |
| 4    | illegal lifecycle (record-transition only)         | B10 ILLEGAL-TRANSITION checkpoint     |
| 5    | node / design_id not found                         | B10 STRUCTURAL checkpoint             |
| 6    | incomplete (verify-completion only)                | emit stuck/incomplete signal          |
| 1    | other                                              | B10 INFRASTRUCTURE checkpoint         |
