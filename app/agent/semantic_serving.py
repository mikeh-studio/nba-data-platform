"""Bounded, cached warehouse evidence for governed Ask requests."""

from __future__ import annotations

import re
from collections import OrderedDict
from threading import Lock
from time import monotonic
from typing import Any

from app.agent.player_resolver import load_player_aliases, normalize_player_text
from app.agent.semantic_source import BigQuerySemanticSource, snapshot_evidence
from app.agent.semantics import Evidence, SemanticError
from app.seasons import DEFAULT_SEASON, validate_season


def requested_seasons(question: str, selected: str) -> list[str]:
    seasons = []
    for match in re.finditer(r"\b(20\d{2})[-–/](20\d{2}|\d{2})\b(?!-\d)", question):
        start, end = match.groups()
        season = f"{start}-{end[-2:]}"
        try:
            validate_season(season)
        except ValueError as exc:
            raise SemanticError(
                "unsupported_coverage", f"Season {season} is unavailable"
            ) from exc
        if season not in seasons:
            seasons.append(season)
    return seasons or [validate_season(selected)]


class SemanticWarehouse:
    def __init__(self, source: BigQuerySemanticSource, ttl_seconds: int = 300):
        self.source = source
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._cache: OrderedDict[tuple[str, ...], tuple[float, dict[str, Any]]] = (
            OrderedDict()
        )

    def players(self, evidence: Evidence) -> list[dict[str, Any]]:
        return source_players(evidence)

    def load(self, seasons: list[str]) -> tuple[dict[str, Any], Evidence]:
        key = tuple(sorted(seasons))
        with self._lock:
            cached = self._cache.get(key)
            if cached and monotonic() - cached[0] < self.ttl_seconds:
                snapshot = cached[1]
            else:
                snapshot = self.source.capture(list(key))
                snapshot_evidence(snapshot)
                self._cache[key] = (monotonic(), snapshot)
                self._cache.move_to_end(key)
                while len(self._cache) > 3:
                    self._cache.popitem(last=False)
        # Validate even cached rows. Errors are never cached as empty evidence.
        return snapshot, snapshot_evidence(snapshot)


def source_players(evidence: Evidence) -> list[dict[str, Any]]:
    players: dict[int, dict[str, Any]] = {}
    for row in evidence.rows:
        player = players.setdefault(
            row["player_id"],
            {
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "aliases": set(),
            },
        )
        player["aliases"].add(row["player_name"])
    aliases = load_player_aliases()
    for player in players.values():
        canonical = {normalize_player_text(n) for n in player["aliases"]}
        player["aliases"].update(
            alias
            for alias, name in aliases.items()
            if normalize_player_text(name) in canonical
        )
        player["aliases"].add(normalize_player_text(player["player_name"]))
        player["aliases"] = sorted(player["aliases"])
    return list(players.values())


_factory_lock = Lock()


def warehouse_for_repository(repo: Any) -> SemanticWarehouse:
    with _factory_lock:
        warehouse = getattr(repo, "_governed_warehouse", None)
        if warehouse is None:
            settings = repo.settings
            dataset = settings.gold_dataset
            if settings.season != DEFAULT_SEASON:
                dataset = dataset.removesuffix("_" + settings.season.replace("-", "_"))
            warehouse = SemanticWarehouse(
                BigQuerySemanticSource(
                    repo.client, project=settings.project_id, gold_dataset=dataset
                ),
                settings.agent_cache_ttl_seconds,
            )
            repo._governed_warehouse = warehouse
        return warehouse
