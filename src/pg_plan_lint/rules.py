"""Anti-pattern rules.

Each rule is a function that takes a PlanNode and yields Finding(s) for
that node only. The linter walks the tree and runs every rule on every
node.

Codes:
  P001  Seq Scan with Filter on a table with > 10k rows -> probable missing index
  P002  Hash Batches > 1 -> hash spilled to disk, work_mem too small
  P003  Sort Method 'external merge Disk' -> sort spilled to disk
  P004  Bitmap Heap Scan with non-zero lossy heap blocks -> work_mem too small for bitmap
  P005  Nested Loop with > 1000 outer rows -> probably wrong join strategy
  P006  Plan-row estimate skew -- actual > 10x or < 0.1x predicted -> ANALYZE may be stale
  P007  Index Scan that returns + then filters out > 50% of rows -> missing covering index
  P008  Sort node with no LIMIT below it -> may be sorting more than needed
"""
from __future__ import annotations

from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .linter import Finding
    from .parser import PlanNode


def _make(rule, severity, node: "PlanNode", message, suggestion) -> "Finding":
    from .linter import Finding
    return Finding(
        rule=rule, severity=severity, node_type=node.node_type,
        relation=node.relation or node.alias or "",
        message=message, suggestion=suggestion,
    )


def rule_seq_scan_filter(node: "PlanNode") -> Iterable["Finding"]:
    if node.node_type != "Seq Scan":
        return
    if not node.filter:
        return
    rows_seen = (node.plan_rows or 0)
    if node.actual_rows is not None:
        rows_seen = max(rows_seen, node.actual_rows + (node.rows_removed_by_filter or 0))
    if rows_seen >= 10_000:
        yield _make(
            "P001", "warning", node,
            f"Seq Scan with Filter on '{node.relation or node.alias}' "
            f"reading {rows_seen:,} rows. Likely missing an index.",
            f"Add an index that covers the Filter predicate: {node.filter}",
        )


def rule_hash_spill(node: "PlanNode") -> Iterable["Finding"]:
    if node.node_type != "Hash":
        return
    if (node.hash_batches or 0) > 1:
        yield _make(
            "P002", "warning", node,
            f"Hash Batches = {node.hash_batches} -- the hash spilled to disk.",
            "Increase work_mem for this query (SET LOCAL work_mem = '128MB';) "
            "or reduce the build-side row count with a more selective filter.",
        )


def rule_sort_disk(node: "PlanNode") -> Iterable["Finding"]:
    if node.node_type != "Sort":
        return
    if node.sort_method and "disk" in node.sort_method.lower():
        yield _make(
            "P003", "warning", node,
            f"Sort spilled to disk (method: {node.sort_method}, "
            f"size: {node.sort_space_kb}kB).",
            "Increase work_mem (SET LOCAL work_mem = ...) or add a "
            "matching index so the planner can stream sorted output.",
        )


def rule_bitmap_lossy(node: "PlanNode") -> Iterable["Finding"]:
    if node.node_type != "Bitmap Heap Scan":
        return
    if (node.heap_blocks_lossy or 0) > 0:
        yield _make(
            "P004", "warning", node,
            f"Bitmap Heap Scan has {node.heap_blocks_lossy} lossy heap blocks "
            "-- the bitmap exceeded work_mem and re-checked individual pages.",
            "Increase work_mem for this query, or narrow the index condition "
            "so fewer pages are flagged.",
        )


def rule_nested_loop_heavy(node: "PlanNode") -> Iterable["Finding"]:
    if node.node_type != "Nested Loop":
        return
    if not node.children:
        return
    outer = node.children[0]
    outer_rows = outer.actual_rows or outer.plan_rows or 0
    if outer.actual_loops and outer.actual_loops > 1:
        outer_rows *= outer.actual_loops
    if outer_rows > 1000:
        yield _make(
            "P005", "warning", node,
            f"Nested Loop with {outer_rows:,} outer rows -- inner side will "
            "be re-evaluated that many times.",
            "Either ensure the inner side is an Index Scan keyed on the join "
            "column, or increase enable_hashjoin/enable_mergejoin for this "
            "query so the planner picks Hash/Merge.",
        )


def rule_estimate_skew(node: "PlanNode") -> Iterable["Finding"]:
    skew = node.estimate_skew
    if skew is None:
        return
    if skew > 10 or skew < 0.1:
        direction = "underestimated" if skew > 1 else "overestimated"
        yield _make(
            "P006", "info", node,
            f"Planner {direction} rows for {node.node_type}"
            f"{' on ' + node.relation if node.relation else ''}"
            f": estimated {node.plan_rows:,}, actual {int(node.actual_rows * (node.actual_loops or 1)):,} "
            f"({skew:.1f}x).",
            "Run ANALYZE on the table or increase its statistics target for "
            "the columns the planner is misjudging "
            "(ALTER TABLE ... ALTER COLUMN ... SET STATISTICS 1000;).",
        )


def rule_index_scan_high_filter(node: "PlanNode") -> Iterable["Finding"]:
    if node.node_type not in ("Index Scan", "Index Only Scan"):
        return
    removed = node.rows_removed_by_filter or 0
    kept = node.actual_rows or 0
    total = removed + kept
    if total < 1000:
        return
    if removed > kept and kept > 0:  # filtered out > 50%
        yield _make(
            "P007", "info", node,
            f"Index Scan on '{node.relation}' filtered out {removed:,} of "
            f"{total:,} rows after the index match -- the index isn't selective enough.",
            "Add columns from the Filter predicate to the index, or create "
            "a partial/expression index that covers both the Index Cond and "
            "the post-filter predicate.",
        )


RULES = [
    rule_seq_scan_filter,
    rule_hash_spill,
    rule_sort_disk,
    rule_bitmap_lossy,
    rule_nested_loop_heavy,
    rule_estimate_skew,
    rule_index_scan_high_filter,
]
