from datetime import UTC, datetime

from app.config import Settings
from app.freshness import build_publication_health


def health(
    now,
    *,
    failure=None,
    metadata=True,
    refreshed="2026-06-19T12:00:00+00:00",
    source_date="2026-06-19",
):
    rows = [
        {
            "asset": name,
            "last_successful_finished_at_utc": refreshed,
            "latest_source_date": source_date,
            "last_attempt_status": "failed_non_blocking"
            if name == failure
            else "success",
        }
        for name in ["stats", "injuries", "similarity"]
    ]
    return build_publication_health(
        {"finished_at_utc": refreshed},
        rows if metadata else None,
        {"latest_game_date": source_date},
        settings=Settings("demo", "gold", "metadata", 36, 12),
        now=now,
    )


def test_offseason_and_preseason_do_not_mark_archive_stale():
    for now in [
        datetime(2026, 9, 5, tzinfo=UTC),
        datetime(2026, 10, 19, 23, tzinfo=UTC),
    ]:
        result = health(now)
        assert result["status"] == "offseason"
        assert result["is_fresh"] is None
        assert result["updates_expected"] is False
        assert result["assets"]["similarity"]["latest_source_date"] == "2026-06-19"


def test_offseason_does_not_hide_actual_publication_failure():
    result = health(datetime(2026, 9, 5, tzinfo=UTC), failure="similarity")
    assert result["status"] == "partially_updated"
    assert result["season_phase"] == "offseason"
    assert result["assets"]["similarity"]["serving_previous_version"] is True
    assert result["assets"]["stats"]["status"] == "offseason"


def test_opening_day_uses_eastern_time_and_has_ingestion_grace():
    assert health(datetime(2026, 10, 20, 3, 59, tzinfo=UTC))["status"] == "offseason"
    result = health(datetime(2026, 10, 20, 4, tzinfo=UTC))
    assert result["status"] == "awaiting_refresh"
    assert result["updates_expected"] is True
    assert health(datetime(2026, 10, 21, 16, tzinfo=UTC))["status"] == "stale"


def test_recent_run_cannot_make_old_source_data_fresh_after_opener():
    result = health(
        datetime(2026, 10, 22, 12, tzinfo=UTC), refreshed="2026-10-22T11:00:00+00:00"
    )
    assert result["status"] == "stale"
    assert result["assets"]["stats"]["status"] == "stale"


def test_opening_day_data_is_current_as_soon_as_it_is_published():
    result = health(
        datetime(2026, 10, 21, 14, tzinfo=UTC),
        refreshed="2026-10-21T12:00:00+00:00",
        source_date="2026-10-20",
    )
    assert result["status"] == "fresh"


def test_active_season_freshness_and_failures_are_independent():
    now = datetime(2026, 2, 11, 16, tzinfo=UTC)
    args = {"refreshed": "2026-02-11T12:00:00+00:00", "source_date": "2026-02-10"}
    assert health(now, **args)["status"] == "fresh"
    result = health(now, failure="injuries", **args)
    assert result["status"] == "partially_updated"
    assert result["assets"]["stats"]["status"] == "fresh"


def test_missing_metadata_is_disclosed_without_inventing_asset_refresh_dates():
    result = health(datetime(2026, 9, 5, tzinfo=UTC), metadata=False)
    assert result["asset_metadata_available"] is False
    assert result["assets"]["injuries"]["last_successful_finished_at_utc"] is None
    assert result["assets"]["injuries"]["status"] == "missing"
