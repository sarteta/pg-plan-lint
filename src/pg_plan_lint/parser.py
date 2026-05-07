"""Parse Postgres EXPLAIN ANALYZE output into a tree of PlanNode objects.

Supports JSON (preferred -- `EXPLAIN (ANALYZE, FORMAT JSON)`) and the
default text format. JSON is used when the input starts with `[` or `{`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PlanNode:
    node_type: str
    relation: Optional[str] = None
    alias: Optional[str] = None

    # Planner estimates
    plan_rows: Optional[int] = None
    plan_width: Optional[int] = None
    startup_cost: Optional[float] = None
    total_cost: Optional[float] = None

    # Actual execution stats (from ANALYZE)
    actual_rows: Optional[int] = None
    actual_loops: Optional[int] = None
    actual_startup_time: Optional[float] = None
    actual_total_time: Optional[float] = None

    # Optional / detail attributes
    filter: Optional[str] = None
    rows_removed_by_filter: Optional[int] = None
    index_cond: Optional[str] = None
    join_filter: Optional[str] = None
    hash_batches: Optional[int] = None
    hash_buckets: Optional[int] = None
    hash_memory_kb: Optional[int] = None
    sort_method: Optional[str] = None
    sort_space_kb: Optional[int] = None
    heap_blocks_lossy: Optional[int] = None
    heap_blocks_exact: Optional[int] = None

    children: list["PlanNode"] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def estimate_skew(self) -> Optional[float]:
        """ratio of actual_rows / plan_rows -- > 10 or < 0.1 means stats are off."""
        if self.actual_rows is None or self.plan_rows is None or self.plan_rows == 0:
            return None
        # for nodes that loop, multiply per-loop actual rows by loops
        loops = self.actual_loops or 1
        actual = self.actual_rows * loops if self.actual_loops and self.actual_loops > 1 else self.actual_rows
        return actual / self.plan_rows


def parse_plan(text: str) -> PlanNode:
    """Auto-detect format and parse. Returns the root PlanNode."""
    s = text.strip()
    if s.startswith("[") or s.startswith("{"):
        return _parse_json(s)
    return _parse_text(s)


# ---------------------------------------------------------------------------
# JSON parser (EXPLAIN (ANALYZE, FORMAT JSON))
# ---------------------------------------------------------------------------
def _parse_json(s: str) -> PlanNode:
    data = json.loads(s)
    if isinstance(data, list) and data:
        data = data[0]
    plan = data.get("Plan") if isinstance(data, dict) else None
    if plan is None:
        raise ValueError("JSON does not contain a 'Plan' key")
    return _node_from_json(plan)


def _node_from_json(p: dict) -> PlanNode:
    n = PlanNode(node_type=p.get("Node Type", "Unknown"), raw=p)
    n.relation = p.get("Relation Name")
    n.alias = p.get("Alias")
    n.plan_rows = p.get("Plan Rows")
    n.plan_width = p.get("Plan Width")
    n.startup_cost = p.get("Startup Cost")
    n.total_cost = p.get("Total Cost")
    n.actual_rows = p.get("Actual Rows")
    n.actual_loops = p.get("Actual Loops")
    n.actual_startup_time = p.get("Actual Startup Time")
    n.actual_total_time = p.get("Actual Total Time")
    n.filter = p.get("Filter")
    n.rows_removed_by_filter = p.get("Rows Removed by Filter")
    n.index_cond = p.get("Index Cond")
    n.join_filter = p.get("Join Filter")
    n.hash_batches = p.get("Hash Batches") or p.get("Original Hash Batches")
    n.hash_buckets = p.get("Hash Buckets")
    n.hash_memory_kb = p.get("Peak Memory Usage")  # in JSON, kB
    n.sort_method = p.get("Sort Method")
    n.sort_space_kb = p.get("Sort Space Used")
    n.heap_blocks_exact = p.get("Heap Blocks") if isinstance(p.get("Heap Blocks"), int) else None
    # heap blocks may be {"exact": N, "lossy": M}
    hb = p.get("Heap Blocks")
    if isinstance(hb, dict):
        n.heap_blocks_exact = hb.get("exact")
        n.heap_blocks_lossy = hb.get("lossy")
    for child in p.get("Plans", []) or []:
        n.children.append(_node_from_json(child))
    return n


# ---------------------------------------------------------------------------
# Text parser (default EXPLAIN ANALYZE output)
# ---------------------------------------------------------------------------
_RX_NODE_LINE = re.compile(
    r"""^
    (?P<indent>\s*)
    (?:->\s+)?
    (?P<type>[A-Z][A-Za-z0-9 ]+?)
    (?:\s+on\s+(?P<rel>\S+)(?:\s+(?P<alias>\S+))?)?
    \s+\(cost=(?P<sc>[\d.]+)\.\.(?P<tc>[\d.]+)\s+rows=(?P<pr>\d+)\s+width=(?P<pw>\d+)\)
    (?:\s+\(actual\s+time=(?P<ast>[\d.]+)\.\.(?P<att>[\d.]+)\s+rows=(?P<ar>\d+)\s+loops=(?P<al>\d+)\))?
    \s*$""",
    re.VERBOSE,
)
_RX_FILTER = re.compile(r"^\s*Filter:\s*(.+)$")
_RX_ROWS_REMOVED = re.compile(r"^\s*Rows Removed by Filter:\s*(\d+)")
_RX_INDEX_COND = re.compile(r"^\s*Index Cond:\s*(.+)$")
_RX_HASH_BATCHES = re.compile(r"^\s*Buckets:\s*(\d+)(?:\s+\(originally \d+\))?\s+Batches:\s*(\d+)")
_RX_HASH_MEM = re.compile(r"Memory Usage:\s*(\d+)kB")
_RX_SORT_METHOD = re.compile(r"^\s*Sort Method:\s*(.+?):\s*(\d+)kB", re.I)
_RX_HEAP_BLOCKS = re.compile(r"^\s*Heap Blocks:.*?(?:exact=(\d+))?.*?(?:lossy=(\d+))?")


def _parse_text(s: str) -> PlanNode:
    lines = [ln for ln in s.splitlines() if ln.strip() and "QUERY PLAN" not in ln and not ln.lstrip().startswith("---")]
    if not lines:
        raise ValueError("No parseable lines in text plan")

    # Build nodes with their indent levels
    parsed: list[tuple[int, PlanNode]] = []  # (indent, node)
    current_node: Optional[PlanNode] = None
    for ln in lines:
        m = _RX_NODE_LINE.match(ln)
        if m:
            n = PlanNode(
                node_type=m.group("type").strip(),
                relation=m.group("rel"),
                alias=m.group("alias"),
                startup_cost=float(m.group("sc")),
                total_cost=float(m.group("tc")),
                plan_rows=int(m.group("pr")),
                plan_width=int(m.group("pw")),
            )
            if m.group("ast"):
                n.actual_startup_time = float(m.group("ast"))
                n.actual_total_time = float(m.group("att"))
                n.actual_rows = int(m.group("ar"))
                n.actual_loops = int(m.group("al"))
            indent = len(m.group("indent"))
            parsed.append((indent, n))
            current_node = n
            continue

        # Detail lines belong to current_node
        if current_node is None:
            continue
        if (mm := _RX_FILTER.match(ln)):
            current_node.filter = mm.group(1).strip()
        elif (mm := _RX_ROWS_REMOVED.match(ln)):
            current_node.rows_removed_by_filter = int(mm.group(1))
        elif (mm := _RX_INDEX_COND.match(ln)):
            current_node.index_cond = mm.group(1).strip()
        elif (mm := _RX_HASH_BATCHES.match(ln)):
            current_node.hash_buckets = int(mm.group(1))
            current_node.hash_batches = int(mm.group(2))
            mem = _RX_HASH_MEM.search(ln)
            if mem:
                current_node.hash_memory_kb = int(mem.group(1))
        elif (mm := _RX_SORT_METHOD.match(ln)):
            current_node.sort_method = mm.group(1).strip()
            current_node.sort_space_kb = int(mm.group(2))
        elif (mm := _RX_HEAP_BLOCKS.match(ln)):
            ex, lo = mm.group(1), mm.group(2)
            if ex: current_node.heap_blocks_exact = int(ex)
            if lo: current_node.heap_blocks_lossy = int(lo)

    if not parsed:
        raise ValueError("No node lines matched parser")

    # Build tree by indent stack
    # Root is the smallest-indent node
    parsed.sort(key=lambda t: 0)  # preserve order
    root = parsed[0][1]
    stack: list[tuple[int, PlanNode]] = [parsed[0]]
    for indent, node in parsed[1:]:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            # disconnected -- treat as new root (rare)
            stack.append((indent, node))
            continue
        parent = stack[-1][1]
        parent.children.append(node)
        stack.append((indent, node))

    return root


def walk(node: PlanNode):
    """Pre-order traversal."""
    yield node
    for c in node.children:
        yield from walk(c)
