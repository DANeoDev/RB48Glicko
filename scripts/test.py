from database import get_connection
from db_matches import get_match_teams

connection = get_connection()

team_a, team_b = get_match_teams(
    connection,
    "2026-07-15-1"
)

print("Team A:", team_a)
print("Team B:", team_b)

connection.close()