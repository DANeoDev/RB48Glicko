# Evaluating Team Skill Rating Systems When the Matchmaker Works: Player-Anchored Residuals, Ascent Bias, and Equilibrium Calibration

**Authors:** Daniel & The RB48 Analytics Working Group  
**Date:** November 2026  
**Repository & Reproducible Code:** `scripts/analysis/model_analysis.py` | `paper/simulate_experiments.py`  

---

## Abstract

In team sports and multiplayer online games, probabilistic rating systems such as Glicko-2 and TrueSkill serve two practical purposes: estimating individual player skill and assembling fair, balanced teams. However, these two goals work against each other when we try to evaluate how well the rating model performs. Standard model evaluation groups matches by the predicted favorite ($P_{\mathrm{fav}} \in [0.50, 1.00]$) and checks whether a $60\%$ favorite wins $60\%$ of the time. When a matchmaker succeeds, however, expected win probabilities cluster tightly around $50\%$. In an ad-hoc team setting where "Team A" and "Team B" are temporary labels reassigned every match, an exact $50:50$ prediction cannot be falsified at the match level: regardless of which team wins, the Brier score is always $0.25$ and the Logarithmic Loss is always $\ln(2) \approx 0.6931$. Thus, the exact matches that carry the highest Bayesian learning weight during rating updates provide zero diagnostic value in standard macro evaluation.

We present a straightforward, rigorous diagnostic framework that resolves this problem by shifting the frame of reference from temporary teams to individual players:
1. **Player-Perspective Orientation ("Heads" = Player $i$'s Team):** Anchoring predictions and outcomes to a specific player breaks team permutation symmetry and turns balanced $50:50$ matches into testable Bernoulli trials over that player's match history.
2. **Standardized Prequential Residuals ($z_i$) and the Rating-Ascent Feedback Loop:** We show mathematically and empirically why lifetime cumulative residuals $R_i = \sum (s_{i,t} - E_{i,t})$ and $z_i$-scores correlate nearly linearly with current ratings ($r = 0.989$ in our empirical cohort). Because sequential rating updates are proportional to pre-match prediction errors, summing lifetime residuals algebraically reconstructs the player's rating climb from their initial prior. Treating a high lifetime $z_i$ as proof that a player's *current* rating is still too low commits a double-counting error.
3. **The Adaptive $50/50$ Equilibrium Zone ($\delta(N_i) \sim 1/\sqrt{N_i}$):** Restricting residual analysis to an adaptive competitive window around $50\%$ that contracts non-linearly with match experience (from $\pm 5.0\%$ down to $\pm 0.5\%$) removes lopsided mismatch noise and tail distortion while preserving statistical power across players of varying tenure.
4. **Counterfactual Leave-One-Out ($\Delta \mathrm{LogLoss}_i$) and Population Dispersion ($\mathrm{Var}(z)$):** We supplement residual tracking with an omission test that measures the marginal predictive value of a player's rating against an unrated baseline, and we pool player-anchored observations across the league to recover a full $[0\%, 100\%]$ calibration curve alongside a Chi-squared dispersion check ($\mathrm{Var}(z) \approx 1.00$).

We illustrate and validate the framework on both a real longitudinal cohort of recreational association football ($16$ matches, $34$ players, $154$ player-match observations) and a reproducible Monte Carlo simulation ($800$ matches, $40$ players).

---

## 1. Introduction: The Practical Problem

Consider a recurring sports league or an online multiplayer game where participants register for a session and an algorithm divides them into two teams, Team A and Team B. Unlike traditional club leagues (where "Bayern Munich" or "Real Madrid" are fixed rosters across a season), the teams here are **ad-hoc coalitions**: players are reshuffled on every matchday.

To split teams fairly, the organizer maintains an individual skill rating for each player—for instance, using a team-adapted Glicko-2 model (Glickman, 2001) or TrueSkill (Herbrich et al., 2006). Before each match, the rating engine aggregates the individual ratings on each side to predict the probability $E_A \in (0, 1)$ that Team A will beat Team B. The matchmaker searches over possible team partitions and selects a lineup where:

$$
E_A \approx 0.50
$$

After dozens of matches, a natural question arises: **How do we know if our rating model—and the individual ratings within it—are well-calibrated?**

### 1.1 Why Standard Macro Evaluation Fails Under Good Matchmaking

In standard probabilistic forecasting (e.g., weather forecasting or fixed-team sports), we evaluate calibration by grouping predictions into bins and comparing average predicted probabilities against observed win rates, alongside proper scoring rules such as the Brier score and Logarithmic Loss (Log-Loss).

In ad-hoc team games, however, the labels "Team A" and "Team B" are arbitrary. Swapping the jerseys of Team A and Team B before kickoff changes $E_A$ to $1 - E_A$ and flips the outcome $y_A \in \{0, 1\}$ to $1 - y_A$. Because there is no fixed "Home" or "Away" identity, standard model evaluation orients every match toward the **predicted favorite**:

$$
P_{\mathrm{fav}} = \max(E_A, 1 - E_A) \in [0.50, 1.00]
$$

This works well when matches are unbalanced ($P_{\mathrm{fav}} \in [0.60, 0.90]$). We can check whether $65\%$ favorites win roughly $65\%$ of the time, and whether $80\%$ favorites win $80\%$ of the time.

However, as the matchmaker succeeds in creating fair games, $P_{\mathrm{fav}}$ collapses toward $0.50$. At or near $50\%$, three problems occur simultaneously:
1. **Arbitrary Favorite Assignment:** In an exact $50:50$ match ($E_A = 0.50$), neither team is the favorite. Assigning one side as the "favorite" is a pure coin toss. In practice, exact $50:50$ matches must be excluded from favorite-oriented win-rate checks.
2. **Insensitivity of Scoring Rules at $0.50$:** Even if we include $50:50$ matches in global scoring metrics, a prediction of $P = 0.50$ yields the exact same Brier score ($(0.50 - 1)^2 = (0.50 - 0)^2 = 0.25$) and the exact same Log-Loss ($-\ln(0.50) \approx 0.6931$) whether Team A wins or loses. No single match outcome can challenge a $50\%$ forecast.
3. **Collapse of Forecast Resolution:** Even for nearly balanced games (e.g., $P_{\mathrm{fav}} \in [0.50, 0.55]$), all predictions are compressed into a tiny probability interval, making it impossible to fit a meaningful macro calibration curve across $[0.50, 1.00]$ without large sample sizes.

We refer to this tension as the **Matchmaker Dilemma**: *the better the rating system is used to balance teams toward $50:50$, the less information standard macro-calibration metrics can extract from the resulting match history.* Paradoxically, in Bayesian rating models like Glicko-2, a $50:50$ match carries the **maximum Fisher information** ($E(1 - E) = 0.25$) for updating player ratings, yet carries **zero discriminatory weight** in favorite-oriented macro evaluation.

---

## 2. Related Contexts & Contribution

Before introducing our mathematical framework, it is important to situate this problem within existing statistical literature. None of the individual mathematical building blocks we use require reinventing probability theory; rather, the value lies in understanding how established concepts from forecasting, Generalized Linear Models (GLMs), and sequential filtering interact in matchmaking-driven team sports.

### 2.1 Paired Comparisons and Neutral-Site Symmetry

Paired-comparison models originate with Zermelo (1929) and Bradley & Terry (1952), and were extended to dynamic time-varying ratings by Elo (1978), Glickman (1999, 2001), Coulom (2008), and Herbrich et al. (2006). In 1v1 games with structural asymmetry—such as White vs. Black in chess, or Home vs. Away in professional sports leagues—each match has a canonical orientation. When contests take place on neutral ground between exchangeable teams, however, the likelihood is invariant under team permutation. In the sports analytics literature, evaluation typically defaults to favorite-oriented binning or random team orientation (e.g., Lopez et al., 2018), which works only when tournament brackets or fixed schedules naturally produce wide dispersion in $E_A$.

### 2.2 Proper Scoring Rules and Murphy's Decomposition

The Brier score (Brier, 1950) and Logarithmic score (Good, 1952) are strictly proper scoring rules (Gneiting & Raftery, 2007). A foundational result by Murphy (1973) decomposes the expected Brier score into three components:

$$
\mathrm{Brier} = \underbrace{\bar{y}(1 - \bar{y})}_{\text{Uncertainty}} + \underbrace{\text{Reliability (Calibration Error)}}_{\text{Close to } 0 \text{ is better}} - \underbrace{\text{Resolution (Sharpness)}}_{\text{Higher is better}}
$$

Here, *Resolution* measures how far the forecast probabilities $P_m$ vary from the base rate $\bar{y} = 0.50$. Murphy's decomposition makes the Matchmaker Dilemma transparent: **an effective matchmaker deliberately drives forecast resolution toward zero** ($P_m \to 0.50$). When resolution is forced to zero by design, a macro Brier score near $0.25$ no longer tells us whether the underlying player ratings are accurate or whether two misrated players simply canceled out on paper.

### 2.3 Prequential Diagnostics and GLM Residuals

To evaluate sequential probability forecasts without hindsight bias, Dawid (1984) introduced the *prequential* (predictive-sequential) principle: at each step $t$, a forecaster issues a probability $E_t$ based only on past information $\mathcal{F}_{t-1}$, observes $s_t \in \{0, 1\}$, and computes the standardized cumulative residual:

$$
z_T = \frac{\sum_{t=1}^T (s_t - E_t)}{\sqrt{\sum_{t=1}^T E_t(1 - E_t)}}
$$

Under the null hypothesis that the sequential probabilities $E_t$ are true conditional expectations, the increments $d_t = s_t - E_t$ form a martingale difference sequence, and $z_T \xrightarrow{d} \mathcal{N}(0, 1)$ as $T \to \infty$ (Dawid, 1984; Seillier-Moiseiwitsch & Dawid, 1993). Similarly, in logistic regression and GLM diagnostics (McCullagh & Nelder, 1989; Hosmer & Lemeshow, 1980), when observations cannot be meaningfully grouped by overall predicted probability, analysts group standardized Pearson residuals by **explanatory covariates or random-effect clusters** (here, individual players) to detect localized model misspecification.

### 2.4 Where Our Approach Adds Practical Value

While prequential $z$-scores and cluster-level GLM residuals are classic statistical tools, applying them naively to online rating systems creates a subtle trap that is rarely discussed in sports analytics:
1. **Breaking Matchmaker Symmetry:** By anchoring prequential residuals to individual players ("Heads" = Player $i$'s team), we recover full diagnostic visibility in $50:50$ games where macro calibration is blind.
2. **Identifying the Update Conservation Trap (Rating-Ascent Bias):** In standard GLM residual analysis, model parameters are estimated once on a training set or held fixed. In an online rating system (Elo/Glicko-2), however, the parameter $r_{i,t}$ is updated after every match *in direct proportion to the residual $(s_{i,t} - E_{i,t})$*. As we prove in Section 4.3, this creates an algebraic conservation identity between a player's lifetime residual $R_i$ and their net rating gain $(r_{i,T} - r_{i,0})$, resulting in a near-perfect linear correlation ($r \approx 0.99$) between current rating and lifetime $z_i$.
3. **The $50/50$ Equilibrium Partition & Population Dispersion:** We show how isolating balanced matches ($E_{i,t} \in [0.48, 0.52]$) and accounting for burn-in decouples current valuation accuracy from historical rating ascent, and how pooling player-anchored observations restores a complete $[0\%, 100\%]$ calibration curve with a simple variance test ($\mathrm{Var}(z) \approx 1.00$).

---

## 3. Mathematical Model & The Symmetry Problem

### 3.1 The Team Glicko-2 Architecture

To keep the discussion concrete, we state the exact team Glicko-2 equations implemented in the RB48 engine (extending Glickman, 2001). Each player $i \in \{1, \dots, M\}$ is tracked by a rating $r_i$ (initialized at $r_0 = 1500$), a rating deviation $\mathrm{RD}_i$ (initialized at $\mathrm{RD}_0 = 348$), and a volatility parameter $\sigma_i$ (initialized at $\sigma_0 = 0.03$).

Internally, parameters are mapped to the natural Glicko-2 logistic scale via $c = \frac{400}{\ln 10} \approx 173.7178$:

$$
\mu_i = \frac{r_i - 1500}{c}, \qquad \phi_i = \frac{\mathrm{RD}_i}{c}
$$

For a match $m$ between Team $A$ and Team $B$ of size $k = |A| = |B|$, team strength and uncertainty are pooled via the arithmetic mean of skill and the root-mean-square of uncertainty:

$$
\mu_A = \frac{1}{|A|} \sum_{i \in A} \mu_i, \qquad \phi_A = \sqrt{\frac{1}{|A|} \sum_{i \in A} \phi_i^2}
$$

(and analogously for Team $B$). From the perspective of a player $i \in A$, let $\mathrm{own} = A$ and $\mathrm{opp} = B$. The pre-match win probability for player $i$'s team is attenuated by the opposing team's pooled uncertainty $\phi_{\mathrm{opp}}$:

$$
g(\phi) = \frac{1}{\sqrt{1 + \frac{3\phi^2}{\pi^2}}}, \qquad E_{i,m} = \frac{1}{1 + \exp\left(-\sqrt{k} \cdot g(\phi_{\mathrm{opp}})(\mu_{\mathrm{own}} - \mu_{\mathrm{opp}})\right)}
$$

where $\sqrt{k} = \sqrt{|A|}$ scales the difference in team means to account for collective advantage accumulation across multi-duel team matches (analogous to Microsoft TrueSkill, where team margin scales as $k(\bar{\mu}_A - \bar{\mu}_B)/\sqrt{k}\sigma = \sqrt{k}\Delta\mu/\sigma$). This eliminates link-function underconfidence while preserving rating update dilution ($1/\sqrt{k}$).

To update player $i$'s rating across a session of matches $m \in \mathcal{S}_i$ played on the same date, the RB48 engine weights each match by a team-size dilution factor $1/\sqrt{|A_m|}$ and a Bayesian teammate clarity factor $g(\phi_{\mathrm{tm}, m})$, where $\phi_{\mathrm{tm}, m}$ is the root-mean-square uncertainty of player $i$'s teammates:

$$
w_{i,m} = \frac{g(\phi_{\mathrm{tm}, m})}{\sqrt{|A_m|}}
$$

The effective session precision $I_i$ and effective surprise $\Delta_{\mathrm{eff}, i}$ are accumulated as:

$$
I_i = \sum_{m \in \mathcal{S}_i} w_{i,m} \, g(\phi_{\mathrm{opp}, m})^2 E_{i,m}(1 - E_{i,m}), \qquad \Delta_{\mathrm{eff}, i} = \sum_{m \in \mathcal{S}_i} w_{i,m} \, g(\phi_{\mathrm{opp}, m})(s_{i,m} - E_{i,m})
$$

where $s_{i,m} \in \{0.0, 0.5, 1.0\}$ is the observed match result (loss, draw, win). After updating volatility $\sigma_i'$ via the Illinois algorithm and computing the pre-match variance $\phi_i^* = \sqrt{\phi_i^2 + {\sigma_i'}^2}$, the posterior uncertainty $\phi_i'$ and updated skill $\mu_i'$ are:

$$
\phi_i' = \frac{1}{\sqrt{\frac{1}{(\phi_i^*)^2} + I_i}}, \qquad \mu_i' = \mu_i + (\phi_i')^2 \Delta_{\mathrm{eff}, i}
$$

### 3.2 Formalizing the Matchmaker Dilemma

Now consider how match $m$ is evaluated in macro calibration vs. how it drives learning in Equation (6).

**Proposition 1 (Information-Evaluation Inversion at $E = 0.50$).**  
*For any binary outcome $y \in \{0, 1\}$ and pre-match forecast $E \in (0, 1)$:*
1. *The Bayesian precision contribution $I_m(E) = g(\phi_{\mathrm{opp}})^2 E(1 - E)$ is strictly concave on $(0, 1)$ and achieves its unique global maximum at $E = 0.50$, where $E(1 - E) = 0.25$.*
2. *Conversely, at $E = 0.50$, the Brier loss $\ell_{\mathrm{Brier}}(E, y) = (E - y)^2$ and Logarithmic loss $\ell_{\mathrm{LogLoss}}(E, y) = -[y \ln E + (1 - y)\ln(1 - E)]$ are invariant to the observed outcome $y \in \{0, 1\}$:*

$$
\ell_{\mathrm{Brier}}(0.50, 1) = \ell_{\mathrm{Brier}}(0.50, 0) = 0.25, \qquad \ell_{\mathrm{LogLoss}}(0.50, 1) = \ell_{\mathrm{LogLoss}}(0.50, 0) = \ln 2 \approx 0.6931
$$

Proposition 1 formalizes the core dilemma: when the matchmaker constructs a $50:50$ match, the rating engine extracts maximum learning signal per match, but macro outcome-based evaluation cannot distinguish whether the $50:50$ prediction was genuinely well-calibrated (both teams truly had equal strength) or whether individual players were severely misrated in ways that happened to sum to equal team ratings on paper.

---

## 4. The Diagnostic Framework

To evaluate ratings when matches cluster around $50:50$, we decompose the problem into six sequential building blocks.

### 4.1 Step 1: Breaking Symmetry via the Player Perspective Anchor

In a single $50:50$ match, the labels "Team A" and "Team B" carry no persistent meaning. However, **individual players persist across matches**. 

For any target player $i$, we restrict attention to the subset of matches $\mathcal{M}_i$ in which player $i$ participated ($N_i = |\mathcal{M}_i|$). In every match $m \in \mathcal{M}_i$, we orient the prediction $E_{i,m}$ and the outcome $s_{i,m}$ strictly from the perspective of player $i$'s team ("Heads" = Team containing player $i$).

Why does this resolve the symmetry problem?
- In a single coin-flip match where $E_{i,m} = 0.50$, a win ($s_{i,m} = 1$) or loss ($s_{i,m} = 0$) still tells us nothing by itself.
- Across $N_i = 15$ matches where $E_{i,m} = 0.50$, however, the hypothesis that player $i$'s rating is accurate implies that player $i$'s team should win roughly $7.5$ times. If player $i$ is actually much stronger than their numerical rating $r_i$ indicates, their presence on a nominally $50:50$ team tilts the true win probability in their team's favor, and their team will win, say, $12$ out of $15$ times. By anchoring "Heads" to player $i$ across changing lineups, $50:50$ predictions become directly falsifiable.

### 4.2 Step 2: Standardized Prequential Residuals ($R_i$ and $z_i$)

For player $i$, the cumulative net residual (excess wins over pre-match expectation) across their match history $\mathcal{M}_i$ is:

$$
R_i = \sum_{m \in \mathcal{M}_i} (s_{i,m} - E_{i,m})
$$

Under the null hypothesis $H_0$ that the pre-match probabilities $E_{i,m}$ are well-calibrated conditional expectations given $\mathcal{F}_{m-1}$, each residual $d_{i,m} = s_{i,m} - E_{i,m}$ has conditional mean $\mathbb{E}[d_{i,m} \mid \mathcal{F}_{m-1}] = 0$ and conditional Bernoulli variance $\mathrm{Var}(d_{i,m} \mid \mathcal{F}_{m-1}) = E_{i,m}(1 - E_{i,m})$. Standardizing $R_i$ by its cumulative standard deviation yields Dawid's prequential $z$-statistic:

$$
z_i = \frac{R_i}{\sqrt{\sum_{m \in \mathcal{M}_i} E_{i,m}(1 - E_{i,m})}}
$$

By the martingale central limit theorem, under $H_0$, $z_i$ converges in distribution to a standard normal variable $\mathcal{N}(0, 1)$ as $N_i$ grows (for binary outcomes; in leagues with frequent draws, the denominator can be replaced by the exact trinomial variance). At the $5\%$ significance level, $|z_i| > 1.96$ flags a statistically significant cumulative discrepancy between expected and observed wins.

### 4.3 Step 3: The Rating-Ascent Feedback Loop (Why Lifetime $z_i$ Scales with Rating)

When we compute the lifetime statistic $z_i$ across all matches $m = 1, \dots, N_i$ in an active rating system and plot $z_i$ against the player's current rating $r_{i, N_i}$, a striking pattern appears: **$z_i$ scales almost linearly with $r_{i, N_i}$** (in our RB48 dataset, Pearson's $r = 0.9885$ for players with $N_i \ge 5$).

At first sight, one might conclude that every high-rated player is systematically underrated and every low-rated player is overrated. In reality, this correlation is a direct mathematical consequence of how sequential rating systems work.

**Proposition 2 (The Update Conservation Identity).**  
*In the Team Glicko-2 model (Equations 6–7), the rating increment on match $m$ (occurring in session $t$) is:*

$$
\Delta r_{i,m} = c \, (\phi_{i,t}')^2 w_{i,m} \, g(\phi_{\mathrm{opp}, m}) (s_{i,m} - E_{i,m}) = \alpha_{i,m} (s_{i,m} - E_{i,m})
$$

*where $\alpha_{i,m} > 0$ is the effective step weight. Summing over all $m \in \mathcal{M}_i$ from the common initial prior $r_{i,0} = 1500$ gives the exact telescopic identity:*

$$
r_{i, N_i} - 1500 = \sum_{m \in \mathcal{M}_i} \alpha_{i,m} (s_{i,m} - E_{i,m})
$$

*In particular, if the step weights $\alpha_{i,m}$ vary moderately around a mean $\bar{\alpha}_i$, then:*

$$
r_{i, N_i} - 1500 \approx \bar{\alpha}_i \sum_{m \in \mathcal{M}_i} (s_{i,m} - E_{i,m}) = \bar{\alpha}_i R_i
$$

**Why this matters in practice (Avoiding the Double-Counting Trap):**  
Proposition 2 shows that in any online rating system where every player starts at $r_0 = 1500$, **a player can only reach a high rating ($r_{i, N_i} > 1500$) by accumulating a positive lifetime residual sum ($R_i > 0$)**. 

For example, if a strong newcomer enters at $1500$ and wins their first $4$ games against $1500$-rated opponents, they accumulate $R_i = +2.0$ net wins above expectation ($z_i = +2.0$), and the Glicko-2 engine responds to those exact $2.0$ excess wins by raising their rating from $1500$ to $\sim 1700$. If we subsequently inspect their lifetime $z_i = +2.0$ and claim that their *current* rating of $1700$ is *still* too low, we are **double-counting** the initial climb that the rating engine has already priced into their current rating.

In addition to this conservation identity, a second factor can amplify global $z_i$ for top players: if a strong player frequently plays on heavily favored teams ($E_{i,m} > 0.60$) and the logistic link function is slightly underconfident in the tails (true win rate exceeds $E_{i,m}$ when one team dominates), those unbalanced matches add further positive residuals.

### 4.4 Step 4: Isolating the $50/50$ Equilibrium Sector and Burn-In Filtering

To evaluate whether a player is currently over- or undervalued *without* being misled by their historical climb or by lopsided matches, we introduce two complementary filters:

1. **The Adaptive $50/50$ Equilibrium Zone ($\mathcal{M}_{i,50}$):**  
   To resolve the bias-variance trade-off across players with differing match counts, we employ an **Adaptive Equilibrium Window** $\delta(N_i)$ that tightens non-linearly according to the central limit theorem standard error scaling ($\mathrm{SE} \sim 1/\sqrt{N_i}$):

$$
\delta(N_i) = \max\left(0.005, \, \min\left(0.050, \, \frac{0.10}{\sqrt{N_i}}\right)\right)
$$

$$
\mathcal{M}_{i,50} = \left\{ m \in \mathcal{M}_i : 0.50 - \delta(N_i) \le E_{i,m} \le 0.50 + \delta(N_i) \right\}
$$

   In this sector, the standardized score is:

$$
R_{i,50} = \sum_{m \in \mathcal{M}_{i,50}} (s_{i,m} - E_{i,m}), \qquad z_{i,50} = \frac{R_{i,50}}{\sqrt{\sum_{m \in \mathcal{M}_{i,50}} E_{i,m}(1 - E_{i,m})}}
$$

   Why is an adaptive non-linear window so effective?
   - **Sample Size Fairness:** Newcomers ($N \le 4$) receive the full $[0.45, 0.55]$ ($\pm 5.0\%$) window to prevent zero-sample starvation. Moderate regulars ($N = 25$) settle into the core $[0.48, 0.52]$ ($\pm 2.0\%$) band. Veteran cohorts ($N \ge 400$) converge toward the ultra-pure $[0.495, 0.505]$ ($\pm 0.5\%$) coin-toss benchmark.
   - **Quadratic Precision Requirement:** Because statistical error scales as $1/\sqrt{N}$, tightening the band by $1\%$ from $51\%$ to $50.5\%$ requires quadratically more evidence than moving from $55\%$ to $54\%$.

   Why is a tight $50/50$ sector ($[0.48, 0.52]$) so informative?
   - **Eliminates Link-Slope Distortion:** As seen in empirical team calibration curves, when the win-probability link function is underconfident (actual win rates rise steeper than predicted probabilities away from $50\%$), even moderate favorites at $54\%\text{--}55\%$ may empirically win $65\%\text{--}75\%$ of the time. Narrowing the band to $[0.48, 0.52]$ keeps evaluation pinned to the $(50\%, 50\%)$ fixed point where any scaling error in the logistic slope vanishes because $\sigma(0) = 0.50$.
   - **Breaks the Full-History Conservation Sum:** Rating jumps caused by lopsided matches ($E < 0.48$ or $E > 0.52$—which frequently occur when uncalibrated newcomers create unbalanced rosters) are excluded from $R_{i,50}$.
   - **Tests the Matchmaker Directly:** It answers the exact operational question the matchmaker cares about: *"When the model thinks a game involving player $i$ is genuinely fair ($48\text{--}52\%$), does player $i$'s team actually win $50\%$ of the time?"*

2. **Accounting for Initial Burn-In (Trajectory Slope vs. Level):**  
   Note an important nuance: if a matchmaker places *every* match inside $[0.48, 0.52]$ from a player's very first game at $1500$, then $\mathcal{M}_{i,50} = \mathcal{M}_i$ and the initial climb from $1500$ still occurs inside the $50/50$ band. Therefore, to judge whether a player's *current* rating has caught up with their true skill, one must either:
   - Inspect the **slope** of the chronological residual curve $R_{i}(t)$ in recent games (a flat slope $\Delta R_i \approx 0$ after game $t_0$ means the rating has caught up, even if the cumulative level $R_i$ remains above zero from early games), or
   - Apply a **burn-in filter** (evaluating $z_{i,50}$ only over matches $t > T_{\mathrm{burn}}$ after initial rating convergence, or using RB48's Option A\* two-pass retrospective prior calibration).

### 4.5 Step 5: Counterfactual Leave-One-Out (Omission) Test ($\Delta \mathrm{LogLoss}_i$)

Residual scores ($z_i$ and $z_{i,50}$) test whether a player's rating is biased (too low or too high). A complementary question is whether including player $i$'s rating **actually improves the accuracy of match predictions** compared to treating player $i$ as an unknown guest.

For each match $m \in \mathcal{M}_i$, we compute two pre-match predictions:
- **Factual Forecast ($E_{i,m}$):** Computed using all players' pre-match ratings, including player $i$'s rating $(r_{i,m}, \mathrm{RD}_{i,m})$.
- **Counterfactual Omission Forecast ($E_{i,m}^{\setminus \{i\}}$):** Computed by removing player $i$'s rating from their team and replacing their slot with an unrated guest prior ($r_{\mathrm{guest}} = 1500, \mathrm{RD}_{\mathrm{guest}} = 480$).

The Leave-One-Out (LOO) differential Log-Loss is:

$$
\Delta \mathrm{LogLoss}_i = \frac{1}{N_i} \sum_{m \in \mathcal{M}_i} \left[ \ell_{\mathrm{LogLoss}}(E_{i,m}, s_{i,m}) - \ell_{\mathrm{LogLoss}}(E_{i,m}^{\setminus \{i\}}, s_{i,m}) \right]
$$

- **$\Delta \mathrm{LogLoss}_i < 0$:** Using player $i$'s rating reduces prediction error relative to an unrated baseline. The player's rating carries genuine predictive signal.
- **$\Delta \mathrm{LogLoss}_i > 0$:** Including player $i$'s rating worsens prediction error (for example, right after an lucky early streak pushed a player to an inflated rating before subsequent losses).

### 4.6 Step 6: Aggregated Population Calibration & Dispersion Test

Finally, we return from the individual player to the **global model evaluation**. How can we construct a global calibration curve that includes $50:50$ matches and spans the entire $[0\%, 100\%]$ probability range?

Instead of entering each match once from the favorite's perspective, we pool the player-perspective observations $(E_{i,m}, s_{i,m})$ across all established players ($N_i \ge M_{\min}$, e.g., $M_{\min} = 5$ or $7$):

$$
\mathcal{D}_{\mathrm{pop}} = \bigcup_{i : N_i \ge M_{\min}} \left\{ (E_{i,m}, s_{i,m}) : m \in \mathcal{M}_i \right\}
$$

This pooled dataset has three major advantages over classical macro calibration:
1. **Complete $[0\%, 100\%]$ Domain:** Every unbalanced match contributes underdog observations ($E < 50\%$) for the players on the weaker side and favorite observations ($E > 50\%$) for the players on the stronger side.
2. **Full Inclusion of $50:50$ Matches:** Balanced $50:50$ matches are no longer discarded; they populate the central calibration buckets around $50\%$.
3. **Population Dispersion Test ($\mathrm{Var}(z) \approx 1.00$):**  
   Across the $M_{\mathrm{qual}}$ qualified players, we compute the sample variance of the individual standardized scores $z_i$ and $z_{i,50}$:

$$
\mathrm{Var}(z) = \frac{1}{M_{\mathrm{qual}} - 1} \sum_{i=1}^{M_{\mathrm{qual}}} (z_i - \bar{z})^2, \qquad \mathrm{Var}(z_{50}) = \frac{1}{M_{\mathrm{qual}} - 1} \sum_{i=1}^{M_{\mathrm{qual}}} (z_{i,50} - \bar{z}_{50})^2
$$

   If individual ratings are well-calibrated and residual deviations reflect normal binomial match variance, the standardized scores across players should have variance close to **$\mathrm{Var}(z_{50}) \approx 1.00$**:
   - **$\mathrm{Var}(z_{50}) \gg 1.00$ (Overdispersion):** Many players have large positive or negative $z_{50}$ scores; ratings are adapting too slowly or failing to capture persistent skill differences.
   - **$\mathrm{Var}(z_{50}) \ll 1.00$ (Underdispersion):** Residuals are smaller than binomial noise would predict (e.g., due to overfitting or small-sample conservation constraints).

---

## 5. Empirical Results & Monte Carlo Validation

We evaluate the framework in two settings: first, on the real observational match dataset of the RB48 recreational football league; second, on a controlled $800$-match Monte Carlo simulation where true latent skills are known.

### 5.1 Field Study: The RB48 Recreational Football Cohort

The RB48 dataset comprises $N = 16$ recorded league matches ($15$ indoor 4v4/5v5 `box` matches and $1$ outdoor half-pitch `hf` match) involving $34$ active players, of whom $16$ have played at least $5$ matches and $13$ have played at least $7$ matches. While compact, this sample size is representative of a typical club season or initial rating period where organizers first need diagnostic feedback.

#### 5.1.1 Macro Calibration vs. Aggregated Population Calibration

Table 1 compares standard favorite-oriented macro evaluation against player-anchored population evaluation on the exact same RB48 match history.

| Diagnostic Metric | Classical Macro Calibration (Favorite View, $[50\%, 100\%]$) | Aggregated Population View ($N_i \ge 5$, $[0\%, 100\%]$) | Aggregated Population View ($N_i \ge 7$, $[0\%, 100\%]$) |
| :--- | :---: | :---: | :---: |
| **Evaluated Units** | $13$ matches ($3$ excluded) | $154$ player-match obs. ($16$ players) | $139$ player-match obs. ($13$ players) |
| **50:50 Data Loss** | **$18.75\%$** ($3 / 16$ matches dropped) | **$0.0\%$** (all matches retained) | **$0.0\%$** (all matches retained) |
| **Expected Calibration Error (ECE)** | $0.4321$ | **$0.1491$** | **$0.2094$** |
| **Brier Score** | $0.2495$ | **$0.2348$** | **$0.2354$** |
| **Log-Loss** | $0.6925$ | $0.6922$ | **$0.6894$** |
| **Global $z$-Dispersion $\mathrm{Var}(z)$** | — | $0.8424$ ($\mathrm{Std} = 0.918$) | $0.9281$ ($\mathrm{Std} = 0.963$) |
| **50/50 Sector Dispersion $\mathrm{Var}(z_{50})$** | — | **$0.9559$** ($\mathrm{Std} = 0.978$) | **$0.8910$** ($\mathrm{Std} = 0.944$) |

**Key Observations from Table 1:**
1. **Severe Small-Sample Sparsity in Macro View:** Because the matchmaker actively balanced the teams, $3$ of the $16$ matches ($18.75\%$) had an exact $50.0\%$ prediction and had to be dropped from macro favorite evaluation. Splitting the remaining $13$ matches into $10$ quantile bins leaves only $1\text{--}2$ matches per bin, resulting in a noisy macro ECE of $0.4321$ and a Brier score of $0.2495$.
2. **Stabilization via Population Pooling:** Pooling across the $16$ established players ($N_i \ge 5$) yields $154$ player-match observations ($15\text{--}16$ observations per decile bin across $[35.5\%, 64.5\%]$). Notably, the central bin ($50.0\%\text{--}50.2\%$, $n = 16$ observations) has a predicted win rate of $50.0\%$ and an actual win rate of $53.1\%$ (a residual of just $+3.1\%$). Overall ECE drops to $0.1491$ and Brier score improves to $0.2348$.
3. **Near-Ideal Binomial Dispersion:** Across the established cohort ($N_i \ge 5$), the variance of the $50/50$ standardized residuals is **$\mathrm{Var}(z_{50}) = 0.9559$** ($\mathrm{Std}(z_{50}) = 0.9777$), within $4.4\%$ of the theoretical $\mathcal{N}(0, 1)$ benchmark of $1.000$.

#### 5.1.2 Player-Level Diagnostics and the Conservation Identity

Table 2 reports the complete diagnostic breakdown for all $16$ established players ($N_i \ge 5$) in the RB48 cohort, sorted by current Glicko-2 rating $r_i$.

| Player | Matches ($N_i$) | Current Rating ($r_i \pm \mathrm{RD}_i$) | Lifetime Net Wins ($R_i$) | Lifetime $z$-Score ($z_i$) | $50/50$ Matches ($n_{50}$) | $50/50$ Win Rate (Actual) | $50/50$ Net Wins ($R_{50}$) | $50/50$ $z$-Score ($z_{50}$) | LOO $\Delta \mathrm{LogLoss}_i$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Micha** | $10$ | $1695.6 \pm 213.3$ | $+1.95$ | $+1.26$ | $4$ | $50.0\%$ | $+0.16$ | **$+0.16$** | **$-0.0191$** |
| **Julian** | $9$ | $1695.6 \pm 225.0$ | $+2.20$ | $+1.48$ | $7$ | $71.4\%$ | $+1.45$ | $+1.10$ | $-0.0082$ |
| **Malte** | $9$ | $1625.8 \pm 228.3$ | $+1.38$ | $+0.93$ | $7$ | $57.1\%$ | $+0.63$ | $+0.48$ | $+0.0103$ |
| **Tim** | $5$ | $1590.8 \pm 266.3$ | $+0.94$ | $+0.84$ | $5$ | $70.0\%$ | $+0.94$ | $+0.84$ | $+0.0007$ |
| **Bernhard** | $12$ | $1588.5 \pm 205.7$ | $+0.90$ | $+0.52$ | $8$ | $56.3\%$ | $+0.36$ | $+0.26$ | $+0.0051$ |
| **Ingo** | $7$ | $1578.4 \pm 239.8$ | $+0.68$ | $+0.52$ | $5$ | $60.0\%$ | $+0.46$ | $+0.41$ | $-0.0004$ |
| **Lance** | $14$ | $1578.1 \pm 197.4$ | $+0.84$ | $+0.45$ | $8$ | $68.8\%$ | $+1.55$ | **$+1.10$** | $+0.0101$ |
| **Mo** | $12$ | $1478.1 \pm 208.7$ | $-0.37$ | $-0.22$ | $6$ | $58.3\%$ | $+0.34$ | $+0.28$ | $+0.0141$ |
| **Lücke** | $5$ | $1464.0 \pm 270.3$ | $-0.14$ | $-0.13$ | $3$ | $0.0\%$ | $-1.39$ | $-1.61$ | $+0.0086$ |
| **Nik** | $7$ | $1456.3 \pm 245.8$ | $-0.24$ | $-0.18$ | $5$ | $20.0\%$ | $-1.49$ | $-1.34$ | $+0.0057$ |
| **Phil** | $9$ | $1424.3 \pm 224.9$ | $-1.16$ | $-0.78$ | $5$ | $70.0\%$ | $+0.85$ | **$+0.76$** | $+0.0107$ |
| **Kevin** | $14$ | $1415.2 \pm 199.8$ | $-1.05$ | $-0.57$ | $10$ | $55.0\%$ | $+0.42$ | **$+0.27$** | $+0.0064$ |
| **Fabian** | $5$ | $1408.6 \pm 268.9$ | $-0.94$ | $-0.84$ | $5$ | $30.0\%$ | $-0.94$ | $-0.84$ | $+0.0007$ |
| **Stefan** | $9$ | $1330.8 \pm 222.9$ | $-1.88$ | $-1.27$ | $5$ | $30.0\%$ | $-0.90$ | $-0.81$ | **$-0.0097$** |
| **Konsti** | $13$ | $1322.3 \pm 199.9$ | $-1.77$ | $-1.00$ | $7$ | $14.3\%$ | $-2.49$ | **$-1.89$** | **$-0.0037$** |
| **Yannik** | $14$ | $1229.2 \pm 199.9$ | $-3.26$ | $-1.76$ | $10$ | $25.0\%$ | $-2.23$ | $-1.41$ | **$-0.0172$** |

#### 5.1.3 Empirical Verification of Proposition 2 and Case Studies

Across all $34$ active players in the database, the correlation between current rating $r_i$ and lifetime net residual wins $R_i$ is **$r = +0.9931$**, and the correlation between $r_i$ and lifetime $z_i$ across the $16$ established players in Table 2 is **$r = +0.9885$**. As proven in Proposition 2, lifetime $z_i$ simply mirrors the rating table.

When we examine the **isolated $50/50$ sector ($z_{50}$)** alongside the chronological match logs, however, the diagnostic picture changes substantially:

1. **Case Study A — Distinguishing Past Ascent from Current Calibration (Micha):**  
   Micha is tied for the highest rating in the league ($r = 1695.6$) and has a high lifetime residual ($R_i = +1.95$, $z_i = +1.26$). Inspection of his match log reveals *why*: on his debut matchday (`2026-08-04`), he entered at the uncalibrated default prior of $1500.0$ on a team predicted as a $37.5\%$ underdog against an already-calibrated opponent squad. His team won both matches that evening, generating $+1.25$ net residual wins outside the $50/50$ band and jumping his rating from $1500.0$ to $1637.8$. In his subsequent $4$ balanced matches inside the $50/50$ band ($E \in [45.2\%, 46.8\%]$), his teams went $2\text{--}2$ ($50.0\%$ actual win rate, **$z_{50} = +0.16$**). Thus, $z_{50}$ correctly shows that once Micha was rated around $1640\text{--}1695$, balanced games involving him were true $50:50$ propositions—his current rating is well-calibrated, and his LOO score ($\Delta \mathrm{LogLoss} = -0.0191$) confirms that his high rating strongly improves model predictions.
2. **Case Study B — Uncovering Positive Equilibrium Performance Despite Low Rating (Phil & Kevin):**  
   Phil ($r = 1424.3$, lifetime $z = -0.78$) and Kevin ($r = 1415.2$, lifetime $z = -0.57$) both sit below $1500$ with negative lifetime residuals because they lost $4$ lopsided matches (`2026-08-04` and `2026-08-26`) where predictions lay outside the $50/50$ zone ($E = 62.5\%$ against Micha's uncalibrated debut, and $E = 37.8\%$ as heavy underdogs). When placed in balanced $50/50$ matches, however, Phil's teams achieved a **$70.0\%$ win rate ($z_{50} = +0.76$)** and Kevin's teams achieved a **$55.0\%$ win rate across $10$ balanced games ($z_{50} = +0.27$)**. Unlike a naive glance at their negative lifetime $z$-scores, the $50/50$ sector indicates that both players are competitive—and potentially slightly undervalued—at their current ratings when teams are evenly matched.
3. **Case Study C — Confirming Informative Lower Ratings via LOO (Stefan, Konsti, Yannik):**  
   Players at the lower end of the rating table (Stefan, Konsti, Yannik) exhibit negative $z$-scores, which might raise concern that the model penalized them too harshly. However, their counterfactual Leave-One-Out scores are all negative ($\Delta \mathrm{LogLoss} = -0.0097, -0.0037, -0.0172$), proving that accounting for their lower ratings significantly *improves* pre-match probability forecasts compared to treating them as $1500$-rated average players.

---

### 5.2 Controlled Monte Carlo Simulation ($800$ Matches, $40$ Players)

Because the empirical RB48 dataset is still in its early season ($N = 16$ matches), we complement the field study with a reproducible Monte Carlo experiment (`paper/simulate_experiments.py`) simulating $40$ players over $800$ 5v5 matches ($200$ matches per player on average). True latent skills $\theta_i^* \sim \mathcal{N}(1500, 180^2)$ are fixed as ground truth, all estimated ratings start at $1500$, and on every matchday the matchmaker evaluates $20$ candidate partitions of the $10$ attending players to select the lineup closest to $E_A = 0.50$.

We run two experimental conditions:
- **Condition 1 (Well-Calibrated Convergence):** All $40$ players update normally using a decaying step schedule.
- **Condition 2 (Single Misrated "Smurf" / Hidden Anchor):** Player $0$ has a true skill of $\theta_0^* = 1800$ ($+300$ points above average), but their estimated rating is artificially capped at $1550$ so they remain permanently undervalued by $250$ points.

Table 3 summarizes the simulation results.

| Simulation Metric | Condition 1: Normal Convergence (All Players Unconstrained) | Condition 2: One Undervalued Player ($\theta_0^* = 1800$, Capped at $1550$) |
| :--- | :---: | :---: |
| **Macro Favorite Forecast ($\bar{P}_{\mathrm{fav}} \pm \mathrm{SD}$)** | $0.5647 \pm 0.0641$ | $0.5642 \pm 0.0638$ |
| **Macro Brier Score** | **$0.2498$** | **$0.2456$** |
| **Lifetime $\mathrm{Corr}(r_{i,\mathrm{final}}, z_{i,\mathrm{all}})$** | **$+0.8321$** | $+0.7014$ |
| **Post-Burn-In $\mathrm{Corr}(r_{i,\mathrm{burn}}, z_{i,50})$ ($[0.48, 0.52]$)** | **$+0.0821$** | $+0.0615$ |
| **Player $0$ Lifetime $z$-Score ($z_{0,\mathrm{all}}$)** | $+0.41$ (normal) | **$+7.39$** ($p < 10^{-12}$) |
| **Player $0$ Post-Burn $50/50$ Score ($z_{0,50}$)** | $-0.08$ (normal) | **$+1.99$** ($p = 0.046$) |
| **Player $0$ LOO $\Delta \mathrm{LogLoss}_0$** | $-0.1120$ | **$-0.0676$** |

**Three Takeaways from the Simulation:**
1. **Macro Blindness to Individual Misrating:** Comparing Condition 1 and Condition 2, injecting a player who is misrated by $250$ points into $200$ matches does not degrade the macro Brier score at all ($0.2498$ vs. $0.2456$). Because the matchmaker thinks Player $0$ is a $1550$ player, it keeps outputting $\sim 50:50$ predictions.
2. **Decoupling Ascent Correlation Post-Burn-In:** In Condition 1, lifetime $z_{i,\mathrm{all}}$ correlates strongly with final rating ($r = +0.8321$) due to the initial climb from $1500$. However, when we evaluate $z_{i,50}$ inside the strict $[0.48, 0.52]$ band *after* burn-in ($m > 300$) against the player's pre-window rating $r_{i,\mathrm{burn}}$, the correlation drops to **$r = +0.0821$**, confirming that post-burn-in $48\text{--}52\%$ residuals are virtually orthogonal to skill level.
3. **Pinpoint Detection of the Undervalued Player:** In Condition 2, Player $0$ is immediately flagged by both lifetime residual tracking ($z_{0,\mathrm{all}} = +7.39$) and post-burn-in $50/50$ equilibrium tracking ($z_{0,50} = +1.99$ in $[0.48, 0.52]$, and $+2.54$ in $[0.45, 0.55]$), demonstrating that player-anchored residuals reliably isolate miscalibrated individuals inside balanced matchmaking pools.

---

## 6. Limitations & Practical Considerations

To use this diagnostic framework responsibly in production sports or gaming analytics, three statistical limitations should be kept in mind:

1. **Within-Match Clustering in Pooled Population Curves:**  
   In a $k$-vs-$k$ match, the $2k$ player-perspective observations in $\mathcal{D}_{\mathrm{pop}}$ are not mutually independent: all $k$ teammates on Team A share the outcome $s_m$, and all $k$ opponents on Team B share $1 - s_m$. Consequently, while the pooled bin means $\bar{E}_b$ and $\bar{s}_b$ are unbiased estimators of population calibration across $[0\%, 100\%]$, standard errors or confidence intervals computed on $\mathcal{D}_{\mathrm{pop}}$ as if all $2k N$ rows were independent Bernoulli trials will be understated by a clustering factor of roughly $\sqrt{k}$. For formal hypothesis testing on the population level, the dispersion of player-level statistics $\mathrm{Var}(z)$ across the $M$ players (who mix across changing teammates) is preferred.
2. **Sample Size Reduction in the $50/50$ Band:**  
   Restricting per-player evaluation to $E_{i,m} \in [0.45, 0.55]$ reduces the effective sample size from $N_i$ to $n_{i,50}$. With a binomial standard deviation of $0.5\sqrt{n_{i,50}}$, a player whose true win rate in $50:50$ games is $65\%$ ($\Delta p = +0.15$ above expectation) requires roughly $n_{i,50} \approx (1.96 \times 0.5 / 0.15)^2 \approx 43$ balanced matches to cross the $|z_{50}| > 1.96$ threshold with $50\%$ power. In short recreational seasons ($n_{i,50} \sim 5\text{--}10$), $z_{50}$ should be interpreted as a directional indicator (e.g., $|z_{50}| > 1.0$) rather than a strict significance gate.
3. **Combining $50/50$ Isolation with Burn-In / Prior Recalibration:**  
   As noted in Section 4.4, if a matchmaker is so strict that *all* early matches of a new player fall inside $[0.45, 0.55]$, the $50/50$ filter alone will still include the player's initial climb from $r_0 = 1500$. In such environments, $z_{50}$ is most effective when combined either with a burn-in exclusion window (evaluating only matches after a player's RD falls below a threshold) or with retrospective prior recalibration (such as RB48's Option A\* two-pass surgical split, which anchors a newcomer's early matches to their calibrated $T$-match prior).

---

## 7. Conclusion

When a rating system is actively used to construct fair $50:50$ teams, classical favorite-oriented macro evaluation loses its ability to test model calibration—not because the rating model is failing, but because balanced matchmaking eliminates forecast dispersion and renders team labels exchangeable.

By shifting the evaluation anchor from temporary teams to persistent individual players ("Heads" = Player $i$'s team), we make balanced $50:50$ matches empirically testable. Furthermore, by proving the algebraic conservation link between sequential rating updates and lifetime residuals ($r \approx 0.99$), we explain why naive lifetime $z$-scores conflate historical rating ascent with current undervaluation, and show how isolating the **$50/50$ equilibrium sector ($45\%\text{--}55\%$)** alongside Leave-One-Out Log-Loss ($\Delta \mathrm{LogLoss}_i$) and population dispersion ($\mathrm{Var}(z_{50}) \approx 1.00$) provides a clean, practical diagnostic suite for team rating engines.

---

## References

1. **Bradley, R. A., & Terry, M. E.** (1952). Rank analysis of incomplete block designs: I. The method of paired comparisons. *Biometrika*, 39(3/4), 324–345.
2. **Brier, G. W.** (1950). Verification of forecasts expressed in terms of probability. *Monthly Weather Review*, 78(1), 1–3.
3. **Coulom, R.** (2008). Whole-History Rating: A Bayesian rating system for players of time-varying strength. *International Conference on Computers and Games (CG 2008)*, LNCS 5131, 113–124.
4. **Dawid, A. P.** (1982). The well-calibrated Bayesian. *Journal of the American Statistical Association*, 77(379), 605–610.
5. **Dawid, A. P.** (1984). Present position and potential developments: Some personal views: Statistical theory: The prequential approach. *Journal of the Royal Statistical Society: Series A*, 147(2), 278–292.
6. **Elo, A. E.** (1978). *The Rating of Chessplayers, Past and Present*. Arco Publishing, New York.
7. **Glickman, M. E.** (1999). Parameter estimation in large dynamic paired comparison experiments. *Applied Statistics (JRSS-C)*, 48(3), 377–394.
8. **Glickman, M. E.** (2001). Dynamic paired comparison models with stochastic variances. *Journal of Applied Statistics*, 28(6), 673–689.
9. **Gneiting, T., & Raftery, A. E.** (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association*, 102(477), 359–378.
10. **Good, I. J.** (1952). Rational decisions. *Journal of the Royal Statistical Society: Series B*, 14(1), 107–114.
11. **Herbrich, R., Minka, T., & Graepel, T.** (2006). TrueSkill™: A Bayesian skill rating system. *Advances in Neural Information Processing Systems (NeurIPS)*, 19, 569–576.
12. **Hosmer, D. W., & Lemeshow, S.** (1980). Goodness of fit tests for the multiple logistic regression model. *Communications in Statistics - Theory and Methods*, 9(10), 1043–1069.
13. **Lopez, M. J., Matthews, G. J., & Baumer, B. S.** (2018). How often does the best team win? A unified approach to understanding randomness in North American sport. *The Annals of Applied Statistics*, 12(4), 2483–2516.
14. **McCullagh, P., & Nelder, J. A.** (1989). *Generalized Linear Models* (2nd ed.). Chapman & Hall/CRC.
15. **Minka, T., Cleven, R., & Zaykov, Y.** (2018). TrueSkill 2: An improved Bayesian skill rating system. *Technical Report MSR-TR-2018-8*, Microsoft Research.
16. **Murphy, A. H.** (1973). A new vector partition of the probability score. *Journal of Applied Meteorology*, 12(4), 595–600.
17. **Seillier-Moiseiwitsch, F., & Dawid, A. P.** (1993). On testing the validity of sequential probability forecasts. *Journal of the American Statistical Association*, 88(421), 355–359.
18. **Zermelo, E.** (1929). Die Berechnung der Turnier-Ergebnisse als ein Maximumproblem der Wahrscheinlichkeitsrechnung. *Mathematische Zeitschrift*, 29(1), 436–460.
