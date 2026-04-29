#!/usr/bin/env python3
"""
Corridor Isolation Experiment - Quantifying Loop Flow Contribution to FBMC Benefits

This experiment tests the hypothesis that FBMC benefits arise primarily from
properly accounting for loop flows through Norwegian interconnections.

Methodology:
- Case A (Baseline): Full network with all Norwegian interconnections (SE2-NO4, NO3-SE2, NO1-SE3)
- Case B (Isolated): Network with Norwegian interconnections removed/disabled

If the hypothesis is correct:
- Baseline should show ~6.5% FBMC savings (from loop flow optimization)
- Isolated should show reduced FBMC savings (no loop flows to optimize)
- Loop flow contribution = Baseline savings - Isolated savings

Author: Simon Palmborg
Date: January 2024
"""

import os
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from scipy.optimize import linprog

# ============================================================================
# Configuration
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data" / "january_2024"
RESULTS_DIR = REPO_ROOT / "results" / "corridor_isolation"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Norwegian interconnections to isolate
NORWEGIAN_LINES = ['L_NO4_SE1', 'L_NO3_SE2', 'L_NO1_SE3']
NORWEGIAN_ZONES = ['NO1', 'NO3', 'NO4']

# Swedish bidding zones
SWEDISH_ZONES = ['SE1', 'SE2', 'SE3', 'SE4']

# All neighbor zones (including Norwegian)
ALL_NEIGHBOR_ZONES = ['NO1', 'NO3', 'NO4', 'FI', 'DK1', 'DK2', 'PL', 'LT', 'DE']

# Non-Norwegian neighbors
NON_NORWEGIAN_NEIGHBORS = ['FI', 'DK1', 'DK2', 'PL', 'LT', 'DE']

# Large capacity for virtual neighbor limits
NEIGHBOR_CAPACITY = 50000

# Global neighbor prices (loaded from CSV)
NEIGHBOR_PRICES = {}

print("=" * 80)
print("CORRIDOR ISOLATION EXPERIMENT")
print("Quantifying Loop Flow Contribution to FBMC Benefits")
print("=" * 80)


# ============================================================================
# Data Loading
# ============================================================================

def load_data():
    """Load all input data"""
    print("\nLoading input data...")

    demand_df = pd.read_csv(DATA_DIR / "demand_el.csv")
    plants_df = pd.read_csv(DATA_DIR / "plants.csv")
    avail_df = pd.read_csv(DATA_DIR / "availability.csv")
    nodes_df = pd.read_csv(DATA_DIR / "nodes.csv")
    lines_df = pd.read_csv(DATA_DIR / "lines.csv")
    neighbor_prices_df = pd.read_csv(DATA_DIR / "neighbor_prices.csv")

    # Melt demand and availability
    demand_melted = demand_df.melt(id_vars=['timestep'], var_name='node', value_name='demand_el')
    avail_melted = avail_df.melt(id_vars=['timestep'], var_name='plant', value_name='availability')

    # Load neighbor prices
    global NEIGHBOR_PRICES
    NEIGHBOR_PRICES = {row['zone']: row['price'] for _, row in neighbor_prices_df.iterrows()}

    print(f"  Loaded {len(demand_df)} timesteps, {len(plants_df)} plants, {len(lines_df)} lines")

    return demand_melted, plants_df, avail_melted, nodes_df, lines_df


def create_isolated_network(lines_df, nodes_df):
    """Create network with Norwegian interconnections removed"""
    # Remove Norwegian lines
    isolated_lines = lines_df[~lines_df['index'].isin(NORWEGIAN_LINES)].copy()

    # Remove Norwegian nodes
    isolated_nodes = nodes_df[~nodes_df['index'].isin(NORWEGIAN_ZONES)].copy()

    print(f"\n  Baseline network: {len(lines_df)} lines, {len(nodes_df)} nodes")
    print(f"  Isolated network: {len(isolated_lines)} lines, {len(isolated_nodes)} nodes")
    print(f"  Removed lines: {NORWEGIAN_LINES}")
    print(f"  Removed zones: {NORWEGIAN_ZONES}")

    return isolated_lines, isolated_nodes


# ============================================================================
# PTDF Calculation
# ============================================================================

def calculate_ptdf(lines_df, nodes_df, slack_node='SE3'):
    """Calculate PTDF matrix for given network topology"""
    n_nodes = len(nodes_df)
    n_lines = len(lines_df)

    nodes = nodes_df['index'].tolist()
    node_idx = {n: i for i, n in enumerate(nodes)}

    slack_idx = node_idx[slack_node]

    # Build susceptance matrix B
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

    # Remove slack row/col and invert
    B_red = np.delete(np.delete(B, slack_idx, 0), slack_idx, 1)

    try:
        B_inv = np.linalg.inv(B_red)
    except np.linalg.LinAlgError:
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

    ptdf_df = pd.DataFrame(PTDF, columns=nodes, index=lines_df['index'])

    return ptdf_df


# ============================================================================
# Merit Order Dispatch (Fallback)
# ============================================================================

def merit_order_dispatch(plants_df, avail, demand):
    """Simple merit order dispatch as fallback"""
    gen = {p: 0.0 for p in plants_df['index']}
    remaining = sum(demand.values())

    sorted_plants = plants_df.sort_values('mc_el')

    for _, plant in sorted_plants.iterrows():
        if remaining <= 0:
            break
        p_id = plant['index']
        g_max = plant['g_max'] * avail.get(p_id, 1.0)
        g = min(g_max, remaining)
        gen[p_id] = g
        remaining -= g

    cost = sum(gen[p] * plants_df.set_index('index').loc[p, 'mc_el']
               for p in gen if gen[p] > 0)
    return gen, cost


# ============================================================================
# FBMC Market Clearing
# ============================================================================

def run_fbmc(demand_df, plants_df, avail_df, lines_df, nodes_df, ptdf_df, neighbor_zones):
    """Run FBMC market clearing with PTDF constraints"""
    plants_list = plants_df['index'].tolist()
    lines = lines_df['index'].tolist()

    n_plants = len(plants_list)
    n_neighbors = len(neighbor_zones)
    n_vars = n_plants + n_neighbors

    # Mappings
    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    total_cost = 0.0
    total_import_cost = 0.0
    lp_failures = 0

    # Neighbor capacities
    neighbor_caps = {}
    neighbor_to_swedish = {}
    for neighbor in neighbor_zones:
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
            neighbor_caps[neighbor] = NEIGHBOR_CAPACITY

    for t in timesteps:
        # Get demand
        t_demand = demand_df[demand_df['timestep'] == t]
        demand = {row['node']: row['demand_el'] for _, row in t_demand.iterrows()}
        total_swedish_demand = sum(demand.values())

        # Get availability
        t_avail = avail_df[avail_df['timestep'] == t]
        avail = {row['plant']: row['availability'] for _, row in t_avail.iterrows()}

        # Objective: minimize cost
        c = np.zeros(n_vars)
        for j, p in enumerate(plants_list):
            c[j] = plant_mc[p]
        for j, neighbor in enumerate(neighbor_zones):
            c[n_plants + j] = NEIGHBOR_PRICES.get(neighbor, 50.0)

        # Bounds
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])
        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in neighbor_zones:
            cap = neighbor_caps.get(neighbor, NEIGHBOR_CAPACITY)
            bounds.append((-cap, cap))

        # System balance
        A_eq = np.zeros((1, n_vars))
        b_eq = np.zeros(1)
        A_eq[0, :n_plants] = 1.0
        A_eq[0, n_plants:] = 1.0
        b_eq[0] = total_swedish_demand

        # PTDF-based flow limits
        A_ub = []
        b_ub = []

        for l_idx, line in enumerate(lines):
            cap = line_cap[line]

            ptdf_row = np.zeros(n_vars)

            # Plant contributions
            for j, plant in enumerate(plants_list):
                zone = plant_zone[plant]
                if zone in ptdf_df.columns:
                    ptdf_row[j] = ptdf_df.loc[line, zone]

            # Neighbor contributions
            for j, neighbor in enumerate(neighbor_zones):
                swedish_zone = neighbor_to_swedish.get(neighbor)
                if swedish_zone and swedish_zone in ptdf_df.columns:
                    ptdf_row[n_plants + j] = ptdf_df.loc[line, swedish_zone]

            # Demand contribution
            ptdf_demand = 0.0
            for zone in SWEDISH_ZONES:
                if zone in ptdf_df.columns:
                    ptdf_demand += ptdf_df.loc[line, zone] * demand.get(zone, 0)

            A_ub.append(ptdf_row.copy())
            b_ub.append(cap + ptdf_demand)
            A_ub.append(-ptdf_row.copy())
            b_ub.append(cap - ptdf_demand)

        A_ub = np.array(A_ub) if A_ub else np.zeros((0, n_vars))
        b_ub = np.array(b_ub) if b_ub else np.zeros(0)

        # Solve
        try:
            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                           bounds=bounds, method='highs')

            if result.success:
                gen = {plants_list[j]: result.x[j] for j in range(n_plants)}
                imports = {neighbor_zones[j]: result.x[n_plants + j] for j in range(n_neighbors)}
                t_cost = sum(gen[p] * plant_mc[p] for p in plants_list)
                t_import_cost = sum(imports[n] * NEIGHBOR_PRICES.get(n, 50.0) for n in neighbor_zones)
            else:
                lp_failures += 1
                gen, t_cost = merit_order_dispatch(plants_df, avail, demand)
                imports = {n: 0.0 for n in neighbor_zones}
                t_import_cost = 0.0
        except Exception:
            lp_failures += 1
            gen, t_cost = merit_order_dispatch(plants_df, avail, demand)
            imports = {n: 0.0 for n in neighbor_zones}
            t_import_cost = 0.0

        total_cost += t_cost
        total_import_cost += t_import_cost

    return total_cost, total_import_cost, lp_failures


# ============================================================================
# ATC Market Clearing
# ============================================================================

def run_atc(demand_df, plants_df, avail_df, lines_df, nodes_df, neighbor_zones):
    """Run ATC market clearing with NTC limits"""
    plants_list = plants_df['index'].tolist()
    n_plants = len(plants_list)
    n_neighbors = len(neighbor_zones)
    n_vars = n_plants + n_neighbors

    # Mappings
    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    total_cost = 0.0
    total_import_cost = 0.0
    lp_failures = 0

    # Neighbor capacities
    neighbor_caps = {}
    neighbor_to_swedish = {}
    for neighbor in neighbor_zones:
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
            neighbor_caps[neighbor] = NEIGHBOR_CAPACITY

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
        for j, neighbor in enumerate(neighbor_zones):
            c[n_plants + j] = NEIGHBOR_PRICES.get(neighbor, 50.0)

        # Bounds
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])
        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in neighbor_zones:
            cap = neighbor_caps.get(neighbor, NEIGHBOR_CAPACITY)
            bounds.append((-cap, cap))

        # System balance
        A_eq = np.zeros((1, n_vars))
        b_eq = np.zeros(1)
        A_eq[0, :n_plants] = 1.0
        A_eq[0, n_plants:] = 1.0
        b_eq[0] = total_swedish_demand

        # ATC constraints: independent NTC limits
        A_ub = []
        b_ub = []

        # SE1-SE2
        se1_plants = [j for j, p in enumerate(plants_list) if plant_zone[p] == 'SE1']
        row = np.zeros(n_vars)
        for j in se1_plants:
            row[j] = 1.0
        for j, neighbor in enumerate(neighbor_zones):
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
        for j, neighbor in enumerate(neighbor_zones):
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
        for j, neighbor in enumerate(neighbor_zones):
            if neighbor_to_swedish.get(neighbor) == 'SE4':
                row[n_plants + j] = -1.0

        se34_ntc = line_cap.get('L_SE3_SE4', 5300)
        A_ub.append(row.copy())
        b_ub.append(se34_ntc - demand.get('SE4', 0))
        A_ub.append(-row.copy())
        b_ub.append(se34_ntc + demand.get('SE4', 0))

        A_ub = np.array(A_ub)
        b_ub = np.array(b_ub)

        # Solve
        try:
            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                           bounds=bounds, method='highs')

            if result.success:
                gen = {plants_list[j]: result.x[j] for j in range(n_plants)}
                imports = {neighbor_zones[j]: result.x[n_plants + j] for j in range(n_neighbors)}
                t_cost = sum(gen[p] * plant_mc[p] for p in plants_list)
                t_import_cost = sum(imports[n] * NEIGHBOR_PRICES.get(n, 50.0) for n in neighbor_zones)
            else:
                lp_failures += 1
                gen, t_cost = merit_order_dispatch(plants_df, avail, demand)
                imports = {n: 0.0 for n in neighbor_zones}
                t_import_cost = 0.0
        except Exception:
            lp_failures += 1
            gen, t_cost = merit_order_dispatch(plants_df, avail, demand)
            imports = {n: 0.0 for n in neighbor_zones}
            t_import_cost = 0.0

        total_cost += t_cost
        total_import_cost += t_import_cost

    return total_cost, total_import_cost, lp_failures


# ============================================================================
# Main Experiment
# ============================================================================

def run_experiment():
    """Run the corridor isolation experiment"""

    # Load data
    demand_df, plants_df, avail_df, nodes_df, lines_df = load_data()

    # Create isolated network (without Norwegian connections)
    isolated_lines, isolated_nodes = create_isolated_network(lines_df, nodes_df)

    results = {}

    # =========================================================================
    # CASE A: BASELINE (Full Network with Norwegian Interconnections)
    # =========================================================================
    print("\n" + "=" * 80)
    print("CASE A: BASELINE (Full Network with Norwegian Interconnections)")
    print("=" * 80)

    # Calculate PTDF for full network
    ptdf_baseline = calculate_ptdf(lines_df, nodes_df)
    print(f"\n  PTDF matrix (baseline): {ptdf_baseline.shape[0]} lines × {ptdf_baseline.shape[1]} zones")

    # Show Norwegian zone PTDFs for key line
    print("\n  PTDF for SE2-SE3 line (key congestion point):")
    for zone in ['SE1', 'SE2', 'SE3', 'SE4', 'NO1', 'NO3', 'NO4']:
        if zone in ptdf_baseline.columns:
            print(f"    {zone}: {ptdf_baseline.loc['L_SE2_SE3', zone]:.4f}")

    # Run FBMC baseline
    print("\n  Running FBMC (baseline)...")
    fbmc_gen_b, fbmc_imp_b, fbmc_fail_b = run_fbmc(
        demand_df, plants_df, avail_df, lines_df, nodes_df,
        ptdf_baseline, ALL_NEIGHBOR_ZONES
    )
    fbmc_total_b = fbmc_gen_b + fbmc_imp_b

    # Run ATC baseline
    print("  Running ATC (baseline)...")
    atc_gen_b, atc_imp_b, atc_fail_b = run_atc(
        demand_df, plants_df, avail_df, lines_df, nodes_df,
        ALL_NEIGHBOR_ZONES
    )
    atc_total_b = atc_gen_b + atc_imp_b

    # Calculate baseline savings
    savings_b = atc_total_b - fbmc_total_b
    savings_pct_b = (savings_b / abs(atc_total_b) * 100) if atc_total_b != 0 else 0

    results['baseline'] = {
        'fbmc_gen_cost': fbmc_gen_b,
        'fbmc_import_cost': fbmc_imp_b,
        'fbmc_total': fbmc_total_b,
        'atc_gen_cost': atc_gen_b,
        'atc_import_cost': atc_imp_b,
        'atc_total': atc_total_b,
        'fbmc_savings': savings_b,
        'fbmc_savings_pct': savings_pct_b,
        'lp_failures_fbmc': fbmc_fail_b,
        'lp_failures_atc': atc_fail_b
    }

    print(f"\n  BASELINE RESULTS:")
    print(f"    FBMC Total Cost: {fbmc_total_b:,.0f} EUR")
    print(f"    ATC Total Cost:  {atc_total_b:,.0f} EUR")
    print(f"    FBMC Savings:    {savings_b:,.0f} EUR ({savings_pct_b:.2f}%)")

    # =========================================================================
    # CASE B: ISOLATED (Without Norwegian Interconnections)
    # =========================================================================
    print("\n" + "=" * 80)
    print("CASE B: ISOLATED (Without Norwegian Interconnections)")
    print("=" * 80)

    # Calculate PTDF for isolated network
    ptdf_isolated = calculate_ptdf(isolated_lines, isolated_nodes)
    print(f"\n  PTDF matrix (isolated): {ptdf_isolated.shape[0]} lines × {ptdf_isolated.shape[1]} zones")

    # Show Swedish zone PTDFs for key line
    print("\n  PTDF for SE2-SE3 line (isolated network):")
    for zone in ['SE1', 'SE2', 'SE3', 'SE4']:
        if zone in ptdf_isolated.columns:
            print(f"    {zone}: {ptdf_isolated.loc['L_SE2_SE3', zone]:.4f}")

    # Run FBMC isolated
    print("\n  Running FBMC (isolated)...")
    fbmc_gen_i, fbmc_imp_i, fbmc_fail_i = run_fbmc(
        demand_df, plants_df, avail_df, isolated_lines, isolated_nodes,
        ptdf_isolated, NON_NORWEGIAN_NEIGHBORS
    )
    fbmc_total_i = fbmc_gen_i + fbmc_imp_i

    # Run ATC isolated
    print("  Running ATC (isolated)...")
    atc_gen_i, atc_imp_i, atc_fail_i = run_atc(
        demand_df, plants_df, avail_df, isolated_lines, isolated_nodes,
        NON_NORWEGIAN_NEIGHBORS
    )
    atc_total_i = atc_gen_i + atc_imp_i

    # Calculate isolated savings
    savings_i = atc_total_i - fbmc_total_i
    savings_pct_i = (savings_i / abs(atc_total_i) * 100) if atc_total_i != 0 else 0

    results['isolated'] = {
        'fbmc_gen_cost': fbmc_gen_i,
        'fbmc_import_cost': fbmc_imp_i,
        'fbmc_total': fbmc_total_i,
        'atc_gen_cost': atc_gen_i,
        'atc_import_cost': atc_imp_i,
        'atc_total': atc_total_i,
        'fbmc_savings': savings_i,
        'fbmc_savings_pct': savings_pct_i,
        'lp_failures_fbmc': fbmc_fail_i,
        'lp_failures_atc': atc_fail_i
    }

    print(f"\n  ISOLATED RESULTS:")
    print(f"    FBMC Total Cost: {fbmc_total_i:,.0f} EUR")
    print(f"    ATC Total Cost:  {atc_total_i:,.0f} EUR")
    print(f"    FBMC Savings:    {savings_i:,.0f} EUR ({savings_pct_i:.2f}%)")

    # =========================================================================
    # ANALYSIS: Loop Flow Contribution
    # =========================================================================
    print("\n" + "=" * 80)
    print("LOOP FLOW CONTRIBUTION ANALYSIS")
    print("=" * 80)

    loop_flow_contribution = savings_b - savings_i
    loop_flow_pct = (loop_flow_contribution / savings_b * 100) if savings_b != 0 else 0

    remaining_benefit = savings_i
    remaining_pct = (remaining_benefit / savings_b * 100) if savings_b != 0 else 0

    results['analysis'] = {
        'loop_flow_contribution_eur': loop_flow_contribution,
        'loop_flow_contribution_pct': loop_flow_pct,
        'remaining_fbmc_benefit_eur': remaining_benefit,
        'remaining_fbmc_benefit_pct': remaining_pct,
        'baseline_savings_pct': savings_pct_b,
        'isolated_savings_pct': savings_pct_i,
        'savings_reduction': savings_pct_b - savings_pct_i
    }

    print(f"\n  Baseline FBMC Savings:     {savings_b:>12,.0f} EUR ({savings_pct_b:.2f}%)")
    print(f"  Isolated FBMC Savings:     {savings_i:>12,.0f} EUR ({savings_pct_i:.2f}%)")
    print(f"  " + "-" * 50)
    print(f"  Loop Flow Contribution:    {loop_flow_contribution:>12,.0f} EUR ({loop_flow_pct:.1f}% of baseline savings)")
    print(f"  Remaining FBMC Benefit:    {remaining_benefit:>12,.0f} EUR ({remaining_pct:.1f}% of baseline savings)")

    # =========================================================================
    # HYPOTHESIS EVALUATION
    # =========================================================================
    print("\n" + "=" * 80)
    print("HYPOTHESIS EVALUATION")
    print("=" * 80)

    print(f"\n  HYPOTHESIS: FBMC benefits arise primarily from loop flows")
    print(f"              through Norwegian interconnections.")
    print(f"\n  EVIDENCE:")

    if loop_flow_pct > 50:
        verdict = "STRONGLY SUPPORTED"
        explanation = "Loop flows account for majority of FBMC benefits"
    elif loop_flow_pct > 25:
        verdict = "SUPPORTED"
        explanation = "Loop flows account for significant portion of FBMC benefits"
    elif loop_flow_pct > 10:
        verdict = "PARTIALLY SUPPORTED"
        explanation = "Loop flows contribute meaningfully but other factors also important"
    else:
        verdict = "NOT SUPPORTED"
        explanation = "Loop flows play minor role; FBMC benefits from other mechanisms"

    print(f"    - Loop flow contribution: {loop_flow_pct:.1f}% of total FBMC savings")
    print(f"    - Savings reduction when NO connections removed: {savings_pct_b - savings_pct_i:.2f}pp")
    print(f"\n  VERDICT: {verdict}")
    print(f"  {explanation}")

    results['verdict'] = {
        'conclusion': verdict,
        'explanation': explanation
    }

    # =========================================================================
    # Save Results
    # =========================================================================
    print("\n" + "=" * 80)
    print("SAVING RESULTS")
    print("=" * 80)

    # Create summary DataFrame
    summary_data = [
        {'scenario': 'Baseline (Full Network)', 'fbmc_cost': fbmc_total_b, 'atc_cost': atc_total_b,
         'fbmc_savings_eur': savings_b, 'fbmc_savings_pct': savings_pct_b},
        {'scenario': 'Isolated (No NO connections)', 'fbmc_cost': fbmc_total_i, 'atc_cost': atc_total_i,
         'fbmc_savings_eur': savings_i, 'fbmc_savings_pct': savings_pct_i},
        {'scenario': 'Loop Flow Contribution', 'fbmc_cost': None, 'atc_cost': None,
         'fbmc_savings_eur': loop_flow_contribution, 'fbmc_savings_pct': loop_flow_pct}
    ]

    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(RESULTS_DIR / "topology_isolation_results.csv", index=False)
    print(f"\n  Saved: results/topology_isolation_results.csv")

    # Save detailed results
    detailed_results = {
        'experiment': 'Corridor Isolation Experiment',
        'date': datetime.now().isoformat(),
        'hypothesis': 'FBMC benefits arise primarily from loop flows through Norwegian interconnections',
        'norwegian_lines_removed': NORWEGIAN_LINES,
        'norwegian_zones_removed': NORWEGIAN_ZONES,
        'results': results
    }

    import json
    with open(RESULTS_DIR / "topology_isolation_detailed.json", 'w') as f:
        json.dump(detailed_results, f, indent=2, default=str)
    print(f"  Saved: results/topology_isolation_detailed.json")

    # Save PTDF comparison
    ptdf_comparison = pd.DataFrame({
        'line': ['L_SE2_SE3'] * 7,
        'zone': ['SE1', 'SE2', 'SE3', 'SE4', 'NO1', 'NO3', 'NO4'],
        'ptdf_baseline': [ptdf_baseline.loc['L_SE2_SE3', z] if z in ptdf_baseline.columns else None
                         for z in ['SE1', 'SE2', 'SE3', 'SE4', 'NO1', 'NO3', 'NO4']],
        'ptdf_isolated': [ptdf_isolated.loc['L_SE2_SE3', z] if z in ptdf_isolated.columns else None
                         for z in ['SE1', 'SE2', 'SE3', 'SE4', 'NO1', 'NO3', 'NO4']]
    })
    ptdf_comparison.to_csv(RESULTS_DIR / "ptdf_comparison.csv", index=False)
    print(f"  Saved: results/ptdf_comparison.csv")

    return results


if __name__ == "__main__":
    results = run_experiment()

    print("\n" + "=" * 80)
    print("EXPERIMENT COMPLETE")
    print("=" * 80)
    print("\nResults can be used in thesis to support topology dependency claim.")
    print("Key files generated:")
    print("  - results/topology_isolation_results.csv")
    print("  - results/topology_isolation_detailed.json")
    print("  - results/ptdf_comparison.csv")
