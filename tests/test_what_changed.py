from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from app.config import Settings
from app.repository import BigQueryWarehouseRepository
from app.what_changed import WhatChangedUnavailable, build_what_changed
from google.api_core.exceptions import NotFound


def game_rows():
    rows = []
    for game in range(8):
        for player, name, points in [
            (1, "Steady Star", 25),
            (2, "Rising Guard", 8 if game < 4 else 22),
        ]:
            rows.append(
                {
                    "player_id": player,
                    "player_name": name,
                    "game_id": f"game-{game}",
                    "season": "2025-26",
                    "season_type": "Regular Season",
                    "game_date": (
                        date(2026, 2, 1) + timedelta(days=2 * game)
                    ).isoformat(),
                    "team_abbr": "AAA",
                    "opponent_abbr": "BBB",
                    "min": 30,
                    "pts": points,
                    "reb": 6,
                    "oreb": 2,
                    "dreb": 4,
                    "ast": 5,
                    "stl": 1,
                    "blk": 1,
                    "tov": 2,
                    "pf": 2,
                    "fgm": 8,
                    "fga": 16,
                    "ftm": 4,
                    "fta": 5,
                    "fg3m": 1,
                    "fg3a": 3,
                    "ingested_at_utc": "2026-02-16T00:00:00Z",
                }
            )
    return rows


def player(result, player_id=1):
    return next(item for item in result["items"] if item["player_id"] == player_id)


def test_top_production_and_positive_surge_are_distinct():
    result = build_what_changed(game_rows(), [])
    star, rising = player(result), player(result, 2)
    assert star["top_rank"] == 1
    assert star["top_score"] == 36
    assert star["surge_score"] is None
    assert rising["surge_rank"] == 1
    assert rising["surge_score"] == 14
    assert star["current"]["games_played"] == star["previous"]["games_played"] == 4
    assert [cluster["key"] for cluster in star["clusters"]] == [
        "availability",
        "offense",
        "defense",
    ]
    json.dumps(result, allow_nan=False)


def test_missing_appearance_is_not_a_zero_stat_line_or_dnp_cd():
    rows = [
        row
        for row in game_rows()
        if not (row["player_id"] == 2 and row["game_id"] == "game-7")
    ]
    item = player(build_what_changed(rows, None), 2)
    assert item["current"]["team_games"] == 4
    assert item["current"]["games_played"] == 3
    assert item["current"]["no_recorded_appearance"] == 1
    assert item["current"]["values"]["pts"] == 22
    assert item["current"]["totals"]["pts"] == 66
    assert item["current"]["dnp_cd"] is None
    assert item["current"]["injuries"]["available"] is False
    assert item["current"]["games"][-1]["stats"]["pts"] is None


def test_shooting_percentages_weight_attempts_and_report_percentage_points():
    rows = game_rows()
    for row in rows:
        if row["player_id"] == 1 and int(row["game_id"][-1]) >= 4:
            row["fgm"], row["fga"] = (
                (1, 1) if int(row["game_id"][-1]) % 2 == 0 else (9, 18)
            )
    item = player(build_what_changed(rows, []))
    metric = next(
        metric for metric in item["clusters"][1]["metrics"] if metric["key"] == "fg_pct"
    )
    assert metric["current"] == 52.63
    assert metric["previous"] == 50
    assert metric["delta"] == 2.63
    assert metric["unit"] == "percent"


def test_null_stats_and_zero_attempts_stay_unknown():
    rows = game_rows()
    for row in rows:
        row.update(pf=None, fga=0, fgm=0, fta=0, ftm=0)
    current = player(build_what_changed(rows, []))["current"]
    assert current["values"]["pf"] is None
    assert current["values"]["fg_pct"] is None
    assert current["values"]["ts_pct"] is None


def test_small_samples_cannot_top_rank_or_surge():
    rows = [
        row
        for row in game_rows()
        if row["player_id"] == 1 or row["game_id"] not in {"game-6", "game-7"}
    ]
    item = player(build_what_changed(rows, []), 2)
    assert item["top_score"] is None
    assert item["surge_score"] is None


def test_missing_baseline_can_rank_top_but_not_surge():
    rows = [
        row
        for row in game_rows()
        if row["player_id"] == 1 or int(row["game_id"][-1]) >= 4
    ]
    item = player(build_what_changed(rows, []), 2)
    assert item["top_score"] is not None
    assert item["surge_score"] is None
    assert item["previous"]["games_played"] == 0


def test_corrected_duplicate_does_not_double_count_games():
    rows = game_rows()
    rows.append({**rows[-1], "pts": 26, "ingested_at_utc": "2026-02-17T00:00:00Z"})
    item = player(build_what_changed(rows, []), 2)
    assert item["current"]["games_played"] == 4
    assert item["current"]["values"]["pts"] == 23


def test_complete_calendar_weeks_are_disjoint_and_have_real_game_counts():
    result = build_what_changed(game_rows(), [], period="week")
    assert result["calendar_windows"] == {
        "current": {"start": "2026-02-09", "end": "2026-02-15"},
        "previous": {"start": "2026-02-02", "end": "2026-02-08"},
    }
    item = player(result)
    assert item["current"]["games_played"] == 4
    assert item["previous"]["games_played"] == 3
    early = build_what_changed(game_rows(), [], period="week", as_of="2026-02-13")
    assert early["calendar_windows"]["current"]["end"] == "2026-02-08"


def test_injury_reports_are_dated_evidence_not_confirmed_missed_games():
    report = {
        "player_id": 1,
        "team_abbr": "AAA",
        "game_date": "2026-02-15",
        "report_date": "2026-02-15",
        "report_timestamp_utc": "2026-02-15T18:00:00Z",
        "injury_status": "Out",
        "source_url": "https://example.com/report.pdf",
    }
    reports = [
        report,
        {
            **report,
            "report_date": "2026-02-16",
            "report_timestamp_utc": "2026-02-16T18:00:00Z",
            "injury_status": "Available",
        },
    ]
    current = player(build_what_changed(game_rows(), reports))["current"]
    assert current["injuries"]["games_covered"] == 1
    assert current["injuries"]["out_reports"] == 1
    assert current["games_played"] == 4
    assert current["no_recorded_appearance"] == 0


def test_trades_and_season_types_do_not_generate_artificial_surges():
    rows = game_rows()
    for row in rows:
        if row["player_id"] == 2 and row["game_id"] == "game-0":
            row["team_abbr"] = "CCC"
    result = build_what_changed(rows, [])
    assert player(result, 2)["team_changed"] is True
    assert player(result, 2)["surge_score"] is None
    assert build_what_changed(rows, [], season_type="Playoffs")["state"] == "empty"


def test_repository_uses_bounded_parameterized_game_read_and_optional_injuries():
    repo = BigQueryWarehouseRepository(
        Settings("demo", "gold", "metadata", 36, 12), client=object()
    )
    calls = []

    def query(sql, params):
        calls.append((sql, params))
        if len(calls) == 2:
            raise NotFound("optional table not yet published")
        return game_rows()

    repo._query = query
    result = repo.get_what_changed(as_of="2026-02-15")
    assert result["injury_source_available"] is False
    assert "INTERVAL 60 DAY" in calls[0][0]
    assert "LIMIT 20001" in calls[0][0]
    assert calls[0][1][-1].value == "2026-02-15"


def test_repository_rejects_truncated_league_rankings():
    repo = BigQueryWarehouseRepository(
        Settings("demo", "gold", "metadata", 36, 12), client=object()
    )
    repo._query = lambda *_: [{}] * 20001
    with pytest.raises(WhatChangedUnavailable, match="safety limit"):
        repo.get_what_changed()
