from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

import nba_pipeline as pipeline
from optional_assets import optional_injury_stage, publication_details
from publication import publish_candidates


class PublicationClient:
    def __init__(self, fail_load=0, fail_commit=False):
        self.tables = {}
        self.events = []
        self.loads = 0
        self.fail_load = fail_load
        self.fail_commit = fail_commit
        self.sql = ""

    def create_table(self, table, **kwargs):
        self.events.append(("create", table.table_id))
        self.tables.setdefault(str(table.reference), deepcopy(table))
        return self.tables[str(table.reference)]

    def get_table(self, table_id):
        return self.tables[table_id]

    def update_table(self, table, fields):
        self.events.append(("update", fields))
        self.tables[str(table.reference)] = table
        return table

    def load_table_from_dataframe(self, frame, table_id, job_config):
        self.loads += 1
        self.events.append(("load", table_id))

        def result():
            if self.loads == self.fail_load:
                raise RuntimeError("load failed")
            self.events.append(("loaded", table_id))

        return SimpleNamespace(result=result)

    def query(self, sql, job_config):
        self.sql = sql
        self.events.append(("transaction", job_config))

        def result():
            if self.fail_commit:
                raise RuntimeError("transaction aborted")
            self.events.append(("committed", None))

        return SimpleNamespace(result=result)

    def delete_table(self, table_id, **kwargs):
        self.events.append(("cleanup", table_id))


def frames():
    return pd.DataFrame(
        [
            {
                "season": "2025-26",
                "player_id": 1,
                "archetype_id": "wing",
                "archetype_label": "Connector Wing",
            }
        ]
    )


def publish(client, feature_frame=None, archetype_frame=None):
    pipeline.write_player_similarity_tables(
        client,
        features_table_id="demo.gold.features",
        archetypes_table_id="demo.gold.archetypes",
        features_df=frames() if feature_frame is None else feature_frame,
        archetypes_df=frames() if archetype_frame is None else archetype_frame,
    )


def test_both_candidates_finish_loading_before_one_atomic_publication():
    client = PublicationClient()
    publish(client)
    events = [event for event, _ in client.events]
    assert events.count("transaction") == 1
    assert events.count("loaded") == 2
    assert max(i for i, event in enumerate(events) if event == "loaded") < events.index(
        "transaction"
    )
    assert events.index("committed") < events.index("cleanup")
    assert client.sql.startswith("BEGIN TRANSACTION;")
    assert client.sql.endswith("COMMIT TRANSACTION;")
    assert client.sql.count("DELETE FROM") == 2
    assert client.sql.count("INSERT INTO") == 2
    assert client.sql.count("season IN UNNEST(@seasons)") == 2
    assert all(
        table.expires for key, table in client.tables.items() if "candidate" in key
    )


@pytest.mark.parametrize("failed_load", [1, 2])
def test_failed_candidate_load_never_touches_serving_tables(failed_load):
    client = PublicationClient(fail_load=failed_load)
    with pytest.raises(RuntimeError, match="load failed"):
        publish(client)
    assert client.sql == ""
    assert all("candidate" in key for key in client.tables)


def test_aborted_transaction_is_reported_and_candidates_remain_for_diagnosis():
    client = PublicationClient(fail_commit=True)
    with pytest.raises(RuntimeError, match="transaction aborted"):
        publish(client)
    assert not any(event in {"committed", "cleanup"} for event, _ in client.events)


@pytest.mark.parametrize(
    "invalid", ["empty", "duplicate", "null_season", "different_players"]
)
def test_invalid_similarity_candidate_never_reaches_bigquery(invalid):
    client = PublicationClient()
    feature = frames()
    archetype = frames()
    if invalid == "empty":
        feature = feature.iloc[:0]
    elif invalid == "duplicate":
        feature = pd.concat([feature, feature])
    elif invalid == "null_season":
        feature["season"] = None
    else:
        archetype["player_id"] = 2
    with pytest.raises(ValueError):
        publish(client, feature, archetype)
    assert client.events == []


def test_additive_schema_migration_keeps_rows_until_transaction():
    client = PublicationClient()
    old = bigquery.SchemaField("season", "STRING")
    new = bigquery.SchemaField("new_metric", "FLOAT")
    client.create_table(bigquery.Table("demo.gold.live", schema=[old]))
    client.create_table(bigquery.Table("demo.gold.candidate", schema=[old, new]))
    publish_candidates(client, [("demo.gold.live", "demo.gold.candidate")])
    assert len(client.tables["demo.gold.live"].schema) == 2
    assert ("update", ["schema"]) in client.events
    assert "DELETE FROM `demo.gold.live` WHERE TRUE;" in client.sql


def test_optional_injury_failure_retries_then_short_circuits_downstream(monkeypatch):
    ti = SimpleNamespace(try_number=1, max_tries=2)
    monkeypatch.setitem(
        sys.modules,
        "airflow.operators.python",
        SimpleNamespace(get_current_context=lambda: {"ti": ti}),
    )

    @optional_injury_stage
    def broken_stage(previous):
        raise RuntimeError("upstream unavailable")

    previous = {"watermark_before": "2026-02-01", "watermark_after": "2026-02-03"}
    with pytest.raises(RuntimeError):
        broken_stage(previous)
    ti.try_number = 3
    failed = broken_stage(previous)
    assert failed["asset_status"] == "failed_non_blocking"
    assert failed["watermark_after"] == "2026-02-01"
    assert failed["rows_loaded"] == failed["row_count"] == 0

    @optional_injury_stage
    def downstream(_):
        pytest.fail("Failed injury data must never reach the next stage")

    assert downstream(failed) is failed


def test_run_log_reports_partial_success_without_changing_core_success():
    details = publication_details(
        {
            "dbt_status": "success",
            "core_warehouse_changed": True,
            "injury_status": "failed_non_blocking",
            "similarity_status": "success",
            "watermark_after": "2026-02-11",
        }
    )
    assert "publication_status=partially_updated;" in details
    assert "stats_status=success;" in details
    assert "injuries_status=failed_non_blocking;" in details
    assert "stats_source_date=2026-02-11;" in details
    assert "stats_status=no_change;" in publication_details({"dbt_status": "skipped"})
