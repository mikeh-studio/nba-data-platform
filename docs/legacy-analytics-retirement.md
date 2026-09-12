# Legacy analytics retirement

This change removes `/api/leaderboard`, `/api/trends`, `/api/analysis/latest` and
`/api/recommendations`; they now return 404. Current Ask, rankings, performance,
comparison, player detail and similarity endpoints remain. Retired clients must
move to the retained APIs; there is no compatibility response with stale data.

The `daily_leaderboard` and `fantasy_insights` dbt models and the runtime
`analysis_snapshots` writer are removed, including historical placeholder creation,
publication/triage metadata and obsolete tests. The dbt model count is 29 (was 31).

Legacy metric YAML now contains presentation/alias metadata rather than duplicate
formula and direction definitions. The governed contract supplies those definitions;
its FG% legacy formula preserves conversion of precomputed ratio values to percent.
Legacy trend aggregation behavior is intentionally preserved. Query and planner
phase defaults read the contract. Agent search obtains its dimension fields from
`player_search_index`; the index remains an independent fallback when the richer
agent table is unavailable. Availability enrichment and ranking qualification stay.

## Warehouse removal sequence

The nine candidates are `daily_leaderboard` (VIEW), `fantasy_insights` (TABLE), and
`analysis_snapshots` (TABLE), in each of `nba_gold`, `nba_gold_2023_24` and
`nba_gold_2024_25`, in project `nba-data-485505`.

Read-only inspection found all nine. A bounded 180-day US-region project query-history
check found historical reads as recent as September 9, 2026. This is not proof of
absence of external consumers: cross-project jobs, cached results, view expansion,
and non-query reads may be missing. No warehouse objects were dropped by this PR.

After merging and rolling out the app, DAG and backfill changes:

1. Verify old API routes are absent and deployed DAGs no longer contain the snapshot
   task; ensure no old pipeline run is still active. Confirm any external clients
   have migrated and recheck job history for the candidates.
2. Save each object's metadata/DDL with `bq show --format=prettyjson`. Snapshot the
   six tables into explicitly named retirement backups with seven-day expiration;
   preserve the three view definitions separately. Verify backup row counts and
   expiration before any drop. Backups are temporary, not new serving tables.
3. Drop only the three named objects in each of the three named datasets, using
   `DROP VIEW` for daily_leaderboard and `DROP TABLE` for the others. Do not drop
   shared facts, similarity inputs, search indexes or datasets.
4. Validate retained APIs and the next pipeline run. Restore table backups and
   saved view DDL if a missed consumer is discovered within the retention window.

Deployment and warehouse drops remain separate steps. Removing SQL files does not
remove existing warehouse objects; executing the drop before retiring deployed
writers would break old consumers or allow the objects to be recreated.
