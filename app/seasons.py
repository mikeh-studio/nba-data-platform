"""Validated season selection and isolated historical warehouse routing."""

from contextvars import ContextVar
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

DEFAULT_SEASON = "2025-26"
SEASONS = ("2025-26", "2024-25", "2023-24")
_selected_season: ContextVar[str] = ContextVar("nba_season", default=DEFAULT_SEASON)


def validate_season(season: str) -> str:
    if season not in SEASONS:
        raise ValueError(f"Unsupported season: {season}")
    return season


def season_bounds(season: str) -> tuple[date, date]:
    year = int(validate_season(season)[:4])
    return date(year, 7, 1), date(year + 1, 6, 30)


def current_season() -> str:
    return _selected_season.get()


def dataset_for_season(dataset: str, season: str) -> str:
    validate_season(season)
    return (
        dataset if season == DEFAULT_SEASON else f"{dataset}_{season.replace('-', '_')}"
    )


def settings_for_season(settings: "Settings", season: str) -> "Settings":
    history = Path(settings.agent_history_path)
    history_path = (
        str(history.with_name(f"{history.stem}_{season}{history.suffix}"))
        if season != DEFAULT_SEASON
        else settings.agent_history_path
    )
    return replace(
        settings,
        agent_history_path=history_path,
        season=validate_season(season),
        gold_dataset=dataset_for_season(settings.gold_dataset, season),
        agent_dataset=dataset_for_season(settings.agent_dataset, season),
        metadata_dataset=dataset_for_season(settings.metadata_dataset, season),
    )
