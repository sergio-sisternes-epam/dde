---
name: diagram-driven-execution
description: >-
  Use this skill when the user supplies a mermaid diagram that represents
  a process the agent must follow step-by-step with deterministic tracking.
  Two modes via session SQL todos table (both produce the Copilot visual
  plan widget): simple (mode="simple"; up to 15 nodes, agent reads diagram
  from context, inserts todos+todo_deps, no parse script, no gates/loops)
  and advanced (default mode="advanced"; gates with multi-way routing and
  escalation, bounded loops via pre-expansion, deterministic parse via
  parse-diagram.py). Activate on: "follow this diagram",
  "execute this workflow", "enforce these steps", "track against this state
  machine", "drive this process", "run this mermaid as a plan", "step me
  through this flowchart", or any moment a diagram is the source of truth
  for a procedure. Does NOT execute node bodies; node work is delegated to
  subagents, tools, or the calling thread.
---

<!-- ═══════════════════════════════════════════════════════
     AML INTERFACE DEFINITIONS
     Top-level capability contract and sub-capability nodes.
     ═══════════════════════════════════════════════════════ -->

<skill define="interface" name="diagram-driven-execution">
  Execute a mermaid diagram step-by-step with deterministic SQL-backed
  tracking. The diagram is the process contract. The driver enforces
  transition order and halts on stuck states. Node bodies are delegated;
  this interface owns cursor management only.
</skill>

<skill define="interface" name="dde.grammar-check">
  Validate the operator's mermaid diagram against the supported v1 grammar
  (references/diagram-grammar.md). Reject loudly with line/column
  diagnostics on any unsupported syntax. In simple mode: also assert
  absence of type=gate and type=loop nodes, and node count <= 15.
</skill>

<skill define="interface" name="dde.plan-init">
  Initialise the execution plan in the session SQL store. INSERT one todos
  row per diagram node and one todo_deps row per edge. Check for design_id
  collisions before inserting. The node list is frozen after this step.
</skill>

<skill define="interface" name="dde.execution-loop">
  Drive diagram nodes to completion. Each turn: query ready nodes (pending
  with all deps done or skipped), pick one, mark in_progress, execute body,
  mark done or blocked. Repeat until no ready nodes remain or stuck state.
</skill>

<skill define="interface" name="dde.gate-router">
  Evaluate a gate node's condition and route execution. Mark false-branch
  root nodes as skipped (resolving their deps for downstream nodes). On no
  matching branch: escalate to parent session if available, else emit B10.
</skill>

<skill define="interface" name="dde.loop-expander">
  Pre-expand a type=loop|max_iter=N node into N sequential iteration todos
  at plan-init time. Wire predecessor → iter_1 → ... → iter_N → successor
  via todo_deps. No runtime plan mutation after expansion.
</skill>

<skill define="interface" name="dde.verify">
  Confirm all plan nodes have reached a terminal status. Query for any rows
  not in (done, skipped); zero rows = complete. Non-zero rows emit B10
  with the incomplete node list.
</skill>

<!-- ═══════════════════════════════════════════════════════
     AML INTERFACE DEFINITIONS — MODE CONTRACTS
     ═══════════════════════════════════════════════════════ -->

<skill define="interface" name="dde-simple" implements="diagram-driven-execution">
  Lightweight path. Agent reads diagram from context; no subprocess.
  Nodes: dde.grammar-check (assert no gate/loop, count<=15),
  dde.plan-init (context extraction), dde.execution-loop (rowid order
  as tiebreak), dde.verify. Does not instantiate dde.gate-router or
  dde.loop-expander. Protocol: references/simple-protocol.md
</skill>

<skill define="interface" name="dde-advanced" implements="diagram-driven-execution">
  Full path. Deterministic parse via parse-diagram.py.
  Nodes: dde.grammar-check (parse-diagram.py), dde.loop-expander
  (pre-expand at init), dde.plan-init (todos + todo_deps + dde_gates),
  dde.execution-loop (skipped counts as resolved; delegates to
  dde.gate-router on gate nodes), dde.verify. Protocol:
  references/advanced-protocol.md
</skill>

---

# diagram-driven-execution

- [Driver persona](agents/diagram-driver.agent.md)
- [Grammar rule](references/diagram-grammar.md)
- [Advanced mode protocol](references/advanced-protocol.md)
- [Simple mode protocol](references/simple-protocol.md)

This skill turns a mermaid diagram into a **tracked execution plan**.
Two AML implementations share the same `todos` + `todo_deps` SQL store
and both produce the Copilot visual plan widget.

## Embedding DDE in a skill (AML invocation)

```xml
<!-- Lightweight: ≤15 nodes, no gates/loops, no parse script -->
<skill impl="dde-simple" mode="simple" role="enforcement">
  <!-- mermaid diagram or reference -->
</skill>

<!-- Full: gates, loops, parallel branches, deterministic parse -->
<skill impl="dde-advanced" mode="advanced" role="enforcement">
  <!-- mermaid diagram or reference -->
</skill>

<!-- Delegate the entire run to a subagent -->
<agent name="diagram-driver" mode="sync">
  <skill impl="dde-advanced" mode="advanced">
    flowchart LR
      A[Fetch] --> B[Transform] --> C[Load]
  </skill>
</agent>
```

## Execution modes

| | `dde-simple` | `dde-advanced` (default) |
|---|---|---|
| **Visual plan widget** | yes | yes |
| **Parser** | agent reads context | `parse-diagram.py` subprocess |
| **Gates** | B10 if detected | multi-way + escalation |
| **Loops** | B10 if detected | bounded pre-expansion |
| **Multi-agent** | no | yes |
| **Token cost** | lower | higher |

## When to activate

Reach for dde when: plan > 3 nodes, fan-out or parallelism, topological
ordering matters, work spans sessions (B4/B8 re-grounding), or "done"
must be a deterministic SQL gate rather than an LLM assertion.

Skip dde for: single-node tasks, ≤3-step throwaway work, exploratory
work where steps aren't known upfront, advisory/Q&A turns.

### Which implementation?

```
Has type=gate or type=loop?  →  dde-advanced
Node count > 15 or complex mermaid syntax?  →  dde-advanced
Otherwise  →  dde-simple
```

## Process

### dde-simple execution

<agent name="diagram-driver" mode="sync">
  <tool allow="sql">
    <skill name="dde.grammar-check">
      Read diagram from context. Assert no type=gate or type=loop nodes.
      Assert node count <= 15. Emit B10 on violation before any SQL writes.
    </skill>
    <skill name="dde.plan-init">
      Extract nodes and edges from context. INSERT todos + todo_deps in
      one batch. design_id collision check first.
    </skill>
    <skill name="dde.execution-loop" policy="sequential">
      SELECT ready nodes (dep-aware, skipped=resolved), ORDER BY rowid.
      Per node: UPDATE in_progress → execute body → UPDATE done or blocked.
      B10 on stuck state.
    </skill>
    <skill name="dde.verify">
      SELECT WHERE status NOT IN ('done','skipped'). Zero rows = complete.
    </skill>
  </tool>
</agent>

### dde-advanced execution

<agent name="diagram-driver" mode="sync">
  <tool allow="sql,bash">
    <skill name="dde.grammar-check">
      python3 scripts/parse-diagram.py --input &lt;file&gt; [--design-id &lt;id&gt;]
      Exit 2 = grammar violation; return diagnostic and stop.
    </skill>
    <skill name="dde.loop-expander">
      Detect type=loop|max_iter=N nodes in parsed JSON. Pre-expand each
      into N iteration todos chained via todo_deps. Wire predecessor and
      successor edges. No further plan mutation permitted after this step.
    </skill>
    <skill name="dde.plan-init">
      INSERT todos + todo_deps from parsed JSON. If gate nodes present:
      CREATE TABLE IF NOT EXISTS dde_gates and INSERT routing rows.
    </skill>
    <skill name="dde.execution-loop" policy="sequential">
      SELECT ready nodes (skipped counts as resolved). Per node:
      UPDATE in_progress → dispatch by type → UPDATE done or blocked.
      <skill name="dde.gate-router" on-failure="halt">
        Read gate result from description JSON. Look up dde_gates for
        matching label. Mark non-matching branch roots skipped (walk
        todo_deps for subtrees). Mark gate done. On no match: escalate
        via send_session_message if parent session present, else B10 +
        mark gate waiting.
      </skill>
    </skill>
    <skill name="dde.verify">
      SELECT status, COUNT(*) GROUP BY status WHERE id LIKE design_id::.
      All done or skipped = complete. Else B10.
    </skill>
  </tool>
</agent>

## Platform and runtime

`common-only`. Advanced mode requires Python 3 on PATH (one call at
plan-init only). Simple mode: no external tools. Parser uses stdlib only.

## Bundled assets

- `scripts/parse-diagram.py` — deterministic mermaid parser (stdlib-only)
- `agents/diagram-driver.agent.md` — process-execution persona
- `references/diagram-grammar.md` — v1 supported grammar subset
- `references/advanced-protocol.md` — dde-advanced contract
- `references/simple-protocol.md` — dde-simple contract

## Limitations (declared)

- Discipline-based enforcement only — no script-level transition gate.
- `dde-simple` rejects gate/loop nodes at grammar-check time (B10).
- v1 grammar excludes subgraphs, composite states, classDefs, click
  handlers (see references/diagram-grammar.md).
- Diagram cycles rejected. Loops expressed via type=loop|max_iter=N.
- Re-planning is a B10 event — start a new design_id for a new diagram.
- Condition-based loops (iterate until condition) not in v0.5.
