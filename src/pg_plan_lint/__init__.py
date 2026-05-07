"""pg-plan-lint: scan Postgres EXPLAIN ANALYZE plans for anti-patterns."""
from .parser import parse_plan, PlanNode
from .linter import lint, Finding
from .rules import RULES

__all__ = ["parse_plan", "PlanNode", "lint", "Finding", "RULES"]
__version__ = "0.1.0"
