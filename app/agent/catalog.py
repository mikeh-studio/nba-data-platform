from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.agent.formulas import extract_formula_variables

CATALOG_PATH = Path(__file__).with_name("semantic_catalog.yml")
DEFAULT_METRIC_KEYS = ("pts", "reb", "ast", "stl", "blk", "tov")


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    game_log_key: str
    trend_stat: str
    detail_average_key: str | None
    baseline_key: str | None
    percentile_key: str | None
    leaderboard_column: str
    direction: str
    formula: str | None

    @property
    def higher_is_better(self) -> bool:
        return self.direction != "lower"

    @property
    def is_derived(self) -> bool:
        return self.formula is not None

    @property
    def formula_variables(self) -> tuple[str, ...]:
        if self.formula is None:
            return ()
        return tuple(sorted(extract_formula_variables(self.formula)))

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "aliases": list(self.aliases),
            "higher_is_better": self.higher_is_better,
            "direction": self.direction,
            "formula": self.formula,
        }


class SemanticCatalog:
    def __init__(self, metrics: dict[str, MetricDefinition]) -> None:
        self.metrics = metrics
        self._aliases: dict[str, str] = {}
        for key, metric in metrics.items():
            self._aliases[_normalize_key(key)] = key
            self._aliases[_normalize_key(metric.label)] = key
            for alias in metric.aliases:
                self._aliases[_normalize_key(alias)] = key

    def list_metrics(self) -> list[dict[str, Any]]:
        return [metric.to_public_dict() for metric in self.metrics.values()]

    def resolve_metric(self, value: str) -> MetricDefinition | None:
        key = self._aliases.get(_normalize_key(value))
        if key is None:
            return None
        return self.metrics[key]

    def resolve_metrics(
        self,
        values: list[str] | None,
        *,
        default_keys: tuple[str, ...] = DEFAULT_METRIC_KEYS,
    ) -> tuple[list[MetricDefinition], list[str]]:
        if not values:
            return [self.metrics[key] for key in default_keys], []

        resolved: list[MetricDefinition] = []
        invalid: list[str] = []
        for value in values:
            metric = self.resolve_metric(str(value))
            if metric is None:
                invalid.append(str(value))
                continue
            if metric.key not in {item.key for item in resolved}:
                resolved.append(metric)
        return resolved, invalid


@lru_cache(maxsize=1)
def load_semantic_catalog(path: str | Path = CATALOG_PATH) -> SemanticCatalog:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    metrics: dict[str, MetricDefinition] = {}
    for key, config in (raw.get("metrics") or {}).items():
        formula = config.get("formula") or None
        if formula is not None:
            extract_formula_variables(str(formula))
        metrics[str(key)] = MetricDefinition(
            key=str(key),
            label=str(config["label"]),
            description=str(config["description"]),
            aliases=tuple(str(item) for item in config.get("aliases", [])),
            game_log_key=str(config.get("game_log_key") or key),
            trend_stat=str(config["trend_stat"]),
            detail_average_key=config.get("detail_average_key") or None,
            baseline_key=config.get("baseline_key") or None,
            percentile_key=config.get("percentile_key") or None,
            leaderboard_column=str(config.get("leaderboard_column") or ""),
            direction=str(config["direction"]),
            formula=str(formula) if formula is not None else None,
        )
    return SemanticCatalog(metrics)
