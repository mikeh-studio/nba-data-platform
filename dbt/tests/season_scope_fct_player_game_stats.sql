select
    player_id,
    game_date,
    matchup,
    season
from {{ ref('fct_player_game_stats') }}
where season != '{{ warehouse_season() }}'
   or game_date < date('{{ warehouse_season_start() }}')
   or game_date > date('{{ warehouse_season_end() }}')
