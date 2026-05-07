"""Test parser handles JSON and text plans, builds correct trees."""
from pathlib import Path
from pg_plan_lint import parse_plan
from pg_plan_lint.parser import walk

FIX = Path(__file__).parent / "fixtures"


def test_parse_seq_scan_json():
    p = parse_plan((FIX / "seq_scan_filter.json").read_text())
    assert p.node_type == "Seq Scan"
    assert p.relation == "events"
    assert p.plan_rows == 50000
    assert p.actual_rows == 12
    assert p.rows_removed_by_filter == 1199988
    assert "user_id" in (p.filter or "")


def test_parse_hash_spill_tree():
    p = parse_plan((FIX / "hash_spill.json").read_text())
    assert p.node_type == "Hash Join"
    assert len(p.children) == 2
    hash_node = next((c for c in p.children if c.node_type == "Hash"), None)
    assert hash_node is not None
    assert hash_node.hash_batches == 8


def test_parse_nested_loop_tree():
    p = parse_plan((FIX / "nested_loop_heavy.json").read_text())
    assert p.node_type == "Nested Loop"
    outer, inner = p.children
    assert outer.node_type == "Seq Scan"
    assert inner.node_type == "Index Scan"
    assert inner.actual_loops == 50000


def test_parse_text_sort_disk():
    p = parse_plan((FIX / "sort_disk.txt").read_text())
    assert p.node_type == "Sort"
    assert p.sort_method and "external" in p.sort_method.lower()
    assert p.sort_space_kb == 28456
    # children
    assert any(c.node_type == "Seq Scan" for c in p.children)


def test_walk_visits_all_nodes():
    p = parse_plan((FIX / "hash_spill.json").read_text())
    types = [n.node_type for n in walk(p)]
    assert types.count("Seq Scan") == 2
    assert "Hash Join" in types
    assert "Hash" in types
