# transition-protocol (rule)

Auto-attach: any thread that holds the `diagram-driver` persona.

This rule defines the agent contract for interacting with the
session SQL store when driving a diagram-driven plan. The store
uses the session's native `todos` and `todo_deps` tables.

## Permitted SQL operations

### Read operations (any time)

Query ready nodes:
```sql
SELECT t.id, t.title FROM todos t
WHERE t.id LIKE '<design_id>::%'
  AND t.status = 'pending'
  AND NOT EXISTS (
    SELECT 1 FROM todo_deps td
    JOIN todos dep ON td.depends_on = dep.id
    WHERE td.todo_id = t.id AND dep.status != 'done'
  );
```

Query completion status:
```sql
SELECT status, COUNT(*) as cnt FROM todos
WHERE id LIKE '<design_id>::%' GROUP BY status;
```

Detect stuck state:
```sql
-- If this returns 0 and non-done nodes exist, the design is stuck
SELECT COUNT(*) FROM todos t
WHERE t.id LIKE '<design_id>::%'
  AND t.status = 'pending'
  AND NOT EXISTS (
    SELECT 1 FROM todo_deps td
    JOIN todos dep ON td.depends_on = dep.id
    WHERE td.todo_id = t.id AND dep.status != 'done'
  );
```

Read node metadata (from todos.description JSON):
```sql
SELECT id, title, description FROM todos
WHERE id = '<design_id>::<node_id>';
```

### Write operations (status transitions only)

Mark a node in progress:
```sql
UPDATE todos SET status = 'in_progress', updated_at = datetime('now')
WHERE id = '<design_id>::<node_id>';
```

Mark a node done:
```sql
UPDATE todos SET status = 'done', updated_at = datetime('now')
WHERE id = '<design_id>::<node_id>';
```

Mark a node blocked (failed):
```sql
UPDATE todos SET status = 'blocked', updated_at = datetime('now')
WHERE id = '<design_id>::<node_id>';
```

## Forbidden operations

- Direct `INSERT` or `DELETE` against `todos` rows with
  `<design_id>::` prefix after the initial load.
- Any `INSERT`, `UPDATE`, or `DELETE` against `todo_deps` rows
  with `<design_id>::` prefix. The dependency graph is frozen.
- Updating `status` to any value other than `in_progress`,
  `done`, or `blocked`.
- Marking a node `in_progress` without first confirming it
  appears in the ready-nodes query result.

## Per-node lifecycle

```
     pending
        |
        v
   in_progress ---------> blocked
        |
        v
       done
```

- `pending`: initial state for all nodes. A node is "ready"
  (eligible for pickup) when it is `pending` AND every node it
  depends on is `done`. This is computed by the ready-nodes
  query, not stored as a separate status.
- `in_progress`: the agent is executing this node's work. The
  next legal status is `done` (success) or `blocked` (failure).
- `done`: terminal success. After marking a node done, re-query
  to discover newly-ready children.
- `blocked`: terminal failure. Requires operator intervention
  (B10 HUMAN CHECKPOINT). The agent must not mark blocked nodes
  as done or retry them without operator direction.

Any other transition (e.g. `pending` → `done`, `done` → `pending`,
`blocked` → `in_progress`) is an illegal transition. The agent
must not issue it. There is no script-level gate — the discipline
is the contract.

## Design ID convention

Todo IDs use the composite pattern `<design_id>::<node_id>`.
Design IDs must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` to be
SQL-literal-safe and prefix-safe for LIKE queries.
