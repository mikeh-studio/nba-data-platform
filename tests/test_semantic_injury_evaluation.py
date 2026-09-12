from app.agent.semantic_source import snapshot_digest
from scripts.evaluate_semantic_injuries import evaluate


def snapshot(times):
    rows = []
    for season, time in zip(("2023-24", "2024-25"), times):
        rows.append(
            {
                "season": season,
                "player_id": 1,
                "game_date": "2025-01-01",
                "game_time_et": time,
                "matchup": "AAA@BBB",
                "report_timestamp_utc": "2025-01-01 18:00:00+00:00",
                "injury_status": "Out",
                "reason": "fixture",
                "source_url": "https://example.test/report.pdf",
            }
        )
    result = {"rows": rows, "query_id": "fixture-job"}
    result["sha256"] = snapshot_digest(result)
    return result


def test_ambiguous_archive_times_remain_unverified():
    result = evaluate(snapshot(["07:30 (ET)", "03:00 (ET)"]))
    assert result["passed"] == result["total"] == 2
    assert result["verified_actual_tipoff_cases"] == 0
    assert all(c["actual"]["status"] == "unverified" for c in result["cases"])


def test_explicit_schedule_meridiem_supports_cutoff_comparison_not_actual_tipoff_claim():
    result = evaluate(snapshot(["07:30PM (ET)", "03:00PM (ET)"]))
    assert result["passed"] == result["total"] == 4
    assert result["verified_actual_tipoff_cases"] == 0
    assert result["cases"][0]["expected"]["status"] == "Out"
