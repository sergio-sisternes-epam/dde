#!/usr/bin/env python3
"""Regression tests for parse-diagram.py chained-edge handling (issue #2)
and SQL-native integration tests for the lite-mode architecture.

Runs the parse-diagram.py script as a subprocess against the repro cases
from the issue plus a couple of extra shapes. No external test runner is
required -- invoke directly:

    python3 skills/diagram-driven-execution/tests/test_parse_diagram_chained.py

Also discoverable by pytest via ``test_*`` naming.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "skills" / "diagram-driven-execution" / "scripts"
PARSE = SCRIPTS / "parse-diagram.py"


def run_parse(diagram_text: str, design_id: str = "t"):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "diagram.mmd"
        path.write_text(diagram_text)
        return subprocess.run(
            [sys.executable, str(PARSE), "--input", str(path), "--design-id", design_id],
            capture_output=True, text=True,
        )


def assert_eq(actual, expected, msg: str) -> None:
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def test_case_a_chained_with_labels_three_nodes() -> None:
    """Issue #2 case A: silent-drop -> now produces 3 nodes + 2 edges."""
    proc = run_parse(
        "flowchart LR\n  a[step-a] --> b[step-b] --> c[step-c]\n",
        design_id="case-a",
    )
    assert_eq(proc.returncode, 0, f"case A exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    node_ids = sorted(n["id"] for n in data["nodes"])
    assert_eq(node_ids, ["a", "b", "c"], "case A node ids")
    edges = sorted((e["from"], e["to"]) for e in data["edges"])
    assert_eq(edges, [("a", "b"), ("b", "c")], "case A edges")
    labels = {n["id"]: n["label"] for n in data["nodes"]}
    assert_eq(labels["a"], "step-a", "case A label a")
    assert_eq(labels["b"], "step-b", "case A label b")
    assert_eq(labels["c"], "step-c", "case A label c")


def test_case_b_per_edge_unchanged() -> None:
    """Issue #2 case B: per-edge statements continue to work."""
    proc = run_parse(
        "flowchart LR\n  a[step-a] --> b[step-b]\n  b --> c[step-c]\n",
        design_id="case-b",
    )
    assert_eq(proc.returncode, 0, f"case B exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    node_ids = sorted(n["id"] for n in data["nodes"])
    assert_eq(node_ids, ["a", "b", "c"], "case B node ids")
    edges = sorted((e["from"], e["to"]) for e in data["edges"])
    assert_eq(edges, [("a", "b"), ("b", "c")], "case B edges")


def test_case_c_unlabelled_chain_now_passes() -> None:
    """Issue #2 case C: ``a --> b --> c --> d`` is now valid (4 nodes, 3 edges)."""
    proc = run_parse(
        "flowchart LR\n  a --> b --> c --> d\n",
        design_id="case-c",
    )
    assert_eq(proc.returncode, 0, f"case C exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    node_ids = sorted(n["id"] for n in data["nodes"])
    assert_eq(node_ids, ["a", "b", "c", "d"], "case C node ids")
    edges = sorted((e["from"], e["to"]) for e in data["edges"])
    assert_eq(edges, [("a", "b"), ("b", "c"), ("c", "d")], "case C edges")


def test_labelled_four_node_chain() -> None:
    """Four-node chain with bracketed labels on every node."""
    proc = run_parse(
        "flowchart LR\n  a[A] --> b[B] --> c[C] --> d[D]\n",
        design_id="chain4",
    )
    assert_eq(proc.returncode, 0, f"chain4 exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    assert_eq(len(data["nodes"]), 4, "chain4 node count")
    assert_eq(len(data["edges"]), 3, "chain4 edge count")


def test_chained_with_edge_label() -> None:
    """Chained edges with a per-arrow edge label attach to the right edge."""
    proc = run_parse(
        "flowchart LR\n  A -->|first| B --> C\n",
        design_id="chain-lbl",
    )
    assert_eq(proc.returncode, 0, f"chain-lbl exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    edges = {(e["from"], e["to"]): e["label"] for e in data["edges"]}
    assert_eq(edges[("A", "B")], "first", "edge label on first arrow")
    assert_eq(edges[("B", "C")], None, "no label on second arrow")


def test_arrow_inside_bracket_label_is_not_chain_split() -> None:
    """Arrows inside ``[...]`` labels must not be mistaken for edge arrows."""
    proc = run_parse(
        "flowchart LR\n  A[do --> something] --> B\n",
        design_id="bracket-arrow",
    )
    assert_eq(proc.returncode, 0, f"bracket-arrow exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    node_ids = sorted(n["id"] for n in data["nodes"])
    assert_eq(node_ids, ["A", "B"], "bracket-arrow node ids")
    label_a = next(n["label"] for n in data["nodes"] if n["id"] == "A")
    assert_eq(label_a, "do --> something", "bracket label preserved")


def test_mismatched_closer_inside_bracket_label() -> None:
    """A literal ``)`` inside ``[...]`` must not pop the bracket stack and
    leak an arrow inside the label out as an edge."""
    proc = run_parse(
        "flowchart LR\n  A[do ) --> something] --> B\n",
        design_id="bracket-mismatch",
    )
    assert_eq(proc.returncode, 0, f"bracket-mismatch exit ({proc.stderr})")
    data = json.loads(proc.stdout)
    node_ids = sorted(n["id"] for n in data["nodes"])
    assert_eq(node_ids, ["A", "B"], "bracket-mismatch node ids")
    edges = [(e["from"], e["to"]) for e in data["edges"]]
    assert_eq(edges, [("A", "B")], "bracket-mismatch single edge")
    label_a = next(n["label"] for n in data["nodes"] if n["id"] == "A")
    assert_eq(label_a, "do ) --> something", "bracket-mismatch label preserved")


def test_unterminated_edge_label_rejected() -> None:
    """An ``|label`` opener with no closing ``|`` rejects with exit 2 and a
    dedicated diagnostic, instead of falling through to a generic node
    parse failure."""
    proc = run_parse(
        "flowchart LR\n  A -->|label B\n",
        design_id="unterm-label",
    )
    assert_eq(proc.returncode, 2, f"unterm-label exit ({proc.stderr})")
    if "unterminated edge label" not in proc.stderr:
        raise AssertionError(
            f"unterm-label error message: expected 'unterminated edge label', got {proc.stderr!r}"
        )


def test_sql_native_integration() -> None:
    """End-to-end lite-mode test: parse chained diagram, load into SQLite
    todos/todo_deps, query ready nodes, mark done in order, verify completion.
    Replaces the former script-based integration test."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        diagram = tmp_path / "d.mmd"
        diagram.write_text("flowchart LR\n  a[A] --> b[B] --> c[C]\n")
        r = subprocess.run(
            [sys.executable, str(PARSE), "--input", str(diagram), "--design-id", "it-lite"],
            capture_output=True, text=True,
        )
        assert_eq(r.returncode, 0, f"parse exit ({r.stderr})")
        plan = json.loads(r.stdout)

        # Create in-memory SQLite with session todos schema
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE todos ("
            "  id TEXT PRIMARY KEY, title TEXT NOT NULL,"
            "  description TEXT, status TEXT NOT NULL DEFAULT 'pending',"
            "  created_at TEXT DEFAULT (datetime('now')),"
            "  updated_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        conn.execute(
            "CREATE TABLE todo_deps ("
            "  todo_id TEXT NOT NULL, depends_on TEXT NOT NULL,"
            "  PRIMARY KEY (todo_id, depends_on)"
            ")"
        )

        design_id = plan["design_id"]

        # Load nodes
        for n in plan["nodes"]:
            todo_id = f"{design_id}::{n['id']}"
            meta = json.dumps({
                "dde": True, "design_id": design_id, "node_id": n["id"],
                "label": n["label"], "type": n.get("type"),
                "model": n.get("model"), "max_iter": n.get("max_iter", 1),
                "shape": n["shape"],
                "terminal": n["id"] in plan["terminal_nodes"],
            })
            conn.execute(
                "INSERT INTO todos (id, title, description, status) VALUES (?, ?, ?, 'pending')",
                (todo_id, f"[{design_id}] {n['label']}", meta),
            )

        # Load edges as dependencies
        for e in plan["edges"]:
            if e["from"] == "[*]" or e["to"] == "[*]":
                continue
            conn.execute(
                "INSERT INTO todo_deps (todo_id, depends_on) VALUES (?, ?)",
                (f"{design_id}::{e['to']}", f"{design_id}::{e['from']}"),
            )
        conn.commit()

        # Ready query template
        ready_query = (
            "SELECT t.id, t.title FROM todos t "
            "WHERE t.id LIKE ? AND t.status = 'pending' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM todo_deps td "
            "  JOIN todos dep ON td.depends_on = dep.id "
            "  WHERE td.todo_id = t.id AND dep.status != 'done'"
            ")"
        )

        # Walk the diagram: should proceed a -> b -> c
        executed = []
        for _ in range(10):  # safety bound
            rows = conn.execute(ready_query, (f"{design_id}::%",)).fetchall()
            if not rows:
                break
            node_id = rows[0][0]
            conn.execute(
                "UPDATE todos SET status = 'in_progress', updated_at = datetime('now') WHERE id = ?",
                (node_id,),
            )
            conn.execute(
                "UPDATE todos SET status = 'done', updated_at = datetime('now') WHERE id = ?",
                (node_id,),
            )
            conn.commit()
            executed.append(node_id.split("::", 1)[1])

        assert_eq(executed, ["a", "b", "c"], "execution order")

        # Verify completion
        cur = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE id LIKE ? AND status != 'done'",
            (f"{design_id}::%",),
        )
        assert_eq(cur.fetchone()[0], 0, "all nodes done")

        # Critical: c was previously silently dropped (issue #2); verify it's present
        cur = conn.execute(
            "SELECT COUNT(*) FROM todos WHERE id = ?",
            (f"{design_id}::c",),
        )
        assert_eq(cur.fetchone()[0], 1, "node c exists")


def test_design_id_validation() -> None:
    """Design IDs with invalid characters are rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "d.mmd"
        path.write_text("flowchart LR\n  a --> b\n")
        r = subprocess.run(
            [sys.executable, str(PARSE), "--input", str(path), "--design-id", "bad%id"],
            capture_output=True, text=True,
        )
        assert_eq(r.returncode, 1, f"bad design_id exit ({r.stderr})")


def test_state_diagram_cycle_rejected() -> None:
    """Cycles in stateDiagram-v2 are now rejected (lite mode requires acyclic)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "d.mmd"
        path.write_text("stateDiagram-v2\n  [*] --> A\n  A --> B\n  B --> A\n  B --> [*]\n")
        r = subprocess.run(
            [sys.executable, str(PARSE), "--input", str(path), "--design-id", "cycle-test"],
            capture_output=True, text=True,
        )
        assert_eq(r.returncode, 2, f"cycle should be rejected ({r.stderr})")
        if "cycle" not in r.stderr.lower():
            raise AssertionError(f"expected cycle error, got: {r.stderr!r}")


def main() -> int:
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok  - {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL - {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
