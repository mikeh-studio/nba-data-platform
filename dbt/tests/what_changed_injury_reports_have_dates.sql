select season, player_id, game_date
from {{ ref('what_changed_injury_reports') }}
where game_date is null or report_date is null or report_timestamp_utc is null
