"""Shared helpers for diagram-driven-execution scripts.

Cross-platform: pure Python stdlib (sqlite3, pathlib, json).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_FILENAME = ".copilot-dde.sqlite"
SCHEMA_REL_PATH = Path(__file__).resolve().parent.parent / "assets" / "schema-init.sql"


def db_path() -> Path:
    """Resolve the SQLite database file from DDE_DB_PATH or default."""
    return Path(os.environ.get("DDE_DB_PATH") or DEFAULT_DB_FILENAME)


def connect(apply_schema: bool = True) -> sqlite3.Connection:
    """Open a connection. Optionally apply schema-init.sql (idempotent)."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON;")
    if apply_schema:
        if not SCHEMA_REL_PATH.is_file():
            die(f"schema-init.sql not found at {SCHEMA_REL_PATH}", code=1)
        with open(SCHEMA_REL_PATH, "r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.commit()
    return conn


def emit_json(payload: dict[str, Any]) -> None:
    """Print a JSON object to stdout, sorted + indented, deterministic."""
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def die(msg: str, code: int = 1) -> None:
    """Print an error to stderr and exit with the given code."""
    sys.stderr.write(f"{Path(sys.argv[0]).name}: {msg}\n")
    sys.exit(code)


def parse_args(argv: list[str], spec: dict[str, bool]) -> dict[str, str]:
    """Tiny long-flag parser. spec maps flag -> requires_value (bool).

    Always supports --help / -h. Unknown flags raise.
    """
    out: dict[str, str] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            out["__help__"] = "1"
            return out
        if a.startswith("--") and a[2:] in spec:
            key = a[2:]
            if spec[key]:
                if i + 1 >= len(argv):
                    die(f"flag --{key} requires a value", code=1)
                out[key] = argv[i + 1]
                i += 2
            else:
                out[key] = "1"
                i += 1
        else:
            die(f"unknown argument: {a}", code=1)
    return out


def print_help_from_docstring(doc: str | None) -> None:
    """Print the calling script's module docstring as --help text."""
    sys.stdout.write((doc or "").strip() + "\n")
