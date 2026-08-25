# CAUTION THIS WILL WIPE RATING TABLES DUH, intended for testing

from database import get_connection,create_ratings_table, create_match_ratings_table



connection = get_connection()

connection.execute("DROP TABLE IF EXISTS match_ratings")
connection.execute("DROP TABLE IF EXISTS ratings")
connection.commit()

create_match_ratings_table(connection)
create_ratings_table(connection)

connection.close()

print("Rating tables dropped and recreated successfully.")