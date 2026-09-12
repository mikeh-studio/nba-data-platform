#!/usr/bin/env python3
"""Run deterministic semantic contract fixtures; no warehouse or LLM calls."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.semantics import (  # noqa: E402
    CATALOG_PATH,
    Evidence,
    Query,
    SemanticError,
    load_contract,
    pregame_evidence,
    resolve_entity,
    run_query,
)

DEFAULT_FIXTURE = ROOT / "tests/fixtures/semantics/cases.json"


def evaluate(path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    content = path.read_bytes()
    fixture = json.loads(content)
    contract = load_contract()
    results = []
    for case in fixture["cases"]:
        rows = copy.deepcopy(fixture["rows"])
        for patch in case.get("patches", []):
            for row in rows:
                if row["game_id"] == patch["game_id"]:
                    row.update(patch["values"])
        if case.get("duplicate_game"):
            rows.append(
                next(r for r in rows if r["game_id"] == case["duplicate_game"]).copy()
            )
        evidence = Evidence(
            rows,
            frozenset((s, p) for s, p, _ in fixture["coverage"]),
            "synthetic/player_games",
            hashlib.sha256(content).hexdigest(),
            {(s, p): d for s, p, d in fixture["coverage"]},
            "2026-09-10T00:00:00Z",
            complete=True,
        )
        request = dict(case["request"])
        kind = request.pop("kind", "query")
        try:
            if kind == "entity":
                actual = resolve_entity(request["name"], fixture["players"])
                actual["matches_count"] = len(actual["matches"])
            elif kind == "injury":
                actual = pregame_evidence(fixture["reports"], **request)
            elif kind == "query":
                actual = run_query(evidence, Query(**request), contract)
                actual["rows_count"] = len(actual["rows"])
            else:
                raise ValueError(f"Unknown fixture kind: {kind}")
        except SemanticError as exc:
            actual = {"error": exc.code, "message": str(exc)}
        mismatches = []
        for key, expected in case["expect"].items():
            value: Any = actual
            try:
                for part in key.split("."):
                    value = value[int(part)] if isinstance(value, list) else value[part]
            except (KeyError, IndexError, TypeError):
                mismatches.append({"field": key, "expected": expected, "missing": True})
                continue
            equal = (
                math.isclose(value, expected, rel_tol=0, abs_tol=1e-6)
                if type(value) in (int, float) and type(expected) in (int, float)
                else value == expected
            )
            if not equal:
                mismatches.append({"field": key, "expected": expected, "actual": value})
        results.append(
            {
                "id": case["id"],
                "passed": not mismatches,
                "mismatches": mismatches,
                "actual": actual,
            }
        )
    return {
        "contract_version": contract.version,
        "evidence_kind": fixture["evidence_kind"],
        "fixture_sha256": hashlib.sha256(content).hexdigest(),
        "contract_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "human_reviewed": fixture["human_reviewed"],
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "historical_reference_cases": 0,
        "llm_runs": 0,
        "limitations": [
            "Deterministic fixture checks, not end-to-end Ask accuracy.",
            "These cases cover parts of each proposal family, not every release criterion.",
        ],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.fixture)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
