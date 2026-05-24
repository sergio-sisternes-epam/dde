# diagram-grammar (rule)

Auto-attach: any thread that loads `diagram-driven-execution` or
invokes `scripts/parse-diagram.py`.

This rule defines the v1 supported subset of mermaid syntax. The
parser rejects anything outside this list with a non-zero exit
code and a line/column diagnostic. Do not paper over rejections
in prose; if a diagram fails to parse, return it to the operator
with the rejection message.

## Supported in v1

### Flowchart

- Header: `flowchart LR`, `flowchart TD`, `flowchart RL`,
  `flowchart BT`. Exactly one header line.
- Node shapes (label in brackets; optional):
  - `A[Rectangle]`
  - `A(Round)`
  - `A((Circle))`
  - `A{Diamond}`
  - `A[(Stadium)]`
- Edges:
  - `A --> B`           (kind = `solid`)
  - `A ==> B`           (kind = `tool-result`)
  - `A -.-> B`          (kind = `dashed`)
  - `A -->|edge label| B`
  - Chained edges on a single line are expanded into pairwise edges,
    matching Mermaid's
    [chaining-of-links](https://mermaid.js.org/syntax/flowchart.html#chaining-of-links)
    semantics:
    - `A --> B --> C` is equivalent to `A --> B` followed by `B --> C`.
    - Bracketed labels attach to the first occurrence of each node id;
      subsequent occurrences reuse the id (e.g.
      `a[step-a] --> b[step-b] --> c[step-c]` yields three nodes with
      their labels and two edges).
    - Per-arrow edge labels are supported and attach to the arrow they
      follow: `A -->|first| B --> C` produces edges `(A, B, label=first)`
      and `(B, C, label=None)`.
    - The arrow kinds (`-->`, `==>`, `-.->`) may be mixed within a chain;
      each segment carries the kind of its own arrow.
- Comments: `%% ...` on their own line.
- Node label inline annotations (pipe-separated, after the visible
  label text):
  - `A[Execute|type=subagent|model=opus|max_iter=3]`
  - Recognised keys: `type` (`manual` | `subagent` | `tool` |
    `prompt`), `model` (any string; consumed by the dispatcher),
    `max_iter` (positive integer; cycle bound for stateDiagram).
- The graph MUST be acyclic. Cycles are rejected; use
  `stateDiagram-v2` if your process needs loops.

### State diagram (v2)

- Header: `stateDiagram-v2`.
- Transitions: `A --> B` and `A --> B : note label`.
- Entry / exit pseudostate: `[*]` on either side.
- Cycles are permitted syntactically but **rejected by the parser**
  in all diagram types. The lite-mode dependency model requires
  acyclic graphs. Use linear or branching structures only.

## Rejected in v1 (loud)

The parser exits 2 with a line/column message if the diagram
contains:

- `subgraph` blocks.
- Composite states or `state` keyword.
- `classDef`, `class`, `style`, `linkStyle`.
- `click` handlers.
- `note` blocks (use ` : ` inline labels in stateDiagram).
- Themes / front-matter blocks.
- Edges other than `-->`, `==>`, `-.->`.
- Node shapes other than the five listed above.
- More than one header line.
- Empty diagrams.

Future versions may extend this grammar; until then, rejection is
the contract.

## Why a bounded grammar

A FACT THAT MUST BE TRUE (the node + edge set) cannot be derived
by LLM-asserted "reading" of a free-form diagram (truth #4,
HAND-ROLLED HALLUCINATION). The supported subset is small enough
to parse deterministically with a focused script. Anything we
cannot parse deterministically, we refuse -- silent partial
parses would let drift in through a side door.
