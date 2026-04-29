# FBMC vs ATC: Nordic Electricity Market

Simulation code accompanying the master's thesis *Quantitative Assessment of
Flow-Based Market Coupling versus Available Transfer Capacity for the Nordic
Electricity Market* (KTH Royal Institute of Technology, 2026).

The thesis compares two cross-border capacity allocation methodologies
applied to the Nordic power system using a 13-node zonal DC power flow
model of Sweden's four bidding zones (SE1--SE4) and nine neighbouring
market areas. The model is solved as a linear program in Python using
the HiGHS solver, with three representative weeks of 2024 data drawn
from the ENTSO-E Transparency Platform and Svenska kraftnät.

## Setup

Requires Python 3.11.

    pip install -r requirements.txt

## Running

Each script reads from `data/<period>/` and writes to `results/<period>/`.
Each completes in under 30 seconds on standard hardware.

    python run_extended_analysis.py              # December 2024 base case
    python run_january_analysis.py               # January 2024 winter peak
    python run_july_analysis.py                  # July 2024 summer low
    python run_corridor_isolation_experiment.py  # Topology experiment
    python run_sensitivity_analysis.py           # Five sensitivity scenarios

## Reproducing thesis results

| Thesis section | Script | Output directory |
|----------------|--------|------------------|
| §5.1 Base case (December 2024) | `run_extended_analysis.py` | `results/december_2024/` |
| §5.2 January 2024 | `run_january_analysis.py` | `results/january_2024/` |
| §5.3 July 2024 | `run_july_analysis.py` | `results/july_2024/` |
| §5.4 Sensitivity scenarios A--E | `run_sensitivity_analysis.py` | `results/sensitivity/` |
| §5.6 Corridor isolation | `run_corridor_isolation_experiment.py` | `results/corridor_isolation/` |

## Repository layout

    fbmc_thesis_project_2026/
    ├── README.md
    ├── LICENSE
    ├── requirements.txt
    ├── run_extended_analysis.py
    ├── run_january_analysis.py
    ├── run_july_analysis.py
    ├── run_corridor_isolation_experiment.py
    ├── run_sensitivity_analysis.py
    ├── data/
    │   ├── december_2024/
    │   ├── january_2024/
    │   └── july_2024/
    ├── scenarios/
    │   ├── scenario_A/
    │   ├── scenario_B/
    │   ├── scenario_C/
    │   ├── scenario_D/
    │   └── scenario_E/
    └── results/
        ├── december_2024/
        ├── january_2024/
        ├── july_2024/
        ├── corridor_isolation/
        └── sensitivity/

Each `data/<period>/` directory contains seven CSVs:
`plants.csv`, `lines.csv`, `nodes.csv`, `zones.csv`, `demand_el.csv`,
`availability.csv`, `neighbor_prices.csv`.

The `scenarios/` directory contains the five sensitivity scenarios from
thesis Section 5.4. Each scenario ships the same seven canonical CSVs
as the base case, with one or two files modified per the scenario
definition. See `scenarios/SCENARIOS_README.md` for the per-scenario
file diff.

The `results/` directory contains the verified outputs from the deposit
build. These are the numerical values that match the thesis. Re-running
any script overwrites the corresponding subdirectory with regenerated
outputs.

## Data sources

All input data derives from public sources. Hourly demand is taken from
the ENTSO-E Transparency Platform document type A65 (Day-Ahead Total
Load Forecast). Day-ahead prices for neighbouring zones are taken from
document type A44 and aggregated to weekly means for each simulation
week (see thesis Sections 3.5 and 6.7 for the rationale and
implications). NTC values for the internal Swedish corridors come from
Svenska kraftnät; cross-border NTC values come from ENTSO-E published
data. Line reactances are derived from the PyPSA-Eur dataset.

## Notes on reproducibility

The HiGHS solver is deterministic. Identical inputs produce identical
outputs across runs and platforms. Reactance values for cross-border
corridors use a uniform placeholder (x = 0.05 p.u.) where authoritative
values were unavailable; this is documented in thesis Section 6.7. The
Finnish import envelope and PTDF mapping reflect the modelling choices
described in thesis Section 6.7.

## Citation

If you use this code or data, please cite the thesis:

    Palmborg, S. (2026). Quantitative Assessment of Flow-Based Market
    Coupling versus Available Transfer Capacity for the Nordic
    Electricity Market. Master's thesis, KTH Royal Institute of
    Technology.

## License

MIT. See `LICENSE`.

## Contact

Simon Palmborg
Supervisor: Saeed Mohammadi (KTH)
Examiner: Prof. Mohammad Reza Hesamzadeh (KTH)
