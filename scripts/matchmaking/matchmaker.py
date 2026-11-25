import itertools
import random

from scripts.database.database import get_connection
from scripts.database.db_ratings import get_calibrations
from scripts.glicko.glicko2 import (
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


def _load_calibrations():
    """Load calibration ratings for players without current Glicko ratings."""
    connection = get_connection()
    try:
        return get_calibrations(connection)
    finally:
        connection.close()


def _rating_objects(ratings, player_ids, rating_type, calibrations=None):
    """Build rating objects for the matchmaker with sensible fallbacks.

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
    if calibrations is None:
        calibrations = _load_calibrations()
    rating_objects = _rating_objects(ratings, team, rating_type, calibrations)
    return calculate_team_rating(
        team,
        len(team),
        rating_objects,
        rating_type
    )


def _team_label(index):
    return f"Team {chr(65 + index)}" if index < 26 else f"Team {index + 1}"


def _multi_position_penalty(teams, players):
    if len(teams) == 2:
        return _position_penalty(teams[0], teams[1], players)
    penalty = 0
    for group in POSITION_GROUPS:
        counts = [sum(group in _normalized_positions(players[p]) for p in team) for team in teams]
        penalty += max(counts) - min(counts)

    gk_counts = [sum("gk" in _normalized_positions(players[p]) for p in team) for team in teams]
    if sum(gk_counts) >= 2 and min(gk_counts) == 0 and max(gk_counts) >= 2:
        penalty += 100 * sum(max(0, c - 1) for c in gk_counts)
    return penalty


def _score(team_a, team_b, ratings, players, rating_type, calibrations=None):
    rating_a = _team_rating(team_a, ratings, rating_type, calibrations)
    rating_b = _team_rating(team_b, ratings, rating_type, calibrations)
    rating_difference = abs(rating_a.rating - rating_b.rating)
    position_penalty = _position_penalty(team_a, team_b, players)
    score = rating_difference + position_penalty * 12
    return score, rating_a, rating_b


def _multi_score(teams, ratings, players, rating_type, calibrations=None):
    team_ratings = [_team_rating(team, ratings, rating_type, calibrations) for team in teams]
    rating_vals = [r.rating for r in team_ratings]
    rating_difference = max(rating_vals) - min(rating_vals)
    position_penalty = _multi_position_penalty(teams, players)
    score = rating_difference + position_penalty * 12
    pairwise_spread = sum(
        abs(rating_vals[i] - rating_vals[j])
        for i in range(len(rating_vals))
        for j in range(i + 1, len(rating_vals))
    )
    return score, pairwise_spread, rating_difference, position_penalty, team_ratings


def _balanced_team_sizes(n, k):
    base, rem = divmod(n, k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def _generate_multi_team_candidates(shuffled, num_teams, ratings, players, rating_type, calibrations, randomizer):
    n = len(shuffled)
    sizes = _balanced_team_sizes(n, num_teams)
    candidates = []
    seen = set()

    if num_teams == 3 and n <= 12:
        # Exact canonical enumeration for small 3-team tournaments
        s0, s1, s2 = sizes
        for t0_tuple in itertools.combinations(shuffled, s0):
            t0 = list(t0_tuple)
            rem1 = [p for p in shuffled if p not in t0_tuple]
            for t1_tuple in itertools.combinations(rem1, s1):
                t1 = list(t1_tuple)
                t2 = [p for p in rem1 if p not in t1_tuple]
                if s0 == s1 and min(t0) > min(t1):
                    continue
                if s1 == s2 and min(t1) > min(t2):
                    continue
                if s0 == s2 and min(t0) > min(t2):
                    continue
                teams = [t0, t1, t2]
                key = frozenset(frozenset(t) for t in teams)
                if key in seen:
                    continue
                seen.add(key)
                score, spread, rdiff, ppen, tratings = _multi_score(
                    teams, ratings, players, rating_type, calibrations
                )
                candidates.append((score, spread, teams, rdiff, ppen, tratings))
        return candidates

    restarts = 100
    for _ in range(restarts):
        work = shuffled[:]
        randomizer.shuffle(work)
        teams = []
        idx = 0
        for sz in sizes:
            teams.append(work[idx:idx + sz])
            idx += sz

        curr_score, curr_spread, curr_rdiff, curr_ppen, curr_ratings = _multi_score(
            teams, ratings, players, rating_type, calibrations
        )

        # Hill-climbing 2-player swaps across teams
        for _ in range(30):
            best_move = None
            best_eval = (curr_score, curr_spread)
            for ti in range(num_teams):
                for tj in range(ti + 1, num_teams):
                    for pi in range(len(teams[ti])):
                        for pj in range(len(teams[tj])):
                            teams[ti][pi], teams[tj][pj] = teams[tj][pj], teams[ti][pi]
                            cand_eval = _multi_score(
                                teams, ratings, players, rating_type, calibrations
                            )
                            if (cand_eval[0], cand_eval[1]) < best_eval:
                                best_eval = (cand_eval[0], cand_eval[1])
                                best_move = (ti, tj, pi, pj, cand_eval)
                            teams[ti][pi], teams[tj][pj] = teams[tj][pj], teams[ti][pi]
            if best_move is None:
                break
            ti, tj, pi, pj, cand_eval = best_move
            teams[ti][pi], teams[tj][pj] = teams[tj][pj], teams[ti][pi]
            curr_score, curr_spread, curr_rdiff, curr_ppen, curr_ratings = cand_eval

        key = frozenset(frozenset(t) for t in teams)
        if key not in seen:
            seen.add(key)
            candidates.append((
                curr_score,
                curr_spread,
                [t[:] for t in teams],
                curr_rdiff,
                curr_ppen,
                curr_ratings,
            ))

    return candidates


def generate_match(team_player_ids, players, ratings, rating_type, seed=None, calibrations=None, num_teams=2):
    team_player_ids = list(dict.fromkeys(team_player_ids))
    try:
        num_teams = int(num_teams or 2)
    except (TypeError, ValueError):
        num_teams = 2
    num_teams = max(2, num_teams)

    if len(team_player_ids) < num_teams:
        return None

    if calibrations is None:
        calibrations = _load_calibrations()

    randomizer = random.Random(seed)
    shuffled = team_player_ids[:]
    randomizer.shuffle(shuffled)

    if num_teams == 2:
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

        chosen_teams = [team_a, team_b]
        chosen_ratings = [rating_a, rating_b]
        rating_diff = abs(rating_a.rating - rating_b.rating)
        pos_pen = _position_penalty(team_a, team_b, players)
    else:
        candidates = _generate_multi_team_candidates(
            shuffled, num_teams, ratings, players, rating_type, calibrations, randomizer
        )
        candidates.sort(key=lambda item: (item[0], item[1]))
        if not candidates:
            return None

        pool_size = min(12, len(candidates))
        choice = randomizer.choice(candidates[:pool_size])
        _, _, chosen_teams, rating_diff, pos_pen, chosen_ratings = choice

    teams_payload = []
    for idx, team_pids in enumerate(chosen_teams):
        randomizer.shuffle(team_pids)
        teams_payload.append({
            "label": _team_label(idx),
            "players": team_pids,
            "rating": chosen_ratings[idx],
            "considered_positions": _considered_positions(team_pids, players),
        })

    res = {
        "num_teams": num_teams,
        "teams": teams_payload,
        "rating_difference": rating_diff,
        "position_penalty": pos_pen,
    }
    if len(teams_payload) >= 2:
        res["team_a"] = teams_payload[0]["players"]
        res["team_b"] = teams_payload[1]["players"]
        res["rating_a"] = teams_payload[0]["rating"]
        res["rating_b"] = teams_payload[1]["rating"]
        res["considered_positions_a"] = teams_payload[0]["considered_positions"]
        res["considered_positions_b"] = teams_payload[1]["considered_positions"]
    return res
