# Simulation evaluation

## Experiment

This experiment uses **fixed hidden player strengths** and 1,500 synthetic games. Glicko starts from the configured common rating, RD and sigma. Checkpoints use the exact same schedule as `run_demo.py`: dense sampling through the early convergence period, then progressively wider intervals through 1,500 games. Only TOTAL Glicko is evaluated.

The analysis separates **ordering**, **rating scale**, **probability recovery**, and **outcome prediction**. A temporary deterioration in probability metrics is therefore not automatically a failure: starting from identical ratings, Glicko can acquire directional information before its probability scale is correctly calibrated.

## Convergence benchmark table

The table gives the **first available checkpoint at which a practical benchmark is crossed**. The thresholds are conventions for comparing experiments, **not universal statistical standards**. A single crossing does not prove permanent convergence; the benchmark logic can later be extended with a persistence/stability requirement.

| Benchmark | Criterion | First checkpoint | Achieved value |
|---|---:|---:|---:|
| Strength Pearson correlation | >= 0.25 | 250 games | 0.298702 |
| Strength Pearson correlation | >= 0.5 | 430 games | 0.515069 |
| Strength Pearson correlation | >= 0.75 | 800 games | 0.770601 |
| Strength Pearson correlation | >= 0.9 | not reached | — |
| Strength rank (Spearman) correlation | >= 0.5 | 440 games | 0.515957 |
| Strength rank (Spearman) correlation | >= 0.75 | 800 games | 0.786691 |
| Prediction beats 50/50 (Brier skill) | > 0 | 1,375 games | 0.000702929 |
| Prediction beats base-rate baseline | > 0 | 1,375 games | 0.000660114 |
| Probability correlation | >= 0.25 | 25 games | 0.305908 |
| Probability correlation | >= 0.5 | 1,250 games | 0.529147 |
| Probability correlation | >= 0.75 | not reached | — |
| Probability MAE | <= 0.1 | 1,375 games | 0.0997763 |
| Probability MAE | <= 0.05 | not reached | — |
| Probability MSE | <= 0.01 | not reached | — |
| Calibration reliability | <= 0.01 | 1,125 games | 0.00800192 |
| Mean probability bias (absolute) | <= 0.01 | 119 games | 0.00940709 |

## Numerical outputs

- `strength_metrics.csv`: MSE, MAE, Pearson/Spearman correlation, bias, mean RD and mean sigma.
- `brier_metrics.csv`: outcome Brier metrics, Murphy decomposition, probability MSE/MAE/correlation and bias.
- `benchmark_metrics.csv`: first checkpoint crossing each convergence benchmark.
- `probability_observations.csv`: match-level true probability, Glicko probability and realised outcome.
- `config.json`: exact starting conditions and simulation parameters.

The checkpoint schedule is deliberately defined identically in the simulation exporter and evaluator. Missing `players=0` rows therefore indicate a genuinely missing snapshot rather than a checkpoint-definition mismatch.
