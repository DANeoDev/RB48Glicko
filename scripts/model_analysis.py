import math

from scripts.glicko2 import (
    BOX,
    DEFAULT_SIGMA,
    GLICKO2_SCALE,
    HF,
    IGNORED_RD,
    TOTAL,
)
from scripts.db_matches import get_match_teams, get_matches
from scripts.db_ratings import get_match_ratings


CALIBRATION_BUCKETS = 10


def _expected_score(team_a, team_b):
    """Return Glicko-2 expected score for two team ratings."""
    mu_a = (team_a["rating"] - 1500.0) / GLICKO2_SCALE
    mu_b = (team_b["rating"] - 1500.0) / GLICKO2_SCALE
    phi_b = team_b["rd"] / GLICKO2_SCALE

    impact = 1 / math.sqrt(1 + (3 * phi_b**2) / (math.pi**2))
    return 1 / (1 + math.exp(-impact * (mu_a - mu_b)))


def _team_rating(player_ids, total_players, ratings, rating_type):
    """Recreate the team-rating calculation used by the Glicko updater."""
    if not player_ids:
        return None

    ignored_players = total_players - len(player_ids)

    average_rating = sum(
        ratings[player][rating_type]["rating"] for player in player_ids
    ) / len(player_ids)

    average_rd = math.sqrt(
        (
            sum(ratings[player][rating_type]["rd"] ** 2 for player in player_ids)
            + IGNORED_RD**2 * ignored_players
        ) / total_players
    )

    average_sigma = math.sqrt(
        (
            sum(ratings[player][rating_type]["sigma"] ** 2 for player in player_ids)
            + DEFAULT_SIGMA**2 * ignored_players
        ) / total_players
    )

    return {"rating": average_rating, "rd": average_rd, "sigma": average_sigma}


def _actual_score(match):
    if match["goals_a"] > match["goals_b"]:
        return 1.0
    if match["goals_a"] < match["goals_b"]:
        return 0.0
    return 0.5


def _log_loss(prediction, actual):
    prediction = min(max(prediction, 1e-15), 1 - 1e-15)
    return -(actual * math.log(prediction) + (1 - actual) * math.log(1 - prediction))


def _calibration(predictions):
    buckets = []

    for bucket_index in range(CALIBRATION_BUCKETS):
        lower = bucket_index / CALIBRATION_BUCKETS
        upper = (bucket_index + 1) / CALIBRATION_BUCKETS
        values = [
            item for item in predictions
            if lower <= item["prediction"] < upper
            or (bucket_index == CALIBRATION_BUCKETS - 1 and item["prediction"] == upper)
        ]

        if values:
            buckets.append({
                "label": f"{lower:.1f}–{upper:.1f}",
                "count": len(values),
                "predicted": sum(item["prediction"] for item in values) / len(values),
                "actual": sum(item["actual"] for item in values) / len(values),
            })

    return buckets


def analyze_model(connection, mode=TOTAL):
    """
    Analyse historical match predictions using pre-match rating snapshots.

    mode='total' uses TOTAL ratings for every match.
    mode='pitch' uses BOX ratings for Box matches and HF ratings for HF matches.
    Matches with an exactly 50% prediction are excluded because the initial
    rating state contains no useful information for those observations.
    """
    if mode not in (TOTAL, "pitch"):
        raise ValueError("mode must be 'total' or 'pitch'")

    matches = get_matches(connection)
    predictions = []
    excluded = 0

    for match in matches.values():
        rating_type = TOTAL
        if mode == "pitch":
            if match["pitch"] == BOX:
                rating_type = BOX
            elif match["pitch"] == HF:
                rating_type = HF
            else:
                excluded += 1
                continue

        team_a_ids, team_b_ids = get_match_teams(connection, match["match_id"])
        if not team_a_ids or not team_b_ids:
            excluded += 1
            continue

        ratings = get_match_ratings(connection, match["match_id"])
        if any(
            player_id not in ratings or rating_type not in ratings[player_id]
            for player_id in team_a_ids + team_b_ids
        ):
            excluded += 1
            continue

        team_a = _team_rating(team_a_ids, match["players_a"], ratings, rating_type)
        team_b = _team_rating(team_b_ids, match["players_b"], ratings, rating_type)
        if team_a is None or team_b is None:
            excluded += 1
            continue

        prediction = _expected_score(team_a, team_b)
        if math.isclose(prediction, 0.5, abs_tol=1e-12):
            excluded += 1
            continue

        predictions.append({"prediction": prediction, "actual": _actual_score(match)})

    count = len(predictions)
    if not count:
        return {
            "mode": mode,
            "games": 0,
            "excluded": excluded,
            "brier": None,
            "log_loss": None,
            "mean_absolute_error": None,
            "accuracy": None,
            "calibration": [],
        }

    brier = sum((item["prediction"] - item["actual"]) ** 2 for item in predictions) / count
    log_loss = sum(_log_loss(item["prediction"], item["actual"]) for item in predictions) / count
    mean_absolute_error = sum(abs(item["prediction"] - item["actual"]) for item in predictions) / count
    accuracy = sum(
        (item["prediction"] > 0.5 and item["actual"] == 1.0)
        or (item["prediction"] < 0.5 and item["actual"] == 0.0)
        for item in predictions
    ) / count

    return {
        "mode": mode,
        "games": count,
        "excluded": excluded,
        "brier": brier,
        "log_loss": log_loss,
        "mean_absolute_error": mean_absolute_error,
        "accuracy": accuracy,
        "calibration": _calibration(predictions),
    }
