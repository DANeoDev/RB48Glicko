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


def _goal_diff_distribution(observations):
    """Return historical favourite goal-difference frequency and shares by pitch."""
    by_pitch = {}
    for obs in observations:
        pitch = obs["pitch"]
        diff = int(round(obs.get("raw_goal_diff", obs.get("goal_diff", 0.0))))
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


def _calibration_baskets(predictions, basket_count=10, step=None):
    """Group favourite predictions (>= 50%) into dynamic quantile intervals with equal match counts."""
    if not predictions:
        return []
    if isinstance(basket_count, float):
        # Gracefully handle legacy positional step argument
        basket_count = 10

    ordered = sorted(predictions, key=lambda x: x["prediction"])
    n = len(ordered)
    k_count = min(basket_count, n)
    slices = [ordered[k * n // k_count : (k + 1) * n // k_count] for k in range(k_count)]

    raw_bounds = [0.50]
    for k in range(k_count - 1):
        p_last = slices[k][-1]["prediction"]
        p_first = slices[k + 1][0]["prediction"]
        raw_bounds.append((p_last + p_first) / 2.0)
    last_p = slices[-1][-1]["prediction"]
    penult = raw_bounds[-1]
    raw_bounds.append(min(1.0, max(last_p + (last_p - penult), last_p + 0.01, 0.75)))

    for i in range(1, len(raw_bounds)):
        if raw_bounds[i] <= raw_bounds[i - 1] + 0.001:
            raw_bounds[i] = raw_bounds[i - 1] + 0.002

    baskets = []
    for k in range(k_count):
        vals = slices[k]
        low = raw_bounds[k]
        high = raw_bounds[k + 1]
        preds = [v["prediction"] for v in vals]
        acts = [v["actual"] for v in vals]
        diffs = [v["goal_diff"] for v in vals]
        avg_diff = sum(diffs) / len(vals)
        baskets.append({
            "label": f"{low * 100:.1f}% – {high * 100:.1f}%",
            "count": len(vals),
            "predicted": sum(preds) / len(vals),
            "actual": sum(acts) / len(vals),
            "avg_goal_diff": avg_diff,
            "goal_diff": avg_diff,
        })

    return baskets


_quantile_baskets = _calibration_baskets


def _linear_trend(predictions, value_key="actual", points=50, min_val=0.0, max_val=1.0):
    """Return a linear regression trendline for one observation field across predicted probabilities [0.5, 1.0]."""
    if len(predictions) < 2:
        return []
    xs = [item["prediction"] for item in predictions]
    ys = [item[value_key] for item in predictions]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 1e-12 else 0.0
    intercept = mean_y - slope * mean_x

    curve = []
    for step in range(points):
        x0 = 0.5 + (step / (points - 1)) * 0.5
        fitted = intercept + slope * x0
        if min_val is not None:
            fitted = max(min_val, fitted)
        if max_val is not None:
            fitted = min(max_val, fitted)
        curve.append({"predicted": x0, value_key: fitted})

    return curve


_lowess = _linear_trend


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
        if raw_prediction > 0.5:
            fav_goals, und_goals = goals_a, goals_b
        else:
            fav_goals, und_goals = goals_b, goals_a

        raw_diff = fav_goals - und_goals
        winner_goals = max(goals_a, goals_b)

        if mode == TOTAL and match["pitch"] == HF:
            # Scale HF games to 10 goals for winner (e.g. 4:1 -> 10:2.5, diff = +7.5; 1:4 -> 2.5:10, diff = -7.5)
            if winner_goals > 0:
                goal_diff = 10.0 * (fav_goals - und_goals) / winner_goals
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
    goal_diff_reference, goal_diff_pitch_totals = _goal_diff_distribution(observations)

    if count:
        min_obs = min(item["goal_diff"] for item in observations)
        max_obs = max(item["goal_diff"] for item in observations)
        if mode == TOTAL or pitch == BOX:
            goal_diff_max = max(10, int(math.ceil(max_obs / 2.0)) * 2)
            goal_diff_min = min(0, int(math.floor(min_obs / 2.0)) * 2)
            goal_diff_ticks = list(range(goal_diff_min, goal_diff_max + 1, 2))
        else:
            goal_diff_max = max(5, int(math.ceil(max_obs)))
            goal_diff_min = min(0, int(math.floor(min_obs)))
            step = 1 if (goal_diff_max - goal_diff_min) <= 8 else 2
            goal_diff_ticks = list(range(goal_diff_min, goal_diff_max + 1, step))
    else:
        goal_diff_min = 0
        goal_diff_max = 10 if (mode == TOTAL or pitch == BOX) else 5
        step = 2 if (mode == TOTAL or pitch == BOX) else 1
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
            "goal_diff_min": goal_diff_min,
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
        "goal_diff_lowess": _lowess(observations, "goal_diff", min_val=float(goal_diff_min), max_val=float(goal_diff_max)),
        "goal_diff_reference": goal_diff_reference,
        "goal_diff_pitch_totals": goal_diff_pitch_totals,
        "goal_diff_min": goal_diff_min,
        "goal_diff_max": goal_diff_max,
        "goal_diff_ticks": goal_diff_ticks,
    }
