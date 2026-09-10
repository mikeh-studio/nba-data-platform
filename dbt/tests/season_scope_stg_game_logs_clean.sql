select
    player_id,
    game_date,
    matchup,
    season
from {{ ref('stg_game_logs_clean') }}
where season != '{{ warehouse_season() }}'
   or game_date < date('{{ warehouse_season_start() }}')
   or game_date > date('{{ warehouse_season_end() }}')
