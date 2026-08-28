"""Compare synthetic ground truth with the Glicko ratings recovered by RB48."""
from __future__ import annotations

import csv
import math
import os
import statistics
from pathlib import Path

from scripts.database.database import get_connection
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_ratings

ROOT = Path(__file__).resolve().parents[2]
TRUTH_FILE = ROOT / "data" / "demo" / "demo_players.csv"
DEMO_DB = ROOT / "data" / "demo" / "demo.db"


def load_truth():
    with TRUTH_FILE.open("r", encoding="utf-8", newline="") as file:
        return {
            int(row["player_id"]): {
                "name": row["name"],
                "true_strength": float(row["true_strength"]),
            }
            for row in csv.DictReader(file)
        }


def correlation(xs, ys):
    if len(xs) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) *
        sum((y - mean_y) ** 2 for y in ys)
    )
    return numerator / denominator if denominator else None


def ranking_agreement(rows, rating_type):
    truth_order = sorted(rows, key=lambda row: row["true_strength"], reverse=True)
    rating_order = sorted(rows, key=lambda row: row[rating_type], reverse=True)
    truth_rank = {row["player_id"]: rank for rank, row in enumerate(truth_order, 1)}
    rating_rank = {row["player_id"]: rank for rank, row in enumerate(rating_order, 1)}
    return sum(truth_rank[p] == rating_rank[p] for p in truth_rank) / len(truth_rank)


def main():
    if not DEMO_DB.exists():
        raise SystemExit("demo.db not found. Run: python -m scripts.simulation.run_demo")

    truth = load_truth()
    previous = os.environ.get("RB48_DATABASE_FILE")
    os.environ["RB48_DATABASE_FILE"] = str(DEMO_DB)
    try:
        connection = get_connection()
        ratings = get_ratings(connection)
        players = get_players(connection)
        connection.close()
    finally:
        if previous is None:
            os.environ.pop("RB48_DATABASE_FILE", None)
        else:
            os.environ["RB48_DATABASE_FILE"] = previous

    rows = []
    for player_id, info in truth.items():
        player_ratings = ratings.get(player_id, {})
        rows.append({
            "player_id": player_id,
            "name": info["name"],
            "true_strength": info["true_strength"],
            "total": player_ratings.get("total", {}).get("rating"),
            "box": player_ratings.get("box", {}).get("rating"),
            "hf": player_ratings.get("hf", {}).get("rating"),
        })

    print("\nRB48 DEMO — TRUE STRENGTH VS GLICKO\n")
    print(f"{'Player':<22} {'Truth':>7} {'Total':>8} {'Error':>8} {'Box':>8} {'HF':>8}")
    print("-" * 67)
    for row in sorted(rows, key=lambda x: x["true_strength"], reverse=True):
        total = row["total"]
        error = total - row["true_strength"] if total is not None else None
        print(f"{row['name']:<22} {row['true_strength']:>7.0f} {total:>8.1f} {error:>+8.1f} {row['box']:>8.1f} {row['hf']:>8.1f}")

    print("\nSUMMARY")
    for rating_type in ("total", "box", "hf"):
        valid = [r for r in rows if r[rating_type] is not None]
        truth_values = [r["true_strength"] for r in valid]
        rating_values = [r[rating_type] for r in valid]
        mae = statistics.mean(abs(a - b) for a, b in zip(truth_values, rating_values))
        rmse = math.sqrt(statistics.mean((a - b) ** 2 for a, b in zip(truth_values, rating_values)))
        corr = correlation(truth_values, rating_values)
        agreement = ranking_agreement(valid, rating_type)
        print(f"{rating_type.upper():<5}  MAE={mae:6.1f}  RMSE={rmse:6.1f}  correlation={corr:6.3f}  exact-rank={agreement:6.1%}")


if __name__ == "__main__":
    main()
