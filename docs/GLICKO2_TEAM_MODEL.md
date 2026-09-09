# The RB48 Team-Based Glicko-2 Engine: Technical & Conceptual Documentation

> 🔄 **Dynamic Documentation Notice:** All values, formulas, and parameters in this document are automatically derived from the active system constants in [`scripts/glicko/glicko2.py`](../scripts/glicko/glicko2.py) and [`scripts/matches/match_entry.py`](../scripts/matches/match_entry.py).

## Table of Contents
1. [Introduction: Why Glicko-2 for Recreational Football?](#1-introduction-why-glicko-2-for-recreational-football)
2. [What Are the Numbers? (The Core Parameters)](#2-what-are-the-numbers-the-core-parameters)
   - [Rating (\(r\) / \(\mu\)): Expected Skill](#rating-r--mu-expected-skill)
   - [Rating Deviation (\(\text{RD}\) / \(\phi\)): Uncertainty](#rating-deviation-rd--phi-uncertainty)
   - [Volatility (\(\sigma\)): Erratic Performance vs. Consistency](#volatility-sigma-erratic-performance-vs-consistency)
   - [Conservative Rating (\(C\)): The Leaderboard Standard](#conservative-rating-c-the-leaderboard-standard)
3. [What Are the Numbers Good For?](#3-what-are-the-numbers-good-for)
4. [The RB48 Team Dilemma & The "Sieve" Philosophy](#4-the-rb48-team-dilemma--the-sieve-philosophy)
5. [How the Numbers Are Derived: Mathematical Architecture](#5-how-the-numbers-are-derived-mathematical-architecture)
   - [Scale Conversion (Standard to Glicko-2)](#step-0-scale-conversion)
   - [Step 1: Team Uncertainty & Quadratic Mean Pooling](#step-1-team-uncertainty--quadratic-mean-pooling)
   - [Step 2: Expected Win Probabilities & Opponent Impact](#step-2-expected-win-probabilities--opponent-impact)
   - [Step 3: Bayesian Teammate Clarity Dampening (\(w_{\text{team}}\))](#step-3-bayesian-teammate-clarity-dampening-w_textteam)
   - [Step 4: Session (Same-Day) Batching](#step-4-session-same-day-batching)
   - [Step 5: Updating Volatility (\(\sigma\)) via the Illinois Method](#step-5-updating-volatility-sigma-via-the-illinois-method)
   - [Step 6: Final Rating & RD Update](#step-6-final-rating--rd-update)
   - [Step 7: Inactivity Decay](#step-7-inactivity-decay)
6. [Special Features of RB48](#6-special-features-of-rb48)
   - [Multi-Track Engine (TOTAL, BOX, HF)](#multi-track-engine-total-box-hf)
   - [Anonymous / Ignored Guest Players (\(\text{IGNORED\_RD} = 480\))](#anonymous--ignored-guest-players-ignored_rd--480)
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

### Rating (\(r\) / \(\mu\)): Expected Skill
- **Default:** `1500`
- **What it represents:** The center of the player's skill distribution.


### Rating Deviation (\(\text{RD}\) / \(\phi\)): Uncertainty
- **Default:** `348` (uncalibrated newcomer) down to `~ 50.0 - 70.0` (established veteran).
- **What it represents:** The standard deviation (spread) of the skill curve.
- **Mathematical meaning:** There is a **95% probability** that the player's true skill lies within:
  $$\left[ \text{Rating} - 2 \cdot \text{RD}, \quad \text{Rating} + 2 \cdot \text{RD} \right]$$
  - A newcomer with \(r = 1500, \text{RD} = 348\) has a 95% confidence interval of \([804, 2196]\) (the system knows almost nothing).
  - A veteran with \(r = 1600, \text{RD} = 60\) has an interval of \([1480, 1720]\) (the system is confident).
- **Analogy:** The stiffness of the anchor. A high RD makes the player's rating responsive like a feather in a breeze. A low RD acts like a 10-ton ship anchor embedded in rock.

### Volatility (\(\sigma\)): Erratic Performance vs. Consistency
- **Default:** `0.03` (with \(\tau = 1\)).
- **What it represents:** How erratically a player's skill is expected to fluctuate over time.
- **Why it matters:** It acts as an **automatic circuit breaker**. If a veteran with \(\text{RD} = 60\) suddenly starts beating top-tier squads or losing to rookies, their volatility \(\sigma\) will spike. In Glicko-2, higher volatility **forces RD to expand**, allowing the player to quickly move to a new rating tier rather than being permanently trapped by a small RD.

### Conservative Rating (\(C\)): The Leaderboard Standard
- **Formula:**
  $$C = \text{Rating} - 3 \cdot \text{RD}$$
- **What it represents:** The statistical **99.7% lower bound** of the player's ability.
- **Why we use it for the Leaderboard:**
  If a new player joins, wins their first two games, and jumps to \(r = 1780\) with \(\text{RD} = 270\), their Conservative Rating is only:
  $$C = 1780 - 3(270) = 970$$
  They cannot claim the #1 spot on the leaderboard by being lucky. To climb the leaderboard, **you must prove consistency over time to shrink your RD**.

---

## 3. What Are the Numbers Good For?

| Application | How the numbers are used |
| :--- | :--- |
| **Match Outcome Prediction** | Using team ratings and opponent RD, the engine computes the exact win probability \(E \in (0, 1)\). |
| **Combinatorial Matchmaker** | Evaluates all \(\binom{N}{N/2}\) combinations of available players to generate teams as close to a 50/50 win probability as possible, balanced by positions. |
| **Individual Skill Attribution** | Separates a player's genuine contribution from their teammates' quality over time. |
| **Fair Inactivity Management** | Automatically expands uncertainty (\(\text{RD}\) by `+0.218034` per date) when players miss games, without artificially altering their rating. |

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
 │   {r_i, RD_i, σ_i}     │       │   {r_j, RD_j, σ_j}     │
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
Glicko-2 converts traditional ratings into an internal scale (\(\mu, \phi\)) centered at \(0.0\) using the scaling constant:
$$c = \frac{400}{\ln(10)} \approx 173.7178$$

$$\mu = \frac{r - 1500}{173.7178}, \qquad \phi = \frac{\text{RD}}{173.7178}$$

---

### Step 1: Team Uncertainty & Quadratic Mean Pooling

For a team of \(N\) players, where \(M\) players are anonymous guests:
1. **Team Rating (\(r_{\text{team}}\)):** The simple arithmetic mean of the known active players:
   $$r_{\text{team}} = \frac{1}{K} \sum_{i=1}^K r_i$$
2. **Team Uncertainty (\(\text{RD}_{\text{team}}\)):** Calculated via **quadratic mean (root-mean-square) pooling**:
   $$\text{RD}_{\text{team}} = \sqrt{\frac{\sum_{i=1}^K \text{RD}_i^2 + M \cdot 480^2}{N}}$$

#### Why Quadratic Mean?
In probability theory, independent variances add linearly (\(\text{Var}_{\text{sum}} = \sum \sigma_i^2\)). If you have five seasoned veterans with \(\text{RD} = 60\) and one wild newcomer with \(\text{RD} = 348\):
- Arithmetic mean: \(\frac{5 \times 60 + 348}{6} = 108.0\)
- Quadratic mean: \(\sqrt{\frac{5 \times 60^2 + 348^2}{6}} = 152.3\)

The quadratic mean correctly reflects that **a single unknown wildcard makes the entire team's performance significantly more volatile and harder to predict**.

---

### Step 2: Expected Win Probabilities & Opponent Impact

Glicko defines an impact function \(g(\phi)\) that shrinks the weight of an outcome if the opponent's skill is uncertain:
$$g(\phi_{\text{opp}}) = \frac{1}{\sqrt{1 + \frac{3 \phi_{\text{opp}}^2}{\pi^2}}}$$

The expected score \(E\) (win probability for Team A) is:
$$E = \frac{1}{1 + \exp\left( -g(\phi_{\text{opp}}) \cdot (\mu_{\text{own}} - \mu_{\text{opp}}) \right)}$$

- If the opponent team has \(\text{RD} \to 0\), \(g(\phi) \to 1.0\), and the win curve has full steepness.
- If the opponent team is highly uncalibrated (\(\text{RD} \to \infty\)), \(g(\phi) \to 0\), and \(E \to 0.50\) (the match approaches a coin toss in information content).

---

### Step 3: Bayesian Teammate Clarity Dampening (\(w_{\text{team}}\))

A central innovation of the RB48 model is **decoupling personal RD from team RD**.

In older, naive implementations, an individual's rating update used a combined virtual RD:
$$\text{virtual\_RD} = \sqrt{\frac{\text{RD}_{\text{player}}^2 + \text{RD}_{\text{team}}^2}{2}}$$
This had a disastrous flaw: if an established veteran with \(\text{RD} = 60\) played on a team with five rookies (\(\text{RD} = 348\)), the veteran's virtual RD was inflated to \(\approx 250\), causing their rating to swing wildly by 60–80 points from a single casual match!

#### The TrueSkill-Inspired Bayesian Solution:
We keep the player's personal uncertainty (\(\phi_{\text{player}}\)) intact. Instead, we calculate the root-mean-square RD of the player's **teammates**:
$$\text{RD}_{\text{teammates}} = \sqrt{\frac{\sum_{j \neq i} \text{RD}_j^2 + M \cdot 480^2}{N - 1}}$$

We then apply Glicko's native information clarity function to teammates:
$$w_{\text{team}} = g(\phi_{\text{teammates}}) = \frac{1}{\sqrt{1 + \frac{3 \phi_{\text{teammates}}^2}{\pi^2}}}$$

- **Playing with Veterans (\(\text{RD}_{\text{teammates}} \approx 60\)):**
  $$w_{\text{team}} \approx 0.98$$
  The team outcome is crystal clear. The individual receives **98%** of the full update.
- **Playing with Rookies (\(\text{RD}_{\text{teammates}} \approx 330\)):**
  $$w_{\text{team}} \approx 0.69$$
  Because teammates are unknown wildcards, the match contains high observational noise. Both rating change and RD reduction are **gracefully dampened by ~31%**.

---

### Step 4: Session (Same-Day) Batching

In RB48, players typically play 2 (sometimes 3) games in a single evening session.

#### The Problem with Match-by-Match Sequential Updating:
If Game 1 is processed immediately before Game 2:
1. **Order Dependence:** A player winning Game 1 and losing Game 2 gets a different rating than if they lost Game 1 and won Game 2!
2. **Cold-Start Tracksetter Bias:** For new players, Game 1 caused a massive shift from 1500 to 1690. When Game 2 began, the model falsely believed the player was an established 1690 player, distorting the expectations for Game 2.

#### The Session Batching Formula:
All matches played on the same calendar date are batched into a single rating period. For each match \(m \in \text{Session}\), we compute:
$$\text{match\_precision}_m = g(\phi_{\text{opp}, m})^2 \cdot E_m \cdot (1 - E_m)$$
$$\text{match\_difference}_m = g(\phi_{\text{opp}, m}) \cdot (s_m - E_m)$$

We accumulate effective precision and surprise across all games of the evening, weighted by teammate clarity \(w_{\text{team}, m}\):
$$I = \text{total\_effective\_precision} = \sum_{m} w_{\text{team}, m} \cdot \text{match\_precision}_m$$
$$\Delta = \text{total\_effective\_difference} = \sum_{m} w_{\text{team}, m} \cdot \text{match\_difference}_m$$

The estimated session variance is \(v = \frac{1}{I}\), and the normalized performance difference is \(\frac{\Delta}{I}\).

---

### Step 5: Updating Volatility (\(\sigma\)) via the Illinois Method

Glicko-2 updates volatility \(\sigma\) by finding the root of an objective function \(f(x)\):
$$f(x) = \frac{e^x (\Delta^2 / I^2 - \phi^2 - v - e^x)}{2 (\phi^2 + v + e^x)^2} - \frac{x - \ln(\sigma^2)}{\tau^2}$$
where \(\tau = 1\) governs the system volatility limit.

The engine solves \(f(x) = 0\) using the **Illinois algorithm** (an improved false-position root-finding technique with bracket halving) down to a convergence tolerance of \(\epsilon = 1e-06\). The new volatility is:
$$\sigma' = e^{A / 2}$$

---

### Step 6: Final Rating & RD Update

1. **Pre-Rating Uncertainty Expansion:**
   $$\phi^* = \sqrt{\phi^2 + (\sigma')^2}$$
2. **Posterior Uncertainty Update:**
   $$\phi' = \frac{1}{\sqrt{\frac{1}{(\phi^*)^2} + I}}$$
3. **Posterior Skill Mean Update:**
   $$\mu' = \mu + (\phi')^2 \cdot \Delta$$
4. **Scale Conversion Back to Traditional Scale:**
   $$r' = \mu' \cdot 173.7178 + 1500$$
   $$\text{RD}' = \phi' \cdot 173.7178$$

---

### Step 7: Inactivity Decay

When a player does not participate on a matchday date, their skill uncertainty naturally increases (their form becomes less certain).
The RB48 engine applies an **inactivity RD tick once per matchday date**:
$$\text{RD}_{\text{new}} = \text{RD}_{\text{old}} + 0.2180339$$
Over months of absence, an inactive player's RD slowly creeps upward back toward `348`, reflecting growing uncertainty without arbitrarily lowering their rating.

---

## 6. Special Features of RB48

### Multi-Track Engine (TOTAL, BOX, HF)
Recreational football dynamics change radically depending on the pitch:
- **`BOX` (Indoor enclosed pitch):** Small-sided (4v4 / 5v5), high goal count, rapid wall rebounds, favours quick footwork and high-tempo endurance.
- **`HF` (Half-pitch outdoor):** 6v6 / 7v7, larger spatial tactics, crossing, longer sprints, off-ball positioning.
- **`TOTAL`:** The unified multi-format composite skill rating.

The engine maintains three independent rating triples \((r, \text{RD}, \sigma)\) for each player. Matches played on a `box` pitch update both `BOX` and `TOTAL`, while `hf` fixtures update `HF` and `TOTAL`.

---

### Anonymous / Ignored Guest Players (\(\text{IGNORED\_RD} = 480\))
Often, recreational groups invite a guest or substitute player who is not registered in the league.
- In RB48, external players are assigned:
  $$\text{IGNORED\_RD} = 480$$
- **Why 480?**
  In Glicko's scaled units, \(\phi = 480 / 173.7178 \approx 2.763\).
  The clarity factor for an external player is:
  $$g(2.763) = \frac{1}{\sqrt{1 + \frac{3(2.763^2)}{\pi^2}}} \approx 0.55$$
  This ensures that guest players absorb noise and widen team variance without artificially inflating or collapsing the ratings of permanent league members.

---

### New Player Entry Certainty Calibration (5-Step Prior)
When onboarding a newcomer, the match organizer is prompted with:
> *"How certain are you about the strength of this player?"*

| Level | Initial RD | 95% Confidence Interval | Typical Single-Game Delta | Practical Usage |
| :--- | :---: | :---: | :---: | :--- |
| **Uncertain (standard — 350 RD)** | **`348`** | ± 700 pts | ± 80 to ± 180 pts | Complete unknown; never seen them play. |
| **Somewhat uncertain (250 RD)** | **`250`** | ± 500 pts | ± 45 to ± 90 pts | Heard about them, or seen 1 casual match. |
| **Moderately certain (180 RD)** | **`180`** | ± 360 pts | ± 25 to ± 50 pts | Played with them a few times before. |
| **Very certain (120 RD)** | **`120`** | ± 240 pts | ± 15 to ± 30 pts | Known player with established baseline. |
| **Extremely certain (80 RD)** | **`80`** | ± 160 pts | ± 8 to ± 15 pts | Fully verified veteran entering a new track. |

This transforms new player creation from an arbitrary default into a **true Bayesian prior**.

---

### Order Invariance Proof
Because session updates compute total precision \(I = \sum w_m I_m\) and total difference \(\Delta = \sum w_m \Delta_m\) by summing over games, addition is commutative:
$$I_1 + I_2 = I_2 + I_1 \qquad \text{and} \qquad \Delta_1 + \Delta_2 = \Delta_2 + \Delta_1$$

Swapping the chronological order of two matches on the same date produces the **identical final rating and RD down to 9 decimal places**.

---

## 7. Glossary & Reference Formulas

| Term | Symbol | Meaning / Current Active Value |
| :--- | :---: | :--- |
| **Rating** | \(r, \mu\) | Center of estimated skill distribution (default `1500`). |
| **Rating Deviation** | \(\text{RD}, \phi\) | Uncertainty / standard deviation of skill distribution (default `348`). |
| **Volatility** | \(\sigma\) | Consistency parameter measuring degree of erratic performance (default `0.03`). |
| **Conservative Rating** | \(C\) | \(r - 3\text{RD}\). Lower bound for leaderboard ranking. |
| **Scaling Constant** | \(c\) | `173.7178`. Converts between 1500-scale and Glicko-2 \(\mu\)-scale. |
| **Opponent Impact** | \(g(\phi)\) | \(\left(1 + \frac{3\phi^2}{\pi^2}\right)^{-1/2}\). Dampens weight of uncertain opponents. |
| **Teammate Clarity** | \(w_{\text{team}}\) | \(g(\phi_{\text{teammates}})\). Dampens weight when playing with uncalibrated teammates. |
| **System Constant** | \(\tau\) | `1`. Constrains volatility changes over time. |
| **Inactivity Tick** | — | `+0.2180339` RD per missed matchday date. |
| **Guest RD** | \(\text{IGNORED\_RD}\) | `480`. Assigned to unregistered external players. |
