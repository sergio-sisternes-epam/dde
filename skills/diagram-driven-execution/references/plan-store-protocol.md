# plan-store-protocol (rule)

Auto-attach: any thread that holds the `diagram-driver` persona AND
whose skill invocation block declares `store="plan"`.

This rule defines the agent contract for the **SQL lite execution
path** — the lightweight counterpart to `transition-protocol` (full
SQL + dependency graph). Both paths use the session `todos` table and
produce the same Copilot visual plan widget; they differ in whether
edges (`todo_deps`) are tracked.

The two protocols are mutually exclusive per run: the `store=`
attribute in the skill invocation block is the selector.

## When SQL lite mode is appropriate

Use `store="plan"` when ALL of the following hold:

- The workflow is **strictly linear** — a single chain of nodes with
  no branches, no fan-out, no parallel execution.
- The node count is **≤ 10**.
- A **single agent** drives the entire run.

Use `store="sql"` (see `transition-protocol`) when ANY of the
following holds: DAG with dependencies, parallel branches, multi-agent
coordination, or a programmatic dependency gate is needed.

If uncertain, default to SQL mode.

## Protocol steps

### Step 1 — Detect linearity (BEFORE inserting any todos)

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

### Step 2 — Initialise todos (SQL lite)

Read the diagram node sequence in diagram order (left-to-right /
top-to-bottom). INSERT one todo row per node — **no `todo_deps`
inserts**:

```sql
INSERT INTO todos (id, title, description) VALUES
  ('<design_id>::<node_id_1>', '<label_1>', '{"design_id":"<design_id>","node":"<node_id_1>"}'),
  ('<design_id>::<node_id_2>', '<label_2>', '{"design_id":"<design_id>","node":"<node_id_2>"}'),
  ...;
```

This single INSERT produces the Copilot visual plan widget showing all
nodes as pending. No `todo_deps` rows are written; linear order is
maintained by the diagram, not by SQL constraints.

The `design_id` is the value passed in the skill invocation block, or
a short slug derived from the first node label if none is given.
Format: `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`.

### Step 3 — Execute nodes (loop)

**Before each node:**
1. Query the next ready node — the first pending todo in this design:
   ```sql
   SELECT id, title FROM todos
   WHERE id LIKE '<design_id>::%' AND status = 'pending'
   ORDER BY rowid LIMIT 1;
   ```
2. Mark it `in_progress`:
   ```sql
   UPDATE todos SET status = 'in_progress' WHERE id = '<todo_id>';
   ```
3. Execute the node body (delegate per `type` annotation if present;
   default `prompt` = this thread).

**After each node:**
4. Mark it `done`:
   ```sql
   UPDATE todos SET status = 'done' WHERE id = '<todo_id>';
   ```

If a node fails and cannot be retried:
4b. Mark it `blocked`:
    ```sql
    UPDATE todos SET status = 'blocked' WHERE id = '<todo_id>';
    ```
5b. Emit B10 HUMAN CHECKPOINT. Do not continue execution.

### Step 4 — Verify completion

After the last node, query for any non-done rows:

```sql
SELECT id, status FROM todos
WHERE id LIKE '<design_id>::%' AND status != 'done';
```

If the query returns zero rows, the run is complete. Report to the
operator.

If any rows remain, emit B10 HUMAN CHECKPOINT with the incomplete
node list.

## Permitted SQL operations

```
INSERT   todos rows at step 2 (once, before execution)
SELECT   next pending todo before each node (B8 anchor)
UPDATE   status to in_progress before node execution
UPDATE   status to done (or blocked) after node execution
SELECT   verify completion at step 4
```

Forbidden: writing `todo_deps` rows; deleting todos mid-run;
reordering by changing rowids; marking a done row back to pending.

## Hard discipline

1. **No narrated state.** Before any node decision, run the
   ready-node query. Never say "we are on step N" without a fresh
   SQL read in the same turn.

2. **One node per turn.** Execute exactly one node per turn. Do not
   batch transitions.

3. **Linear guard is mandatory.** If the operator reveals branches
   mid-run, emit B10 immediately. Do not invent a serialisation order
   for parallel branches.

4. **The node list is frozen.** Adding, removing, or reordering nodes
   after step 2 is a RE-PLAN event; surface B10, start a new design_id.

## Tool call budget (7-node flow)

```
Step 2: 1  INSERT  (all todos in one call)
Step 3: 7× SELECT ready + UPDATE in_progress + UPDATE done = 21 ops
Step 4: 1  SELECT  verify
Total:  ~23 SQL tool calls
```

Compare to `store="sql"` full mode: adds parse-diagram.py (1 bash) +
N `todo_deps` inserts + dep-query loop per node ≈ +8–12 calls.


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
