"""Validated candidates become visible together, or the previous data stays live."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from google.cloud import bigquery

logger = logging.getLogger("nba_pipeline")


def quoted_table(table_id: str) -> str:
    if not re.fullmatch(r"[\w-]+\.[\w]+\.[\w]+", table_id):
        raise ValueError(f"Invalid publication table identifier: {table_id!r}")
    return f"`{table_id}`"


def expire_candidate(client: Any, table_id: str) -> None:
    table = client.get_table(table_id)
    table.expires = datetime.now(UTC) + timedelta(days=1)
    client.update_table(table, ["expires"])


def publish_candidates(
    client: Any,
    candidates: list[tuple[str, str]],
    *,
    seasons: list[str] | None = None,
) -> None:
    """Publish prevalidated tables in one transaction; schema additions are additive.

    Load jobs and DDL cannot participate in this transaction. Candidates are
    created first and destination schemas are reconciled without removing rows.
    Any DML failure rolls back ALL serving-table changes. Expiring candidates
    also bounds cleanup after a lost connection or a worker crash.
    """
    statements = ["BEGIN TRANSACTION;"]
    for active_id, candidate_id in candidates:
        active_sql, candidate_sql = quoted_table(active_id), quoted_table(candidate_id)
        candidate = client.get_table(candidate_id)
        active = client.create_table(
            bigquery.Table(active_id, schema=candidate.schema), exists_ok=True
        )
        existing = {field.name: field for field in active.schema}
        additions = []
        for field in candidate.schema:
            if field.name not in existing:
                if field.mode != "NULLABLE":
                    raise ValueError(
                        "Publication only supports nullable schema additions"
                    )
                additions.append(field)
            elif existing[field.name].to_api_repr() != field.to_api_repr():
                # Descriptions may differ between dbt and Python schemas.
                old = existing[field.name]
                if (old.field_type, old.mode, old.fields) != (
                    field.field_type,
                    field.mode,
                    field.fields,
                ):
                    raise ValueError(f"Incompatible publication field: {field.name}")
        if additions:
            active.schema = [*active.schema, *additions]
            client.update_table(active, ["schema"])
        columns = ", ".join(f"`{field.name}`" for field in candidate.schema)
        predicate = "season IN UNNEST(@seasons)" if seasons is not None else "TRUE"
        statements.extend(
            [
                f"DELETE FROM {active_sql} WHERE {predicate};",
                f"INSERT INTO {active_sql} ({columns}) "
                f"SELECT {columns} FROM {candidate_sql};",
            ]
        )
    statements.append("COMMIT TRANSACTION;")
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("seasons", "STRING", seasons)]
        if seasons is not None
        else []
    )
    client.query("\n".join(statements), job_config=config).result()
    for _, candidate_id in candidates:
        try:
            client.delete_table(candidate_id, not_found_ok=True)
        except Exception:
            # A cleanup failure must not misreport an already committed publish.
            logger.warning("Candidate cleanup deferred to expiration", exc_info=True)
