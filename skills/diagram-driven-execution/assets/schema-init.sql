-- diagram-driven-execution: schema bootstrap
--
-- Applied once per design_id via load-plan.py. Reuses the host
-- harness's existing `todos` and `todo_deps` tables (substrate
-- concept 6, TODO/STATUS slot) and adds four design-scoped tables:
--   dde_designs   one row per loaded diagram
--   dde_nodes     per-node metadata (label, shape, type, model)
--   dde_edges     the parsed edge list (the legal transition graph)
--   dde_history   append-only audit of every transition attempt
--
-- The bridge to the substrate todo table is the composite id pattern
--   todos.id = '<design_id>::<node_id>'
-- so a single SQL store can hold multiple designs without collision
-- and the substrate's existing tooling continues to work.

CREATE TABLE IF NOT EXISTS dde_designs (
  design_id   TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,
  format      TEXT NOT NULL,          -- 'flowchart' | 'stateDiagram'
  loaded_at   TEXT NOT NULL DEFAULT (datetime('now')),
  entry_nodes TEXT NOT NULL,          -- JSON array of node_ids
  terminal_nodes TEXT NOT NULL        -- JSON array of node_ids
);

CREATE TABLE IF NOT EXISTS dde_nodes (
  design_id TEXT NOT NULL,
  node_id   TEXT NOT NULL,
  label     TEXT NOT NULL,
  shape     TEXT NOT NULL,            -- 'rect'|'round'|'circle'|'diamond'|'stadium'|'state'
  type      TEXT,                     -- 'manual'|'subagent'|'tool'|'prompt' (optional)
  model     TEXT,                     -- per-node model weight (optional)
  max_iter  INTEGER NOT NULL DEFAULT 1, -- cycle bound (A8 discipline)
  PRIMARY KEY (design_id, node_id),
  FOREIGN KEY (design_id) REFERENCES dde_designs(design_id)
);

CREATE TABLE IF NOT EXISTS dde_edges (
  design_id TEXT NOT NULL,
  from_node TEXT NOT NULL,
  to_node   TEXT NOT NULL,
  label     TEXT,
  kind      TEXT NOT NULL DEFAULT 'solid', -- 'solid'|'tool-result'|'dashed'
  PRIMARY KEY (design_id, from_node, to_node),
  FOREIGN KEY (design_id) REFERENCES dde_designs(design_id)
);

CREATE TABLE IF NOT EXISTS dde_history (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  design_id     TEXT NOT NULL,
  node_id       TEXT NOT NULL,
  from_status   TEXT NOT NULL,
  to_status     TEXT NOT NULL,
  accepted      INTEGER NOT NULL,     -- 1=accepted, 0=rejected
  reject_reason TEXT,                 -- non-null only when accepted=0
  output_ref    TEXT,
  note          TEXT,
  ts            TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (design_id) REFERENCES dde_designs(design_id)
);

CREATE INDEX IF NOT EXISTS dde_history_design_idx
  ON dde_history (design_id, ts);

-- Substrate todo tables (created defensively if the harness has not
-- materialised them yet; harmless if they already exist).
CREATE TABLE IF NOT EXISTS todos (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS todo_deps (
  todo_id    TEXT NOT NULL,
  depends_on TEXT NOT NULL,
  PRIMARY KEY (todo_id, depends_on)
);
