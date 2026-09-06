"""Deterministic, dated league movers over consecutive team-game windows."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from math import isfinite
from typing import Any, Literal

ComparisonPeriod = Literal["four_games", "week"]
SeasonPhase = Literal["Regular Season", "Playoffs"]


class WhatChangedUnavailable(RuntimeError):
    """The bounded source read cannot safely produce a complete league ranking."""


METRICS = {
    "availability": [("min", "Minutes / appearance"), ("pf", "Fouls / appearance")],
    "offense": [
        ("pts", "Points"),
        ("ast", "Assists"),
        ("fg3m", "Made threes"),
        ("oreb", "Offensive rebounds"),
        ("tov", "Turnovers"),
        ("fg_pct", "FG%"),
        ("ft_pct", "FT%"),
        ("ts_pct", "TS%"),
    ],
    "defense": [("dreb", "Defensive rebounds"), ("stl", "Steals"), ("blk", "Blocks")],
}
COUNTING = {
    "min",
    "pf",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fg3m",
    "oreb",
    "dreb",
    "fgm",
    "fga",
    "ftm",
    "fta",
    "fg3a",
}
PRODUCTION = ("pts", "reb", "ast", "stl", "blk", "tov")


def _date(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _rounded(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _aggregate(rows: list[dict]) -> dict:
    played = [row for row in rows if (_number(row.get("min")) or 0) > 0]
    totals: dict[str, float | None] = {}
    for key in COUNTING:
        observations = [_number(row.get(key)) for row in played]
        totals[key] = (
            sum(value for value in observations if value is not None)
            if observations and all(value is not None for value in observations)
            else None
        )
    values = {
        key: total / len(played) if total is not None and played else None
        for key, total in totals.items()
    }
    for key, made, attempted in [("fg_pct", "fgm", "fga"), ("ft_pct", "ftm", "fta")]:
        numerator, denominator = totals[made], totals[attempted]
        values[key] = (
            100 * numerator / denominator
            if numerator is not None and denominator
            else None
        )
    pts, fga, fta = totals["pts"], totals["fga"], totals["fta"]
    attempts = (fga + 0.44 * fta) if fga is not None and fta is not None else None
    values["ts_pct"] = (
        100 * pts / (2 * attempts) if pts is not None and attempts else None
    )
    production = (
        sum(float(values[key] or 0) * (-1 if key == "tov" else 1) for key in PRODUCTION)
        if all(values[key] is not None for key in PRODUCTION)
        else None
    )
    return {
        "games_played": len(played),
        "values": values,
        "totals": totals,
        "production": production,
    }


def _metric(key: str, label: str, current: dict, previous: dict) -> dict:
    value, prior = current["values"].get(key), previous["values"].get(key)
    return {
        "key": key,
        "label": label,
        "unit": "percent" if key.endswith("pct") else "count",
        "current": _rounded(value),
        "previous": _rounded(prior),
        "delta": _rounded(value - prior)
        if value is not None and prior is not None
        else None,
        "current_total": _rounded(current["totals"].get(key)),
        "previous_total": _rounded(previous["totals"].get(key)),
        "lower_is_better": key in {"tov", "pf"},
    }


def _injuries(
    player_id: int,
    team: str,
    games: list[dict],
    reports: list[dict] | None,
    as_of: date,
) -> dict:
    if reports is None:
        return {
            "available": False,
            "games_covered": 0,
            "out_reports": None,
            "reports": [],
        }
    game_dates = {game["game_date"] for game in games}
    latest: dict[str, dict] = {}
    for row in reports:
        if row.get("player_id") != player_id or row.get("team_abbr") != team:
            continue
        game_date = str(row.get("game_date", ""))[:10]
        report_date = str(row.get("report_date", ""))[:10]
        # A report is evidence of a reported status, never proof of a missed game.
        if (
            game_date not in game_dates
            or not report_date
            or report_date > min(game_date, as_of.isoformat())
        ):
            continue
        stamp = str(row.get("report_timestamp_utc") or report_date)
        if stamp[:10] > as_of.isoformat():
            continue
        if game_date not in latest or stamp > str(
            latest[game_date].get("report_timestamp_utc")
            or latest[game_date].get("report_date")
        ):
            latest[game_date] = row
    selected = [latest[key] for key in sorted(latest)]
    return {
        "available": True,
        "games_covered": len(selected),
        "out_reports": sum(row.get("injury_status") == "Out" for row in selected)
        if selected
        else None,
        "reports": [
            {
                key: row.get(key)
                for key in [
                    "game_date",
                    "report_date",
                    "report_timestamp_utc",
                    "injury_status",
                    "reason",
                    "source_url",
                ]
            }
            for row in selected
        ],
    }


def _window(
    games: list[dict],
    rows: list[dict],
    player_id: int,
    team: str,
    reports: list[dict] | None,
    as_of: date,
) -> dict:
    by_game = {row["game_id"]: row for row in rows if row.get("team_abbr") == team}
    selected = [
        by_game[game["game_id"]] for game in games if game["game_id"] in by_game
    ]
    result = _aggregate(selected)
    result.update(
        {
            "team_games": len(games),
            "start_date": min((game["game_date"] for game in games), default=None),
            "end_date": max((game["game_date"] for game in games), default=None),
            "no_recorded_appearance": len(games) - result["games_played"],
            "dnp_cd": None,
            "injuries": _injuries(player_id, team, games, reports, as_of),
            "games": [
                {
                    **game,
                    "played": (
                        _number(by_game.get(game["game_id"], {}).get("min")) or 0
                    )
                    > 0,
                    "stats": {
                        key: _number(by_game.get(game["game_id"], {}).get(key))
                        for key in [
                            "min",
                            "pts",
                            "reb",
                            "ast",
                            "stl",
                            "blk",
                            "tov",
                            "pf",
                        ]
                    },
                }
                for game in sorted(
                    games, key=lambda game: (game["game_date"], game["game_id"])
                )
            ],
        }
    )
    return result


def build_what_changed(
    game_rows: list[dict],
    injury_rows: list[dict] | None,
    *,
    period: ComparisonPeriod = "four_games",
    season_type: SeasonPhase = "Regular Season",
    as_of: str | None = None,
) -> dict[str, Any]:
    if period not in {"four_games", "week"} or season_type not in {
        "Regular Season",
        "Playoffs",
    }:
        raise ValueError("Unsupported comparison window or season type")
    requested = _date(as_of) if as_of else None
    # Corrections are deduplicated before either game counting or aggregation.
    deduped: dict[tuple[int, str], dict] = {}
    for row in sorted(game_rows, key=lambda row: str(row.get("ingested_at_utc") or "")):
        if (
            row.get("season_type") != season_type
            or not row.get("game_id")
            or not row.get("player_id")
        ):
            continue
        if requested and _date(row["game_date"]) > requested:
            continue
        deduped[(int(row["player_id"]), str(row["game_id"]))] = {
            **row,
            "game_id": str(row["game_id"]),
            "game_date": _date(row["game_date"]).isoformat(),
        }
    rows = list(deduped.values())
    data_through = max((_date(row["game_date"]) for row in rows), default=None)
    payload: dict[str, Any] = {
        "period": period,
        "season_type": season_type,
        "data_through": data_through.isoformat() if data_through else None,
        "requested_as_of": as_of,
        "window_basis": "team_games",
        "items": [],
        "injury_source_available": injury_rows is not None,
        "dnp_cd_available": False,
        "ranking": {
            "formula": "PTS + REB + AST + STL + BLK − TOV per recorded appearance",
            "top": "Highest recent production index",
            "surging": "Largest positive change from the previous window",
            "minimum_games": 3 if period == "four_games" else 2,
            "minimum_minutes_per_appearance": 10,
            "note": "A transparent box-score proxy, not your fantasy league's scoring or an all-around player rating.",
        },
    }
    if data_through is None:
        payload["state"] = "empty"
        return payload
    anchor = min(requested, data_through) if requested else data_through
    if period == "week":
        # Compare two complete Monday–Sunday weeks anchored to available data.
        end = (
            anchor
            if anchor.weekday() == 6
            else anchor - timedelta(days=anchor.weekday() + 1)
        )
        current_start, previous_start = (
            end - timedelta(days=6),
            end - timedelta(days=13),
        )
        payload["calendar_windows"] = {
            "current": {"start": current_start.isoformat(), "end": end.isoformat()},
            "previous": {
                "start": previous_start.isoformat(),
                "end": (current_start - timedelta(days=1)).isoformat(),
            },
        }
        anchor = end
    payload["as_of"] = anchor.isoformat()
    rows = [row for row in rows if _date(row["game_date"]) <= anchor]
    teams: dict[str, dict[str, dict]] = defaultdict(dict)
    players: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        team, opponent = row.get("team_abbr"), row.get("opponent_abbr")
        if not team:
            continue
        players[int(row["player_id"])].append(row)
        for team_key, other in [(team, opponent), (opponent, team)]:
            if team_key:
                teams[team_key][row["game_id"]] = {
                    "game_id": row["game_id"],
                    "game_date": row["game_date"],
                    "opponent": other,
                }
    for player_id, history in players.items():
        latest = max(history, key=lambda row: (row["game_date"], row["game_id"]))
        team = latest["team_abbr"]
        team_games = sorted(
            teams[team].values(),
            key=lambda game: (game["game_date"], game["game_id"]),
            reverse=True,
        )
        if not team_games or _date(team_games[0]["game_date"]) < anchor - timedelta(
            days=6
        ):
            continue  # Do not present eliminated/inactive teams as current movers.
        if period == "four_games":
            current_games, previous_games = team_games[:4], team_games[4:8]
        else:
            current_games = [
                game
                for game in team_games
                if current_start <= _date(game["game_date"]) <= anchor
            ]
            previous_games = [
                game
                for game in team_games
                if previous_start <= _date(game["game_date"]) < current_start
            ]
        current = _window(current_games, history, player_id, team, injury_rows, anchor)
        previous = _window(
            previous_games, history, player_id, team, injury_rows, anchor
        )
        minimum = payload["ranking"]["minimum_games"]
        top_eligible = (
            current["games_played"] >= minimum
            and (current["values"]["min"] or 0) >= 10
            and current["production"] is not None
        )
        if period == "four_games":
            top_eligible = top_eligible and current["team_games"] == 4
        comparison_start = previous["start_date"] or current["start_date"]
        team_changed = (
            any(
                row["team_abbr"] != team and row["game_date"] >= comparison_start
                for row in history
            )
            if comparison_start
            else False
        )
        surge_eligible = (
            top_eligible
            and previous["games_played"] >= minimum
            and previous["production"] is not None
            and not team_changed
        )
        if period == "four_games":
            surge_eligible = surge_eligible and previous["team_games"] == 4
        delta = (
            current["production"] - previous["production"]
            if current["production"] is not None and previous["production"] is not None
            else None
        )
        clusters = [
            {
                "key": key,
                "label": {
                    "availability": "Playing availability",
                    "offense": "Offense",
                    "defense": "Defense",
                }[key],
                "metrics": [
                    _metric(stat, label, current, previous) for stat, label in metrics
                ],
            }
            for key, metrics in METRICS.items()
        ]
        payload["items"].append(
            {
                "player_id": player_id,
                "player_name": latest["player_name"],
                "team_abbr": team,
                "current": current,
                "previous": previous,
                "clusters": clusters,
                "top_score": _rounded(current["production"]) if top_eligible else None,
                "surge_score": _rounded(delta)
                if surge_eligible and delta is not None and delta > 0
                else None,
                "production_delta": _rounded(delta),
                "team_changed": team_changed,
                "sample_note": "Team changed within the comparison; surge ranking excluded."
                if team_changed
                else "Limited comparison sample."
                if not surge_eligible
                else "Small descriptive sample; not a forecast.",
            }
        )
    payload["items"].sort(
        key=lambda item: (
            -(item["top_score"] if item["top_score"] is not None else float("-inf")),
            item["player_id"],
        )
    )
    for score, rank_key in [("top_score", "top_rank"), ("surge_score", "surge_rank")]:
        eligible = sorted(
            (item for item in payload["items"] if item[score] is not None),
            key=lambda item: (-item[score], item["player_id"]),
        )
        for rank, item in enumerate(eligible, 1):
            item[rank_key] = rank
    payload["state"] = "ready" if payload["items"] else "empty"
    return payload
