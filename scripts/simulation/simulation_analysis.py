from scripts.database.database import get_connection
from scripts.database.db_matches import get_matches, get_match_teams
from scripts.database.db_ratings import get_match_ratings, get_ratings
from scripts.glicko.glicko2 import TOTAL, BOX, HF, expected_score
from scripts.simulation.generate_demo import win_probability
from scripts.simulation.true_strength1 import PLAYERS

TRUE_STRENGTH_BY_ID = {player_id: strength for player_id, (_, strength) in enumerate(PLAYERS, start=1)}
RATING_TYPES = {'total': TOTAL, 'box': BOX, 'hf': HF}


class SimulationTable(list):
    """List of player rows with page-level simulation diagnostics attached."""
    def __init__(self, rows, brier_simulation):
        super().__init__(rows)
        self.brier_simulation = brier_simulation


def _conservative(rating):
    return rating['rating'] - 3 * rating['rd']


def _build_brier_simulation(connection, selected_pitch='total'):
    rating_type = RATING_TYPES[selected_pitch]
    observations = []
    for match_id, match in get_matches(connection).items():
        if selected_pitch != 'total' and match['pitch'] != selected_pitch:
            continue
        team_a, team_b = get_match_teams(connection, match_id)
        if not team_a or not team_b:
            continue
        match_ratings = get_match_ratings(connection, match_id)
        if any(pid not in match_ratings or rating_type not in match_ratings[pid] for pid in team_a + team_b):
            continue
        true_a = sum(TRUE_STRENGTH_BY_ID[pid] for pid in team_a) / len(team_a)
        true_b = sum(TRUE_STRENGTH_BY_ID[pid] for pid in team_b) / len(team_b)
        true_probability = win_probability(true_a, true_b)
        rating_a = sum(match_ratings[pid][rating_type]['rating'] for pid in team_a) / len(team_a)
        rating_b = sum(match_ratings[pid][rating_type]['rating'] for pid in team_b) / len(team_b)
        rd_b = (sum(match_ratings[pid][rating_type]['rd'] ** 2 for pid in team_b) / len(team_b)) ** 0.5
        glicko_probability = expected_score(rating_a, rating_b, rd_b)
        observations.append({'true': true_probability, 'glicko': glicko_probability})

    n = len(observations)
    if not n:
        return {'games': 0, 'mse': None, 'mae': None, 'correlation': None, 'true_mean': None, 'glicko_mean': None, 'baskets': []}

    true_mean = sum(x['true'] for x in observations) / n
    glicko_mean = sum(x['glicko'] for x in observations) / n
    mse = sum((x['glicko'] - x['true']) ** 2 for x in observations) / n
    mae = sum(abs(x['glicko'] - x['true']) for x in observations) / n
    covariance = sum((x['glicko'] - glicko_mean) * (x['true'] - true_mean) for x in observations) / n
    glicko_sd = (sum((x['glicko'] - glicko_mean) ** 2 for x in observations) / n) ** 0.5
    true_sd = (sum((x['true'] - true_mean) ** 2 for x in observations) / n) ** 0.5
    correlation = covariance / (glicko_sd * true_sd) if glicko_sd > 0 and true_sd > 0 else None

    ordered = sorted(observations, key=lambda x: x['true'])
    basket_count = 20 if n >= 200 else 10
    baskets = []
    for i in range(basket_count):
        values = ordered[i * n // basket_count:(i + 1) * n // basket_count]
        if values:
            baskets.append({'label': f"{min(x['true'] for x in values) * 100:.1f}–{max(x['true'] for x in values) * 100:.1f}%", 'count': len(values), 'true': sum(x['true'] for x in values) / len(values), 'glicko': sum(x['glicko'] for x in values) / len(values)})
    return {'games': n, 'mse': mse, 'mae': mae, 'correlation': correlation, 'true_mean': true_mean, 'glicko_mean': glicko_mean, 'baskets': baskets}


def build_simulation_table(players, ratings, selected_pitch='total'):
    rows = []
    rating_type = RATING_TYPES[selected_pitch]
    for player_id, player in players.items():
        rating = ratings.get(player_id, {}).get(rating_type)
        if rating is None:
            continue
        true_strength = TRUE_STRENGTH_BY_ID[player_id]
        rows.append({'player_id': player_id, 'name': player['aliases'][0] if player['aliases'] else f'Player {player_id}', 'true_strength': true_strength, 'rating': rating['rating'], 'rd': rating['rd'], 'conservative': _conservative(rating), 'true_minus_estimated': true_strength - rating['rating']})
    rows.sort(key=lambda row: row['conservative'], reverse=True)
    connection = get_connection()
    try:
        brier_simulation = _build_brier_simulation(connection, selected_pitch)
    finally:
        connection.close()
    return SimulationTable(rows, brier_simulation)


def _match_prediction(match, team_a, team_b, match_ratings, player_id):
    if player_id in team_a:
        player_team, opponent_team, player_is_a = team_a, team_b, True
    elif player_id in team_b:
        player_team, opponent_team, player_is_a = team_b, team_a, False
    else:
        return None
    true_a = sum(TRUE_STRENGTH_BY_ID[pid] for pid in team_a) / len(team_a)
    true_b = sum(TRUE_STRENGTH_BY_ID[pid] for pid in team_b) / len(team_b)
    true_probability_a = win_probability(true_a, true_b)
    true_probability = true_probability_a if player_is_a else 1 - true_probability_a
    rating_type = BOX if match['pitch'] == 'box' else HF
    if any(pid not in match_ratings or rating_type not in match_ratings[pid] for pid in player_team + opponent_team):
        glicko_probability = None
    else:
        team_rating = sum(match_ratings[pid][rating_type]['rating'] for pid in player_team) / len(player_team)
        opponent_rating = sum(match_ratings[pid][rating_type]['rating'] for pid in opponent_team) / len(opponent_team)
        opponent_rd = (sum(match_ratings[pid][rating_type]['rd'] ** 2 for pid in opponent_team) / len(opponent_team)) ** 0.5
        glicko_probability = expected_score(team_rating, opponent_rating, opponent_rd)
    goals_a, goals_b = match['goals_a'], match['goals_b']
    actual = 0.5 if goals_a == goals_b else 1.0 if (goals_a > goals_b) == player_is_a else 0.0
    return {'match_id': match['match_id'], 'date': match['date'], 'pitch': match['pitch'], 'true_probability': true_probability, 'glicko_probability': glicko_probability, 'actual': actual}


def build_player_analysis(connection, player_id):
    matches = get_matches(connection)
    ratings = get_ratings(connection)
    history = []
    for match_id, match in matches.items():
        team_a, team_b = get_match_teams(connection, match_id)
        if player_id not in team_a and player_id not in team_b:
            continue
        prediction = _match_prediction(match, team_a, team_b, get_match_ratings(connection, match_id), player_id)
        if prediction is not None:
            history.append(prediction)
    history.sort(key=lambda row: (row['date'], str(row['match_id'])))
    true_expected = true_actual = glicko_expected = glicko_actual = 0.0
    for row in history:
        true_expected += row['true_probability']
        true_actual += row['actual']
        row['true_expected_wins'], row['true_actual_wins'], row['true_delta'] = true_expected, true_actual, true_actual - true_expected
        if row['glicko_probability'] is not None:
            glicko_expected += row['glicko_probability']
            glicko_actual += row['actual']
        row['glicko_expected_wins'], row['glicko_actual_wins'], row['glicko_delta'] = glicko_expected, glicko_actual, glicko_actual - glicko_expected
    return {'player': {'player_id': player_id, 'name': PLAYERS[player_id - 1][0], 'true_strength': TRUE_STRENGTH_BY_ID[player_id]}, 'history': history, 'ratings': ratings.get(player_id, {})}
