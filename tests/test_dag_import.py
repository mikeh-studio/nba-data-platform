from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow_home_"))
airflow = pytest.importorskip("airflow")
from airflow.models import DagBag


def test_airflow_dag_parses_without_import_errors(tmp_path):
    dags_path = Path(__file__).resolve().parents[1] / "dags"
    dag_bag = DagBag(dag_folder=str(dags_path), include_examples=False)

    assert dag_bag.import_errors == {}
    assert "nba_analytics_pipeline" in dag_bag.dags


@pytest.mark.parametrize("core_code,injury_code", [(0, 0), (0, 1), (1, 0)])
def test_dbt_injury_candidates_cannot_block_or_replace_successful_core(
    monkeypatch, core_code, injury_code
):
    from google.cloud import bigquery

    import publication

    dag_bag = DagBag(
        dag_folder=str(Path(__file__).resolve().parents[1] / "dags"),
        include_examples=False,
    )
    function = (
        dag_bag.dags["nba_analytics_pipeline"].get_task("dbt_build").python_callable
    )
    scope = function.__globals__
    monkeypatch.setitem(
        scope,
        "get_config",
        lambda key, default=None: {"BQ_PROJECT": "demo"}.get(key, default),
    )
    monkeypatch.setattr(bigquery, "Client", lambda **kwargs: object())
    monkeypatch.setattr(publication, "expire_candidate", lambda *args: None)
    published = []
    monkeypatch.setattr(
        publication,
        "publish_candidates",
        lambda client, candidates: published.extend(candidates),
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=core_code if len(commands) == 1 else injury_code,
            stdout="",
            stderr="test failure",
        )

    monkeypatch.setattr(scope["subprocess"], "run", run)
    context = {
        "should_build": True,
        "core_warehouse_changed": True,
        "injury_report_rows_loaded": 4,
    }
    if core_code:
        with pytest.raises(Exception, match="test failure"):
            function(context)
        assert len(commands) == 1
        assert published == []
        return
    result = function(context)
    assert result["dbt_status"] == "success"
    assert commands[0][-1] == "stg_player_injury_reports_clean+"
    assert "--exclude" in commands[0]
    assert "--select" in commands[1]
    assert "--vars" in commands[1]
    if injury_code:
        assert result["injury_status"] == "failed_non_blocking"
        assert published == []
    else:
        assert result["injury_dbt_status"] == "success"
        assert len(published) == 4
        assert all(
            "_candidate_" in candidate and "_candidate_" not in active
            for active, candidate in published
        )
