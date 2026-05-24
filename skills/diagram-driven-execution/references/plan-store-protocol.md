# plan-store-protocol (rule)

Auto-attach: any thread that holds the `diagram-driver` persona AND
whose skill invocation block declares `store="plan"`.

This rule defines the agent contract for the **plan.md execution path**.
It is the lightweight counterpart to `transition-protocol`, which owns
the SQL execution path. The two protocols are mutually exclusive per
run: the `store=` attribute in the skill invocation block is the
selector.

## When plan.md mode is appropriate

Use `store="plan"` when ALL of the following hold:

- The workflow is **strictly linear** — a single chain of nodes with
  no branches, no fan-out, no parallel execution.
- The node count is **≤ 10**.
- A **single agent** drives the entire run.
- Deterministic completion gating (SQL query) is **not required**; a
  human-readable checklist is sufficient evidence of completion.

Use `store="sql"` (see `transition-protocol`) when ANY of the following
holds: DAG with dependencies, parallel branches, multi-agent
coordination, or a programmatic "all-done" gate is needed.

If uncertain, default to SQL mode.

## Plan.md format

The driver creates one plan.md file per design run at the start of
execution. The file lives in the session's plan persistence slot.

```markdown
# DDE: {design_id}

store: plan

## Workflow
- [ ] {node_id_1} · {label_1}
- [ ] {node_id_2} · {label_2}
- [ ] {node_id_3} · {label_3}

## Log
- [{timestamp}] {node_id} → in_progress
- [{timestamp}] {node_id} → done
```

Rules:
- Each `- [ ]` item is a pending node. `- [x]` is a completed node.
- Node ID and label come directly from the diagram; do not invent or
  reorder them.
- The `## Log` section is append-only. Add one entry when a node
  moves to `in_progress` and one when it moves to `done`.
- Timestamps use ISO-8601 local time (YYYY-MM-DD HH:MM:SS).

## Protocol steps

### Step 1 — Detect linearity (BEFORE creating plan.md)

Read the diagram from context. Verify the graph is a single chain:
every node has at most one predecessor and at most one successor. If
any node has more than one incoming or outgoing edge, the diagram is
NOT linear. Emit a **B10 HUMAN CHECKPOINT**:

```
B10 HUMAN CHECKPOINT — non-linear diagram in plan.md mode
The diagram contains branches or parallel paths, which require SQL
mode for correct dependency tracking.
Options:
  A. Switch to store="sql" and re-invoke with SQL tracking.
  B. Confirm you want plan.md mode anyway (execution order will be
     left-to-right / top-to-bottom, branches are NOT tracked).
```

Do NOT proceed to step 2 until the operator responds.

### Step 2 — Initialise plan.md

Read the diagram's node sequence (in diagram order, left-to-right /
top-to-bottom). Create the plan.md file using the format above, with
all nodes as `- [ ]`. This is the B4 PLAN MEMENTO for this run.

The `design_id` is the value passed in the skill invocation block, or
a short slug derived from the diagram's first node label if none is
given.

### Step 3 — Execute nodes (loop)

**Before each node:**
1. Re-read plan.md (B8 ATTENTION ANCHOR — do not rely on recall).
2. Identify the **first** `- [ ]` item; that is the ready node.
3. Append to the `## Log`: `- [{now}] {node_id} → in_progress`.
4. Execute the node body (delegate per `type` annotation if present;
   default `prompt` = this thread).

**After each node:**
5. Change `- [ ] {node_id}` to `- [x] {node_id}` in plan.md.
6. Append to `## Log`: `- [{now}] {node_id} → done`.

If a node fails and cannot be retried:
5b. Append to `## Log`: `- [{now}] {node_id} → blocked: {reason}`.
6b. Emit B10 HUMAN CHECKPOINT. Do not continue execution.

### Step 4 — Verify completion

After the last node: re-read plan.md (B8). Confirm all items are
`- [x]`. If any item is still `- [ ]`, the run is incomplete — emit
B10 HUMAN CHECKPOINT with the incomplete node list.

If all items are `- [x]`, the run is complete. Report to the operator.

## Permitted plan.md operations

```
CREATE   plan.md at step 2 (once, before execution)
READ     plan.md at step 3 before each node (B8 anchor)
EDIT     plan.md after each node ([ ] → [x], log append)
READ     plan.md at step 4 (completion verify)
```

Forbidden: deleting or recreating plan.md mid-run; reordering the
checklist items; editing `- [x]` items back to `- [ ]`.

## Hard discipline

1. **No narrated state.** Before any node decision, re-read plan.md.
   Never say "we are on step N" without a fresh read in the same turn.

2. **One node per turn.** Execute exactly one node per turn. Do not
   batch transitions.

3. **Linear guard is mandatory.** If the operator later reveals the
   diagram has branches mid-run, emit B10 immediately. Do not invent
   a serialisation order for parallel branches.

4. **The checklist is frozen.** Adding, removing, or reordering nodes
   after step 2 is a RE-PLAN event; surface B10, start a new design_id.

## Design ID convention

Same as SQL mode: `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. If no `design_id`
is supplied, derive one from the first node's label (lowercase,
hyphens for spaces, truncated to 32 chars).
