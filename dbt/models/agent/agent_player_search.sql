{{ config(
    materialized='table',
    schema=env_var('BQ_DATASET_AGENT', 'nba_agent')
) }}

{% set current_ts = 'current_timestamp()' if target.type == 'bigquery' else 'current_timestamp' %}

with detail as (
    select *
    from {{ ref('workbench_player_detail') }}
),
category_profile as (
    select
        season,
        player_id,
        avg_pts,
        avg_reb,
        avg_ast,
        avg_stl,
        avg_blk,
        avg_fg3m,
        avg_tov,
        avg_min,
        avg_fantasy_points_simple
    from {{ ref('player_category_profile') }}
),
player_dimension as (
    select
        player_id,
        latest_season,
        latest_team_abbr,
        position,
        last_seen_at_utc
    from {{ ref('dim_player') }}
),
availability as (
    select
        season,
        player_id,
        injury_status,
        availability_bucket,
        reason as availability_reason,
        is_report_stale,
        next_reported_game_date,
        next_reported_matchup
    from {{ ref('player_availability_current') }}
)
select
    d.player_id,
    d.player_name,
    d.season as latest_season,
    coalesce(d.latest_team_abbr, p.latest_team_abbr) as latest_team_abbr,
    p.position,
    d.latest_game_date,
    d.games_sampled,
    d.qualification_games,
    d.is_qualified,
    d.sample_status,
    d.sample_warning,
    d.overall_rank,
    d.recommendation_score,
    d.recommendation_tier,
    c.avg_min,
    c.avg_pts,
    c.avg_reb,
    c.avg_ast,
    c.avg_stl,
    c.avg_blk,
    c.avg_fg3m,
    c.avg_tov,
    c.avg_fantasy_points_simple,
    round(c.avg_pts + c.avg_ast * 2, 2) as avg_points_created,
    d.pts_percentile,
    d.reb_percentile,
    d.ast_percentile,
    d.stl_percentile,
    d.blk_percentile,
    d.tov_percentile,
    d.category_strengths,
    d.category_risks,
    d.trend_delta,
    d.trend_pct_change,
    d.trend_status,
    d.next_game_date,
    d.next_opponent_abbr,
    d.games_next_7d,
    d.back_to_backs_next_7d,
    d.opportunity_score,
    a.injury_status,
    a.availability_bucket,
    a.availability_reason,
    a.is_report_stale,
    a.next_reported_game_date,
    a.next_reported_matchup,
    p.last_seen_at_utc,
    {{ current_ts }} as agent_context_updated_at_utc,
    lower(
        concat(
            coalesce(d.player_name, ''), ' ',
            coalesce(d.latest_team_abbr, p.latest_team_abbr, ''), ' ',
            coalesce(p.position, ''), ' ',
            coalesce(d.category_strengths, ''), ' ',
            coalesce(d.category_risks, ''), ' ',
            coalesce(a.availability_bucket, '')
        )
    ) as search_text,
    concat(
        coalesce(d.player_name, 'Player'), ' ',
        coalesce(d.latest_team_abbr, p.latest_team_abbr, ''), ' ',
        coalesce(p.position, ''), '. ',
        'Sample: ', coalesce(d.sample_status, 'unknown'), '. ',
        'Trend: ', coalesce(d.trend_status, 'unknown'), '. ',
        'Strengths: ', coalesce(d.category_strengths, 'none recorded'), '. ',
        'Risks: ', coalesce(d.category_risks, 'none recorded'), '. ',
        'Availability: ', coalesce(a.availability_bucket, 'not reported'), '.'
    ) as answer_context
from detail d
left join category_profile c
    on d.season = c.season
   and d.player_id = c.player_id
left join player_dimension p
    on d.player_id = p.player_id
   and d.season = p.latest_season
left join availability a
    on d.season = a.season
   and d.player_id = a.player_id
where coalesce(d.is_qualified, false)
