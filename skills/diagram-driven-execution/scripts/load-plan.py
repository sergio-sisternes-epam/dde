#!/usr/bin/env python3
"""load-plan.py

Apply schema-init.sql, then atomically insert the parsed plan
(output of parse-diagram.py) into the session SQL store as:
  - one dde_designs row
  - one dde_nodes row per node
  - one dde_edges row per edge
  - one todos row per node (id = '<design_id>::<node_id>', status='pending')
  - one todo_deps row per edge (todo dependency = predecessor edge)

Refuses if design_id already exists in dde_designs (idempotent).
Sets entry-node todos to status='ready' on success.

Usage:
  python3 load-plan.py --json <parsed.json> [--design-id <id>]

Output:
  stdout: JSON {design_id, plan_id, nodes_loaded, edges_loaded, entry_ready}
  exit 0 ok | 3 design exists | 1 other error

Environment:
  DDE_DB_PATH   path to the SQLite database file.
                Default: '.copilot-dde.sqlite' in cwd.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _dde import connect, die, emit_json, parse_args, print_help_from_docstring


def main() -> None:
    args = parse_args(sys.argv[1:], {"json": True, "design-id": True})
    if args.get("__help__"):
        print_help_from_docstring(__doc__)
        return

    json_path = args.get("json")
    if not json_path or not Path(json_path).is_file():
        die("--json <file> required and must exist")

    with open(json_path, "r", encoding="utf-8") as fh:
        plan = json.load(fh)

    design_id = args.get("design-id") or plan["design_id"]

    conn = connect(apply_schema=True)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM dde_designs WHERE design_id = ?", (design_id,))
    if cur.fetchone()[0] != 0:
        die(f"design_id '{design_id}' already loaded; refusing (re-plan = B10 checkpoint)", code=3)

    try:
        cur.execute("BEGIN")
        cur.execute(
            "INSERT INTO dde_designs(design_id, source_hash, format, entry_nodes, terminal_nodes) "
            "VALUES(?, ?, ?, ?, ?)",
            (design_id, plan["source_hash"], plan["format"],
             json.dumps(plan["entry_nodes"]), json.dumps(plan["terminal_nodes"])),
        )
        for n in plan["nodes"]:
            cur.execute(
                "INSERT INTO dde_nodes(design_id, node_id, label, shape, type, model, max_iter) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (design_id, n["id"], n["label"], n["shape"],
                 n.get("type"), n.get("model"), n.get("max_iter", 1)),
            )
        for e in plan["edges"]:
            if e["from"] == "[*]" or e["to"] == "[*]":
                continue
            cur.execute(
                "INSERT INTO dde_edges(design_id, from_node, to_node, label, kind) "
                "VALUES(?, ?, ?, ?, ?)",
                (design_id, e["from"], e["to"], e.get("label"), e["kind"]),
            )
        for n in plan["nodes"]:
            todo_id = f"{design_id}::{n['id']}"
            status = "ready" if n["id"] in plan["entry_nodes"] else "pending"
            cur.execute(
                "INSERT INTO todos(id, title, description, status) VALUES(?, ?, ?, ?)",
                (todo_id, f"[{design_id}] {n['label']}", f"dde node {n['id']}", status),
            )
        for e in plan["edges"]:
            if e["from"] == "[*]" or e["to"] == "[*]":
                continue
            child = f"{design_id}::{e['to']}"
            parent = f"{design_id}::{e['from']}"
            cur.execute(
                "INSERT OR IGNORE INTO todo_deps(todo_id, depends_on) VALUES(?, ?)",
                (child, parent),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    cur.execute("SELECT COUNT(*) FROM dde_nodes WHERE design_id = ?", (design_id,))
    nodes_loaded = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM dde_edges WHERE design_id = ?", (design_id,))
    edges_loaded = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM todos WHERE id LIKE ? AND status = 'ready'",
        (f"{design_id}::%",),
    )
    entry_ready = cur.fetchone()[0]

    emit_json({
        "design_id":    design_id,
        "plan_id":      design_id,
        "nodes_loaded": nodes_loaded,
        "edges_loaded": edges_loaded,
        "entry_ready":  entry_ready,
    })


if __name__ == "__main__":
    main()
