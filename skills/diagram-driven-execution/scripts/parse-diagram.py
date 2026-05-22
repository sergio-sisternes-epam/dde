#!/usr/bin/env python3
"""parse-diagram.py

Deterministically parse a bounded subset of mermaid into a JSON plan
structure. The output is consumed by load-plan.py.

Supported grammar (v1) -- everything else is REJECTED LOUDLY:
  flowchart LR | flowchart TD | flowchart RL | flowchart BT
    node shapes: [text]  (text)  ((text))  {text}  [(text)]
    edges:       A --> B
                 A ==> B            (kind=tool-result)
                 A -.-> B           (kind=dashed)
                 A -->|label| B
    comments:    %% ...             (ignored)
    node label inline annotations (pipe-separated):
      [text|type=subagent|model=opus|max_iter=3]
  stateDiagram-v2
    transitions: A --> B            with [*] for entry/terminal
    labels:      A --> B : note

NOT supported in v1 (rejected): subgraphs, composite states, class
definitions, click handlers, conditional styling, themes.

Usage:
  python3 parse-diagram.py --input <file> [--design-id <id>]
                           [--format auto|flowchart|stateDiagram]

Output:
  stdout: JSON {design_id, format, source_hash, entry_nodes,
                terminal_nodes, nodes:[...], edges:[...]}
  stderr: parse diagnostics (line/column of rejections)
  exit 0 ok | 2 grammar reject | 1 other error
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from _dde import die, emit_json, parse_args, print_help_from_docstring


REJECTED_KEYWORDS = (
    "subgraph", "class ", "classDef ", "click ",
    "style ", "linkStyle ", "state ", "note ",
)

NODE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_-]*)"
    r"(?:(\[\(.*?\)\])|(\[\[.*?\]\])|(\(\(.*?\)\))|(\[.*?\])|(\(.*?\))|(\{.*?\}))?"
)
SHAPE_MAP = {
    "[(": "stadium", "((": "circle", "[": "rect",
    "(": "round", "{": "diamond",
}
EDGE_RE = re.compile(
    r"^\s*(.+?)\s*(-->|==>|-\.->)\s*(?:\|([^|]+)\|\s*)?(.+?)\s*$"
)


def reject(lineno: int, col: int, msg: str) -> None:
    sys.stderr.write(f"parse-diagram: line {lineno} col {col}: {msg}\n")
    sys.exit(2)


def parse_label_meta(raw_label: str) -> tuple[str, dict[str, str]]:
    parts = raw_label.split("|")
    label = parts[0].strip()
    meta: dict[str, str] = {}
    for p in parts[1:]:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        meta[k.strip()] = v.strip()
    return label, meta


def parse_node_token(tok: str, nodes: dict) -> tuple[str, str | None] | None:
    m = NODE_RE.fullmatch(tok.strip())
    if not m:
        return None
    node_id = m.group(1)
    shape_open = None
    raw_inner = None
    for g in m.groups()[1:]:
        if not g:
            continue
        if g.startswith("[("):
            shape_open, raw_inner = "[(", g[2:-2]
        elif g.startswith("(("):
            shape_open, raw_inner = "((", g[2:-2]
        elif g.startswith("["):
            shape_open, raw_inner = "[", g[1:-1]
        elif g.startswith("("):
            shape_open, raw_inner = "(", g[1:-1]
        elif g.startswith("{"):
            shape_open, raw_inner = "{", g[1:-1]
        break
    if raw_inner is None:
        add_node(nodes, node_id)
        return node_id, None
    raw_inner = raw_inner.strip()
    if raw_inner.startswith('"') and raw_inner.endswith('"'):
        raw_inner = raw_inner[1:-1]
    label, meta = parse_label_meta(raw_inner)
    add_node(nodes, node_id, label=label, shape=SHAPE_MAP[shape_open])
    if "type" in meta:
        nodes[node_id]["type"] = meta["type"]
    if "model" in meta:
        nodes[node_id]["model"] = meta["model"]
    if "max_iter" in meta:
        try:
            nodes[node_id]["max_iter"] = int(meta["max_iter"])
        except ValueError:
            pass
    return node_id, label


def add_node(nodes: dict, node_id: str, label: str | None = None, shape: str = "rect") -> str:
    if node_id == "[*]":
        return node_id
    if node_id not in nodes:
        nodes[node_id] = {
            "id": node_id,
            "label": label or node_id,
            "shape": shape,
            "type": None,
            "model": None,
            "max_iter": 1,
        }
    elif label and nodes[node_id]["label"] == nodes[node_id]["id"]:
        nodes[node_id]["label"] = label
        nodes[node_id]["shape"] = shape
    return node_id


def detect_cycle(nodes: dict, edges: list, entry_nodes: list) -> None:
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        if e["from"] in adj and e["to"] in adj:
            adj[e["from"]].append(e["to"])
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {n: WHITE for n in nodes}
    stack: list[tuple[str, int]] = []
    for start in entry_nodes:
        if colour[start] != WHITE:
            continue
        stack.append((start, 0))
        while stack:
            u, i = stack[-1]
            if i == 0:
                colour[u] = GREY
            if i < len(adj[u]):
                stack[-1] = (u, i + 1)
                v = adj[u][i]
                if colour[v] == GREY:
                    reject(0, 0, f"cycle detected at edge {u} --> {v} (use stateDiagram-v2 for cycles)")
                if colour[v] == WHITE:
                    stack.append((v, 0))
            else:
                colour[u] = BLACK
                stack.pop()


def main() -> None:
    args = parse_args(sys.argv[1:], {"input": True, "design-id": True, "format": True})
    if args.get("__help__"):
        print_help_from_docstring(__doc__)
        return

    input_path = args.get("input")
    if not input_path or not Path(input_path).is_file():
        die("--input <file> required and must exist")

    design_id = args.get("design-id") or ""
    fmt = args.get("format") or "auto"

    raw = Path(input_path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]

    joined = "\n".join(lines).strip()
    if fmt == "auto":
        if re.match(r"^\s*stateDiagram-v2\b", joined):
            fmt = "stateDiagram"
        elif re.match(r"^\s*flowchart\b", joined):
            fmt = "flowchart"
        else:
            reject(0, 0, "cannot detect format; expected 'flowchart' or 'stateDiagram-v2' as first non-empty line")

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    started = False
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        if not started:
            if fmt == "flowchart":
                if not re.match(r"^flowchart\s+(LR|TD|RL|BT)\s*$", stripped):
                    reject(lineno, 1, f"expected 'flowchart LR|TD|RL|BT', got: {stripped!r}")
            else:
                if not re.match(r"^stateDiagram-v2\s*$", stripped):
                    reject(lineno, 1, f"expected 'stateDiagram-v2', got: {stripped!r}")
            started = True
            continue
        for kw in REJECTED_KEYWORDS:
            if stripped.startswith(kw):
                reject(lineno, 1, f"unsupported feature in v1 grammar: {kw.strip()!r}")

        m = EDGE_RE.match(stripped)
        if not m:
            if fmt == "flowchart":
                res = parse_node_token(stripped, nodes)
                if res:
                    continue
            reject(lineno, 1, f"line is neither a supported edge nor a standalone node: {stripped!r}")

        left_raw, arrow, label_inner, right_raw = m.group(1), m.group(2), m.group(3), m.group(4)
        if fmt == "stateDiagram":
            if label_inner is None and " : " in right_raw:
                right_raw, note = right_raw.split(" : ", 1)
                label_inner = note.strip()
            left_id = left_raw.strip()
            right_id = right_raw.strip()
            if left_id != "[*]":
                add_node(nodes, left_id)
            if right_id != "[*]":
                add_node(nodes, right_id)
            edges.append({"from": left_id, "to": right_id, "label": label_inner, "kind": "solid"})
        else:
            left_res = parse_node_token(left_raw, nodes)
            right_res = parse_node_token(right_raw, nodes)
            if not left_res or not right_res:
                reject(lineno, 1, f"could not parse node tokens in edge: {stripped!r}")
            kind = {"-->": "solid", "==>": "tool-result", "-.->": "dashed"}[arrow]
            edges.append({"from": left_res[0], "to": right_res[0], "label": label_inner, "kind": kind})

    if not started:
        reject(0, 0, "empty diagram")

    all_ids = set(nodes.keys())
    has_incoming = {e["to"] for e in edges if e["to"] != "[*]"}
    has_outgoing = {e["from"] for e in edges if e["from"] != "[*]"}

    if fmt == "stateDiagram":
        entry_nodes = sorted({e["to"] for e in edges if e["from"] == "[*]"})
        terminal_nodes = sorted({e["from"] for e in edges if e["to"] == "[*]"})
    else:
        entry_nodes = sorted(all_ids - has_incoming)
        terminal_nodes = sorted(all_ids - has_outgoing)

    if not entry_nodes:
        reject(0, 0, "no entry node(s) found")
    if not terminal_nodes:
        reject(0, 0, "no terminal node(s) found")

    if fmt == "flowchart":
        detect_cycle(nodes, edges, entry_nodes)

    emit_json({
        "design_id":      design_id or source_hash[:12],
        "format":         fmt,
        "source_hash":    source_hash,
        "entry_nodes":    entry_nodes,
        "terminal_nodes": terminal_nodes,
        "nodes":          list(nodes.values()),
        "edges":          edges,
    })


if __name__ == "__main__":
    main()
