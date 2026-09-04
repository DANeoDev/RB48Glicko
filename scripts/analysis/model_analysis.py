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


def _goal_diff_distribution(matches_list):
    """Return historical goal-difference frequency and shares by pitch."""
    by_pitch = {}
    for match in matches_list:
        pitch = match["pitch"]
        diff = abs(match["goals_a"] - match["goals_b"])
        by_pitch.setdefault(pitch, []).append(diff)

    distribution = {}
    totals = {}
    for pitch, diffs in by_pitch.items():
        total = len(diffs)
        totals[pitch] = total
        distribution[pitch] = []
        for diff in sorted(set(diffs)):
            count = diffs.count(diff)
            distribution[pitch].append({
                "goal_diff": diff,
                "count": count,
                "share": (count / total) * 100 if total else 0.0,
            })

    return distribution, totals


def _calibration_baskets(predictions, step=0.05):
    """Group favourite predictions (>= 50%) into distinct probability intervals (e.g. 50-55%, 55-60%)."""
    if not predictions:
        return []
    baskets = []
    num_bins = int(round((1.0 - 0.5) / step))

    for i in range(num_bins):
        bin_start = 0.5 + i * step
        bin_end = bin_start + step
        if i == num_bins - 1:
            values = [
                item for item in predictions
                if bin_start - 1e-9 <= item["prediction"] <= bin_end + 1e-9
            ]
        else:
            values = [
                item for item in predictions
                if bin_start - 1e-9 <= item["prediction"] < bin_end - 1e-9
            ]

        if not values:
            continue

        predictions_only = [item["prediction"] for item in values]
        actuals = [item["actual"] for item in values]
        goal_diffs = [item["goal_diff"] for item in values]
        avg_diff = sum(goal_diffs) / len(values)
        baskets.append({
            "label": f"{bin_start * 100:.0f}% – {bin_end * 100:.0f}%",
            "count": len(values),
            "predicted": sum(predictions_only) / len(values),
            "actual": sum(actuals) / len(values),
            "avg_goal_diff": avg_diff,
            "goal_diff": avg_diff,
        })

    return baskets


_quantile_baskets = _calibration_baskets


def _lowess(predictions, value_key="actual", points=50, fraction=0.35, min_val=0.0, max_val=1.0):
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
        fitted = mean_y + slope * (x0 - mean_x)
        if min_val is not None:
            fitted = max(min_val, fitted)
        if max_val is not None:
            fitted = min(max_val, fitted)
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

        goals_a = match["goals_a"]
        goals_b = match["goals_b"]
        w = max(goals_a, goals_b)
        l = min(goals_a, goals_b)
        raw_diff = w - l

        if mode == TOTAL and match["pitch"] == HF:
            # Scale HF games to 10 goals for winner (e.g. 4:1 -> 10:2.5, diff = 7.5)
            if w > 0:
                goal_diff = 10.0 * (w - l) / w
            else:
                goal_diff = 0.0
        else:
            goal_diff = float(raw_diff)

        prediction, actual = _favourite_observation(raw_prediction, _actual_score(match))
        observations.append({
            "prediction": prediction,
            "actual": actual,
            "pitch": match["pitch"],
            "goal_diff": goal_diff,
            "raw_goal_diff": raw_diff,
        })

    count = len(observations)
    relevant_matches = [m for m in matches.values() if pitch is None or m["pitch"] == pitch]
    goal_diff_reference, goal_diff_pitch_totals = _goal_diff_distribution(relevant_matches)

    if mode == TOTAL or pitch == BOX:
        max_obs = max((item["goal_diff"] for item in observations), default=10.0)
        goal_diff_max = max(10, int(math.ceil(max_obs)))
        goal_diff_ticks = list(range(0, goal_diff_max + 1, 2))
    else:
        max_obs = max((item["goal_diff"] for item in observations), default=5.0)
        goal_diff_max = max(5, int(math.ceil(max_obs)))
        step = 1 if goal_diff_max <= 6 else 2
        goal_diff_ticks = list(range(0, goal_diff_max + 1, step))

    if not count:
        return {
            "mode": mode,
            "pitch": pitch,
            "games": 0,
            "excluded": excluded,
            "ece": None,
            "brier": None,
            "log_loss": None,
            "mean_absolute_error": None,
            "accuracy": None,
            "expected_accuracy": None,
            "calibration": [],
            "lowess": [],
            "goal_diff_lowess": [],
            "goal_diff_reference": goal_diff_reference,
            "goal_diff_pitch_totals": goal_diff_pitch_totals,
            "goal_diff_max": goal_diff_max,
            "goal_diff_ticks": goal_diff_ticks,
        }

    calibration_baskets = _calibration_baskets(observations)
    ece = (
        sum(b["count"] * abs(b["predicted"] - b["actual"]) for b in calibration_baskets) / count
        if calibration_baskets
        else None
    )
    brier = sum((item["prediction"] - item["actual"]) ** 2 for item in observations) / count
    log_loss = sum(_log_loss(item["prediction"], item["actual"]) for item in observations) / count
    mean_absolute_error = sum(abs(item["prediction"] - item["actual"]) for item in observations) / count
    decisive = [item for item in observations if item["actual"] in (0.0, 1.0)]
    accuracy = sum(item["actual"] == 1.0 for item in decisive) / len(decisive) if decisive else None
    expected_accuracy = (
        sum(item["prediction"] for item in decisive) / len(decisive)
        if decisive
        else (sum(item["prediction"] for item in observations) / count if count else None)
    )

    return {
        "mode": mode,
        "pitch": pitch,
        "games": count,
        "excluded": excluded,
        "ece": ece,
        "brier": brier,
        "log_loss": log_loss,
        "mean_absolute_error": mean_absolute_error,
        "accuracy": accuracy,
        "expected_accuracy": expected_accuracy,
        "calibration": calibration_baskets,
        "lowess": _lowess(observations, "actual", min_val=0.0, max_val=1.0),
        "goal_diff_lowess": _lowess(observations, "goal_diff", min_val=0.0, max_val=float(goal_diff_max)),
        "goal_diff_reference": goal_diff_reference,
        "goal_diff_pitch_totals": goal_diff_pitch_totals,
        "goal_diff_max": goal_diff_max,
        "goal_diff_ticks": goal_diff_ticks,
    }
