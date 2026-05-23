---
name: diagram-driven-execution
description: >-
  Use this skill when the user supplies a mermaid diagram (flowchart
  LR/TD/RL/BT, or stateDiagram-v2) that represents a process the
  agent must follow step-by-step, and the user wants deterministic
  execution tracking rather than free-form interpretation. Parses
  the diagram into nodes and edges via a deterministic script,
  writes them to the session SQL store as todos with dependencies,
  exposes a "what is ready next" query, and validates every status
  transition against the diagram so illegal moves are refused.
  Activate on phrases like "follow this diagram", "execute this
  workflow", "enforce these steps", "track against this state
  machine", "drive this process", "run this mermaid as a plan",
  "step me through this flowchart", or any moment a diagram is
  being treated as the source of truth for a procedure. Does NOT
  execute node bodies; node work is delegated to subagents, tools,
  or the calling thread.
---

# diagram-driven-execution

[Driver persona](agents/diagram-driver.agent.md)
[Grammar rule](references/diagram-grammar.md)
[Transition protocol](references/transition-protocol.md)

This skill turns a mermaid diagram into a **deterministic,
SQL-tracked execution plan**. The diagram is the process contract;
the session's SQL store is the cursor. Each node becomes a row,
each edge becomes a dependency, each status update is a validated
transition. Illegal transitions are refused at the SQL boundary,
not "asked nicely against" in prose.

## When to activate

- The operator hands you a flowchart or state diagram and expects
  the steps to be executed in order.
- The operator says any of: "follow this diagram", "drive this
  workflow", "enforce these steps", "step me through", "track
  this state machine".
- You are about to execute a multi-step process and want
  edge-validated transition tracking instead of free-form
  narration.

Do NOT activate for: drawing diagrams, explaining diagrams,
rendering or pretty-printing mermaid, checking diagram syntax in
isolation. Those are not execution tasks.

## What this skill does NOT do

- It does not implement node bodies. Each node's work is delegated
  to a subagent, a tool, or this thread's own prompt -- chosen via
  the node's `type=` annotation (see grammar rule).
- It does not invent diagrams. If you have a process described in
  prose, ask the operator for the diagram first.
- It does not interpret intent. If a node label is ambiguous, the
  driver persona halts to a human checkpoint.

## Applicability (when dde is worth its overhead)

dde adds value by replacing free-form todo mutation with a
diagram-grounded, lifecycle-validated, queryable execution
record. That ceremony is load-bearing for some workloads and
pure overhead for others. Reach for dde when AT LEAST ONE holds:

- The plan has more than ~3 nodes.
- Any fan-out, parallelism, or multiple writers touch the same
  plan.
- Topological ordering matters (drafting in the wrong order
  costs rework).
- The work spans sessions or threads and must re-ground itself
  on resume (B4 PLAN MEMENTO / B8 ATTENTION ANCHOR).
- "Done" must be a deterministic gate (`verify-completion`
  exit 0), not an LLM assertion.

Do NOT reach for dde when ANY of the following describes the
work:

- Single-node task ("fix this typo", "bump this version"). No
  DAG; authoring a diagram is pure ceremony.
- Strictly linear, short (<=3 steps), throwaway work. A plain
  todo list does the same job with less ceremony.
- Exploratory or discovery work where the steps are not known
  in advance. dde requires the diagram up front; authoring it
  during exploration creates a chicken-and-egg.
- Advisory or conversational turns with no execution to gate
  (Q&A, critique, code review).
- REPL-style iteration where the plan churns every turn.

Rule of thumb: if you would reach for the harness's plain
`todos` affordance, you do not need dde. If you would reach
for a sequence diagram or a dependency checklist, you do.

The mandate genesis applies to its step 7b is correctly scoped
because genesis output is always a multi-module DAG with
ordering constraints, ~5-20 nodes, and a "every module drafted
and validated" completion gate -- it meets every "reach for"
criterion. Other skills considering dde should make the call
case by case against this section, not by analogy to genesis.

## Process

```
   1 parse-diagram.py      -- JSON, S7-bridged
        v
   2 load-plan.py          -- apply schema, insert design rows,
        v                     promote entry nodes to 'ready'
   3 next-ready.py ----+
        v              |
   4 PICK ONE ready    |   per-turn loop
        v              |
   5 EXECUTE NODE      |   (delegate by node.type)
        v              |
   6 record-transition.py  -- validated; rejection halts
        v              |
        +--------------+   re-query; back to step 3
        v
   7 verify-completion.py  -- when next-ready reports 'done'
```

### Step 1 -- parse the diagram

Save the operator's mermaid to a file (if inline, write to a
temp). Invoke:

```
python3 scripts/parse-diagram.py --input <file> [--design-id <id>]
```

Captures the parsed JSON. Exit code 2 means the diagram falls
outside the v1 grammar (see `references/diagram-grammar.md`);
return the diagnostic to the operator and stop -- do not patch.

### Step 2 -- load the plan

```
python3 scripts/load-plan.py --json <parsed.json>
```

Idempotent: refuses (exit 3) if the same `design_id` already
exists in `dde_designs`. The script applies `assets/schema-init.sql`
defensively before inserting, so first run on a fresh harness
works without setup.

Sets entry-node todos to status `ready` automatically.

### Step 3 -- query next-ready

EVERY TURN, before deciding anything:

```
python3 scripts/next-ready.py --design-id <id>
```

Returns one of three states:

- `ready`: at least one node has no pending dependencies. Pick
  one (do NOT batch).
- `done`: all terminals reached. Go to step 7.
- `stuck`: no ready nodes and not done. Emit B10.

### Step 4-6 -- pick, execute, record

1. PICK one node from `ready_nodes`. Re-anchor on its label and
   any `type=` / `model=` annotations.
2. Transition to `in_progress`:
   ```
   python3 scripts/record-transition.py --design-id <id> --node <node_id> --to in_progress
   ```
3. EXECUTE the node body. Dispatch by `type`:
   - `manual`: the operator does this step out-of-band; wait.
   - `subagent`: spawn a child thread with the node's brief and
     model weight. Compose with example 06 (TIERED SUPERVISED
     EXECUTION) for cost-aware spawning.
   - `tool`: invoke a deterministic tool.
   - `prompt` (default): you do it in this thread.
4. Transition to terminal lifecycle:
   ```
   python3 scripts/record-transition.py --design-id <id> --node <node_id> --to done --output <ref>
   ```
   Or `--to failed` if the node could not be completed.

Exit code 4 from `record-transition.py` = ILLEGAL TRANSITION.
Halt and emit B10. Do not retry with a different `--to`.

### Step 7 -- verify completion

```
python3 scripts/verify-completion.py --design-id <id>
```

Exits 0 on complete, 6 on incomplete. The structured output names
any failed nodes and counts the illegal-transition attempts that
appeared during the run -- that count is the operator's
process-quality signal.

## Platform and runtime

This skill targets `common-only` and runs on any OS with Python 3
on PATH (macOS, Linux, Windows). It uses ONLY the Python standard
library; no `pip install`, no external `sqlite3` binary, no shell
features. Invoke scripts with `python3 scripts/<name>.py ...` on
Unix-likes, `python scripts\<name>.py ...` on Windows -- the
script bodies are identical.

The single environment hook is `DDE_DB_PATH`, the filesystem path
to the SQLite database file:

| Harness        | Suggested `DDE_DB_PATH`             |
|----------------|-------------------------------------|
| Copilot CLI    | `.copilot-dde.sqlite`               |
| Claude Code    | `.claude/dde.sqlite`                |
| Codex / Cursor | `.dde.sqlite`                       |
| Default        | `.copilot-dde.sqlite` (in cwd)      |

The substrate guarantee (concept 6 TODO/STATUS) is that SOME
queryable store exists per session. SQLite via Python stdlib is
the portable default; the database file is created on first
`load-plan.py` run. If a future harness exposes a native SQL
tool, an alternative `_dde.py` connector could be supplied.

## Bundled assets

- `scripts/parse-diagram.py` -- deterministic mermaid parser
  (bounded grammar; rejects unsupported syntax loudly).
- `scripts/load-plan.py` -- applies schema, inserts rows,
  promotes entries to `ready`.
- `scripts/next-ready.py` -- cursor query.
- `scripts/record-transition.py` -- validated transition writer,
  with auto-promotion of newly-ready children.
- `scripts/verify-completion.py` -- terminal check.
- `scripts/_dde.py` -- shared stdlib-only helpers (db connect,
  JSON emit, argv parsing).
- `assets/schema-init.sql` -- the four design-scoped tables
  (`dde_designs`, `dde_nodes`, `dde_edges`, `dde_history`).
- `agents/diagram-driver.agent.md` -- the process-execution lens.
- `references/diagram-grammar.md` -- the supported subset.
- `references/transition-protocol.md` -- the agent contract.

Every script supports `--help`.

## Composition

This skill composes with **example 06** (TIERED SUPERVISED
EXECUTION). Node `model=` annotations cross-reference into the
per-spawn model-tier discipline: a "diagram with model weights" is
both process-deterministic AND cost-aware.

See `skills/genesis/examples/06-tiered-supervised-execution.md`
for the peer recipe.

## Limitations (declared)

- WEAK FORM A9. The agent retains the capability to write directly
  to the session SQL store and bypass the scripts. The persona +
  this skill's discipline are the only enforcement. A future
  harness with a "scripts-only SQL surface" capability would
  graduate this to strong-form A9.
- v1 grammar excludes subgraphs, composite states, classDefs,
  styling, click handlers (see `references/diagram-grammar.md`).
- Re-planning is a B10 event by design. Mid-run diagram edits are
  refused; the operator must explicitly start a new design.
