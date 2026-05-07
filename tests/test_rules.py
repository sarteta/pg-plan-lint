"""Test each anti-pattern rule fires on its fixture and stays silent on a clean plan."""
from pathlib import Path
from pg_plan_lint import lint

FIX = Path(__file__).parent / "fixtures"


def codes(plan_text: str) -> list[str]:
    return [f.rule for f in lint(plan_text)]


def test_p001_seq_scan_filter_fires():
    out = codes((FIX / "seq_scan_filter.json").read_text())
    assert "P001" in out  # seq scan with filter on big table


def test_p002_hash_spill_fires():
    out = codes((FIX / "hash_spill.json").read_text())
    assert "P002" in out  # hash spilled (8 batches)


def test_p003_sort_disk_fires():
    out = codes((FIX / "sort_disk.txt").read_text())
    assert "P003" in out  # sort spilled to disk


def test_p005_nested_loop_heavy_fires():
    out = codes((FIX / "nested_loop_heavy.json").read_text())
    assert "P005" in out  # nested loop with 50k outer rows


def test_p006_estimate_skew_fires_on_nested_loop():
    out = codes((FIX / "nested_loop_heavy.json").read_text())
    # plan_rows=100, actual_rows=50000 -> 500x skew
    assert "P006" in out


def test_clean_plan_produces_no_findings():
    out = codes((FIX / "clean_index_scan.json").read_text())
    assert out == []


def test_findings_have_severity_and_suggestion():
    findings = lint((FIX / "seq_scan_filter.json").read_text())
    for f in findings:
        assert f.severity in {"critical", "warning", "info"}
        assert f.suggestion  # non-empty
