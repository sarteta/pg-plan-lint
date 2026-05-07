"""Top-level lint API: parse + run rules + return findings sorted by severity."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .parser import parse_plan, walk, PlanNode
from .rules import RULES


@dataclass
class Finding:
    rule: str
    severity: str          # "critical" | "warning" | "info"
    node_type: str
    relation: str
    message: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}


def lint(plan_text: str) -> list[Finding]:
    """Parse a plan (JSON or text) and return all findings."""
    root = parse_plan(plan_text)
    findings: list[Finding] = []
    for node in walk(root):
        for rule in RULES:
            findings.extend(rule(node))
    findings.sort(key=lambda f: (_SEV_RANK.get(f.severity, 99), f.rule))
    return findings
