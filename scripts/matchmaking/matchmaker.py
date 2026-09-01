import itertools
import random

from scripts.glicko.glicko2 import (
    TOTAL,
    BOX,
    HF,
    Rating,
    DEFAULT_RATING,
    DEFAULT_RD,
    DEFAULT_SIGMA,
)
from scripts.glicko.glicko2_calculator import calculate_team_rating


POSITION_GROUPS = {
    "gk": {"gk", "goalkeeper", "torwart", "keeper"},
    "def": {"def", "defender", "defence", "defense", "abwehr"},
    "mid": {"mid", "midfielder", "mittelfeld"},
    "att": {"att", "attacker", "forward", "stürmer", "sturm"},
}


def _normalized_positions(player):
    positions = set()
    for position in player.get("positions", []):
        value = position.rstrip("*").strip().lower()
        for group, names in POSITION_GROUPS.items():
            if value in names:
                positions.add(group)
    return positions


def _rating_objects(ratings, player_ids, rating_type, calibrations=None):
    """Build the rating objects needed by the matchmaker.

    A player may exist in the database without a current Glicko rating, for
    example immediately after being created. In that case the matchmaker uses
    the player's calibration. If no calibration exists either, it falls back
    to the standard Glicko starting values.
    """
    calibrations = calibrations or {}
    converted = {}

    for player_id in player_ids:
        rating_data = ratings.get(player_id, {}).get(rating_type)
        if rating_data is None:
            rating_data = calibrations.get(
                player_id,
                {
                    "rating": DEFAULT_RATING,
                    "rd": DEFAULT_RD,
                    "sigma": DEFAULT_SIGMA,
                },
            )

        converted[player_id] = {
            rating_type: Rating(
                rating_data["rating"],
                rating_data["rd"],
                rating_data["sigma"],
            )
        }

    return converted


def _position_penalty(team_a, team_b, players):
    penalty = 0
    for group in POSITION_GROUPS:
        a_capable = sum(group in _normalized_positions(players[p]) for p in team_a)
        b_capable = sum(group in _normalized_positions(players[p]) for p in team_b)
        penalty += abs(a_capable - b_capable)

    # Two GK-capable players should never end up on the same team.
    gks = [p for p in team_a + team_b if "gk" in _normalized_positions(players[p])]
    if len(gks) >= 2:
        a_gks = sum(p in team_a for p in gks)
        b_gks = len(gks) - a_gks
        if a_gks == 0 or b_gks == 0:
            penalty += 100

    return penalty


def _considered_positions(team, players):
    """Assign a display-only position based on the team's composition."""
    assigned = {}
    counts = {group: 0 for group in POSITION_GROUPS}

    for group in ("gk", "def", "mid", "att"):
        capable = [p for p in team if p not in assigned and group in _normalized_positions(players[p])]
        if group == "gk":
            for player_id in capable:
                assigned[player_id] = "GK"
                counts[group] += 1
        elif len(capable) == 1:
            assigned[capable[0]] = group.upper()
            counts[group] += 1

    for player_id in team:
        if player_id in assigned:
            continue
        capable = _normalized_positions(players[player_id])
        if not capable:
            assigned[player_id] = "Any"
            continue
        group = min(capable, key=lambda g: counts[g])
        assigned[player_id] = group.upper()
        counts[group] += 1

    return assigned


def _team_rating(team, ratings, rating_type, calibrations=None):
    rating_objects = _rating_objects(ratings, team, rating_type, calibrations)
    return calculate_team_rating(
        team,
        len(team),
        rating_objects,
        rating_type
    )


def _score(team_a, team_b, ratings, players, rating_type, calibrations=None):
    rating_a = _team_rating(team_a, ratings, rating_type, calibrations)
    rating_b = _team_rating(team_b, ratings, rating_type, calibrations)
    rating_difference = abs(rating_a.rating - rating_b.rating)
    position_penalty = _position_penalty(team_a, team_b, players)
    score = rating_difference + position_penalty * 12
    return score, rating_a, rating_b


def generate_match(team_player_ids, players, ratings, rating_type, seed=None, calibrations=None):
    team_player_ids = list(dict.fromkeys(team_player_ids))
    if len(team_player_ids) < 2:
        return None

    randomizer = random.Random(seed)
    shuffled = team_player_ids[:]
    randomizer.shuffle(shuffled)

    target_size = len(shuffled) // 2
    sizes = {target_size}
    if len(shuffled) % 2:
        sizes.add(target_size + 1)

    candidates = []
    n = len(shuffled)

    if n <= 20:
        for size in sizes:
            for team_a_tuple in itertools.combinations(shuffled, size):
                team_a = list(team_a_tuple)
                team_b = [p for p in shuffled if p not in team_a]
                if size == n - size and min(team_a) > min(team_b):
                    continue
                score, rating_a, rating_b = _score(team_a, team_b, ratings, players, rating_type, calibrations)
                candidates.append((score, team_a, team_b, rating_a, rating_b))
    else:
        seen = set()
        for _ in range(20000):
            randomizer.shuffle(shuffled)
            size = target_size + (1 if n % 2 and randomizer.random() < 0.5 else 0)
            team_a = shuffled[:size]
            team_b = shuffled[size:]
            key = frozenset(team_a)
            if key in seen:
                continue
            seen.add(key)
            score, rating_a, rating_b = _score(team_a, team_b, ratings, players, rating_type, calibrations)
            candidates.append((score, team_a[:], team_b[:], rating_a, rating_b))

    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None

    pool_size = min(12, len(candidates))
    choice = randomizer.choice(candidates[:pool_size])
    _, team_a, team_b, rating_a, rating_b = choice

    randomizer.shuffle(team_a)
    randomizer.shuffle(team_b)

    return {
        "team_a": team_a,
        "team_b": team_b,
        "rating_a": rating_a,
        "rating_b": rating_b,
        "rating_difference": abs(rating_a.rating - rating_b.rating),
        "position_penalty": _position_penalty(team_a, team_b, players),
        "considered_positions_a": _considered_positions(team_a, players),
        "considered_positions_b": _considered_positions(team_b, players),
    }
