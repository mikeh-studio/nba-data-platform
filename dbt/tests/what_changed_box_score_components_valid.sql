select season, game_id, player_id
from {{ ref('fct_player_game_stats') }}
where pf < 0 or oreb < 0 or dreb < 0
   or (oreb is not null and dreb is not null and oreb + dreb != reb)
