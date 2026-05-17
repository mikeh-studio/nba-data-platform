{{ config(
    materialized='table',
    schema=env_var('BQ_DATASET_GOLD', env_var('BQ_DATASET', 'nba_gold'))
) }}

with category_profile as (
    select
        season,
        player_id,
        player_name,
        latest_team_abbr,
        games_sampled,
        qualification_games,
        is_qualified,
        sample_status,
        sample_warning
    from {{ ref('player_category_profile') }}
),
rankings as (
    select
        season,
        player_id,
        team_abbr,
        latest_game_date,
        overall_rank,
        recommendation_score
    from {{ ref('player_fantasy_rankings') }}
),
recent_form as (
    select
        season,
        player_id,
        latest_game_date
    from {{ ref('player_recent_form') }}
),
player_dimension as (
    select
        player_id,
        latest_season,
        latest_team_abbr,
        position,
        last_seen_at_utc
    from {{ ref('dim_player') }}
)
select
    c.player_id,
    c.player_name,
    c.season as latest_season,
    coalesce(r.team_abbr, c.latest_team_abbr, d.latest_team_abbr) as latest_team_abbr,
    coalesce(r.latest_game_date, f.latest_game_date) as latest_game_date,
    c.games_sampled,
    c.qualification_games,
    c.is_qualified,
    c.sample_status,
    c.sample_warning,
    r.overall_rank,
    r.recommendation_score,
    d.position,
    d.last_seen_at_utc,
    lower(
        c.player_name || ' '
        || coalesce(r.team_abbr, c.latest_team_abbr, d.latest_team_abbr, '')
        || ' '
        || coalesce(d.position, '')
    ) as search_text
from category_profile c
left join rankings r
    on c.season = r.season
   and c.player_id = r.player_id
left join recent_form f
    on c.season = f.season
   and c.player_id = f.player_id
left join player_dimension d
    on c.player_id = d.player_id
   and c.season = d.latest_season
where c.is_qualified
