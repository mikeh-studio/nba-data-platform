{{ config(
    materialized='table',
    hours_to_expiration=24 if var('injury_publication_suffix', '') else none,
    alias='what_changed_injury_reports' ~ var('injury_publication_suffix', ''),
    schema=env_var('BQ_DATASET_GOLD', env_var('BQ_DATASET', 'nba_gold'))
) }}

-- Preserve dated evidence rather than applying today's injury status to history.
select
    season, player_id, team_abbr, game_date, report_date,
    report_timestamp_utc, injury_status, reason, source_url
from {{ ref('stg_player_injury_reports_clean') }}
where player_id is not null
