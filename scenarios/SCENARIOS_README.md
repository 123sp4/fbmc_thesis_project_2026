# Sensitivity scenarios

Each `scenario_<X>/data/` directory contains the seven canonical CSVs. The base case is `data/december_2024/`. Each scenario differs from the base in a specific way:

| Scenario | Files modified vs base | Modification |
|---|---|---|
| A | `neighbor_prices.csv` | Continental zones (DK1, DK2, PL, LT, DE) prices ×1.30 |
| B | `neighbor_prices.csv` | Norwegian zones (NO1, NO3, NO4) prices ×0.70 |
| C | `neighbor_prices.csv` | All zones set to uniform 60 EUR/MWh |
| D | `lines.csv` | SE2-SE3 corridor capacity ×0.70 |
| E | `lines.csv` | Cross-border line capacities ×1.20 |

`run_sensitivity_analysis.py` regenerates these files deterministically at runtime by copying `data/december_2024/` into each scenario's `data/` and applying the modifications above. The shipped scenario CSVs reflect the post-modification state and match what the script produces.
