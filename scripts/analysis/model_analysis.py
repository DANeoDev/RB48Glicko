"""Model analysis evaluating pre-match Glicko prediction calibration and accuracy."""

import math

from flask import has_request_context, request

from scripts.database.db_matches import get_all_match_players, get_match_teams, get_matches
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_all_match_ratings, get_match_ratings, get_ratings
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
    return _build_analysis_result(observations, count, excluded, mode=mode, pitch=pitch)


def _build_analysis_result(observations, count, excluded, mode, pitch):
    """Aggregate raw observations into standard calibration metrics, LOWESS trendlines, and bins."""
    goal_diff_reference, goal_diff_pitch_totals = _goal_diff_distribution(observations)

    is_box_or_total = mode == TOTAL or pitch == BOX
    if count:
        min_obs = min(item["goal_diff"] for item in observations)
        max_obs = max(item["goal_diff"] for item in observations)
        if is_box_or_total:
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
        goal_diff_max = 10 if is_box_or_total else 5
        step = 2 if is_box_or_total else 1
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


def _classify_residual_status(z_score):
    """Classify a player's standardized calibration residual z-score."""
    if z_score is None:
        return "no_data"
    if z_score > 1.96:
        return "underestimated"
    if z_score > 1.0:
        return "slightly_underestimated"
    if z_score < -1.96:
        return "overestimated"
    if z_score < -1.0:
        return "slightly_overestimated"
    return "calibrated"


def _player_calibration_baskets(predictions, max_baskets=8):
    """Group player-oriented predictions across [0.0, 1.0] into adaptive quantile baskets."""
    if not predictions:
        return []

    ordered = sorted(predictions, key=lambda x: x["prediction"])
    n = len(ordered)
    if n < 3:
        k_count = 1
    else:
        k_count = min(max_baskets, max(2, n // 3))
        k_count = min(k_count, n)

    slices = [ordered[k * n // k_count : (k + 1) * n // k_count] for k in range(k_count)]

    first_p = slices[0][0]["prediction"]
    raw_bounds = [max(0.0, min(0.45, first_p - 0.02))]
    for k in range(k_count - 1):
        p_last = slices[k][-1]["prediction"]
        p_first = slices[k + 1][0]["prediction"]
        raw_bounds.append((p_last + p_first) / 2.0)
    last_p = slices[-1][-1]["prediction"]
    raw_bounds.append(min(1.0, max(0.55, last_p + 0.02)))

    for i in range(1, len(raw_bounds)):
        if raw_bounds[i] <= raw_bounds[i - 1] + 0.001:
            raw_bounds[i] = min(1.0, raw_bounds[i - 1] + 0.002)

    baskets = []
    for k in range(k_count):
        vals = slices[k]
        low = raw_bounds[k]
        high = raw_bounds[k + 1]
        preds = [v["prediction"] for v in vals]
        preds_without = [v.get("prediction_without", v["prediction"]) for v in vals]
        acts = [v["actual"] for v in vals]
        diffs = [v["goal_diff"] for v in vals]
        avg_pred = sum(preds) / len(vals)
        avg_act = sum(acts) / len(vals)
        avg_diff = sum(diffs) / len(vals)
        baskets.append({
            "label": f"{low * 100:.1f}% – {high * 100:.1f}%",
            "count": len(vals),
            "predicted": avg_pred,
            "predicted_without": sum(preds_without) / len(vals),
            "actual": avg_act,
            "residual": avg_act - avg_pred,
            "avg_goal_diff": avg_diff,
            "goal_diff": avg_diff,
        })

    return baskets


def _linear_trend_full_range(predictions, value_key="actual", points=50, min_val=0.0, max_val=1.0):
    """Return a linear regression trendline across the full [0.0, 1.0] probability domain."""
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
        x0 = (step / (points - 1)) * 1.0
        fitted = intercept + slope * x0
        if min_val is not None:
            fitted = max(min_val, fitted)
        if max_val is not None:
            fitted = min(max_val, fitted)
        curve.append({"predicted": x0, value_key: fitted})

    return curve


def _team_rating_without_player(player_ids, total_players, ratings, rating_type, excluded_player_id):
    """Compute team rating when one specific player is removed (treated as an unrated slot)."""
    remaining_ids = [pid for pid in player_ids if pid != excluded_player_id]
    if not remaining_ids:
        return {"rating": 1500.0, "rd": IGNORED_RD, "sigma": DEFAULT_SIGMA}
    return _team_rating(remaining_ids, total_players, ratings, rating_type)


def analyze_player_perspective(connection, player_id, mode=TOTAL, pitch=None):
    """
    Evaluate model calibration and residuals anchored to a specific player's perspective ('Heads' = Player's team).
    Includes exact 50:50 matches and counterfactual leave-one-out ('Streich-Test') evaluation.
    """
    if mode not in (TOTAL, "pitch"):
        raise ValueError("mode must be 'total' or 'pitch'")
    if pitch not in (None, BOX, HF):
        raise ValueError("pitch must be None, BOX, or HF")

    player_id = int(player_id)
    matches = get_matches(connection)
    all_match_players = get_all_match_players(connection)
    all_match_ratings = get_all_match_ratings(connection)
    players = get_players(connection)
    current_ratings = get_ratings(connection)

    player_info = players.get(player_id, {})
    player_name = player_info.get("aliases", [f"Player #{player_id}"])[0]
    rating_key = TOTAL if mode == TOTAL else (pitch or BOX)
    curr_r = current_ratings.get(player_id, {}).get(rating_key, {})

    observations = []
    residual_history = []
    cum_residual = 0.0
    cum_variance = 0.0

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
                continue

        mid = match["match_id"]
        mp_list = all_match_players.get(mid, [])
        team_a_ids = [p["player_id"] for p in mp_list if p["team"] == "a"]
        team_b_ids = [p["player_id"] for p in mp_list if p["team"] == "b"]
        if not team_a_ids or not team_b_ids:
            continue

        in_team_a = player_id in team_a_ids
        in_team_b = player_id in team_b_ids
        if not in_team_a and not in_team_b:
            continue

        ratings = all_match_ratings.get(mid, {})
        if any(
            pid not in ratings or rating_type not in ratings[pid]
            for pid in team_a_ids + team_b_ids
        ):
            continue

        team_a = _team_rating(team_a_ids, match["players_a"], ratings, rating_type)
        team_b = _team_rating(team_b_ids, match["players_b"], ratings, rating_type)
        if team_a is None or team_b is None:
            continue

        raw_prediction_a = _expected_score(team_a, team_b)
        raw_actual_a = _actual_score(match)

        if in_team_a:
            prediction = raw_prediction_a
            actual = raw_actual_a
            team_a_wo = _team_rating_without_player(team_a_ids, match["players_a"], ratings, rating_type, player_id)
            prediction_without = _expected_score(team_a_wo, team_b)
            own_goals, opp_goals = match["goals_a"], match["goals_b"]
        else:
            prediction = 1.0 - raw_prediction_a
            actual = 1.0 - raw_actual_a
            team_b_wo = _team_rating_without_player(team_b_ids, match["players_b"], ratings, rating_type, player_id)
            prediction_without = 1.0 - _expected_score(team_a, team_b_wo)
            own_goals, opp_goals = match["goals_b"], match["goals_a"]

        raw_diff = own_goals - opp_goals
        winner_goals = max(match["goals_a"], match["goals_b"])
        if mode == TOTAL and match["pitch"] == HF:
            goal_diff = (10.0 * raw_diff / winner_goals) if winner_goals > 0 else 0.0
        else:
            goal_diff = float(raw_diff)

        residual = actual - prediction
        variance = prediction * (1.0 - prediction)
        cum_residual += residual
        cum_variance += variance
        cum_std = math.sqrt(cum_variance) if cum_variance > 0 else 0.0
        step_z = (cum_residual / cum_std) if cum_std > 1e-12 else 0.0

        step_idx = len(observations) + 1
        obs = {
            "step": step_idx,
            "match_id": mid,
            "date": match["date"],
            "pitch": match["pitch"],
            "prediction": prediction,
            "prediction_without": prediction_without,
            "actual": actual,
            "residual": residual,
            "variance": variance,
            "goal_diff": goal_diff,
            "raw_goal_diff": raw_diff,
            "player_rating_before": ratings[player_id][rating_type]["rating"],
            "player_rd_before": ratings[player_id][rating_type]["rd"],
        }
        observations.append(obs)
        residual_history.append({
            "step": step_idx,
            "match_id": mid,
            "date": match["date"],
            "pitch": match["pitch"],
            "prediction": prediction,
            "prediction_without": prediction_without,
            "actual": actual,
            "residual": residual,
            "cum_residual": cum_residual,
            "cum_std": cum_std,
            "ci_95": 1.96 * cum_std,
            "z_score": step_z,
            "player_rating_before": ratings[player_id][rating_type]["rating"],
        })

    count = len(observations)
    if not count:
        return {
            "player_id": player_id,
            "player_name": player_name,
            "current_rating": curr_r.get("rating"),
            "current_rd": curr_r.get("rd"),
            "mode": mode,
            "pitch": pitch,
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "expected_win_rate": None,
            "actual_win_rate": None,
            "expected_win_rate_without": None,
            "net_residual_wins": 0.0,
            "residual_std": 0.0,
            "z_score": None,
            "status": "no_data",
            "balanced_games": 0,
            "balanced_expected_win_rate": None,
            "balanced_actual_win_rate": None,
            "balanced_net_residual": 0.0,
            "balanced_z_score": None,
            "ece": None,
            "brier": None,
            "brier_without": None,
            "brier_delta": None,
            "log_loss": None,
            "log_loss_without": None,
            "log_loss_delta": None,
            "mean_absolute_error": None,
            "calibration": [],
            "lowess": [],
            "without_lowess": [],
            "residual_history": [],
            "residual_y_max": 2.0,
        }

    wins = sum(1 for o in observations if o["actual"] == 1.0)
    draws = sum(1 for o in observations if o["actual"] == 0.5)
    losses = sum(1 for o in observations if o["actual"] == 0.0)

    expected_win_rate = sum(o["prediction"] for o in observations) / count
    actual_win_rate = sum(o["actual"] for o in observations) / count
    expected_win_rate_without = sum(o["prediction_without"] for o in observations) / count

    residual_std = math.sqrt(cum_variance) if cum_variance > 0 else 0.0
    z_score = (cum_residual / residual_std) if residual_std > 1e-12 else 0.0

    # Isolate balanced Matchmaker games (45% <= E_X <= 55%)
    balanced_obs = [o for o in observations if 0.45 <= o["prediction"] <= 0.55]
    balanced_games = len(balanced_obs)
    if balanced_games:
        balanced_expected = sum(o["prediction"] for o in balanced_obs) / balanced_games
        balanced_actual = sum(o["actual"] for o in balanced_obs) / balanced_games
        balanced_net_res = sum(o["residual"] for o in balanced_obs)
        balanced_var = sum(o["variance"] for o in balanced_obs)
        balanced_z = (balanced_net_res / math.sqrt(balanced_var)) if balanced_var > 1e-12 else 0.0
    else:
        balanced_expected = None
        balanced_actual = None
        balanced_net_res = 0.0
        balanced_z = None

    baskets = _player_calibration_baskets(observations)
    ece = (
        sum(b["count"] * abs(b["predicted"] - b["actual"]) for b in baskets) / count
        if baskets
        else None
    )

    brier = sum((o["prediction"] - o["actual"]) ** 2 for o in observations) / count
    brier_without = sum((o["prediction_without"] - o["actual"]) ** 2 for o in observations) / count
    brier_delta = brier - brier_without

    log_loss = sum(_log_loss(o["prediction"], o["actual"]) for o in observations) / count
    log_loss_without = sum(_log_loss(o["prediction_without"], o["actual"]) for o in observations) / count
    log_loss_delta = log_loss - log_loss_without

    mae = sum(abs(o["prediction"] - o["actual"]) for o in observations) / count

    max_abs_res = max(
        [abs(h["cum_residual"]) for h in residual_history] + [h["ci_95"] for h in residual_history] + [2.0]
    )
    residual_y_max = float(max(2, int(math.ceil(max_abs_res))))

    return {
        "player_id": player_id,
        "player_name": player_name,
        "current_rating": curr_r.get("rating"),
        "current_rd": curr_r.get("rd"),
        "mode": mode,
        "pitch": pitch,
        "games": count,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "expected_win_rate": expected_win_rate,
        "actual_win_rate": actual_win_rate,
        "expected_win_rate_without": expected_win_rate_without,
        "net_residual_wins": cum_residual,
        "residual_std": residual_std,
        "z_score": z_score,
        "status": _classify_residual_status(z_score),
        "balanced_games": balanced_games,
        "balanced_expected_win_rate": balanced_expected,
        "balanced_actual_win_rate": balanced_actual,
        "balanced_net_residual": balanced_net_res,
        "balanced_z_score": balanced_z,
        "ece": ece,
        "brier": brier,
        "brier_without": brier_without,
        "brier_delta": brier_delta,
        "log_loss": log_loss,
        "log_loss_without": log_loss_without,
        "log_loss_delta": log_loss_delta,
        "mean_absolute_error": mae,
        "calibration": baskets,
        "lowess": _linear_trend_full_range(observations, "actual", min_val=0.0, max_val=1.0),
        "without_lowess": _linear_trend_full_range(
            [{"prediction": o["prediction"], "actual": o["prediction_without"]} for o in observations],
            "actual",
            min_val=0.0,
            max_val=1.0,
        ),
        "residual_history": residual_history,
        "residual_y_max": residual_y_max,
    }


def analyze_all_players_summary(connection, mode=TOTAL, pitch=None):
    """
    Compute a single-pass summary of player-perspective calibration residuals and leave-one-out
    log-loss deltas across all players for the Webmaster selector and overview table.
    """
    if mode not in (TOTAL, "pitch"):
        raise ValueError("mode must be 'total' or 'pitch'")
    if pitch not in (None, BOX, HF):
        raise ValueError("pitch must be None, BOX, or HF")

    matches = get_matches(connection)
    all_match_players = get_all_match_players(connection)
    all_match_ratings = get_all_match_ratings(connection)
    players = get_players(connection)
    current_ratings = get_ratings(connection)
    rating_key = TOTAL if mode == TOTAL else (pitch or BOX)

    accum = {
        pid: {
            "games": 0,
            "sum_pred": 0.0,
            "sum_act": 0.0,
            "sum_res": 0.0,
            "sum_var": 0.0,
            "balanced_games": 0,
            "balanced_act": 0.0,
            "balanced_pred": 0.0,
            "sum_ll_with": 0.0,
            "sum_ll_without": 0.0,
        }
        for pid in players
    }

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
                continue

        mid = match["match_id"]
        mp_list = all_match_players.get(mid, [])
        team_a_ids = [p["player_id"] for p in mp_list if p["team"] == "a"]
        team_b_ids = [p["player_id"] for p in mp_list if p["team"] == "b"]
        if not team_a_ids or not team_b_ids:
            continue

        ratings = all_match_ratings.get(mid, {})
        if any(
            pid not in ratings or rating_type not in ratings[pid]
            for pid in team_a_ids + team_b_ids
        ):
            continue

        team_a = _team_rating(team_a_ids, match["players_a"], ratings, rating_type)
        team_b = _team_rating(team_b_ids, match["players_b"], ratings, rating_type)
        if team_a is None or team_b is None:
            continue

        raw_pred_a = _expected_score(team_a, team_b)
        raw_act_a = _actual_score(match)

        for pid in team_a_ids:
            if pid not in accum:
                continue
            team_a_wo = _team_rating_without_player(team_a_ids, match["players_a"], ratings, rating_type, pid)
            pred_wo = _expected_score(team_a_wo, team_b)
            st = accum[pid]
            st["games"] += 1
            st["sum_pred"] += raw_pred_a
            st["sum_act"] += raw_act_a
            st["sum_res"] += raw_act_a - raw_pred_a
            st["sum_var"] += raw_pred_a * (1.0 - raw_pred_a)
            st["sum_ll_with"] += _log_loss(raw_pred_a, raw_act_a)
            st["sum_ll_without"] += _log_loss(pred_wo, raw_act_a)
            if 0.45 <= raw_pred_a <= 0.55:
                st["balanced_games"] += 1
                st["balanced_pred"] += raw_pred_a
                st["balanced_act"] += raw_act_a

        pred_b = 1.0 - raw_pred_a
        act_b = 1.0 - raw_act_a
        for pid in team_b_ids:
            if pid not in accum:
                continue
            team_b_wo = _team_rating_without_player(team_b_ids, match["players_b"], ratings, rating_type, pid)
            pred_wo = 1.0 - _expected_score(team_a, team_b_wo)
            st = accum[pid]
            st["games"] += 1
            st["sum_pred"] += pred_b
            st["sum_act"] += act_b
            st["sum_res"] += act_b - pred_b
            st["sum_var"] += pred_b * (1.0 - pred_b)
            st["sum_ll_with"] += _log_loss(pred_b, act_b)
            st["sum_ll_without"] += _log_loss(pred_wo, act_b)
            if 0.45 <= pred_b <= 0.55:
                st["balanced_games"] += 1
                st["balanced_pred"] += pred_b
                st["balanced_act"] += act_b

    summary = []
    for pid, p_info in players.items():
        st = accum[pid]
        games = st["games"]
        aliases = p_info.get("aliases", [])
        name = aliases[0] if aliases else f"Player #{pid}"
        curr_r = current_ratings.get(pid, {}).get(rating_key, {})
        if games > 0:
            std = math.sqrt(st["sum_var"]) if st["sum_var"] > 0 else 0.0
            z_val = (st["sum_res"] / std) if std > 1e-12 else 0.0
            exp_wr = st["sum_pred"] / games
            act_wr = st["sum_act"] / games
            ll_delta = (st["sum_ll_with"] - st["sum_ll_without"]) / games
            bal_act = (st["balanced_act"] / st["balanced_games"]) if st["balanced_games"] else None
        else:
            z_val = None
            exp_wr = None
            act_wr = None
            ll_delta = None
            bal_act = None

        summary.append({
            "id": pid,
            "name": name,
            "aliases": aliases,
            "search_text": " ".join(aliases).lower() if aliases else name.lower(),
            "rating": curr_r.get("rating"),
            "rd": curr_r.get("rd"),
            "games": games,
            "expected_win_rate": exp_wr,
            "actual_win_rate": act_wr,
            "net_residual_wins": st["sum_res"],
            "z_score": z_val,
            "status": _classify_residual_status(z_val),
            "balanced_games": st["balanced_games"],
            "balanced_actual_win_rate": bal_act,
            "log_loss_delta": ll_delta,
        })

    summary.sort(key=lambda item: item["name"].lower())
    return summary
