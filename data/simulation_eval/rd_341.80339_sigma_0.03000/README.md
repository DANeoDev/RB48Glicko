# Simulation evaluation

## Experiment

This experiment uses **fixed hidden player strengths** and 1,500 synthetic games. Glicko starts from the configured common rating, RD and sigma. Checkpoints use the exact same schedule as `run_demo.py`: dense sampling through the early convergence period, then progressively wider intervals through 1,500 games. Only TOTAL Glicko is evaluated.

The analysis separates **ordering**, **rating scale**, **probability recovery**, and **outcome prediction**. A temporary deterioration in probability metrics is therefore not automatically a failure: starting from identical ratings, Glicko can acquire directional information before its probability scale is correctly calibrated.

## Convergence benchmark table

The table gives the **first available checkpoint at which a practical benchmark is crossed**. The thresholds are conventions for comparing experiments, **not universal statistical standards**. A single crossing does not prove permanent convergence; the benchmark logic can later be extended with a persistence/stability requirement.

| Benchmark | Criterion | First checkpoint | Achieved value |
|---|---:|---:|---:|
| Strength Pearson correlation | >= 0.25 | 25 games | 0.440986 |
| Strength Pearson correlation | >= 0.5 | 31 games | 0.50314 |
| Strength Pearson correlation | >= 0.75 | 141 games | 0.752585 |
| Strength Pearson correlation | >= 0.9 | 480 games | 0.904723 |
| Strength rank (Spearman) correlation | >= 0.5 | 31 games | 0.520625 |
| Strength rank (Spearman) correlation | >= 0.75 | 133 games | 0.757707 |
| Prediction beats 50/50 (Brier skill) | > 0 | 25 games | 0.160319 |
| Prediction beats base-rate baseline | > 0 | 25 games | 0.158973 |
| Probability correlation | >= 0.25 | 25 games | 0.431431 |
| Probability correlation | >= 0.5 | 27 games | 0.536371 |
| Probability correlation | >= 0.75 | 450 games | 0.750066 |
| Probability MAE | <= 0.1 | not reached | — |
| Probability MAE | <= 0.05 | not reached | — |
| Probability MSE | <= 0.01 | not reached | — |
| Calibration reliability | <= 0.01 | 101 games | 0.00819487 |
| Mean probability bias (absolute) | <= 0.01 | 107 games | 0.00952981 |

## Numerical outputs

- `strength_metrics.csv`: MSE, MAE, Pearson/Spearman correlation, bias, mean RD and mean sigma.
- `brier_metrics.csv`: outcome Brier metrics, Murphy decomposition, probability MSE/MAE/correlation and bias.
- `benchmark_metrics.csv`: first checkpoint crossing each convergence benchmark.
- `probability_observations.csv`: match-level true probability, Glicko probability and realised outcome.
- `config.json`: exact starting conditions and simulation parameters.

The checkpoint schedule is deliberately defined identically in the simulation exporter and evaluator. Missing `players=0` rows therefore indicate a genuinely missing snapshot rather than a checkpoint-definition mismatch.
