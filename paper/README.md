# Academic Research & Paper Drafts

This directory contains research papers, formal mathematical proofs, and academic manuscripts stemming from the RB48 Glicko-2 dynamic rating architecture.

---

## Manuscripts

- **[`PAPER_DRAFT.md`](./PAPER_DRAFT.md)**  
  **Title:** *The Matchmaker's Paradox: Evaluating Bayesian Team Rating Calibration Under Symmetric 50/50 Equilibria*  
  **Format:** Applied Sports Analytics / Machine Learning Working Paper  
  **Status:** Version 1.0 (Draft)  
  **Target Venues:**
  - *Journal of Quantitative Analysis in Sports (JQAS)*
  - *MIT Sloan Sports Analytics Conference (Research Track)*
  - *ACM SIGKDD Workshop on Machine Learning in Sports*
  - *IEEE Transactions on Games*

---

## Code & Data Grounding

All mathematical formulations, residual metrics, and empirical results presented in the paper are implemented in the RB48 core engine:
- **Core Diagnostics:** [`scripts/analysis/model_analysis.py`](../scripts/analysis/model_analysis.py)
  - `analyze_player_perspective()`: Player-perspective residual tracking & counterfactual leave-one-out testing.
  - `analyze_all_players_summary()`: Player overview with 50/50 sector isolation.
  - `analyze_aggregate_player_calibration()`: Population-wide $[0.0, 1.0]$ calibration & Chi-squared dispersion test.
- **Model Documentation:** [`docs/GLICKO2_TEAM_MODEL.md`](../docs/GLICKO2_TEAM_MODEL.md) (Section 7)
- **Interactive UI:** `/model-analysis` (Tabs: *Macro*, *Player Perspective*, *Population*)
- **Test Suite:** [`tests/test_model_analysis.py`](../tests/test_model_analysis.py)
