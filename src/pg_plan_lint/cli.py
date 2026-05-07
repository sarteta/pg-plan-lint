"""pg-plan-lint CLI: read a plan file (or stdin) and print findings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .linter import lint


_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}


def _format_text(findings, source: str) -> str:
    if not findings:
        return f"{source}: clean -- 0 findings\n"
    lines = [f"{source}: {len(findings)} finding(s)"]
    for f in findings:
        lines.append(f"  [{f.severity.upper()}] {f.rule} -- {f.node_type}"
                     + (f" on '{f.relation}'" if f.relation else ""))
        lines.append(f"    {f.message}")
        lines.append(f"    suggestion: {f.suggestion}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="pg-plan-lint",
        description="Lint Postgres EXPLAIN ANALYZE plans for anti-patterns.",
    )
    p.add_argument("file", nargs="?", help="Plan file (JSON or text). '-' or omitted = stdin.")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--fail-on", choices=["critical", "warning", "info"],
                   default="warning",
                   help="Exit non-zero when any finding meets or exceeds this severity (default: warning)")
    args = p.parse_args(argv)

    if args.file is None or args.file == "-":
        plan_text = sys.stdin.read()
        source = "<stdin>"
    else:
        path = Path(args.file)
        if not path.exists():
            print(f"# error: {args.file} not found", file=sys.stderr)
            return 2
        plan_text = path.read_text(encoding="utf-8")
        source = str(path)

    try:
        findings = lint(plan_text)
    except Exception as e:
        print(f"# parse error: {e}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps({"source": source, "findings": [f.to_dict() for f in findings]}, indent=2))
    else:
        sys.stdout.write(_format_text(findings, source))

    threshold = _SEV_RANK[args.fail_on]
    if findings and min(_SEV_RANK[f.severity] for f in findings) <= threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
