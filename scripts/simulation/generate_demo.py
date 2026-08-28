"""Generate a synthetic RB48 demo world from hidden player strengths."""

from dataclasses import dataclass
from pathlib import Path
import csv
import random

from scripts.simulation.true_strength1 import PLAYERS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = PROJECT_ROOT / "data" / "demo"
TRUTH_FILE = DEMO_DIR / "demo_players.csv"
MATCHES_FILE = DEMO_DIR / "demo_matches.csv"

SEED = 42
MATCH_COUNT = 1_500
TEAM_SIZE = 6
MIN_WIN_PROBABILITY = 0.05
MAX_WIN_PROBABILITY = 0.95


@dataclass(frozen=True)
class DemoPlayer:
    player_id: int
    name: str
    true_strength: float


# The hidden ground truth is defined separately in true_strength1.py.
# Player IDs are assigned according to the order in that file.
PLAYERS = tuple(
    DemoPlayer(player_id=index, name=name, true_strength=strength)
    for index, (name, strength) in enumerate(PLAYERS, start=1)
)


def write_truth_table(players=PLAYERS, path=TRUTH_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("player_id", "name", "true_strength"))
        writer.writerows((p.player_id, p.name, p.true_strength) for p in players)


def team_strength(players):
    return sum(player.true_strength for player in players) / len(players)


def win_probability(team_a_strength, team_b_strength):
    difference = team_a_strength - team_b_strength
    return 1.0 / (1.0 + 10 ** (-difference / 400.0))


def true_probability(team_a, team_b):
    return win_probability(team_strength(team_a), team_strength(team_b))


def choose_balanced_teams(players=PLAYERS, rng=None):
    rng = rng or random.Random(SEED)
    while True:
        selected = rng.sample(list(players), TEAM_SIZE * 2)
        team_a, team_b = selected[:TEAM_SIZE], selected[TEAM_SIZE:]
        probability = true_probability(team_a, team_b)
        if MIN_WIN_PROBABILITY <= probability <= MAX_WIN_PROBABILITY:
            return team_a, team_b, probability


def generate_score(probability, winner_a, pitch, rng):
    imbalance = abs(probability - 0.5) * 2.0
    expected_margin = 1.0 + 8.0 * imbalance
    variance = 1.5 if pitch == "box" else 2.0
    margin = max(1, round(rng.gauss(expected_margin, variance)))
    loser_goals = max(0, round(rng.gauss(6.0 if pitch == "box" else 7.0, 2.0)))
    winner_goals = loser_goals + margin
    if pitch == "box" and rng.random() < 0.75:
        winner_goals = max(winner_goals, 10)
        loser_goals = min(loser_goals, winner_goals - 1)
    return (winner_goals, loser_goals) if winner_a else (loser_goals, winner_goals)


def generate_matches(players=PLAYERS, count=MATCH_COUNT, seed=SEED):
    rng = random.Random(seed)
    matches = []
    for match_number in range(1, count + 1):
        team_a, team_b, probability = choose_balanced_teams(players, rng)
        if 0.4 <= probability <= 0.6:
            winner_a = rng.random() < probability
        elif probability < 0.4:
            winner_a = 0
        elif probability > 0.6:
            winner_a = 1
        pitch = "box" if rng.random() < 0.5 else "hf"
        goals_a, goals_b = generate_score(probability, winner_a, pitch, rng)
        matches.append({
            "match_id": match_number,
            "pitch": pitch,
            "players_a": ",".join(str(p.player_id) for p in team_a),
            "players_b": ",".join(str(p.player_id) for p in team_b),
            "true_team_a_strength": round(team_strength(team_a), 3),
            "true_team_b_strength": round(team_strength(team_b), 3),
            "true_probability_a": round(probability, 6),
            "goals_a": goals_a,
            "goals_b": goals_b,
        })
    return matches


def write_matches(matches, path=MATCHES_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        fieldnames = (
            "match_id", "pitch", "players_a", "players_b",
            "true_team_a_strength", "true_team_b_strength",
            "true_probability_a", "goals_a", "goals_b",
        )
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(matches)


def main():
    write_truth_table()
    matches = generate_matches()
    write_matches(matches)
    print(f"Wrote {len(PLAYERS)} demo players to {TRUTH_FILE}")
    print(f"Wrote {len(matches)} demo matches to {MATCHES_FILE}")


if __name__ == "__main__": main()
