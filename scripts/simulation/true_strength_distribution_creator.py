"""Generate the hidden true-strength table used by the simulation."""

import random
from pathlib import Path

import matplotlib.pyplot as plt


# 48 football legends, ordered from strongest to weakest.
# The list is intentionally German-heavy while including major international legends.
PLAYER_NAMES = [
    "Franz Beckenbauer",
    "Gerd Müller",
    "Lothar Matthäus",
    "Lionel Messi",
    "Pelé",
    "Cristiano Ronaldo",
    "Johan Cruyff",
    "Diego Maradona",
    "Zinedine Zidane",
    "Miroslav Klose",
    "Karl-Heinz Rummenigge",
    "Manuel Neuer",
    "Philipp Lahm",
    "Bastian Schweinsteiger",
    "Toni Kroos",
    "Thomas Müller",
    "Sepp Maier",
    "Oliver Kahn",
    "Paul Breitner",
    "Andreas Brehme",
    "Matthias Sammer",
    "Uwe Seeler",
    "Fritz Walter",
    "Rivaldo",
    "Ronaldinho",
    "Ronaldo Nazário",
    "Xavi",
    "Andrés Iniesta",
    "Paolo Maldini",
    "Gianluigi Buffon",
    "Thierry Henry",
    "Michel Platini",
    "Marco van Basten",
    "Franco Baresi",
    "Kaká",
    "Luka Modrić",
    "Luis Suárez",
    "Neymar",
    "Mesut Özil",
    "Michael Ballack",
    "Mats Hummels",
    "Jürgen Klinsmann",
    "Rudi Völler",
    "Bernd Schuster",
    "Karl-Heinz Schnellinger",
    "Thomas Häßler",
    "Mario Götze",
    "Jürgen Kohler",
]


MEAN = 1500.0
STD_DEV = 200.0

OUTPUT_PATH = Path("scripts/simulation/true_strength1.py")
GRAPH_PATH = Path("scripts/simulation/true_strength1.png")


def create_simulation_table():
    """Generate 48 normally distributed strengths and assign them to the legends."""

    if len(PLAYER_NAMES) != 48:
        raise ValueError(
            f"Expected exactly 48 players, got {len(PLAYER_NAMES)}."
        )

    strengths = sorted(
        (random.gauss(MEAN, STD_DEV) for _ in range(48)),
        reverse=True,
    )
    players = tuple(zip(PLAYER_NAMES, strengths))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        file.write("# Automatically generated simulation data.\n")
        file.write("# Do not edit manually.\n\n")
        file.write("PLAYERS = (\n")
        for name, strength in players:
            file.write(f'    ("{name}", {strength:.2f}),\n')
        file.write(")\n")

    fig, ax = plt.subplots()
    ax.hist(strengths, bins="auto", density=True, alpha=0.6)
    ax.set_title("True Strength Distribution")
    ax.set_xlabel("True Strength")
    ax.set_ylabel("Probability Density")
    ax.grid(alpha=0.2)
    fig.savefig(GRAPH_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"\nGenerated {len(players)} players.")
    print(f"Saved simulation data to: {OUTPUT_PATH}")
    print(f"Saved distribution graph to: {GRAPH_PATH}\n")
    for name, strength in players:
        print(f"{name:<25} {strength:8.2f}")

    return players


if __name__ == "__main__":
    create_simulation_table()
