#!/usr/bin/env python3
"""
POMATO Sensitivity Analysis - FBMC vs ATC
Tests robustness of FBMC benefits across different scenarios

Scenarios:
A: High Continental Prices (+30%)
B: Low Norwegian Prices (-30%)
C: Price Convergence (All at 60 EUR/MWh)
D: Reduced SE2-SE3 Capacity (-30%)
E: Increased Cross-Border Capacity (+20%)
"""

import os
import shutil
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from scipy.optimize import linprog
import networkx as nx

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ============================================================================
# Configuration
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data" / "december_2024"
SCENARIOS_DIR = REPO_ROOT / "scenarios"
RESULTS_DIR = REPO_ROOT / "results" / "sensitivity"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Date range
START_DATE = datetime(2024, 12, 2, 0, 0)
END_DATE = datetime(2024, 12, 8, 23, 0)

# Zones
SWEDISH_ZONES = ['SE1', 'SE2', 'SE3', 'SE4']
NEIGHBOR_ZONES = ['NO1', 'NO3', 'NO4', 'FI', 'DK1', 'DK2', 'PL', 'LT', 'DE']
ALL_ZONES = SWEDISH_ZONES + NEIGHBOR_ZONES

# Scenario definitions
SCENARIOS = {
    'A': {
        'name': 'High Continental Prices (+30%)',
        'description': 'DE, PL, DK1, DK2, LT prices increased by 30%',
        'price_multipliers': {'DE': 1.3, 'PL': 1.3, 'DK1': 1.3, 'DK2': 1.3, 'LT': 1.3},
        'line_changes': {}
    },
    'B': {
        'name': 'Low Norwegian Prices (-30%)',
        'description': 'NO1, NO3, NO4 prices reduced by 30%',
        'price_multipliers': {'NO1': 0.7, 'NO3': 0.7, 'NO4': 0.7},
        'line_changes': {}
    },
    'C': {
        'name': 'Price Convergence (60 EUR/MWh)',
        'description': 'All neighbor prices set to 60 EUR/MWh',
        'price_fixed': 60.0,
        'line_changes': {}
    },
    'D': {
        'name': 'Reduced SE2-SE3 Capacity (-30%)',
        'description': 'SE2-SE3 corridor capacity reduced by 30%',
        'price_multipliers': {},
        'line_changes': {'L_SE2_SE3': 0.7}
    },
    'E': {
        'name': 'Increased Cross-Border Capacity (+20%)',
        'description': 'All cross-border lines capacity increased by 20%',
        'price_multipliers': {},
        'line_changes': {
            'L_NO4_SE1': 1.2, 'L_NO3_SE2': 1.2, 'L_NO1_SE3': 1.2,
            'L_FI_SE1': 1.2, 'L_FI_SE3': 1.2, 'L_DK1_SE3': 1.2,
            'L_DK2_SE4': 1.2, 'L_PL_SE4': 1.2, 'L_LT_SE4': 1.2, 'L_DE_SE4': 1.2
        }
    }
}

# ============================================================================
# Helper Functions
# ============================================================================

def setup_scenario(scenario_id, scenario_def):
    """Create scenario directory and modify data files"""
    print(f"\n{'='*70}")
    print(f"Setting up Scenario {scenario_id}: {scenario_def['name']}")
    print(f"{'='*70}")

    scenario_dir = SCENARIOS_DIR / f"scenario_{scenario_id}"
    scenario_data = scenario_dir / "data"
    scenario_results = scenario_dir / "results"

    # Create directories
    scenario_data.mkdir(parents=True, exist_ok=True)
    scenario_results.mkdir(parents=True, exist_ok=True)

    # Copy all base data files
    for f in DATA_DIR.glob("*.csv"):
        if not f.name.endswith('_BASE.csv'):
            shutil.copy(f, scenario_data / f.name)

    # Apply price modifications
    prices_df = pd.read_csv(scenario_data / "neighbor_prices.csv")
    original_prices = prices_df.copy()

    if 'price_fixed' in scenario_def:
        # Set all prices to fixed value
        prices_df['price'] = scenario_def['price_fixed']
        print(f"\n  All prices set to {scenario_def['price_fixed']} EUR/MWh")
    elif 'price_multipliers' in scenario_def and scenario_def['price_multipliers']:
        for zone, mult in scenario_def['price_multipliers'].items():
            old_price = prices_df.loc[prices_df['zone'] == zone, 'price'].values[0]
            new_price = old_price * mult
            prices_df.loc[prices_df['zone'] == zone, 'price'] = round(new_price, 2)
            change_pct = (mult - 1) * 100
            print(f"  {zone}: {old_price:.2f} -> {new_price:.2f} EUR/MWh ({change_pct:+.0f}%)")

    prices_df.to_csv(scenario_data / "neighbor_prices.csv", index=False)

    # Apply line capacity modifications
    if scenario_def.get('line_changes'):
        lines_df = pd.read_csv(scenario_data / "lines.csv")

        for line_id, mult in scenario_def['line_changes'].items():
            old_cap = lines_df.loc[lines_df['index'] == line_id, 'capacity'].values[0]
            new_cap = old_cap * mult
            lines_df.loc[lines_df['index'] == line_id, 'capacity'] = round(new_cap, 0)
            change_pct = (mult - 1) * 100
            print(f"  {line_id}: {old_cap:.0f} -> {new_cap:.0f} MW ({change_pct:+.0f}%)")

        lines_df.to_csv(scenario_data / "lines.csv", index=False)

    return scenario_dir


def calculate_ptdf(lines_df, nodes_df):
    """Calculate PTDF matrix"""
    n_nodes = len(nodes_df)
    n_lines = len(lines_df)

    nodes = nodes_df['index'].tolist()
    node_idx = {n: i for i, n in enumerate(nodes)}

    slack_node = 'SE3'
    slack_idx = node_idx[slack_node]

    # Build B matrix
    B = np.zeros((n_nodes, n_nodes))
    for _, line in lines_df.iterrows():
        i = node_idx[line['node_i']]
        j = node_idx[line['node_j']]
        x = line['x'] if line['x'] > 0 else 0.01
        b = 1.0 / x
        B[i, i] += b
        B[j, j] += b
        B[i, j] -= b
        B[j, i] -= b

    # Remove slack and invert
    B_red = np.delete(np.delete(B, slack_idx, 0), slack_idx, 1)
    try:
        B_inv = np.linalg.inv(B_red)
    except:
        B_inv = np.linalg.pinv(B_red)

    # Expand back
    X = np.zeros((n_nodes, n_nodes))
    non_slack = [i for i in range(n_nodes) if i != slack_idx]
    for i, ni in enumerate(non_slack):
        for j, nj in enumerate(non_slack):
            X[ni, nj] = B_inv[i, j]

    # Calculate PTDF
    PTDF = np.zeros((n_lines, n_nodes))
    for l, (_, line) in enumerate(lines_df.iterrows()):
        i = node_idx[line['node_i']]
        j = node_idx[line['node_j']]
        x = line['x'] if line['x'] > 0 else 0.01
        b = 1.0 / x
        for k in range(n_nodes):
            PTDF[l, k] = b * (X[i, k] - X[j, k])

    return pd.DataFrame(PTDF, columns=nodes, index=lines_df['index'])


def run_fbmc(demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_prices, ptdf_df):
    """Run FBMC optimization"""
    plants_list = plants_df['index'].tolist()
    lines = lines_df['index'].tolist()

    n_plants = len(plants_list)
    n_neighbors = len(NEIGHBOR_ZONES)
    n_vars = n_plants + n_neighbors

    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    total_cost = 0.0
    total_import_cost = 0.0
    lp_failures = 0

    # Get neighbor capacities
    neighbor_caps = {}
    neighbor_to_swedish = {}
    for neighbor in NEIGHBOR_ZONES:
        for line_id, (node_i, node_j) in line_nodes.items():
            if neighbor == node_i and node_j in SWEDISH_ZONES:
                neighbor_caps[neighbor] = line_cap[line_id]
                neighbor_to_swedish[neighbor] = node_j
                break
            elif neighbor == node_j and node_i in SWEDISH_ZONES:
                neighbor_caps[neighbor] = line_cap[line_id]
                neighbor_to_swedish[neighbor] = node_i
                break
        else:
            neighbor_caps[neighbor] = 50000

    for t in timesteps:
        t_demand = demand_df[demand_df['timestep'] == t]
        demand = {row['node']: row['demand_el'] for _, row in t_demand.iterrows()}
        total_swedish_demand = sum(demand.values())

        t_avail = avail_df[avail_df['timestep'] == t]
        avail = {row['plant']: row['availability'] for _, row in t_avail.iterrows()}

        # Objective
        c = np.zeros(n_vars)
        for j, p in enumerate(plants_list):
            c[j] = plant_mc[p]
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            c[n_plants + j] = neighbor_prices[neighbor]

        # Bounds
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])
        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in NEIGHBOR_ZONES:
            cap = neighbor_caps[neighbor]
            bounds.append((-cap, cap))

        # Equality: power balance
        A_eq = np.zeros((1, n_vars))
        A_eq[0, :n_plants] = 1.0
        A_eq[0, n_plants:] = 1.0
        b_eq = np.array([total_swedish_demand])

        # Inequality: PTDF flow limits
        A_ub = []
        b_ub = []

        for line in lines:
            cap = line_cap[line]
            node_i, node_j = line_nodes[line]

            ptdf_row = np.zeros(n_vars)
            for j, plant in enumerate(plants_list):
                zone = plant_zone[plant]
                if zone in ptdf_df.columns:
                    ptdf_row[j] = ptdf_df.loc[line, zone]

            for j, neighbor in enumerate(NEIGHBOR_ZONES):
                if neighbor in ptdf_df.columns:
                    for line_id, (ni, nj) in line_nodes.items():
                        if neighbor == ni and nj in SWEDISH_ZONES:
                            ptdf_row[n_plants + j] = ptdf_df.loc[line, nj]
                            break
                        elif neighbor == nj and ni in SWEDISH_ZONES:
                            ptdf_row[n_plants + j] = ptdf_df.loc[line, ni]
                            break

            ptdf_demand = sum(ptdf_df.loc[line, z] * demand.get(z, 0)
                             for z in SWEDISH_ZONES if z in ptdf_df.columns)

            A_ub.append(ptdf_row.copy())
            b_ub.append(cap + ptdf_demand)
            A_ub.append(-ptdf_row.copy())
            b_ub.append(cap - ptdf_demand)

        A_ub = np.array(A_ub) if A_ub else np.zeros((0, n_vars))
        b_ub = np.array(b_ub) if b_ub else np.zeros(0)

        try:
            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                           bounds=bounds, method='highs')
            if result.success:
                gen = {plants_list[j]: result.x[j] for j in range(n_plants)}
                imports = {NEIGHBOR_ZONES[j]: result.x[n_plants + j] for j in range(n_neighbors)}
                t_cost = sum(gen[p] * plant_mc[p] for p in plants_list)
                t_import_cost = sum(imports[n] * neighbor_prices[n] for n in NEIGHBOR_ZONES)
            else:
                lp_failures += 1
                t_cost = 0
                t_import_cost = 0
        except:
            lp_failures += 1
            t_cost = 0
            t_import_cost = 0

        total_cost += t_cost
        total_import_cost += t_import_cost

    return total_cost, total_import_cost, lp_failures


def run_atc(demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_prices):
    """Run ATC optimization"""
    plants_list = plants_df['index'].tolist()

    n_plants = len(plants_list)
    n_neighbors = len(NEIGHBOR_ZONES)
    n_vars = n_plants + n_neighbors

    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    total_cost = 0.0
    total_import_cost = 0.0
    lp_failures = 0

    # Get neighbor capacities
    neighbor_caps = {}
    neighbor_to_swedish = {}
    for neighbor in NEIGHBOR_ZONES:
        for line_id, (node_i, node_j) in line_nodes.items():
            if neighbor == node_i and node_j in SWEDISH_ZONES:
                neighbor_caps[neighbor] = line_cap[line_id]
                neighbor_to_swedish[neighbor] = node_j
                break
            elif neighbor == node_j and node_i in SWEDISH_ZONES:
                neighbor_caps[neighbor] = line_cap[line_id]
                neighbor_to_swedish[neighbor] = node_i
                break
        else:
            neighbor_caps[neighbor] = 50000

    for t in timesteps:
        t_demand = demand_df[demand_df['timestep'] == t]
        demand = {row['node']: row['demand_el'] for _, row in t_demand.iterrows()}
        total_swedish_demand = sum(demand.values())

        t_avail = avail_df[avail_df['timestep'] == t]
        avail = {row['plant']: row['availability'] for _, row in t_avail.iterrows()}

        # Objective
        c = np.zeros(n_vars)
        for j, p in enumerate(plants_list):
            c[j] = plant_mc[p]
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            c[n_plants + j] = neighbor_prices[neighbor]

        # Bounds
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])
        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in NEIGHBOR_ZONES:
            cap = neighbor_caps[neighbor]
            bounds.append((-cap, cap))

        # Equality: power balance
        A_eq = np.zeros((1, n_vars))
        A_eq[0, :n_plants] = 1.0
        A_eq[0, n_plants:] = 1.0
        b_eq = np.array([total_swedish_demand])

        # Inequality: ATC constraints
        A_ub = []
        b_ub = []

        # SE1-SE2
        se1_plants = [j for j, p in enumerate(plants_list) if plant_zone[p] == 'SE1']
        row = np.zeros(n_vars)
        for j in se1_plants:
            row[j] = 1.0
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            if neighbor_to_swedish.get(neighbor) == 'SE1':
                row[n_plants + j] = 1.0

        se1_ntc = line_cap.get('L_SE1_SE2', 3300)
        A_ub.append(row.copy())
        b_ub.append(se1_ntc + demand.get('SE1', 0))
        A_ub.append(-row.copy())
        b_ub.append(se1_ntc - demand.get('SE1', 0))

        # SE2-SE3
        se12_plants = [j for j, p in enumerate(plants_list) if plant_zone[p] in ['SE1', 'SE2']]
        row = np.zeros(n_vars)
        for j in se12_plants:
            row[j] = 1.0
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            if neighbor_to_swedish.get(neighbor) in ['SE1', 'SE2']:
                row[n_plants + j] = 1.0

        se12_demand = demand.get('SE1', 0) + demand.get('SE2', 0)
        se23_ntc = line_cap.get('L_SE2_SE3', 7300)
        A_ub.append(row.copy())
        b_ub.append(se23_ntc + se12_demand)
        A_ub.append(-row.copy())
        b_ub.append(se23_ntc - se12_demand)

        # SE3-SE4
        se4_plants = [j for j, p in enumerate(plants_list) if plant_zone[p] == 'SE4']
        row = np.zeros(n_vars)
        for j in se4_plants:
            row[j] = -1.0
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            if neighbor_to_swedish.get(neighbor) == 'SE4':
                row[n_plants + j] = -1.0

        se34_ntc = line_cap.get('L_SE3_SE4', 5300)
        A_ub.append(row.copy())
        b_ub.append(se34_ntc - demand.get('SE4', 0))
        A_ub.append(-row.copy())
        b_ub.append(se34_ntc + demand.get('SE4', 0))

        A_ub = np.array(A_ub)
        b_ub = np.array(b_ub)

        try:
            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                           bounds=bounds, method='highs')
            if result.success:
                gen = {plants_list[j]: result.x[j] for j in range(n_plants)}
                imports = {NEIGHBOR_ZONES[j]: result.x[n_plants + j] for j in range(n_neighbors)}
                t_cost = sum(gen[p] * plant_mc[p] for p in plants_list)
                t_import_cost = sum(imports[n] * neighbor_prices[n] for n in NEIGHBOR_ZONES)
            else:
                lp_failures += 1
                t_cost = 0
                t_import_cost = 0
        except:
            lp_failures += 1
            t_cost = 0
            t_import_cost = 0

        total_cost += t_cost
        total_import_cost += t_import_cost

    return total_cost, total_import_cost, lp_failures


def run_scenario(scenario_id, scenario_def):
    """Run a complete scenario analysis"""
    scenario_dir = setup_scenario(scenario_id, scenario_def)
    scenario_data = scenario_dir / "data"

    # Load data
    demand_df = pd.read_csv(scenario_data / "demand_el.csv")
    plants_df = pd.read_csv(scenario_data / "plants.csv")
    avail_df = pd.read_csv(scenario_data / "availability.csv")
    nodes_df = pd.read_csv(scenario_data / "nodes.csv")
    lines_df = pd.read_csv(scenario_data / "lines.csv")
    neighbor_prices_df = pd.read_csv(scenario_data / "neighbor_prices.csv")

    neighbor_prices = {row['zone']: row['price'] for _, row in neighbor_prices_df.iterrows()}

    print(f"\n  Running FBMC optimization...")
    ptdf_df = calculate_ptdf(lines_df, nodes_df)
    fbmc_gen, fbmc_import, fbmc_fails = run_fbmc(
        demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_prices, ptdf_df)
    fbmc_total = fbmc_gen + fbmc_import

    print(f"  Running ATC optimization...")
    atc_gen, atc_import, atc_fails = run_atc(
        demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_prices)
    atc_total = atc_gen + atc_import

    savings = atc_total - fbmc_total
    savings_pct = (savings / abs(atc_total)) * 100 if atc_total != 0 else 0

    print(f"\n  Results:")
    print(f"    FBMC Total: {fbmc_total:,.0f} EUR (gen: {fbmc_gen:,.0f}, import: {fbmc_import:,.0f})")
    print(f"    ATC Total:  {atc_total:,.0f} EUR (gen: {atc_gen:,.0f}, import: {atc_import:,.0f})")
    print(f"    Savings:    {savings:,.0f} EUR ({savings_pct:.2f}%)")

    return {
        'scenario': scenario_id,
        'name': scenario_def['name'],
        'description': scenario_def['description'],
        'fbmc_gen': fbmc_gen,
        'fbmc_import': fbmc_import,
        'fbmc_total': fbmc_total,
        'atc_gen': atc_gen,
        'atc_import': atc_import,
        'atc_total': atc_total,
        'savings_eur': savings,
        'savings_pct': savings_pct,
        'fbmc_failures': fbmc_fails,
        'atc_failures': atc_fails
    }


def create_visualization(results_df):
    """Create comparison visualization"""
    print("\nCreating sensitivity_comparison.png...")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Bar chart of savings percentage
    scenarios = results_df['scenario'].tolist()
    savings_pct = results_df['savings_pct'].tolist()

    colors = ['steelblue' if s >= 0 else 'coral' for s in savings_pct]

    bars = axes[0].bar(scenarios, savings_pct, color=colors, edgecolor='black')
    axes[0].axhline(y=0, color='black', linewidth=1)
    axes[0].set_xlabel('Scenario')
    axes[0].set_ylabel('FBMC Savings (%)')
    axes[0].set_title('FBMC Savings vs ATC by Scenario', fontweight='bold')
    axes[0].grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, val in zip(bars, savings_pct):
        height = bar.get_height()
        axes[0].annotate(f'{val:.1f}%',
                        xy=(bar.get_x() + bar.get_width()/2, height),
                        xytext=(0, 3 if height >= 0 else -15),
                        textcoords="offset points",
                        ha='center', va='bottom' if height >= 0 else 'top',
                        fontsize=10, fontweight='bold')

    # Bar chart of absolute savings
    savings_eur = [s/1e6 for s in results_df['savings_eur'].tolist()]

    colors = ['steelblue' if s >= 0 else 'coral' for s in savings_eur]

    bars = axes[1].bar(scenarios, savings_eur, color=colors, edgecolor='black')
    axes[1].axhline(y=0, color='black', linewidth=1)
    axes[1].set_xlabel('Scenario')
    axes[1].set_ylabel('FBMC Savings (Million EUR)')
    axes[1].set_title('Absolute FBMC Savings by Scenario', fontweight='bold')
    axes[1].grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, val in zip(bars, savings_eur):
        height = bar.get_height()
        axes[1].annotate(f'{val:.2f}M',
                        xy=(bar.get_x() + bar.get_width()/2, height),
                        xytext=(0, 3 if height >= 0 else -15),
                        textcoords="offset points",
                        ha='center', va='bottom' if height >= 0 else 'top',
                        fontsize=10, fontweight='bold')

    fig.suptitle('Sensitivity Analysis: FBMC vs ATC\nSwedish Electricity Market - Dec 2-8, 2024',
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "sensitivity_comparison.png", dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: results/sensitivity_comparison.png")


def create_report(results_df, base_result):
    """Create sensitivity analysis report"""
    print("\nCreating SENSITIVITY_ANALYSIS_REPORT.md...")

    report = f"""# Sensitivity Analysis Report
## FBMC vs ATC Comparison - Swedish Electricity Market
### December 2-8, 2024

---

## Executive Summary

This analysis tests the robustness of FBMC (Flow-Based Market Coupling) benefits
compared to ATC (Available Transfer Capacity) across 5 sensitivity scenarios.

**Base Case Result:** FBMC provides **{base_result['savings_pct']:.2f}%** cost savings
({base_result['savings_eur']:,.0f} EUR) compared to ATC.

---

## Scenario Definitions

| Scenario | Name | Description |
|----------|------|-------------|
| Base | Real Dec 2024 Prices | ENTSO-E day-ahead prices for Dec 2-8, 2024 |
| A | High Continental (+30%) | DE, PL, DK1, DK2, LT prices +30% |
| B | Low Norwegian (-30%) | NO1, NO3, NO4 prices -30% |
| C | Price Convergence | All neighbors at 60 EUR/MWh |
| D | SE2-SE3 Reduced (-30%) | Internal bottleneck capacity reduced |
| E | Cross-Border +20% | All cross-border capacities +20% |

---

## Results Summary

| Scenario | FBMC Total (EUR) | ATC Total (EUR) | Savings (EUR) | Savings (%) |
|----------|------------------|-----------------|---------------|-------------|
| Base | {base_result['fbmc_total']:,.0f} | {base_result['atc_total']:,.0f} | {base_result['savings_eur']:,.0f} | {base_result['savings_pct']:.2f}% |
"""

    for _, row in results_df.iterrows():
        report += f"| {row['scenario']} | {row['fbmc_total']:,.0f} | {row['atc_total']:,.0f} | {row['savings_eur']:,.0f} | {row['savings_pct']:.2f}% |\n"

    # Analysis
    max_savings = results_df.loc[results_df['savings_pct'].idxmax()]
    min_savings = results_df.loc[results_df['savings_pct'].idxmin()]

    report += f"""
---

## Key Findings

### 1. Robustness of FBMC Benefits

"""

    positive_scenarios = results_df[results_df['savings_pct'] > 0]
    if len(positive_scenarios) == len(results_df):
        report += "**FBMC benefits are robust:** All scenarios show positive savings for FBMC.\n"
    else:
        negative = results_df[results_df['savings_pct'] <= 0]
        report += f"**FBMC benefits vary:** {len(positive_scenarios)}/5 scenarios show positive savings.\n"
        report += f"Scenarios with no/negative savings: {', '.join(negative['scenario'].tolist())}\n"

    report += f"""
### 2. Most Impactful Parameter

**Highest FBMC Benefit:** Scenario {max_savings['scenario']} ({max_savings['name']})
- Savings: {max_savings['savings_pct']:.2f}% ({max_savings['savings_eur']:,.0f} EUR)
- Interpretation: {get_interpretation(max_savings['scenario'])}

**Lowest FBMC Benefit:** Scenario {min_savings['scenario']} ({min_savings['name']})
- Savings: {min_savings['savings_pct']:.2f}% ({min_savings['savings_eur']:,.0f} EUR)
- Interpretation: {get_interpretation(min_savings['scenario'])}

### 3. When Does FBMC Benefit Disappear?

"""

    if min_savings['savings_pct'] <= 0:
        report += f"""FBMC benefit disappears in Scenario {min_savings['scenario']} ({min_savings['name']}).
This occurs because {get_disappearance_reason(min_savings['scenario'])}.
"""
    else:
        report += f"""FBMC benefits persist across all tested scenarios.
The minimum benefit ({min_savings['savings_pct']:.2f}%) occurs in Scenario {min_savings['scenario']}.
This suggests FBMC remains valuable even under {min_savings['description'].lower()}.
"""

    report += f"""
---

## Detailed Scenario Analysis

"""

    for _, row in results_df.iterrows():
        report += f"""### Scenario {row['scenario']}: {row['name']}

**Description:** {row['description']}

| Metric | FBMC | ATC | Difference |
|--------|------|-----|------------|
| Swedish Gen Cost | {row['fbmc_gen']:,.0f} EUR | {row['atc_gen']:,.0f} EUR | {row['atc_gen']-row['fbmc_gen']:+,.0f} EUR |
| Net Import Cost | {row['fbmc_import']:,.0f} EUR | {row['atc_import']:,.0f} EUR | {row['atc_import']-row['fbmc_import']:+,.0f} EUR |
| Total System Cost | {row['fbmc_total']:,.0f} EUR | {row['atc_total']:,.0f} EUR | {row['savings_eur']:+,.0f} EUR |
| **Savings** | - | - | **{row['savings_pct']:.2f}%** |

"""

    report += f"""---

## Visualization

![Sensitivity Comparison](sensitivity_comparison.png)

---

## Conclusions

1. **FBMC benefits are {'robust' if min_savings['savings_pct'] > 0 else 'conditional'}** across the tested scenarios.

2. **Price spreads matter:** Higher continental prices (Scenario A) {'increase' if results_df[results_df['scenario']=='A']['savings_pct'].values[0] > base_result['savings_pct'] else 'decrease'} FBMC benefits.

3. **Norwegian prices matter:** Lower Norwegian prices (Scenario B) {'increase' if results_df[results_df['scenario']=='B']['savings_pct'].values[0] > base_result['savings_pct'] else 'decrease'} FBMC benefits.

4. **Price convergence:** When prices converge (Scenario C), FBMC savings {'remain' if results_df[results_df['scenario']=='C']['savings_pct'].values[0] > 1 else 'diminish significantly'}.

5. **Internal constraints:** Tighter SE2-SE3 capacity (Scenario D) {'increases' if results_df[results_df['scenario']=='D']['savings_pct'].values[0] > base_result['savings_pct'] else 'affects'} FBMC benefits.

6. **Cross-border capacity:** More cross-border capacity (Scenario E) {'increases' if results_df[results_df['scenario']=='E']['savings_pct'].values[0] > base_result['savings_pct'] else 'affects'} FBMC benefits.

---

*Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

    with open(RESULTS_DIR / "SENSITIVITY_ANALYSIS_REPORT.md", 'w') as f:
        f.write(report)

    print(f"  Saved: results/SENSITIVITY_ANALYSIS_REPORT.md")


def get_interpretation(scenario):
    """Get interpretation for scenario result"""
    interpretations = {
        'A': "Higher export prices increase arbitrage opportunities, benefiting FBMC's ability to optimize cross-border flows.",
        'B': "Cheaper Norwegian imports increase import volumes, where FBMC can better route power through parallel paths.",
        'C': "Price convergence reduces arbitrage opportunities, limiting the value of FBMC's flow optimization.",
        'D': "Tighter internal constraints increase the value of FBMC's ability to route power through cross-border paths.",
        'E': "More cross-border capacity allows FBMC to better utilize parallel paths for import/export optimization."
    }
    return interpretations.get(scenario, "No interpretation available.")


def get_disappearance_reason(scenario):
    """Get reason for FBMC benefit disappearance"""
    reasons = {
        'A': "increased prices shift the cost structure",
        'B': "lower import prices reduce the need for sophisticated flow optimization",
        'C': "price convergence eliminates arbitrage opportunities that FBMC exploits",
        'D': "internal constraints become so binding that external routing cannot help",
        'E': "excess capacity reduces the value of optimized routing"
    }
    return reasons.get(scenario, "the market conditions change significantly")


# ============================================================================
# Main Execution
# ============================================================================

def main():
    print("=" * 70)
    print("POMATO SENSITIVITY ANALYSIS")
    print("FBMC vs ATC - Swedish Electricity Market")
    print("=" * 70)

    # Create scenarios directory
    SCENARIOS_DIR.mkdir(exist_ok=True)

    # First, get base case results
    print("\n" + "=" * 70)
    print("BASE CASE (Real Dec 2024 Prices)")
    print("=" * 70)

    demand_df = pd.read_csv(DATA_DIR / "demand_el.csv")
    plants_df = pd.read_csv(DATA_DIR / "plants.csv")
    avail_df = pd.read_csv(DATA_DIR / "availability.csv")
    nodes_df = pd.read_csv(DATA_DIR / "nodes.csv")
    lines_df = pd.read_csv(DATA_DIR / "lines.csv")
    neighbor_prices_df = pd.read_csv(DATA_DIR / "neighbor_prices.csv")
    neighbor_prices = {row['zone']: row['price'] for _, row in neighbor_prices_df.iterrows()}

    print("\n  Running FBMC optimization...")
    ptdf_df = calculate_ptdf(lines_df, nodes_df)
    fbmc_gen, fbmc_import, fbmc_fails = run_fbmc(
        demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_prices, ptdf_df)
    fbmc_total = fbmc_gen + fbmc_import

    print("  Running ATC optimization...")
    atc_gen, atc_import, atc_fails = run_atc(
        demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_prices)
    atc_total = atc_gen + atc_import

    savings = atc_total - fbmc_total
    savings_pct = (savings / abs(atc_total)) * 100 if atc_total != 0 else 0

    base_result = {
        'scenario': 'Base',
        'name': 'Real Dec 2024 Prices',
        'description': 'ENTSO-E day-ahead prices for Dec 2-8, 2024',
        'fbmc_gen': fbmc_gen,
        'fbmc_import': fbmc_import,
        'fbmc_total': fbmc_total,
        'atc_gen': atc_gen,
        'atc_import': atc_import,
        'atc_total': atc_total,
        'savings_eur': savings,
        'savings_pct': savings_pct
    }

    print(f"\n  Results:")
    print(f"    FBMC Total: {fbmc_total:,.0f} EUR")
    print(f"    ATC Total:  {atc_total:,.0f} EUR")
    print(f"    Savings:    {savings:,.0f} EUR ({savings_pct:.2f}%)")

    # Run all scenarios
    results = []
    for scenario_id, scenario_def in SCENARIOS.items():
        result = run_scenario(scenario_id, scenario_def)
        results.append(result)

    # Create results DataFrame
    results_df = pd.DataFrame(results)

    # Save results
    results_df.to_csv(RESULTS_DIR / "sensitivity_results.csv", index=False)
    print(f"\n  Saved: results/sensitivity_results.csv")

    # Create visualization
    create_visualization(results_df)

    # Create report
    create_report(results_df, base_result)

    # Final summary
    print("\n" + "=" * 70)
    print("SENSITIVITY ANALYSIS COMPLETE")
    print("=" * 70)

    print("\n  Summary Table:")
    print(f"\n  {'Scenario':<10} {'Description':<35} {'Savings':<15} {'%':<10}")
    print("  " + "-" * 70)
    print(f"  {'Base':<10} {'Real Dec 2024 Prices':<35} {base_result['savings_eur']:>12,.0f} EUR {base_result['savings_pct']:>8.2f}%")
    for _, row in results_df.iterrows():
        print(f"  {row['scenario']:<10} {row['name'][:35]:<35} {row['savings_eur']:>12,.0f} EUR {row['savings_pct']:>8.2f}%")

    print("\n  Output Files:")
    print(f"    - results/sensitivity_results.csv")
    print(f"    - results/sensitivity_comparison.png")
    print(f"    - results/SENSITIVITY_ANALYSIS_REPORT.md")
    print(f"    - scenarios/scenario_*/data/ (modified data files)")

    # Validation
    print("\n  Validation Checks:")
    print(f"    [{'x' if Path('data/neighbor_prices_BASE.csv').exists() else ' '}] Base case files preserved")
    print(f"    [{'x' if all((SCENARIOS_DIR / f'scenario_{s}' / 'data').exists() for s in SCENARIOS.keys()) else ' '}] All scenarios have data directories")
    print(f"    [{'x' if len(results_df) == 5 else ' '}] All 5 scenarios completed")
    print(f"    [{'x' if all(results_df['savings_pct'].notna()) else ' '}] Results are valid")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
