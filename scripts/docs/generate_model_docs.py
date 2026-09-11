"""
Script to generate or update docs/GLICKO2_TEAM_MODEL.md dynamically
from active codebase constants in scripts/glicko/glicko2.py and scripts/matches/match_entry.py.

Whenever constants (e.g. INACTIVITY_RD_TICK, IGNORED_RD, DEFAULT_RD) are updated,
running this script (or running tests) automatically updates the documentation.
"""

import sys
from pathlib import Path
import math
import re

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.glicko.glicko2 import (  # noqa: E402
    DEFAULT_EPSILON,
    DEFAULT_RATING,
    DEFAULT_RD,
    DEFAULT_SIGMA,
    DEFAULT_TAU,
    GLICKO2_SCALE,
    IGNORED_RD,
    INACTIVITY_RD_TICK,
)
from scripts.matches.match_entry import (  # noqa: E402
    CERTAINTY_LEVELS,
)

DOCS_FILE = Path(__file__).resolve().parent.parent.parent / "docs" / "GLICKO2_TEAM_MODEL.md"
HTML_DOCS_FILE = Path(__file__).resolve().parent.parent.parent / "web" / "templates" / "model_docs_content.html"


def generate_markdown() -> str:
    """Generate the complete documentation markdown dynamically using live constants."""
    ignored_phi = IGNORED_RD / GLICKO2_SCALE
    ignored_impact = 1.0 / math.sqrt(1.0 + (3.0 * (ignored_phi ** 2)) / (math.pi ** 2))

    # Build certainty table dynamically
    certainty_rows = []
    descriptions = {
        "uncertain": ("± 700 pts", "± 80 to ± 180 pts", "Complete unknown; never seen them play."),
        "somewhat_uncertain": ("± 500 pts", "± 45 to ± 90 pts", "Heard about them, or seen 1 casual match."),
        "moderate": ("± 360 pts", "± 25 to ± 50 pts", "Played with them a few times before."),
        "high": ("± 240 pts", "± 15 to ± 30 pts", "Known player with established baseline."),
        "extremely_certain": ("± 160 pts", "± 8 to ± 15 pts", "Fully verified veteran entering a new track."),
    }

    for key, (rd_val, label) in CERTAINTY_LEVELS.items():
        conf_int, delta_str, usage = descriptions.get(
            key,
            (f"± {int(rd_val * 2)} pts", "Adaptive delta", "Custom calibration setting.")
        )
        certainty_rows.append(
            f"| **{label}** | **`{rd_val:g}`** | {conf_int} | {delta_str} | {usage} |"
        )
    certainty_table_md = "\n".join(certainty_rows)

    return f"""# The RB48 Team-Based Glicko-2 Engine: Technical & Conceptual Documentation

> 🔄 **Dynamic Documentation Notice:** All values, formulas, and parameters in this document are automatically derived from the active system constants in [`scripts/glicko/glicko2.py`](../scripts/glicko/glicko2.py) and [`scripts/matches/match_entry.py`](../scripts/matches/match_entry.py).

## Table of Contents
1. [Introduction: Why Glicko-2 for Recreational Football?](#1-introduction-why-glicko-2-for-recreational-football)
2. [What Are the Numbers? (The Core Parameters)](#2-what-are-the-numbers-the-core-parameters)
   - [Rating (\\(r\\) / \\(\\mu\\)): Expected Skill](#rating-r--mu-expected-skill)
   - [Rating Deviation (\\(\\text{{RD}}\\) / \\(\\phi\\)): Uncertainty](#rating-deviation-rd--phi-uncertainty)
   - [Volatility (\\(\\sigma\\)): Erratic Performance vs. Consistency](#volatility-sigma-erratic-performance-vs-consistency)
   - [Conservative Rating (\\(C\\)): The Leaderboard Standard](#conservative-rating-c-the-leaderboard-standard)
3. [What Are the Numbers Good For?](#3-what-are-the-numbers-good-for)
4. [The RB48 Team Dilemma & The "Sieve" Philosophy](#4-the-rb48-team-dilemma--the-sieve-philosophy)
5. [How the Numbers Are Derived: Mathematical Architecture](#5-how-the-numbers-are-derived-mathematical-architecture)
   - [Scale Conversion (Standard to Glicko-2)](#step-0-scale-conversion)
   - [Step 1: Team Uncertainty & Quadratic Mean Pooling](#step-1-team-uncertainty--quadratic-mean-pooling)
   - [Step 2: Expected Win Probabilities & Opponent Impact](#step-2-expected-win-probabilities--opponent-impact)
   - [Step 3: Bayesian Teammate Clarity Dampening (\\(w_{{\\text{{team}}}}\\))](#step-3-bayesian-teammate-clarity-dampening-w_textteam)
   - [Step 4: Session (Same-Day) Batching](#step-4-session-same-day-batching)
   - [Step 5: Updating Volatility (\\(\\sigma\\)) via the Illinois Method](#step-5-updating-volatility-sigma-via-the-illinois-method)
   - [Step 6: Final Rating & RD Update](#step-6-final-rating--rd-update)
   - [Step 7: Inactivity Decay](#step-7-inactivity-decay)
6. [Special Features of RB48](#6-special-features-of-rb48)
   - [Multi-Track Engine (TOTAL, BOX, HF)](#multi-track-engine-total-box-hf)
   - [Anonymous / Ignored Guest Players (\\(\\text{{IGNORED\\_RD}} = {IGNORED_RD:g}\\))](#anonymous--ignored-guest-players-ignored_rd--{IGNORED_RD:g})
   - [New Player Entry Certainty Calibration (5-Step Prior)](#new-player-entry-certainty-calibration-5-step-prior)
   - [Order Invariance Proof](#order-invariance-proof)
7. [Glossary & Reference Formulas](#7-glossary--reference-formulas)

---

## 1. Introduction: Why Glicko-2 for Recreational Football?

In recreational sports, measuring individual skill is notoriously difficult:
- **Raw Win Rate is Deceptive:** Win Rate is a decent measure of a players success over time, but it loses crucial information about the games difficulty. Two players of similair strength might have different winrates due to different **perceived strength** which resulted in a bias in matchmaking. Glicko2 offers a more sophisticated measure of how successfull a player has been.
- **The Elo Problem:** The classical Elo system (used in chess) tracks a single number. If an established player stops playing for 9 months, Elo assumes their skill is frozen with 100% confidence. Furthermore, if a brand-new player wins their first game, Elo updates their rating with the exact same rigid step size as a veteran with 200 games.

To solve this, **Professor Mark Glickman** invented **Glicko** (1995) and **Glicko-2** (2001). Glicko treats a player's skill not as a fixed number, but as a **probability distribution** (a Bell curve).

The RB48 engine takes Glickman's mathematical foundation—originally designed for 1-on-1 games like chess—and expands it into a **full Bayesian team rating engine** specifically tailored for multi-player recreational football (5v5 / 6v6).

---

## 2. What Are the Numbers? (The Core Parameters)

Every player in the RB48 database has three fundamental numbers per track:

```
                  Player Skill Distribution
                            μ (Rating)
                               │
                       ┌───────┴───────┐
                      ╱        │        ╲
                     ╱         │         ╲
                    ╱          │          ╲
                   ╱           │           ╲
     ─────────────┴────────────┼────────────┴─────────────
                  ◄────────────┼────────────►
                      -2·RD          +2·RD
                     (95% Confidence Interval)
```

### Rating (\\(r\\) / \\(\\mu\\)): Expected Skill
- **Default:** `{DEFAULT_RATING:g}`
- **What it represents:** The center of the player's skill distribution.


### Rating Deviation (\\(\\text{{RD}}\\) / \\(\\phi\\)): Uncertainty
- **Default:** `{DEFAULT_RD:g}` (uncalibrated newcomer) down to `~ 50.0 - 70.0` (established veteran).
- **What it represents:** The standard deviation (spread) of the skill curve.
- **Mathematical meaning:** There is a **95% probability** that the player's true skill lies within:
  $$\\left[ \\text{{Rating}} - 2 \\cdot \\text{{RD}}, \\quad \\text{{Rating}} + 2 \\cdot \\text{{RD}} \\right]$$
  - A newcomer with \\(r = {DEFAULT_RATING:g}, \\text{{RD}} = {DEFAULT_RD:g}\\) has a 95% confidence interval of \\([{DEFAULT_RATING - 2 * DEFAULT_RD:.0f}, {DEFAULT_RATING + 2 * DEFAULT_RD:.0f}]\\) (the system knows almost nothing).
  - A veteran with \\(r = 1600, \\text{{RD}} = 60\\) has an interval of \\([1480, 1720]\\) (the system is confident).
- **Analogy:** The stiffness of the anchor. A high RD makes the player's rating responsive like a feather in a breeze. A low RD acts like a 10-ton ship anchor embedded in rock.

### Volatility (\\(\\sigma\\)): Erratic Performance vs. Consistency
- **Default:** `{DEFAULT_SIGMA:g}` (with \\(\\tau = {DEFAULT_TAU:g}\\)).
- **What it represents:** How erratically a player's skill is expected to fluctuate over time.
- **Why it matters:** It acts as an **automatic circuit breaker**. If a veteran with \\(\\text{{RD}} = 60\\) suddenly starts beating top-tier squads or losing to rookies, their volatility \\(\\sigma\\) will spike. In Glicko-2, higher volatility **forces RD to expand**, allowing the player to quickly move to a new rating tier rather than being permanently trapped by a small RD.

### Conservative Rating (\\(C\\)): The Leaderboard Standard
- **Formula:**
  $$C = \\text{{Rating}} - 3 \\cdot \\text{{RD}}$$
- **What it represents:** The statistical **99.7% lower bound** of the player's ability.
- **Why we use it for the Leaderboard:**
  If a new player joins, wins their first two games, and jumps to \\(r = 1780\\) with \\(\\text{{RD}} = 270\\), their Conservative Rating is only:
  $$C = 1780 - 3(270) = 970$$
  They cannot claim the #1 spot on the leaderboard by being lucky. To climb the leaderboard, **you must prove consistency over time to shrink your RD**.

---

## 3. What Are the Numbers Good For?

| Application | How the numbers are used |
| :--- | :--- |
| **Match Outcome Prediction** | Using team ratings and opponent RD, the engine computes the exact win probability \\(E \\in (0, 1)\\). |
| **Combinatorial Matchmaker** | Evaluates all \\(\\binom{{N}}{{N/2}}\\) combinations of available players to generate teams as close to a 50/50 win probability as possible, balanced by positions. |
| **Individual Skill Attribution** | Separates a player's genuine contribution from their teammates' quality over time. |
| **Fair Inactivity Management** | Automatically expands uncertainty (\\(\\text{{RD}}\\) by `+{INACTIVITY_RD_TICK:g}` per date) when players miss games, without artificially altering their rating. |

---

## 4. The RB48 Team Dilemma & The "Sieve" Philosophy

A common misconception in team rating models is to break down a 6v6 match into 36 individual 1v1 duels:
> *"If player A is on Team 1 and player B is on Team 2, treat it as player A playing against player B."*

**This approach is fundamentally flawed in team sports.**
In football, an individual with a rating of 2000 playing with five complete beginners (rating 100) will lose against a balanced team of 1400s almost every single time. An individual 1v1 decomposition would falsely penalize the 2000 player as having lost 1v1 duels against 1400 players.

### The "Sieve" Philosophy:
1. **The Game is Played by Teams:** The contest is evaluated exclusively at the **team level** (Team A vs. Team B).
2. **Personal Information Emerges Over Time:** In any single match, the team outcome is a noisy signal of an individual's skill. But over 10, 20, or 50 games, players are reshuffled into different squads, playing with and against different teammates.
3. Like shaking gravel through a sieve, the shared team noise gradually falls away, leaving behind each player's true individual skill level.

---

## 5. How the Numbers Are Derived: Mathematical Architecture

Here is the exact step-by-step pipeline executed when a matchday session is processed:

```
 ┌────────────────────────┐       ┌────────────────────────┐
 │   Team A Composition   │       │   Team B Composition   │
 │   {{r_i, RD_i, σ_i}}     │       │   {{r_j, RD_j, σ_j}}     │
 └───────────┬────────────┘       └───────────┬────────────┘
             │                                │
             ▼                                ▼
 ┌────────────────────────┐       ┌────────────────────────┐
 │      Team A Rating     │       │      Team B Rating     │
 │  r_A = mean(r_i)       │       │  r_B = mean(r_j)       │
 │  RD_A = quad_mean(RD)  │       │  RD_B = quad_mean(RD)  │
 └───────────┬────────────┘       └───────────┬────────────┘
             │                                │
             └────────────────┬───────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │               Expected Outcome Calculation              │
 │          E = expected_score(r_A, r_B, RD_B)             │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │       Teammate Clarity Dampening (Bayesian Weight)      │
 │          w_team = g(phi_teammates)                      │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │               Session Batch Accumulation                │
 │       Precision = Σ w_m · g_opp² · E · (1 - E)          │
 │       Surprise  = Σ w_m · g_opp  · (score - E)          │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │           Illinois Secant Root Finding for σ'           │
 └────────────────────────────┬────────────────────────────┘
                              │
                              ▼
 ┌─────────────────────────────────────────────────────────┐
 │            Joint Rating & RD Update (New r, RD)         │
 └─────────────────────────────────────────────────────────┘
```

---

### Step 0: Scale Conversion
Glicko-2 converts traditional ratings into an internal scale (\\(\\mu, \\phi\\)) centered at \\(0.0\\) using the scaling constant:
$$c = \\frac{{400}}{{\\ln(10)}} \\approx {GLICKO2_SCALE}$$

$$\\mu = \\frac{{r - {DEFAULT_RATING:g}}}{{{GLICKO2_SCALE}}}, \\qquad \\phi = \\frac{{\\text{{RD}}}}{{{GLICKO2_SCALE}}}$$

---

### Step 1: Team Uncertainty & Quadratic Mean Pooling

For a team of \\(N\\) players, where \\(M\\) players are anonymous guests:
1. **Team Rating (\\(r_{{\\text{{team}}}}\\)):** The simple arithmetic mean of the known active players:
   $$r_{{\\text{{team}}}} = \\frac{{1}}{{K}} \\sum_{{i=1}}^K r_i$$
2. **Team Uncertainty (\\(\\text{{RD}}_{{\\text{{team}}}}\\)):** Calculated via **quadratic mean (root-mean-square) pooling**:
   $$\\text{{RD}}_{{\\text{{team}}}} = \\sqrt{{\\frac{{\\sum_{{i=1}}^K \\text{{RD}}_i^2 + M \\cdot {IGNORED_RD:g}^2}}{{N}}}}$$

#### Why Quadratic Mean?
In probability theory, independent variances add linearly (\\(\\text{{Var}}_{{\\text{{sum}}}} = \\sum \\sigma_i^2\\)). If you have five seasoned veterans with \\(\\text{{RD}} = 60\\) and one wild newcomer with \\(\\text{{RD}} = {DEFAULT_RD:g}\\):
- Arithmetic mean: \\(\\frac{{5 \\times 60 + {DEFAULT_RD:g}}}{{6}} = {(5 * 60 + DEFAULT_RD) / 6:.1f}\\)
- Quadratic mean: \\(\\sqrt{{\\frac{{5 \\times 60^2 + {DEFAULT_RD:g}^2}}{{6}}}} = {math.sqrt((5 * 3600 + DEFAULT_RD ** 2) / 6):.1f}\\)

The quadratic mean correctly reflects that **a single unknown wildcard makes the entire team's performance significantly more volatile and harder to predict**.

---

### Step 2: Expected Win Probabilities & Opponent Impact

Glicko defines an impact function \\(g(\\phi)\\) that shrinks the weight of an outcome if the opponent's skill is uncertain:
$$g(\\phi_{{\\text{{opp}}}}) = \\frac{{1}}{{\\sqrt{{1 + \\frac{{3 \\phi_{{\\text{{opp}}}}^2}}{{\\pi^2}}}}}}$$

The expected score \\(E\\) (win probability for Team A) is:
$$E = \\frac{{1}}{{1 + \\exp\\left( -g(\\phi_{{\\text{{opp}}}}) \\cdot (\\mu_{{\\text{{own}}}} - \\mu_{{\\text{{opp}}}}) \\right)}}$$

- If the opponent team has \\(\\text{{RD}} \\to 0\\), \\(g(\\phi) \\to 1.0\\), and the win curve has full steepness.
- If the opponent team is highly uncalibrated (\\(\\text{{RD}} \\to \\infty\\)), \\(g(\\phi) \\to 0\\), and \\(E \\to 0.50\\) (the match approaches a coin toss in information content).

---

### Step 3: Bayesian Teammate Clarity & Team Dilution (\\(w_{{\\text{{match}}}} = \\frac{{1}}{{\\sqrt{{N}}}} \\cdot w_{{\\text{{team}}}}\\))

A central innovation of the RB48 model is **decoupling personal RD from team RD** while accounting for team size dilution.

In older, naive implementations, an individual's rating update used a combined virtual RD:
$$\\text{{virtual\\_RD}} = \\sqrt{{\\frac{{\\text{{RD}}_{{\\text{{player}}}}^2 + \\text{{RD}}_{{\\text{{team}}}}^2}}{{2}}}}$$
This had a disastrous flaw: if an established veteran with \\(\\text{{RD}} = 60\\) played on a team with five rookies (\\(\\text{{RD}} = {DEFAULT_RD:g}\\)), the veteran's virtual RD was inflated to \\(\\approx 250\\), causing their rating to swing wildly by 60–80 points from a single casual match!

#### The Bayesian Teammate Clarity & Central Limit Dilution:
1. **Teammate Clarity (\\(w_{{\\text{{team}}}}\\)):** We calculate the root-mean-square RD of the player's **teammates**:
   $$\\text{{RD}}_{{\\text{{teammates}}}} = \\sqrt{{\\frac{{\\sum_{{j \\neq i}} \\text{{RD}}_j^2 + M \\cdot {IGNORED_RD:g}^2}}{{N - 1}}}}$$
   We then apply Glicko's native information clarity function:
   $$w_{{\\text{{team}}}} = g(\\phi_{{\\text{{teammates}}}}) = \\frac{{1}}{{\\sqrt{{1 + \\frac{{3 \\phi_{{\\text{{teammates}}}}^2}}{{\\pi^2}}}}}}$$
2. **Team Dilution (\\(\\frac{{1}}{{\\sqrt{{N}}}}\\)):**
   Under the Central Limit Theorem, the signal-to-noise ratio of an individual's contribution within a team of \\(N\\) players scales with \\(\\frac{{1}}{{\\sqrt{{N}}}}\\).
   - **1v1 Singles (\\(N=1\\)):** \\(1/\\sqrt{{1}} = 1.0\\) (100% full duel credit)
   - **5v5 Soccerbox (\\(N=5\\)):** \\(1/\\sqrt{{5}} \\approx 0.447\\) (44.7% credit)
   - **6v6 Half-Pitch (\\(N=6\\)):** \\(1/\\sqrt{{6}} \\approx 0.408\\) (40.8% credit)
   - **9v9 Large Match (\\(N=9\\)):** \\(1/\\sqrt{{9}} \\approx 0.333\\) (33.3% credit)

The composite match weighting factor is:
$$w_{{\\text{{match}}}} = \\frac{{1}}{{\\sqrt{{N}}}} \\cdot w_{{\\text{{team}}}}$$

---

### Step 4: Session (Same-Day) Batching

In RB48, players typically play 2 (sometimes 3) games in a single evening session.

#### The Problem with Match-by-Match Sequential Updating:
If Game 1 is processed immediately before Game 2:
1. **Order Dependence:** A player winning Game 1 and losing Game 2 gets a different rating than if they lost Game 1 and won Game 2!
2. **Cold-Start Tracksetter Bias:** For new players, Game 1 caused a massive shift from 1500 to 1690. When Game 2 began, the model falsely believed the player was an established 1690 player, distorting the expectations for Game 2.

#### The Session Batching Formula:
All matches played on the same calendar date are batched into a single rating period. For each match \\(m \\in \\text{{Session}}\\), we compute:
$$\\text{{match\\_precision}}_m = g(\\phi_{{\\text{{opp}}, m}})^2 \\cdot E_m \\cdot (1 - E_m)$$
$$\\text{{match\\_difference}}_m = g(\\phi_{{\\text{{opp}}, m}}) \\cdot (s_m - E_m)$$

We accumulate effective precision and surprise across all games of the evening, weighted by teammate clarity and team dilution:
$$I = \\text{{total\\_effective\\_precision}} = \\sum_{{m}} \\frac{{1}}{{\\sqrt{{N_m}}}} \\cdot w_{{\\text{{team}}, m}} \\cdot \\text{{match\\_precision}}_m$$
$$\\Delta = \\text{{total\\_effective\\_difference}} = \\sum_{{m}} \\frac{{1}}{{\\sqrt{{N_m}}}} \\cdot w_{{\\text{{team}}, m}} \\cdot \\text{{match\\_difference}}_m$$

The estimated session variance is \\(v = \\frac{{1}}{{I}}\\), and the normalized performance difference is \\(\\frac{{\\Delta}}{{I}}\\).

---

### Step 5: Updating Volatility (\\(\\sigma\\)) via the Illinois Method

Glicko-2 updates volatility \\(\\sigma\\) by finding the root of an objective function \\(f(x)\\):
$$f(x) = \\frac{{e^x (\\Delta^2 / I^2 - \\phi^2 - v - e^x)}}{{2 (\\phi^2 + v + e^x)^2}} - \\frac{{x - \\ln(\\sigma^2)}}{{\\tau^2}}$$
where \\(\\tau = {DEFAULT_TAU:g}\\) governs the system volatility limit.

The engine solves \\(f(x) = 0\\) using the **Illinois algorithm** (an improved false-position root-finding technique with bracket halving) down to a convergence tolerance of \\(\\epsilon = {DEFAULT_EPSILON:g}\\). The new volatility is:
$$\\sigma' = e^{{A / 2}}$$

---

### Step 6: Final Rating & RD Update

1. **Pre-Rating Uncertainty Expansion:**
   $$\\phi^* = \\sqrt{{\\phi^2 + (\\sigma')^2}}$$
2. **Posterior Uncertainty Update:**
   $$\\phi' = \\frac{{1}}{{\\sqrt{{\\frac{{1}}{{(\\phi^*)^2}} + I}}}}$$
3. **Posterior Skill Mean Update:**
   $$\\mu' = \\mu + (\\phi')^2 \\cdot \\Delta$$
4. **Scale Conversion Back to Traditional Scale:**
   $$r' = \\mu' \\cdot {GLICKO2_SCALE} + {DEFAULT_RATING:g}$$
   $$\\text{{RD}}' = \\phi' \\cdot {GLICKO2_SCALE}$$

---

### Step 7: Inactivity Decay

When a player does not participate on a matchday date, their skill uncertainty naturally increases (their form becomes less certain).
The RB48 engine applies an **inactivity RD tick once per matchday date**:
$$\\text{{RD}}_{{\\text{{new}}}} = \\text{{RD}}_{{\\text{{old}}}} + {INACTIVITY_RD_TICK}$$
Over months of absence, an inactive player's RD slowly creeps upward back toward `{DEFAULT_RD:g}`, reflecting growing uncertainty without arbitrarily lowering their rating.

---

## 6. Special Features of RB48

### Multi-Track Engine (TOTAL, BOX, HF)
Recreational football dynamics change radically depending on the pitch:
- **`BOX` (Indoor enclosed pitch):** Small-sided (4v4 / 5v5), high goal count, rapid wall rebounds, favours quick footwork and high-tempo endurance.
- **`HF` (Half-pitch outdoor):** 6v6 / 7v7, larger spatial tactics, crossing, longer sprints, off-ball positioning.
- **`TOTAL`:** The unified multi-format composite skill rating.

The engine maintains three independent rating triples \\((r, \\text{{RD}}, \\sigma)\\) for each player. Matches played on a `box` pitch update both `BOX` and `TOTAL`, while `hf` fixtures update `HF` and `TOTAL`.

---

### Anonymous / Ignored Guest Players (\\(\\text{{IGNORED\\_RD}} = {IGNORED_RD:g}\\))
Often, recreational groups invite a guest or substitute player who is not registered in the league.
- In RB48, external players are assigned:
  $$\\text{{IGNORED\\_RD}} = {IGNORED_RD:g}$$
- **Why {IGNORED_RD:g}?**
  In Glicko's scaled units, \\(\\phi = {IGNORED_RD:g} / {GLICKO2_SCALE} \\approx {ignored_phi:.3f}\\).
  The clarity factor for an external player is:
  $$g({ignored_phi:.3f}) = \\frac{{1}}{{\\sqrt{{1 + \\frac{{3({ignored_phi:.3f}^2)}}{{\\pi^2}}}}}} \\approx {ignored_impact:.2f}$$
  This ensures that guest players absorb noise and widen team variance without artificially inflating or collapsing the ratings of permanent league members.

---

### New Player Entry Certainty Calibration (5-Step Prior)
When onboarding a newcomer, the match organizer is prompted with:
> *"How certain are you about the strength of this player?"*

| Level | Initial RD | 95% Confidence Interval | Typical Single-Game Delta | Practical Usage |
| :--- | :---: | :---: | :---: | :--- |
{certainty_table_md}

This transforms new player creation from an arbitrary default into a **true Bayesian prior**.

---

### Order Invariance Proof
Because session updates compute total precision \\(I = \\sum w_m I_m\\) and total difference \\(\\Delta = \\sum w_m \\Delta_m\\) by summing over games, addition is commutative:
$$I_1 + I_2 = I_2 + I_1 \\qquad \\text{{and}} \\qquad \\Delta_1 + \\Delta_2 = \\Delta_2 + \\Delta_1$$

Swapping the chronological order of two matches on the same date produces the **identical final rating and RD down to 9 decimal places**.

---

## 7. Glossary & Reference Formulas

| Term | Symbol | Meaning / Current Active Value |
| :--- | :---: | :--- |
| **Rating** | \\(r, \\mu\\) | Center of estimated skill distribution (default `{DEFAULT_RATING:g}`). |
| **Rating Deviation** | \\(\\text{{RD}}, \\phi\\) | Uncertainty / standard deviation of skill distribution (default `{DEFAULT_RD:g}`). |
| **Volatility** | \\(\\sigma\\) | Consistency parameter measuring degree of erratic performance (default `{DEFAULT_SIGMA:g}`). |
| **Conservative Rating** | \\(C\\) | \\(r - 3\\text{{RD}}\\). Lower bound for leaderboard ranking. |
| **Scaling Constant** | \\(c\\) | `{GLICKO2_SCALE}`. Converts between 1500-scale and Glicko-2 \\(\\mu\\)-scale. |
| **Opponent Impact** | \\(g(\\phi)\\) | \\(\\left(1 + \\frac{{3\\phi^2}}{{\\pi^2}}\\right)^{{-1/2}}\\). Dampens weight of uncertain opponents. |
| **Teammate Clarity** | \\(w_{{\\text{{team}}}}\\) | \\(g(\\phi_{{\\text{{teammates}}}})\\). Dampens weight when playing with uncalibrated teammates. |
| **System Constant** | \\(\\tau\\) | `{DEFAULT_TAU:g}`. Constrains volatility changes over time. |
| **Inactivity Tick** | — | `+{INACTIVITY_RD_TICK}` RD per missed matchday date. |
| **Guest RD** | \\(\\text{{IGNORED\\_RD}}\\) | `{IGNORED_RD:g}`. Assigned to unregistered external players. |
"""


def markdown_to_html(md: str) -> str:
    """Convert Glicko-2 model documentation Markdown into styled HTML partial."""
    lines = md.splitlines()
    html_out = []

    in_code_block = False
    code_block_lines = []
    in_table = False
    table_headers = []
    table_aligns = []
    table_rows = []
    in_list = False
    list_type = None
    in_section = False
    in_blockquote = False
    blockquote_lines = []

    def format_inline(text: str) -> str:
        # Protect LaTeX math expressions \( ... \), \[ ... \], $$ ... $$, and $ ... $ so markdown syntax doesn't corrupt them
        math_placeholders = []

        def save_math(m):
            math_placeholders.append(m.group(0))
            return f"__MATH_EXPR_{len(math_placeholders)-1}__"

        def convert_single_dollar_math(m):
            math_content = m.group(1).strip()
            math_placeholders.append(f"\\({math_content}\\)")
            return f"__MATH_EXPR_{len(math_placeholders)-1}__"

        # First protect display and inline LaTeX math \( ... \), \[ ... \], $$ ... $$
        text = re.sub(r"\\\[.+?\\\]|\\\(.+?\\\)|\$\$.+?\$\$", save_math, text)

        # Protect and normalize single dollar inline math: $expr$ -> \(expr\)
        text = re.sub(r"(?<![\$\\])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\$)", convert_single_dollar_math, text)

        # Standard inline markdown formatting
        text = re.sub(r"`([^`]+)`", r'<span class="doc-pill">\1</span>', text)
        text = re.sub(r"\*\*([^*]+)\*\*", r'<strong>\1</strong>', text)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r'<em>\1</em>', text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

        # Restore pristine LaTeX math for KaTeX rendering
        for idx, math_str in enumerate(math_placeholders):
            text = text.replace(f"__MATH_EXPR_{idx}__", math_str)

        return text

    def slugify(text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
        return re.sub(r"[\s-]+", "-", text)

    def close_list():
        nonlocal in_list, list_type
        if in_list:
            html_out.append(f"</{list_type}>")
            in_list = False
            list_type = None

    def close_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote:
            content = " ".join(blockquote_lines).strip()
            if content:
                html_out.append(f'<div class="doc-callout"><p style="margin:0;">{format_inline(content)}</p></div>')
            in_blockquote = False
            blockquote_lines = []

    def close_table():
        nonlocal in_table, table_headers, table_aligns, table_rows
        if in_table:
            t_html = ['<div style="overflow-x: auto;"><table class="doc-table">']
            t_html.append("<thead><tr>")
            for idx, h in enumerate(table_headers):
                align = f' style="text-align: {table_aligns[idx]};"' if idx < len(table_aligns) and table_aligns[idx] else ""
                t_html.append(f"<th{align}>{format_inline(h)}</th>")
            t_html.append("</tr></thead>")
            t_html.append("<tbody>")
            for row in table_rows:
                t_html.append("<tr>")
                for idx, c in enumerate(row):
                    align = f' style="text-align: {table_aligns[idx]};"' if idx < len(table_aligns) and table_aligns[idx] else ""
                    t_html.append(f"<td{align}>{format_inline(c)}</td>")
                t_html.append("</tr>")
            t_html.append("</tbody></table></div>")
            html_out.append("\n".join(t_html))
            in_table = False
            table_headers = []
            table_aligns = []
            table_rows = []

    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()

        # Code block
        if trimmed.startswith("```"):
            close_list()
            close_blockquote()
            close_table()
            if in_code_block:
                code_content = "\n".join(code_block_lines)
                html_out.append(f'<pre class="doc-ascii-diagram">{code_content}</pre>')
                in_code_block = False
                code_block_lines = []
            else:
                in_code_block = True
                code_block_lines = []
            i += 1
            continue

        if in_code_block:
            code_block_lines.append(line)
            i += 1
            continue

        # Empty line
        if not trimmed:
            close_list()
            close_blockquote()
            close_table()
            i += 1
            continue

        # Math display: $$ ... $$
        if trimmed.startswith("$$"):
            close_list()
            close_blockquote()
            close_table()
            if trimmed.endswith("$$") and len(trimmed) > 4:
                formula = trimmed[2:-2].strip()
                html_out.append(f'<div class="doc-formula-box">$${formula}$$</div>')
                i += 1
                continue
            else:
                formula_lines = []
                first_line = trimmed[2:].strip()
                if first_line:
                    formula_lines.append(first_line)
                i += 1
                while i < len(lines):
                    l_trim = lines[i].strip()
                    if l_trim.endswith("$$"):
                        last_line = l_trim[:-2].strip()
                        if last_line:
                            formula_lines.append(last_line)
                        i += 1
                        break
                    formula_lines.append(lines[i].strip())
                    i += 1
                formula_combined = "\n".join(formula_lines).strip()
                html_out.append(f'<div class="doc-formula-box">$${formula_combined}$$</div>')
                continue

        # Math display: \[ ... \]
        if trimmed.startswith("\\["):
            close_list()
            close_blockquote()
            close_table()
            if trimmed.endswith("\\]") and len(trimmed) > 4:
                formula = trimmed[2:-2].strip()
                html_out.append(f'<div class="doc-formula-box">\\[{formula}\\]</div>')
                i += 1
                continue
            else:
                formula_lines = []
                first_line = trimmed[2:].strip()
                if first_line:
                    formula_lines.append(first_line)
                i += 1
                while i < len(lines):
                    l_trim = lines[i].strip()
                    if l_trim.endswith("\\]"):
                        last_line = l_trim[:-2].strip()
                        if last_line:
                            formula_lines.append(last_line)
                        i += 1
                        break
                    formula_lines.append(lines[i].strip())
                    i += 1
                formula_combined = "\n".join(formula_lines).strip()
                html_out.append(f'<div class="doc-formula-box">\\[{formula_combined}\\]</div>')
                continue

        # Horizontal rule
        if trimmed in ("---", "___", "***"):
            close_list()
            close_blockquote()
            close_table()
            i += 1
            continue

        # Blockquotes
        if trimmed.startswith(">"):
            close_list()
            close_table()
            bq_text = trimmed[1:].strip()
            if "Dynamic Documentation Notice" in bq_text:
                close_blockquote()
                html_out.append(
                    '<div class="doc-callout" style="border-left: 4px solid #7B52C5; background: rgba(123, 82, 197, 0.12); margin-bottom: 24px;">'
                    f'<p style="margin: 0; font-size: 14.5px; color: #ded6ed;">{format_inline(bq_text)}</p>'
                    '</div>'
                )
                in_blockquote = False
            else:
                in_blockquote = True
                blockquote_lines.append(bq_text)
            i += 1
            continue

        # Tables
        if trimmed.startswith("|") and trimmed.endswith("|"):
            close_list()
            close_blockquote()
            cells = [c.strip() for c in trimmed[1:-1].split("|")]
            if not in_table:
                table_headers = cells
                in_table = True
                table_rows = []
                if i + 1 < len(lines) and lines[i+1].strip().startswith("|") and "---" in lines[i+1]:
                    align_line = lines[i+1].strip()[1:-1].split("|")
                    table_aligns = []
                    for a in align_line:
                        a = a.strip()
                        if a.startswith(":") and a.endswith(":"):
                            table_aligns.append("center")
                        elif a.endswith(":"):
                            table_aligns.append("right")
                        else:
                            table_aligns.append("left")
                    i += 1
            else:
                table_rows.append(cells)
            i += 1
            continue

        # Headings
        if trimmed.startswith("#"):
            close_list()
            close_blockquote()
            close_table()

            if trimmed.startswith("# "):
                i += 1
                continue
            elif trimmed.startswith("## "):
                h2_text = trimmed[3:].strip()
                if in_section:
                    html_out.append("</section>")
                    in_section = False
                slug = slugify(h2_text)

                if "table of contents" in h2_text.lower():
                    toc_links = []
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("## ") and not lines[i].strip().startswith("---"):
                        t_line = lines[i].strip()
                        m = re.match(r"(?:\d+\.|\-)\s*\[([^\]]+)\]\(#([^)]+)\)", t_line)
                        if m:
                            title, anchor = m.groups()
                            toc_links.append(f'<a href="#{anchor}" class="doc-toc-link"><span>&bull;</span> <span>{format_inline(title)}</span></a>')
                        i += 1
                    html_out.append(
                        '<div class="doc-toc-card">'
                        '<h3>📑 Inhaltsverzeichnis / Table of Contents</h3>'
                        '<div class="doc-toc-grid">\n        '
                        + "\n        ".join(toc_links) +
                        '\n</div></div>'
                    )
                    continue

                html_out.append(f'<section id="{slug}" class="doc-section">')
                html_out.append(f'<h2>{format_inline(h2_text)}</h2>')
                in_section = True
                i += 1
                continue
            elif trimmed.startswith("### "):
                h3_text = trimmed[4:].strip()
                slug = slugify(h3_text)
                html_out.append(f'<h3 id="{slug}">{format_inline(h3_text)}</h3>')
                i += 1
                continue
            elif trimmed.startswith("#### "):
                h4_text = trimmed[5:].strip()
                html_out.append(f'<h4>{format_inline(h4_text)}</h4>')
                i += 1
                continue

        # Lists
        m_ul = re.match(r"^[-*]\s+(.*)", trimmed)
        m_ol = re.match(r"^\d+\.\s+(.*)", trimmed)
        if m_ul or m_ol:
            close_blockquote()
            close_table()
            item_text = m_ul.group(1) if m_ul else m_ol.group(1)
            cur_type = 'ul' if m_ul else 'ol'
            if not in_list or list_type != cur_type:
                close_list()
                in_list = True
                list_type = cur_type
                html_out.append(f"<{list_type}>")
            html_out.append(f"<li>{format_inline(item_text)}</li>")
            i += 1
            continue

        # Regular paragraph
        close_list()
        close_blockquote()
        close_table()
        html_out.append(f"<p>{format_inline(trimmed)}</p>")
        i += 1

    close_list()
    close_blockquote()
    close_table()
    if in_section:
        html_out.append("</section>")

    return "\n".join(html_out)


def generate_html(md_content: str | None = None) -> str:
    """Generate the semantic HTML documentation partial dynamically from Markdown."""
    if md_content is None:
        md_content = generate_markdown()
    return markdown_to_html(md_content)


def update_docs_file() -> Path:
    """Regenerate and write both the documentation markdown and HTML partial directly."""
    content = generate_markdown()
    DOCS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOCS_FILE.write_text(content, encoding="utf-8")

    html_content = generate_html(content)
    HTML_DOCS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HTML_DOCS_FILE.write_text(html_content, encoding="utf-8")

    return DOCS_FILE


if __name__ == "__main__":
    path = update_docs_file()
    print(f"Successfully generated dynamic model documentation at:\n{path}\nand\n{HTML_DOCS_FILE}")
