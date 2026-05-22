#!/usr/bin/env python3
"""next-ready.py

Query the SQL store for the currently-ready node set of a design.
A node is READY iff every todo it depends on is 'done'.

State semantics:
  ready    -- at least one node is ready
  done     -- every terminal node is 'done'
  stuck    -- no ready nodes AND not done

Usage:
  python3 next-ready.py --design-id <id>

Output:
  stdout: JSON {state, ready_nodes, in_progress_nodes, blocked_nodes,
                done_nodes, failed_nodes, terminals}
  exit 0 (any state) | 1 error

Environment:
  DDE_DB_PATH   path to the SQLite database file.
"""
from __future__ import annotations

import json
import sys

from _dde import connect, die, emit_json, parse_args, print_help_from_docstring


def main() -> None:
    args = parse_args(sys.argv[1:], {"design-id": True})
    if args.get("__help__"):
        print_help_from_docstring(__doc__)
        return

    design_id = args.get("design-id")
    if not design_id:
        die("--design-id required")

    conn = connect(apply_schema=False)
    cur = conn.cursor()

    cur.execute("SELECT terminal_nodes FROM dde_designs WHERE design_id = ?", (design_id,))
    row = cur.fetchone()
    if row is None:
        die(f"design_id '{design_id}' not found", code=5)
    terminals = json.loads(row[0] or "[]")

    prefix = f"{design_id}::"
    plen = len(prefix)

    cur.execute(
        "SELECT substr(id, ?), status FROM todos WHERE id LIKE ?",
        (plen + 1, f"{prefix}%"),
    )
    status = {nid: st for nid, st in cur.fetchall()}

    cur.execute(
        "SELECT substr(todo_id, ?), substr(depends_on, ?) "
        "FROM todo_deps WHERE todo_id LIKE ?",
        (plen + 1, plen + 1, f"{prefix}%"),
    )
    pending_deps: dict[str, list[str]] = {}
    for child, parent in cur.fetchall():
        pending_deps.setdefault(child, []).append(parent)

    ready, in_progress, blocked, done, failed = [], [], [], [], []
    for nid, st in status.items():
        if st == "done":
            done.append(nid)
        elif st == "failed":
            failed.append(nid)
        elif st == "in_progress":
            in_progress.append(nid)
        else:
            parents = pending_deps.get(nid, [])
            if all(status.get(p) == "done" for p in parents):
                ready.append(nid)
            else:
                blocked.append(nid)

    terminals_done = all(status.get(t) == "done" for t in terminals) if terminals else False
    if terminals_done and not failed:
        state = "done"
    elif not ready and not in_progress:
        state = "stuck"
    else:
        state = "ready"

    emit_json({
        "state":             state,
        "ready_nodes":       sorted(ready),
        "in_progress_nodes": sorted(in_progress),
        "blocked_nodes":     sorted(blocked),
        "done_nodes":        sorted(done),
        "failed_nodes":      sorted(failed),
        "terminals":         terminals,
    })


if __name__ == "__main__":
    main()
