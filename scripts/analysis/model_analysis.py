"""Model analysis evaluating pre-match Glicko prediction calibration and accuracy."""

import math

from flask import has_request_context, request

from scripts.database.db_matches import get_match_teams, get_matches
from scripts.database.db_ratings import get_match_ratings
from scripts.glicko.glicko2 import (
    BOX,
    DEFAULT_SIGMA,
    GLICKO2_SCALE,
    HF,
    IGNORED_RD,
    TOTAL,
)


def _expected_score(team_a, team_b):
    """Return Glicko-2 expected score for two team ratings."""
    mu_a = (team_a["rating"] - 1500.0) / GLICKO2_SCALE
    mu_b = (team_b["rating"] - 1500.0) / GLICKO2_SCALE
    phi_b = team_b["rd"] / GLICKO2_SCALE
    impact = 1 / math.sqrt(1 + (3 * phi_b ** 2) / (math.pi ** 2))
    return 1 / (1 + math.exp(-impact * (mu_a - mu_b)))


def _team_rating(player_ids, total_players, ratings, rating_type):
    """Recreate the team-rating calculation used by the Glicko updater."""
    if not player_ids:
        return None
    ignored_players = total_players - len(player_ids)
    average_rating = sum(ratings[player][rating_type]["rating"] for player in player_ids) / len(player_ids)
    average_rd = math.sqrt(
        (sum(ratings[player][rating_type]["rd"] ** 2 for player in player_ids) + IGNORED_RD ** 2 * ignored_players)
        / total_players
    )
    average_sigma = math.sqrt(
        (sum(ratings[player][rating_type]["sigma"] ** 2 for player in player_ids) + DEFAULT_SIGMA ** 2 * ignored_players)
        / total_players
    )
    return {"rating": average_rating, "rd": average_rd, "sigma": average_sigma}


def _actual_score(match):
    if match["goals_a"] > match["goals_b"]:
        return 1.0
    if match["goals_a"] < match["goals_b"]:
        return 0.0
    return 0.5


def _favourite_observation(prediction, actual):
    """Orient a match toward the team the model predicts to be stronger."""
    if prediction > 0.5:
        return prediction, actual
    return 1.0 - prediction, 1.0 - actual


def _log_loss(prediction, actual):
    prediction = min(max(prediction, 1e-15), 1 - 1e-15)
    return -(actual * math.log(prediction) + (1 - actual) * math.log(1 - prediction))


def _goal_diff_percentiles(observations):
    """Assign an empirical, pitch-specific percentile to each goal difference."""
    by_pitch = {}
    for item in observations:
        by_pitch.setdefault(item["pitch"], []).append(item["goal_diff"])

    percentile_by_pitch = {}
    reference = {}
    for pitch, values in by_pitch.items():
        values = sorted(values)
        count = len(values)
        percentile_by_pitch[pitch] = {}
        reference[pitch] = []
        for value in sorted(set(values)):
            percentile = (
                sum(other < value for other in values) + 0.5 * sum(other == value for other in values)
            ) / count
            percentile_by_pitch[pitch][value] = percentile
            reference[pitch].append({
                "goal_diff": value,
                "percentile": percentile,
                "count": values.count(value),
            })

    for item in observations:
        item["goal_diff_percentile"] = percentile_by_pitch[item["pitch"]][item["goal_diff"]]

    return reference


def _quantile_baskets(predictions):
    """Create equal-count prediction baskets (deciles, or ventiles for larger sets)."""
    count = len(predictions)
    basket_count = 20 if count >= 200 else 10
    ordered = sorted(predictions, key=lambda item: item["prediction"])
    baskets = []

    for index in range(basket_count):
        start = index * count // basket_count
        end = (index + 1) * count // basket_count
        values = ordered[start:end]
        if not values:
            continue
        predictions_only = [item["prediction"] for item in values]
        actuals = [item["actual"] for item in values]
        goal_diff_percentiles = [item["goal_diff_percentile"] for item in values]
        baskets.append({
            "label": f"{min(predictions_only) * 100:.1f}–{max(predictions_only) * 100:.1f}%",
            "count": len(values),
            "predicted": sum(predictions_only) / len(values),
            "actual": sum(actuals) / len(values),
            "goal_diff_percentile": sum(goal_diff_percentiles) / len(values),
        })

    return baskets


def _lowess(predictions, value_key="actual", points=50, fraction=0.35):
    """Return a LOWESS curve for one observation field against prediction."""
    if len(predictions) < 10:
        return []
    ordered = sorted(predictions, key=lambda item: item["prediction"])
    xs = [item["prediction"] for item in ordered]
    ys = [item[value_key] for item in ordered]
    n = len(xs)
    span = max(3, int(math.ceil(fraction * n)))
    curve = []

    for step in range(points):
        x0 = step / (points - 1)
        distances = [abs(x - x0) for x in xs]
        bandwidth = sorted(distances)[min(span - 1, n - 1)]
        if bandwidth == 0:
            weights = [1.0 if distance == 0 else 0.0 for distance in distances]
        else:
            weights = [
                (1 - (distance / bandwidth) ** 3) ** 3 if distance <= bandwidth else 0.0
                for distance in distances
            ]
        weight_sum = sum(weights)
        if weight_sum == 0:
            continue
        mean_x = sum(weight * x for weight, x in zip(weights, xs)) / weight_sum
        mean_y = sum(weight * y for weight, y in zip(weights, ys)) / weight_sum
        sxx = sum(weight * (x - mean_x) ** 2 for weight, x in zip(weights, xs))
        sxy = sum(weight * (x - mean_x) * (y - mean_y) for weight, x, y in zip(weights, xs, ys))
        slope = sxy / sxx if sxx > 1e-12 else 0.0
        fitted = min(1.0, max(0.0, mean_y + slope * (x0 - mean_x)))
        curve.append({"predicted": x0, value_key: fitted})

    return curve


def analyze_model(connection, mode=TOTAL, pitch=None):
    """Analyse historical match predictions using pre-match rating snapshots."""
    if mode not in (TOTAL, "pitch"):
        raise ValueError("mode must be 'total' or 'pitch'")
    if pitch is None and mode == "pitch" and has_request_context():
        pitch = request.args.get("pitch", BOX)
    if pitch not in (None, BOX, HF):
        raise ValueError("pitch must be None, BOX, or HF")

    matches = get_matches(connection)
    observations = []
    excluded = 0

    for match in matches.values():
        if pitch is not None and match["pitch"] != pitch:
            continue
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

        raw_prediction = _expected_score(team_a, team_b)
        if math.isclose(raw_prediction, 0.5, abs_tol=1e-12):
            excluded += 1
            continue

        prediction, actual = _favourite_observation(raw_prediction, _actual_score(match))
        observations.append({
            "prediction": prediction,
            "actual": actual,
            "pitch": match["pitch"],
            "goal_diff": abs(match["goals_a"] - match["goals_b"]),
        })

    count = len(observations)
    if not count:
        return {
            "mode": mode,
            "pitch": pitch,
            "games": 0,
            "excluded": excluded,
            "brier": None,
            "log_loss": None,
            "mean_absolute_error": None,
            "accuracy": None,
            "calibration": [],
            "lowess": [],
            "goal_diff_lowess": [],
            "goal_diff_reference": {},
        }

    goal_diff_reference = _goal_diff_percentiles(observations)
    brier = sum((item["prediction"] - item["actual"]) ** 2 for item in observations) / count
    log_loss = sum(_log_loss(item["prediction"], item["actual"]) for item in observations) / count
    mean_absolute_error = sum(abs(item["prediction"] - item["actual"]) for item in observations) / count
    decisive = [item for item in observations if item["actual"] in (0.0, 1.0)]
    accuracy = sum(item["actual"] == 1.0 for item in decisive) / len(decisive) if decisive else None

    return {
        "mode": mode,
        "pitch": pitch,
        "games": count,
        "excluded": excluded,
        "brier": brier,
        "log_loss": log_loss,
        "mean_absolute_error": mean_absolute_error,
        "accuracy": accuracy,
        "calibration": _quantile_baskets(observations),
        "lowess": _lowess(observations, "actual"),
        "goal_diff_lowess": _lowess(observations, "goal_diff_percentile"),
        "goal_diff_reference": goal_diff_reference,
    }
