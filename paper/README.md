# Academic Research & Paper Manuscript

This directory contains the research paper and reproducible simulation script for the diagnostic methodology developed in the RB48 Glicko-2 rating engine.

---

## Contents

1. **[`PAPER_DRAFT.md`](./PAPER_DRAFT.md)**  
   **Title:** *Evaluating Team Skill Rating Systems When the Matchmaker Works: Player-Anchored Residuals, Ascent Bias, and Equilibrium Calibration*  
   **Summary:** A rigorous, accessible statistical paper analyzing why standard favorite-oriented macro calibration fails when a matchmaker actively constructs balanced $50:50$ teams, how player-perspective residual decomposition ("Heads" = Player $i$'s team) resolves this symmetry blindness, why sequential rating updates create an algebraic conservation coupling between lifetime $z$-scores and current ratings ($r = 0.989$), and how isolating the $50/50$ equilibrium sector alongside Leave-One-Out Log-Loss and population dispersion ($\mathrm{Var}(z_{50}) \approx 1.00$) provides a complete diagnostic framework.

2. **[`simulate_experiments.py`](./simulate_experiments.py)**  
   **Purpose:** Standalone, reproducible Monte Carlo simulation ($800$ 5v5 matches across $40$ players with known ground-truth skills $\theta_i^*$) verifying the large-sample properties reported in Section 5.2 of the paper.
   **Run command:**
   ```bash
   python paper/simulate_experiments.py
   ```

---

## Code & Data Grounding

All empirical tables and equations in `PAPER_DRAFT.md` correspond directly to the live RB48 codebase and database (`data/rb48.db`):
- **Core Diagnostics:** [`scripts/analysis/model_analysis.py`](../scripts/analysis/model_analysis.py)
  - `analyze_model()`: Classical macro favorite calibration ($[50\%, 100\%]$).
  - `analyze_player_perspective()`: Player-anchored residuals ($R_i, z_i, z_{i,50}$) & counterfactual Leave-One-Out ($\Delta \mathrm{LogLoss}_i$).
  - `analyze_all_players_summary()`: League-wide diagnostic summary table.
  - `analyze_aggregate_player_calibration()`: Pooled population calibration ($[0\%, 100\%]$) & dispersion test ($\mathrm{Var}(z), \mathrm{Var}(z_{50})$).
- **Model Documentation:** [`docs/GLICKO2_TEAM_MODEL.md`](../docs/GLICKO2_TEAM_MODEL.md) (Section 7)
- **Unit Tests:** [`tests/test_model_analysis.py`](../tests/test_model_analysis.py)
