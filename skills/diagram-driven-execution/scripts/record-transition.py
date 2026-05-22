#!/usr/bin/env python3
"""record-transition.py

Apply a per-node status transition, validating:
  1. node exists in the design
  2. (current_status -> new_status) is a legal lifecycle transition
  3. ready -> in_progress | failed only
  4. in_progress -> done | failed only
  5. done | failed are terminal

Every attempt (accepted OR rejected) is appended to dde_history so
the audit trail records illegal-transition attempts -- those drive
the B10 HUMAN CHECKPOINT signal.

Lifecycle (NOT the diagram edges -- this is the per-node todo state
machine):

    pending --> ready --> in_progress --> done
                 |             |--> failed
                 v
              (blocked by deps; computed by next-ready)

Usage:
  python3 record-transition.py --design-id <id> --node <node_id> --to <status>
                               [--output <ref>] [--note <text>]

Exit codes:
  0  accepted
  4  illegal lifecycle (history row written, status unchanged)
  5  node not found
  1  other error

Environment:
  DDE_DB_PATH   path to the SQLite database file.
"""
from __future__ import annotations

import sys

from _dde import connect, die, emit_json, parse_args, print_help_from_docstring


LEGAL: dict[str, set[str]] = {
    "pending":     {"ready"},
    "ready":       {"in_progress", "failed"},
    "in_progress": {"done", "failed"},
    "done":        set(),
    "failed":      set(),
}


def main() -> None:
    args = parse_args(sys.argv[1:], {
        "design-id": True, "node": True, "to": True,
        "output": True, "note": True,
    })
    if args.get("__help__"):
        print_help_from_docstring(__doc__)
        return

    design_id = args.get("design-id")
    node = args.get("node")
    to = args.get("to")
    if not design_id or not node or not to:
        die("--design-id, --node, --to required")
    if to not in ("ready", "in_progress", "done", "failed"):
        die("--to must be one of ready|in_progress|done|failed")

    output_ref = args.get("output")
    note = args.get("note")
    todo_id = f"{design_id}::{node}"

    conn = connect(apply_schema=False)
    cur = conn.cursor()

    cur.execute("SELECT status FROM todos WHERE id = ?", (todo_id,))
    row = cur.fetchone()
    if row is None:
        die(f"node '{node}' not found in design '{design_id}'", code=5)
    current = row[0]

    legal = to in LEGAL[current]
    reason = None if legal else f"illegal lifecycle: {current} -> {to}"

    try:
        cur.execute("BEGIN")
        cur.execute(
            "INSERT INTO dde_history(design_id, node_id, from_status, to_status, "
            "accepted, reject_reason, output_ref, note) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (design_id, node, current, to, 1 if legal else 0, reason, output_ref, note),
        )
        if legal:
            cur.execute(
                "UPDATE todos SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (to, todo_id),
            )
            if to == "done":
                # Promote children whose deps are now all done.
                cur.execute(
                    "SELECT DISTINCT td.todo_id FROM todo_deps td "
                    "WHERE td.todo_id LIKE ? AND td.depends_on = ?",
                    (f"{design_id}::%", todo_id),
                )
                candidates = [r[0] for r in cur.fetchall()]
                for child in candidates:
                    cur.execute(
                        "SELECT COUNT(*) FROM todo_deps td "
                        "JOIN todos t2 ON t2.id = td.depends_on "
                        "WHERE td.todo_id = ? AND t2.status != 'done'",
                        (child,),
                    )
                    if cur.fetchone()[0] == 0:
                        cur.execute(
                            "UPDATE todos SET status = 'ready', updated_at = datetime('now') "
                            "WHERE id = ? AND status = 'pending'",
                            (child,),
                        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if not legal:
        sys.stderr.write(
            f"record-transition: REJECTED ({reason}); current={current}, requested={to}\n"
        )
        sys.exit(4)

    emit_json({
        "design_id": design_id,
        "node":      node,
        "from":      current,
        "to":        to,
        "accepted":  True,
    })


if __name__ == "__main__":
    main()
