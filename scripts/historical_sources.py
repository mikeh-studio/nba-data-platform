"""Source adapters for historical formats that differ from the current feed."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests
from nba_api.stats.endpoints import boxscoresummaryv2

import nba_pipeline as pipeline


def report_time_from_header(text: str, day: str) -> str:
    header = re.search(
        r"Injury\s+Report:\s*(\d{2}/\d{2}/\d{2,4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)",
        text,
        re.I,
    )
    if header is None or pd.to_datetime(header[1]).date().isoformat() != day:
        raise ValueError("Unexpected PDF report date/header")
    return f"{header[2].zfill(2)}_{header[3]}{header[4].upper()}"


def extract_injuries(season: str, directory: Path) -> None:
    output = directory / f"{season}_injuries.parquet"
    if output.exists():
        return
    logs = pd.concat(
        [
            pd.read_parquet(directory / f"{season}_{phase}_players.parquet")
            for phase in ("Regular_Season", "Playoffs")
        ]
    )
    start = pd.to_datetime(logs.GAME_DATE).min().date() - timedelta(days=1)
    end = pd.to_datetime(logs.GAME_DATE).max().date()
    dates = pd.date_range(start, end).strftime("%Y-%m-%d").tolist()
    cache = directory / "injury_reports_v2" / season
    cache.mkdir(parents=True, exist_ok=True)
    lookup = pipeline.build_player_id_lookup()

    def read(day):
        path = cache / f"{day}.parquet"
        evidence = cache / f"{day}.json"
        if path.exists() and evidence.exists():
            return pd.read_parquet(path), json.loads(evidence.read_text())
        url = f"{pipeline.OFFICIAL_INJURY_REPORT_BASE_URL}/Injury-Report_{day}_05PM.pdf"
        frame = pd.DataFrame(
            columns=[field.name for field in pipeline.get_injury_report_schema()]
        )
        result = {"date": day, "url": url}
        for attempt in range(3):
            response = None
            try:
                response = requests.get(
                    url, headers=pipeline.OFFICIAL_INJURY_REPORT_HEADERS, timeout=20
                )
                result = {"date": day, "url": url, "status": response.status_code}
                if response.status_code in (403, 404):
                    break
                response.raise_for_status()
                text = pipeline.extract_text_from_injury_report_pdf(response.content)
                report_time = report_time_from_header(text, day)
                result["report_time_et"] = report_time
                frame = pipeline.parse_injury_report_text(
                    text,
                    report_date=day,
                    report_time_et=report_time,
                    source_url=url,
                    season=season,
                    player_lookup=lookup,
                )
                break
            except Exception as exc:
                result = {
                    "date": day,
                    "url": url,
                    "status": "error",
                    "http_status": response.status_code
                    if response is not None
                    else None,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "attempts": attempt + 1,
                }
                # Retry transport/HTTP failures, but a malformed PDF or wrong
                # report header will not improve by parsing it again.
                if not isinstance(exc, requests.RequestException) or attempt == 2:
                    break
                time.sleep(2)
        result["rows"] = len(frame)
        # Failed days retain evidence but no reusable data cache. Removing the
        # combined season output allows a retry to revisit only failed days.
        if result["status"] != "error":
            frame.to_parquet(path, index=False)
        evidence.write_text(json.dumps(result, indent=2))
        return frame, result

    frames = []
    checks = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index, (frame, result) in enumerate(pool.map(read, dates), 1):
            if not frame.empty:
                frames.append(frame)
            checks.append(result)
            if index % 30 == 0:
                print(f"{season}: checked {index}/{len(dates)} injury PDFs", flush=True)
    combined = (
        pd.concat(frames, ignore_index=True).drop_duplicates()
        if frames
        else pd.DataFrame(columns=[f.name for f in pipeline.get_injury_report_schema()])
    )
    combined.to_parquet(output, index=False)
    (directory / f"{season}_injury_source_checks.json").write_text(
        json.dumps(checks, indent=2)
    )
    print(
        f"{season}: {len(combined)} injury rows from {sum(c['status'] == 200 for c in checks)} reports",
        flush=True,
    )


def resolve_neutral_schedule(
    season: str, schedule: pd.DataFrame, directory: Path
) -> pd.DataFrame:
    ambiguous = (
        schedule.groupby("GAME_ID")
        .HOME_AWAY.nunique()
        .loc[lambda n: n != 2]
        .index.tolist()
    )
    if not ambiguous:
        return schedule
    path = directory / f"{season}_game_context.json"
    records = json.loads(path.read_text()) if path.exists() else []
    by_game = {row["GAME_ID"]: row for row in records}
    for game_id in ambiguous:
        if game_id in by_game:
            continue
        endpoint = boxscoresummaryv2.BoxScoreSummaryV2(game_id=game_id, timeout=20)
        summary = endpoint.game_summary.get_data_frame()
        if summary.empty:
            raise ValueError(f"Missing official game context for {game_id}")
        record = (
            summary[["GAME_ID", "HOME_TEAM_ID", "VISITOR_TEAM_ID"]].iloc[0].to_dict()
        )
        if record["GAME_ID"] != game_id:
            raise ValueError("Game context ID mismatch")
        by_game[game_id] = record
        path.write_text(json.dumps(list(by_game.values()), indent=2))
    abbr_by_id = {row["team_id"]: row["team_abbr"] for row in pipeline.NBA_TEAM_LOOKUP}
    output = schedule.copy()
    for game_id in ambiguous:
        record = by_game[game_id]
        home = abbr_by_id[int(record["HOME_TEAM_ID"])]
        away = abbr_by_id[int(record["VISITOR_TEAM_ID"])]
        mask = output.GAME_ID.eq(game_id)
        if home == away or set(output.loc[mask, "TEAM_ABBR"]) != {home, away}:
            raise ValueError("Official game context does not match observed teams")
        output.loc[mask, "HOME_AWAY"] = output.loc[mask, "TEAM_ABBR"].map(
            {home: "HOME", away: "AWAY"}
        )
    return output


def resolve_injury_names(
    frame: pd.DataFrame, logs: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    """Match unambiguous historical names; retain original parsed source text.

    Suffix differences (Jr./III) and punctuation changed between seasons. A
    wrapped preceding reason can also precede a valid Last, First suffix.
    Never choose between different IDs with the same normalized full name.
    """

    def key(name):
        return pipeline.normalize_player_name_key(name).replace(" ", "")

    known = {}
    rows = [(row["id"], row["full_name"]) for row in pipeline.players.get_players()]
    rows += list(
        logs[["PLAYER_ID", "PLAYER_NAME"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    for player_id, name in rows:
        known.setdefault(key(name), set()).add(int(player_id))
        # Accept an omitted suffix from an older report, but never remove a
        # suffix explicitly present in source text (e.g. a father's namesake).
        without_suffix = re.sub(
            r" (?:jr|sr|ii|iii|iv|v)$", "", pipeline.normalize_player_name_key(name)
        )
        known.setdefault(key(without_suffix), set()).add(int(player_id))
    output = frame.copy()
    repaired = 0
    for index, row in output.loc[output.PLAYER_ID.isna()].iterrows():
        tokens = str(row.PLAYER_NAME_SOURCE).split()
        candidates = {}
        for start in range(len(tokens)):
            source_name = " ".join(tokens[start:])
            name = pipeline.normalize_official_player_name(source_name)
            matches = known.get(key(name), set())
            if len(matches) == 1:
                candidates[next(iter(matches))] = name
        if len(candidates) == 1:
            player_id, name = next(iter(candidates.items()))
            output.at[index, "PLAYER_ID"] = player_id
            output.at[index, "PLAYER_NAME"] = name
            repaired += 1
    return output, repaired
