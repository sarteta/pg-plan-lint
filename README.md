# pg-plan-lint

[![tests](https://github.com/sarteta/pg-plan-lint/actions/workflows/tests.yml/badge.svg)](https://github.com/sarteta/pg-plan-lint/actions/workflows/tests.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) ![Python](https://img.shields.io/badge/python-3.10%2B-blue)

Reads a Postgres `EXPLAIN ANALYZE` plan and tells you what's wrong with
it. Supports both JSON (`EXPLAIN (ANALYZE, FORMAT JSON)`) and the
default text format.

```bash
pip install pg-plan-lint
pg-plan-lint plan.json
```

Exit code is non-zero when at least one finding meets `--fail-on`
severity (default: `warning`). Use it in CI to gate slow queries.

## Anti-patterns it flags

```
P001  Seq Scan with Filter on a table > 10k rows  (likely missing index)
P002  Hash Batches > 1                            (work_mem too small, hash spilled)
P003  Sort Method = external merge Disk           (work_mem too small, sort spilled)
P004  Bitmap Heap Scan with lossy heap blocks     (work_mem too small for bitmap)
P005  Nested Loop with > 1000 outer rows          (wrong join strategy)
P006  Plan rows off by > 10x vs actual            (planner stats are stale)
P007  Index Scan filtering out > 50% post-match   (missing covering index)
```

Each finding includes the suggested fix (add an index, raise work_mem,
re-ANALYZE the table, etc.).

## Example

Input plan (a Seq Scan reading 1.2M rows to return 12):

```json
[{ "Plan": {
  "Node Type": "Seq Scan",
  "Relation Name": "events",
  "Plan Rows": 50000, "Actual Rows": 12,
  "Filter": "(user_id = 12345 AND ts > '2026-04-01'::timestamp)",
  "Rows Removed by Filter": 1199988 } }]
```

Output:

```
plan.json: 2 finding(s)
  [WARNING] P001 -- Seq Scan on 'events'
    Seq Scan with Filter on 'events' reading 1,200,000 rows. Likely missing an index.
    suggestion: Add an index that covers the Filter predicate: (user_id = 12345 AND ts > '2026-04-01'::timestamp)
  [INFO] P006 -- Seq Scan on 'events'
    Planner overestimated rows for Seq Scan on events: estimated 50,000, actual 12 (0.0x).
    suggestion: Run ANALYZE on the table or increase its statistics target ...
```

## How the parser works

The JSON path is a straight tree walk over the `Plans` arrays. The text
path is regex-based: it locates each node line by the
`(cost=... rows=... width=...)` signature, then attaches detail lines
(`Filter:`, `Sort Method:`, `Buckets:`, `Heap Blocks:`) to the most
recent node. Nodes are parented by indent level. The parser does not
attempt to interpret PL/pgSQL or `CTE Scan` nesting beyond what
EXPLAIN already shows.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

Fixtures cover four real-shape plans (seq scan with filter, hash join
that spills, nested loop with 50k outer rows, sort that spills to
disk) plus a clean index scan that should produce zero findings.

## Sibling repos

- [`postgres-tuning-cookbook`](https://github.com/sarteta/postgres-tuning-cookbook) -- ranks queries by cost; this repo analyzes the plan of any one of them
- [`postgres-incident-toolkit`](https://github.com/sarteta/postgres-incident-toolkit) -- live incident detection
- [`postgres-migration-safety`](https://github.com/sarteta/postgres-migration-safety) -- lint migrations before they hit prod
- [`postgres-production-playbook`](https://github.com/sarteta/postgres-production-playbook) -- diagnostic SQL keyed to symptom

MIT (c) 2026 Santiago Arteta
