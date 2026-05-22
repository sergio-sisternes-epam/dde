#!/usr/bin/env python3
"""verify-completion.py

Verify a design is complete:
  - every terminal node has status='done'
  - no node has status='failed'
  - emit summary including illegal-transition attempts from history

Usage:
  python3 verify-completion.py --design-id <id>

Output:
  stdout: JSON {design_id, complete, terminals_done, terminals_missing,
                unresolved_failures, total_transitions, illegal_attempts}
  exit 0 complete | 6 incomplete | 1 error

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
    cur.execute(
        "SELECT substr(id, ?), status FROM todos WHERE id LIKE ?",
        (len(prefix) + 1, f"{prefix}%"),
    )
    status = {nid: st for nid, st in cur.fetchall()}

    cur.execute(
        "SELECT COUNT(*) FROM dde_history WHERE design_id = ?", (design_id,),
    )
    total = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM dde_history WHERE design_id = ? AND accepted = 0",
        (design_id,),
    )
    illegal = cur.fetchone()[0]

    terminals_done = sorted([t for t in terminals if status.get(t) == "done"])
    terminals_missing = sorted([t for t in terminals if status.get(t) != "done"])
    unresolved = sorted([n for n, s in status.items() if s == "failed"])
    complete = not terminals_missing and not unresolved

    emit_json({
        "design_id":           design_id,
        "complete":            complete,
        "terminals_done":      terminals_done,
        "terminals_missing":   terminals_missing,
        "unresolved_failures": unresolved,
        "total_transitions":   total,
        "illegal_attempts":    illegal,
    })
    sys.exit(0 if complete else 6)


if __name__ == "__main__":
    main()
