"""Diagnostics for the synthetic demo: hidden truth versus recovered Glicko."""
from __future__ import annotations

import csv
import math
from pathlib import Path

from scripts.database.database import get_connection
from scripts.database.db_matches import get_matches, get_match_teams
from scripts.database.db_ratings import get_match_ratings, get_ratings
from scripts.glicko.glicko2 import TOTAL, BOX, HF, IGNORED_RD, DEFAULT_SIGMA

ROOT = Path(__file__).resolve().parents[2]
TRUTH_FILE = ROOT / "data" / "demo" / "demo_players.csv"
MATCHES_FILE = ROOT / "data" / "demo" / "demo_matches.csv"
SCALE = 173.7178


def _expected_score(a, b):
    mu_a = (a["rating"] - 1500.0) / SCALE
    mu_b = (b["rating"] - 1500.0) / SCALE
    phi_b = b["rd"] / SCALE
    impact = 1 / math.sqrt(1 + (3 * phi_b**2) / (math.pi**2))
    return 1 / (1 + math.exp(-impact * (mu_a - mu_b)))


def _team_rating(ids, total_players, ratings, rating_type):
    if not ids:
        return None
    ignored = total_players - len(ids)
    average_rating = sum(ratings[p][rating_type]["rating"] for p in ids) / len(ids)
    average_rd = math.sqrt((sum(ratings[p][rating_type]["rd"] ** 2 for p in ids) + IGNORED_RD**2 * ignored) / total_players)
    average_sigma = math.sqrt((sum(ratings[p][rating_type]["sigma"] ** 2 for p in ids) + DEFAULT_SIGMA**2 * ignored) / total_players)
    return {"rating": average_rating, "rd": average_rd, "sigma": average_sigma}


def load_truth():
    with TRUTH_FILE.open("r", encoding="utf-8", newline="") as f:
        return {int(r["player_id"]): {"name": r["name"], "strength": float(r["true_strength"])} for r in csv.DictReader(f)}


def load_match_truth():
    with MATCHES_FILE.open("r", encoding="utf-8", newline="") as f:
        return {int(r["match_id"]): r for r in csv.DictReader(f)}


def _actual(goals_a, goals_b):
    return 1.0 if goals_a > goals_b else 0.0 if goals_a < goals_b else 0.5


def build_analysis(connection, player_id=None):
    truth = load_truth()
    match_truth = load_match_truth()
    matches = get_matches(connection)
    current = get_ratings(connection)
    rows = []
    player_rows = []
    cumulative_true = cumulative_glicko = cumulative_actual = 0.0

    for sequence, (match_id, match) in enumerate(sorted(matches.items(), key=lambda x: x[1]["date"])):
        numeric_id = int(match_id.split("-")[0].replace("-", "")) if False else None
        # Demo match IDs are YYYY-MM-DD-1; use the stored chronological order to map to CSV truth.
        demo_number = sequence + 1
        mt = match_truth.get(demo_number)
        if not mt:
            continue
        team_a, team_b = get_match_teams(connection, match_id)
        snapshots = get_match_ratings(connection, match_id)
        rating_type = BOX if match["pitch"] == BOX else HF if match["pitch"] == HF else TOTAL
        if not snapshots or any(pid not in snapshots or rating_type not in snapshots[pid] for pid in team_a + team_b):
            continue
        ra = _team_rating(team_a, match["players_a"], snapshots, rating_type)
        rb = _team_rating(team_b, match["players_b"], snapshots, rating_type)
        glicko_p = _expected_score(ra, rb)
        true_p = float(mt["true_probability_a"])
        actual = _actual(int(match["goals_a"]), int(match["goals_b"]))
        row = {
            "match_id": match_id, "number": demo_number, "date": str(match["date"]), "pitch": match["pitch"],
            "team_a": team_a, "team_b": team_b, "true_probability": true_p, "glicko_probability": glicko_p,
            "actual": actual, "goals_a": int(match["goals_a"]), "goals_b": int(match["goals_b"]),
            "true_team_a": float(mt["true_team_a_strength"]), "true_team_b": float(mt["true_team_b_strength"]),
            "glicko_team_a": ra["rating"], "glicko_team_b": rb["rating"],
        }
        rows.append(row)
        if player_id is not None and (player_id in team_a or player_id in team_b):
            on_a = player_id in team_a
            expected_true = true_p if on_a else 1 - true_p
            expected_glicko = glicko_p if on_a else 1 - glicko_p
            teammate_ids = team_a if on_a else team_b
            opponent_ids = team_b if on_a else team_a
            teammate_ids = [p for p in teammate_ids if p != player_id]
            player_rows.append({**row, "player_expected_true": expected_true, "player_expected_glicko": expected_glicko,
                "player_actual": actual if on_a else 1 - actual,
                "avg_teammate_truth": sum(truth[p]["strength"] for p in teammate_ids) / len(teammate_ids),
                "avg_opponent_truth": sum(truth[p]["strength"] for p in opponent_ids) / len(opponent_ids)})

    for r in player_rows:
        cumulative_true += r["player_expected_true"]
        cumulative_glicko += r["player_expected_glicko"]
        cumulative_actual += r["player_actual"]
        r["cum_true"] = cumulative_true
        r["cum_glicko"] = cumulative_glicko
        r["cum_actual"] = cumulative_actual

    summary = []
    for pid, info in truth.items():
        rating = current.get(pid, {}).get("total", {}).get("rating")
        summary.append({"player_id": pid, "name": info["name"], "truth": info["strength"], "total": rating,
                        "error": rating - info["strength"] if rating is not None else None})
    summary.sort(key=lambda r: r["truth"], reverse=True)
    selected = next((r for r in summary if r["player_id"] == player_id), None)
    return {"summary": summary, "matches": rows, "player_matches": player_rows, "selected": selected}
