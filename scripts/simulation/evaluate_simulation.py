"""Evaluate the simulation as a reproducible Glicko experiment."""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from pathlib import Path

from scripts.glicko.glicko2 import DEFAULT_RD, DEFAULT_SIGMA, TOTAL, expected_score
from scripts.simulation.true_strength1 import PLAYERS

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = ROOT / "data" / "simulation_eval"
DB_FILE = ROOT / "data" / "demo" / "demo.db"
CHECKPOINT_FILE = EVAL_ROOT / "checkpoint_ratings.csv"

# Keep this schedule identical to run_demo.py.  The evaluation must never
# request checkpoints that were not exported by the simulation.
CHECKPOINTS = tuple(
    list(range(25, 151, 2))
    + list(range(154, 209, 4))
    + list(range(210, 501, 10))
    + list(range(550, 1001, 50))
    + list(range(1125, 1501, 125))
)

def experiment_dir() -> Path:
    return EVAL_ROOT / f"rd_{DEFAULT_RD:.5f}_sigma_{DEFAULT_SIGMA:.5f}"


def safe_corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def metrics(xs: list[float], ys: list[float]):
    if not xs:
        return None, None, None
    errors = [y - x for x, y in zip(xs, ys)]
    return (
        sum(e * e for e in errors) / len(errors),
        sum(abs(e) for e in errors) / len(errors),
        safe_corr(xs, ys),
    )


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            result[order[k]] = rank
        i = j + 1
    return result


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return safe_corr(ranks(xs), ranks(ys)) if len(xs) >= 2 else None


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def load_checkpoints() -> list[dict]:
    with CHECKPOINT_FILE.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def load_simulation_data():
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    matches = connection.execute(
        "SELECT match_id, date, pitch, goals_a, goals_b, players_a, players_b "
        "FROM matches ORDER BY date, match_id"
    ).fetchall()
    match_players = connection.execute(
        "SELECT match_id, player_id, team FROM match_players"
    ).fetchall()
    match_ratings = connection.execute(
        "SELECT match_id, player_id, rating_type, rating, rd, sigma "
        "FROM match_ratings WHERE rating_type = ?",
        (TOTAL,),
    ).fetchall()
    connection.close()

    teams = {}
    for row in match_players:
        a, b = teams.setdefault(row["match_id"], ([], []))
        (a if row["team"] == "a" else b).append(row["player_id"])
    snapshots = {(row["match_id"], row["player_id"]): dict(row) for row in match_ratings}
    return matches, teams, snapshots


def strength_analysis() -> list[dict]:
    truth = {i: strength for i, (_, strength) in enumerate(PLAYERS, 1)}
    rows = load_checkpoints()

    checkpoints = sorted({
        int(r["games"])
        for r in rows
        if r["rating_type"].lower() == "total"
    })

    output = []

    for checkpoint in checkpoints:
        subset = [
            r for r in rows
            if int(r["games"]) == checkpoint
            and r["rating_type"].lower() == "total"
        ]

        pairs = [
            (truth[int(r["player_id"])], float(r["rating"]))
            for r in subset
            if int(r["player_id"]) in truth
        ]

        if len(pairs) not in (0, len(truth)):
            raise ValueError(
                f"Incomplete strength checkpoint at {checkpoint} games: "
                f"{len(pairs)}/{len(truth)} players"
            )

        xs, ys = zip(*pairs) if pairs else ([], [])
        xs, ys = list(xs), list(ys)

        mse, mae, corr = metrics(xs, ys)

        output.append({
            "games": checkpoint,
            "players": len(pairs),
            "mse": mse,
            "mae": mae,
            "correlation": corr,
            "spearman": spearman(xs, ys),
            "bias_estimated_minus_true":
                (sum(ys) - sum(xs)) / len(pairs) if pairs else None,
            "mean_rd":
                sum(float(r["rd"]) for r in subset) / len(pairs)
                if pairs else None,
            "mean_sigma":
                sum(float(r["sigma"]) for r in subset) / len(pairs)
                if pairs else None,
        })

    return output

def probability_analysis():
    truth = {i: strength for i, (_, strength) in enumerate(PLAYERS, 1)}
    matches, teams, snapshots = load_simulation_data()
    observations, brier_rows = [], []

    for number, match in enumerate(matches, 1):
        match_id = match["match_id"]
        team_a, team_b = teams[match_id]
        true_a = sum(truth[p] for p in team_a) / len(team_a)
        true_b = sum(truth[p] for p in team_b) / len(team_b)
        true_probability = 1 / (1 + 10 ** (-(true_a - true_b) / 400))
        actual = 1.0 if match["goals_a"] > match["goals_b"] else 0.0
        ra = [snapshots[(match_id, p)] for p in team_a]
        rb = [snapshots[(match_id, p)] for p in team_b]
        rating_a = sum(r["rating"] for r in ra) / len(ra)
        rating_b = sum(r["rating"] for r in rb) / len(rb)
        opponent_rd = math.sqrt(sum(r["rd"] ** 2 for r in rb) / len(rb))
        probability = expected_score(rating_a, rating_b, opponent_rd)
        observations.append((true_probability, probability, actual))

        if number in CHECKPOINTS:
            true_values = [x[0] for x in observations]
            predicted = [x[1] for x in observations]
            actuals = [x[2] for x in observations]
            mse, mae, corr = metrics(true_values, predicted)
            base = sum(actuals) / len(actuals)
            outcome_bs = sum((p - y) ** 2 for p, y in zip(predicted, actuals)) / len(actuals)
            base_bs = sum((base - y) ** 2 for y in actuals) / len(actuals)
            fifty_bs = sum((0.5 - y) ** 2 for y in actuals) / len(actuals)

            ordered = sorted(zip(predicted, actuals), key=lambda x: x[0])
            bins = []
            for i in range(10):
                part = ordered[i * len(ordered) // 10:(i + 1) * len(ordered) // 10]
                if part:
                    bins.append((
                        len(part),
                        sum(x[0] for x in part) / len(part),
                        sum(x[1] for x in part) / len(part),
                    ))
            reliability = sum(n * (p - y) ** 2 for n, p, y in bins) / len(ordered)
            resolution = sum(n * (y - base) ** 2 for n, _, y in bins) / len(ordered)
            brier_rows.append({
                "games": number,
                "observations": len(observations),
                "outcome_brier": outcome_bs,
                "brier_50_50": fifty_bs,
                "brier_base_rate": base_bs,
                "brier_skill_vs_base": 1 - outcome_bs / base_bs if base_bs else None,
                "reliability": reliability,
                "resolution": resolution,
                "uncertainty": base * (1 - base),
                "probability_mse": mse,
                "probability_mae": mae,
                "probability_correlation": corr,
                "mean_true_probability": sum(true_values) / len(true_values),
                "mean_glicko_probability": sum(predicted) / len(predicted),
                "probability_bias": sum(p - t for t, p in zip(true_values, predicted)) / len(observations),
            })

    raw_rows = [
        {"match_number": i, "true_probability": t, "glicko_probability": p, "actual": a}
        for i, (t, p, a) in enumerate(observations, 1)
    ]
    return brier_rows, raw_rows


def first_checkpoint(rows, metric, threshold, direction=">="):
    for row in rows:
        value = row.get(metric)
        if value is None:
            continue
        value = float(value)
        crossed = (
            (direction == ">=" and value >= threshold)
            or (direction == ">" and value > threshold)
            or (direction == "<=" and value <= threshold)
            or (direction == "<" and value < threshold)
        )
        if crossed:
            return int(row["games"]), value
    return None, None


def benchmark_analysis(strength_rows, brier_rows):
    enriched = []
    for row in brier_rows:
        copy = dict(row)
        copy["brier_skill_vs_50"] = (
            1 - float(row["outcome_brier"]) / float(row["brier_50_50"])
            if row["brier_50_50"] else None
        )
        copy["abs_probability_bias"] = abs(float(row["probability_bias"]))
        enriched.append(copy)

    benchmarks = [
        ("Strength Pearson correlation", strength_rows, "correlation", 0.25, ">="),
        ("Strength Pearson correlation", strength_rows, "correlation", 0.50, ">="),
        ("Strength Pearson correlation", strength_rows, "correlation", 0.75, ">="),
        ("Strength Pearson correlation", strength_rows, "correlation", 0.90, ">="),
        ("Strength rank (Spearman) correlation", strength_rows, "spearman", 0.50, ">="),
        ("Strength rank (Spearman) correlation", strength_rows, "spearman", 0.75, ">="),
        ("Prediction beats 50/50 (Brier skill)", enriched, "brier_skill_vs_50", 0.0, ">"),
        ("Prediction beats base-rate baseline", enriched, "brier_skill_vs_base", 0.0, ">"),
        ("Probability correlation", enriched, "probability_correlation", 0.25, ">="),
        ("Probability correlation", enriched, "probability_correlation", 0.50, ">="),
        ("Probability correlation", enriched, "probability_correlation", 0.75, ">="),
        ("Probability MAE", enriched, "probability_mae", 0.10, "<="),
        ("Probability MAE", enriched, "probability_mae", 0.05, "<="),
        ("Probability MSE", enriched, "probability_mse", 0.01, "<="),
        ("Calibration reliability", enriched, "reliability", 0.01, "<="),
        ("Mean probability bias (absolute)", enriched, "abs_probability_bias", 0.01, "<="),
    ]

    output = []
    for label, source, metric, threshold, direction in benchmarks:
        games, value = first_checkpoint(source, metric, threshold, direction)
        output.append({
            "benchmark": label,
            "criterion": f"{direction} {threshold:g}",
            "first_checkpoint_games": games,
            "achieved_value": value,
        })
    return output


def write_config(path):
    path.write_text(json.dumps({
        "rating_type": "total",
        "starting_rating": 1500.0,
        "starting_rd": DEFAULT_RD,
        "starting_sigma": DEFAULT_SIGMA,
        "tau": 1.0,
        "simulation_games": 1_500,
        "checkpoints": list(CHECKPOINTS),
        "team_size": 6,
        "seed": 42,
        "true_strength_probability_scale": 400.0,
    }, indent=2) + "\n", encoding="utf-8")


def _save_plot(path, title, xlabel, ylabel, xs, series, ylim=None):
    import matplotlib.pyplot as plt
    plt.figure()
    for values, label in series:
        plt.plot(xs, values, marker="o", label=label)
    plt.xscale("log")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    if ylim is not None:
        plt.ylim(*ylim)
    if len(series) > 1:
        plt.legend()
    plt.grid(True, alpha=0.25)
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


def make_graphs(directory, strength_rows, brier_rows):
    try:
        import matplotlib.pyplot  # noqa: F401
    except ImportError:
        print("matplotlib not installed; CSV/JSON evaluation written, graphs skipped.")
        return
    xs = [r["games"] for r in strength_rows]
    bxs = [r["games"] for r in brier_rows]
    _save_plot(directory / "strength_correlation.png", "Does Glicko learn who is stronger?", "Games", "Pearson correlation", xs,
               [([r["correlation"] for r in strength_rows], "Rating ↔ true strength"), ([r["spearman"] for r in strength_rows], "Rank correlation")], (-1, 1))
    _save_plot(directory / "strength_error.png", "Absolute recovery of player strength", "Games", "Rating error", xs,
               [([r["mse"] for r in strength_rows], "MSE"), ([r["mae"] for r in strength_rows], "MAE")])
    _save_plot(directory / "probability_correlation.png", "Does Glicko learn the probability landscape?", "Games", "Correlation", bxs,
               [([r["probability_correlation"] for r in brier_rows], "True ↔ Glicko probability")], (-1, 1))
    _save_plot(directory / "probability_mse.png", "True probability recovery error", "Games", "Probability MSE", bxs,
               [([r["probability_mse"] for r in brier_rows], "Probability MSE")])
    _save_plot(directory / "brier_vs_baselines.png", "Outcome Brier score vs simple baselines", "Games", "Brier score", bxs,
               [([r["outcome_brier"] for r in brier_rows], "Glicko"), ([r["brier_base_rate"] for r in brier_rows], "Base rate"), ([r["brier_50_50"] for r in brier_rows], "50/50")])
    _save_plot(directory / "brier_decomposition.png", "Brier decomposition: calibration vs resolution", "Games", "Brier component", bxs,
               [([r["reliability"] for r in brier_rows], "Reliability (lower is better)"), ([r["resolution"] for r in brier_rows], "Resolution (higher is better)")])
    _save_plot(directory / "probability_bias.png", "Probability calibration bias", "Games", "Glicko − true probability", bxs,
               [([r["probability_bias"] for r in brier_rows], "Mean probability bias")])


def write_report(directory, strength_rows, brier_rows, benchmark_rows):
    table = "| Benchmark | Criterion | First checkpoint | Achieved value |\n|---|---:|---:|---:|\n" + "\n".join(
        f"| {r['benchmark']} | {r['criterion']} | {r['first_checkpoint_games']:,} games | {float(r['achieved_value']):.6g} |"
        if r["first_checkpoint_games"] is not None
        else f"| {r['benchmark']} | {r['criterion']} | not reached | — |"
        for r in benchmark_rows
    )
    report = f"""# Simulation evaluation

## Experiment

This experiment uses **fixed hidden player strengths** and 1,500 synthetic games. Glicko starts from the configured common rating, RD and sigma. Checkpoints use the exact same schedule as `run_demo.py`: dense sampling through the early convergence period, then progressively wider intervals through 1,500 games. Only TOTAL Glicko is evaluated.

The analysis separates **ordering**, **rating scale**, **probability recovery**, and **outcome prediction**. A temporary deterioration in probability metrics is therefore not automatically a failure: starting from identical ratings, Glicko can acquire directional information before its probability scale is correctly calibrated.

## Convergence benchmark table

The table gives the **first available checkpoint at which a practical benchmark is crossed**. The thresholds are conventions for comparing experiments, **not universal statistical standards**. A single crossing does not prove permanent convergence; the benchmark logic can later be extended with a persistence/stability requirement.

{table}

## Numerical outputs

- `strength_metrics.csv`: MSE, MAE, Pearson/Spearman correlation, bias, mean RD and mean sigma.
- `brier_metrics.csv`: outcome Brier metrics, Murphy decomposition, probability MSE/MAE/correlation and bias.
- `benchmark_metrics.csv`: first checkpoint crossing each convergence benchmark.
- `probability_observations.csv`: match-level true probability, Glicko probability and realised outcome.
- `config.json`: exact starting conditions and simulation parameters.

The checkpoint schedule is deliberately defined identically in the simulation exporter and evaluator. Missing `players=0` rows therefore indicate a genuinely missing snapshot rather than a checkpoint-definition mismatch.
"""
    (directory / "README.md").write_text(report, encoding="utf-8")


def main():
    directory = experiment_dir()
    directory.mkdir(parents=True, exist_ok=True)
    write_config(directory / "config.json")
    strength_rows = strength_analysis()
    brier_rows, raw_rows = probability_analysis()
    benchmark_rows = benchmark_analysis(strength_rows, brier_rows)
    write_csv(directory / "strength_metrics.csv", strength_rows)
    write_csv(directory / "brier_metrics.csv", brier_rows)
    write_csv(directory / "benchmark_metrics.csv", benchmark_rows)
    write_csv(directory / "probability_observations.csv", raw_rows)
    make_graphs(directory, strength_rows, brier_rows)
    write_report(directory, strength_rows, brier_rows, benchmark_rows)
    print(f"Evaluation written to {directory}")
    print(f"Starting RD: {DEFAULT_RD}; starting sigma: {DEFAULT_SIGMA}")


if __name__ == "__main__":
    main()
