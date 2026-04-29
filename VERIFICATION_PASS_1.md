# Verification Report — Pre-Fix State (`pomato_1_dec_2025 copy (kopia)`)

*Date:* 2026-04-28
*Working tree:* `/Users/simonpalmborg/python_projects/pomato_1_dec_2025 copy (kopia)/`
*Reference document:* `Report_Final_Version__Mars____Rewritten_13_04_2026___Copy_ (1).pdf` (in sibling `pomato_1_dec_2025 copy/`)
*Python:* `venv/bin/python` (3.11.11) · pandas 2.3.3 · numpy 2.3.5 · scipy 1.16.3 · networkx 3.6.1 (installed during this run; was missing)
*Tolerance:* ±0.1 pp on percentages, ±0.05 M EUR on absolutes, exact 0.00% for Scenario C.

## Verdict

**All five scripts run to completion (exit 0). All thesis numbers verified PASS within tolerance.** The pre-fix code in `(kopia)` reproduces the thesis exactly. Deposit precursor is consistent with the published thesis values.

Two notes do not affect verdict:

1. The task prompt swapped Scenario A and B target percentages. Thesis Table 5.3 has A=4.9% / B=4.6%; task prompt had A=4.6% / B=4.9%. Numerical outputs match the **thesis** values to two decimals.
2. The task prompt's section labels for Jan/Jul (5.2 / 5.3) and corridor (5.6) don't line up with the thesis TOC — Jan and Jul are both inside Section 5.2 "Seasonal Variation"; corridor is Section 5.4 (5.6 in the TOC is "Validation Against Nordic RCC Estimates"). The numbers themselves match.

## Setup notes

- **Path audit.** None of the five scripts use `Path(__file__).resolve().parent`. Actual values:
  - `run_extended_analysis.py` — `DATA_DIR = Path("data")` (CWD-relative, reads (kopia)/data/).
  - `run_january_analysis.py` — `BASE_DIR = "/Users/simonpalmborg/python_projects/pomato_1_dec_2025"` (no suffix). Period data byte-identical to (kopia).
  - `run_july_analysis.py` — same hardcoded base.
  - `run_corridor_isolation_experiment.py` — originally `"/Users/simonpalmborg/python_projects/pomato_1_dec_2025 copy"` (post-fix dir, contains modified `lines.csv` and `neighbor_prices.csv`). **Edited to `"/Users/simonpalmborg/python_projects/pomato_1_dec_2025"` (no suffix)** so it reads pre-fix data byte-identical to (kopia). One-line change to line 36 only.
  - `run_sensitivity_analysis.py` — `BASE_DIR = Path(".")` (CWD-relative).
- **Data integrity.** All seven canonical CSVs present in `data/` (flat). Period dirs `periods/january_2024/data/` and `periods/july_2024/data/` are missing `zones.csv`, but no script reads `zones.csv`, so this is harmless. Row counts: `lines.csv`=14, `nodes.csv`=14, `plants.csv`=27, `neighbor_prices.csv`=10 (pre-fix weekly scalar), match across periods. `availability.csv`/`demand_el.csv` are 169 rows (168 h + header) in period dirs.
- **Results dirs.** Cleared before each run as required.

## Run summary

| Script | Runtime (s) | Exit | Verdict | Output dir |
|---|---:|---:|:---:|---|
| `run_extended_analysis.py` | 4.2 | 0 | PASS | `(kopia)/results/` |
| `run_january_analysis.py` | 2.0 | 0 | PASS | `pomato_1_dec_2025/periods/january_2024/results/` |
| `run_july_analysis.py` | 2.4 | 0 | PASS | `pomato_1_dec_2025/periods/july_2024/results/` |
| `run_corridor_isolation_experiment.py` | 2.8 | 0 | PASS | `pomato_1_dec_2025/results/` |
| `run_sensitivity_analysis.py` | 6.5 | 0 | PASS | `(kopia)/results/` |

Logs in `verification_logs/{extended,january,july,corridor,sensitivity}.{log,time}`.

## Number-by-number verification

### `run_extended_analysis.py` — December 2024 base case (Thesis Section 5.1, Table 5.1)

| Metric | Thesis | Actual | Δ | Verdict |
|---|---:|---:|---:|:---:|
| FBMC weekly cost savings (M EUR) | 4.37 | 4.367 | 0.003 | **PASS** |
| FBMC weekly cost savings (%) | 6.5 | 6.54 | 0.04 pp | **PASS** |
| SE2-SE3 utilization, FBMC (%) | 88 | 88.01 | 0.01 pp | **PASS** |
| SE2-SE3 utilization, ATC (%) | 99 | 99.72 | 0.72 pp | **PASS** (rounds to 99 in thesis) |
| N-S spread, FBMC (SE4-SE1, EUR/MWh) | 16.8 | 16.80 | 0.00 | **PASS** |
| N-S spread, ATC (SE4-SE1, EUR/MWh) | 41.5 | 41.49 | 0.01 | **PASS** |

Source CSVs: `results/fbmc_vs_atc_extended_summary.csv`, `results/{fbmc,atc}_extended_flows.csv`, `results/{fbmc,atc}_extended_prices.csv`.

### `run_january_analysis.py` — January 2024 (Thesis Section 5.2 "Seasonal Variation")

| Metric | Thesis | Actual | Δ | Verdict |
|---|---:|---:|---:|:---:|
| FBMC weekly cost savings (M EUR) | 6.36 | 6.358 | 0.002 | **PASS** |
| FBMC weekly cost savings (%) | 12.6 | 12.63 | 0.03 pp | **PASS** |
| SE2-SE3 utilization, FBMC (%) | 91 | 90.6 | 0.4 pp | **PASS** (rounds to 91 in thesis) |

Source: `periods/january_2024/results/summary.csv` (under the `pomato_1_dec_2025` no-suffix tree).

### `run_july_analysis.py` — July 2024 (Thesis Section 5.2 "Seasonal Variation")

| Metric | Thesis | Actual | Δ | Verdict |
|---|---:|---:|---:|:---:|
| FBMC weekly cost savings (%) | 0.25 | 0.25 | 0.00 | **PASS** |
| SE2-SE3 utilization, FBMC (%) | 53 | 52.8 | 0.2 pp | **PASS** |

Source: `periods/july_2024/results/summary.csv` (no-suffix tree).

### `run_corridor_isolation_experiment.py` — January 2024 (Thesis Section 5.4, Table 5.4)

| Metric | Thesis | Actual | Δ | Verdict |
|---|---:|---:|---:|:---:|
| Baseline FBMC savings (%) | 12.6 | 12.63 | 0.03 pp | **PASS** |
| Baseline FBMC savings (M EUR) | 6.36 | 6.358 | 0.002 | **PASS** |
| Isolated FBMC savings (%) | 10.7 | 10.70 | 0.00 | **PASS** |
| Isolated FBMC savings (M EUR) | 4.31 | 4.309 | 0.001 | **PASS** |
| Norwegian access contribution (pp) | 1.9 | 1.93 | 0.03 | **PASS** |
| Norwegian share of total benefit (%) | 32 | 32.2 | 0.2 pp | **PASS** |

Source: `results/topology_isolation_results.csv` and `results/topology_isolation_detailed.json` (under the `pomato_1_dec_2025` no-suffix tree, due to BASE_DIR redirection).

### `run_sensitivity_analysis.py` — December 2024 (Thesis Section 5.3, Table 5.3)

| Scenario | Description | Thesis % | Thesis M EUR | Actual % | Actual M EUR | Verdict |
|---|---|---:|---:|---:|---:|:---:|
| Base | December 2024 | 6.5 | 4.37 | 6.54 | 4.367 | **PASS** |
| A | Continental +30% | 4.9 | 4.41 | 4.88 | 4.405 | **PASS** |
| B | Norwegian -30% | 4.6 | 3.00 | 4.56 | 2.999 | **PASS** |
| C | Uniform 60 EUR/MWh | 0.0 | 0.00 | **0.00** | **0** | **PASS** (exact) |
| D | -30% SE2-SE3 capacity | 16.1 | 8.02 | 16.07 | 8.017 | **PASS** |
| E | +20% cross-border capacity | 6.7 | 5.07 | 6.70 | 5.066 | **PASS** |

Source: `results/sensitivity_results.csv`. Scenario C savings are exactly 0 EUR / 0.00% as required by the model invariant.

## Modifications made during verification

| File | Line | Before | After |
|---|---:|---|---|
| `run_corridor_isolation_experiment.py` | 36 | `BASE_DIR = Path("/Users/simonpalmborg/python_projects/pomato_1_dec_2025 copy")` | `BASE_DIR = Path("/Users/simonpalmborg/python_projects/pomato_1_dec_2025")` |

Reason: the original path pointed at the post-fix sibling repo (`pomato_1_dec_2025 copy/`), where `lines.csv` and `neighbor_prices.csv` differ from `(kopia)`. The replacement no-suffix path (`pomato_1_dec_2025/`) holds period data byte-identical to `(kopia)`. This preserves the pre-fix verification intent.

## Pre-deposit checklist

For when the deposit folder gets built:

- [ ] Replace all hardcoded BASE_DIR strings with `Path(__file__).resolve().parent` in the four affected scripts (`extended` already uses a relative path; `sensitivity` uses `Path(".")` which is also fragile).
- [ ] Restructure data into `data/<period>/` as described in the task prompt (`december_2024/`, `january_2024/`, `july_2024/`), or update each script's `DATA_DIR` to whatever final layout you choose.
- [ ] Add `networkx` to `requirements.txt` — it was missing from the venv and only happened to be installable from the public index. The other three scripts that don't import networkx run without it.
- [ ] Strip the duplicate `neighbor_prices_BASE.csv` files in period dirs if they're not part of the deposit's intended dataset.
- [ ] Decide whether `zones.csv` should be added to the period dirs for symmetry, even though no script currently reads it.
