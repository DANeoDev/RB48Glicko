from database import get_connection
from db_matches import get_match_teams, get_player_stats

connection = get_connection()

stats = get_player_stats(connection)

for player_id, player_stats in stats.items():
    print(player_id, player_stats)

connection.close()