# simple-protocol (rule)

Auto-attach: any thread that holds the `diagram-driver` persona AND
whose skill invocation block declares `mode="simple"`.

This rule defines the agent contract for the **simple execution path** —
the lightweight counterpart to `advanced-protocol` (advanced path). Both
paths use the session `todos` and `todo_deps` tables and produce the
Copilot visual plan widget. They differ in whether a parse script is used
and whether gate/loop execution is supported.

The two protocols are mutually exclusive per run: the `mode=` attribute
in the skill invocation block is the selector.

## When simple mode is appropriate

Use `mode="simple"` when ALL of the following hold:

- The workflow is a **linear chain or small DAG** — no loops, no
  conditional gates.
- The node count is **≤ 15**.
- A **single agent** drives the entire run.
- The mermaid syntax is standard — no aliased node chains, no complex
  multi-type edge mixes. (If parsing the diagram by eye feels risky,
  use advanced mode with `parse-diagram.py`.)

Use `mode="advanced"` (see `advanced-protocol`) when ANY of the
following holds: bounded loops (`type=loop`), conditional gates
(`type=gate`), programmatic dependency enforcement via parse script,
multi-agent coordination, or node count > 15.

If uncertain, default to advanced mode.

## Protocol steps

### Step 1 — Read and extract diagram

Read the diagram from context. Extract:
1. **Nodes**: every distinct node ID and its label.
2. **Edges**: every `A --> B` (or labelled) edge as a directed pair.

Verify the diagram has no loops or gate nodes (i.e., no `type=loop`
or `type=gate` annotations). If found, emit **B10 HUMAN CHECKPOINT**:

```
B10 HUMAN CHECKPOINT — unsupported node type in simple mode
The diagram contains loop or gate nodes, which require mode="advanced".
Switch to mode="advanced" and re-invoke.
```

Do NOT proceed to step 2 until the operator responds.

### Step 2 — Initialise todos and deps

INSERT one todo row per node:

```sql
INSERT INTO todos (id, title, description) VALUES
  ('<design_id>::<node_id_1>', '<label_1>', '{"design_id":"<design_id>","node":"<node_id_1>"}'),
  ('<design_id>::<node_id_2>', '<label_2>', '{"design_id":"<design_id>","node":"<node_id_2>"}'),
  ...;
```

For every edge `A --> B` in the diagram, INSERT a dep row:

```sql
INSERT INTO todo_deps (todo_id, depends_on) VALUES
  ('<design_id>::<node_B>', '<design_id>::<node_A>'),
  ...;
```

These two INSERTs produce the Copilot visual plan widget showing the
dependency tree. For a linear chain A→B→C, the tree renders as a
straight stack. For a small DAG, it renders the branching structure.

The `design_id` is the value passed in the skill invocation block, or
a short slug derived from the first node label if none is given.
Format: `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`.

### Step 3 — Execute nodes (loop)

**Before each node:**
1. Query the next ready node — pending with all deps resolved:
   ```sql
   SELECT t.id, t.title FROM todos t
   WHERE t.id LIKE '<design_id>::%'
     AND t.status = 'pending'
     AND NOT EXISTS (
       SELECT 1 FROM todo_deps td
       JOIN todos dep ON td.depends_on = dep.id
       WHERE td.todo_id = t.id
         AND dep.status NOT IN ('done', 'skipped')
     )
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

Repeat until no ready nodes remain.

### Step 4 — Verify completion

```sql
SELECT id, status FROM todos
WHERE id LIKE '<design_id>::%' AND status NOT IN ('done', 'skipped');
```

Zero rows → run complete. Report to the operator.

Non-zero rows → emit B10 HUMAN CHECKPOINT with the incomplete node list.
Check for stuck state: if all remaining nodes are `pending` but none
pass the ready-node query, all deps are unresolved (a blocked ancestor).

## Permitted SQL operations

```
INSERT   todos rows at step 2 (once, before execution)
INSERT   todo_deps rows at step 2 (once, before execution)
SELECT   ready-node query before each node (B8 anchor)
UPDATE   status to in_progress before node execution
UPDATE   status to done (or blocked) after node execution
SELECT   verify completion at step 4
```

Forbidden: writing todo_deps rows after step 2; deleting todos mid-run;
marking a done row back to pending; inserting new todo rows after step 2.

## Hard discipline

1. **No narrated state.** Before any node decision, run the
   ready-node query. Never say "we are on step N" without a fresh
   SQL read in the same turn.

2. **One node per turn.** Execute exactly one node per turn. Do not
   batch transitions.

3. **No loops or gates.** If the operator reveals the diagram has
   loop or gate nodes mid-run, emit B10 immediately. Do not attempt
   to simulate gate routing or loop repetition in simple mode.

4. **The node list is frozen.** Adding, removing, or reordering nodes
   after step 2 is a RE-PLAN event; surface B10, start a new design_id.

## Tool call budget (7-node linear flow)

```
Step 2: 1 INSERT todos + 1 INSERT todo_deps (6 dep rows = 1 call)
Step 3: 7× (SELECT ready + UPDATE in_progress + UPDATE done) = 21 calls
Step 4: 1 SELECT verify
Total:  ~24 SQL tool calls
```

Compare to `mode="advanced"`: adds parse-diagram.py (1 bash call) and
gate/loop overhead. Simple mode is lighter for flows without those needs.
