#!/usr/bin/env python3
"""Capture a bounded read-only historical fact snapshot for offline evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.semantic_source import BigQuerySemanticSource  # noqa: E402
from app.agent.semantics import SemanticError  # noqa: E402


def main() -> int:
    from google.cloud import bigquery

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--seasons", nargs="+", required=True)
    parser.add_argument("--gold-dataset", default="nba_gold")
    parser.add_argument("--maximum-bytes-billed", type=int, default=100_000_000)
    parser.add_argument("--max-rows", type=int, default=100_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Snapshot exists; choose a new path to preserve frozen evidence")
    try:
        snapshot = BigQuerySemanticSource(
            bigquery.Client(project=args.project),
            project=args.project,
            gold_dataset=args.gold_dataset,
            max_rows=args.max_rows,
            maximum_bytes_billed=args.maximum_bytes_billed,
        ).capture(args.seasons)
    except SemanticError as exc:
        print(json.dumps({"status": exc.code, "message": str(exc)}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(snapshot, indent=2) + "\n")
    print(
        json.dumps(
            {
                "snapshot_sha256": snapshot["sha256"],
                "rows": len(snapshot["rows"]),
                "coverage": snapshot["coverage"],
                "capture": snapshot["capture"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
