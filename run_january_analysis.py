#!/usr/bin/env python3
"""
POMATO January 2024 Analysis - FBMC vs ATC
Swedish Electricity Market with Cross-Border Connections

Date Range: January 8-14, 2024 (168 hours)
Network: 13 nodes (4 Swedish + 9 neighbors), 13 lines

This is a multi-period analysis comparing winter conditions (January)
with the base case (December 2024).
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
import networkx as nx

# ============================================================================
# Configuration
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data" / "january_2024"
RESULTS_DIR = REPO_ROOT / "results" / "january_2024"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Date range: January 8-14, 2024 (168 hours)
START_DATE = datetime(2024, 1, 8, 0, 0)
END_DATE = datetime(2024, 1, 14, 23, 0)
NUM_HOURS = 168

# Swedish bidding zones
SWEDISH_ZONES = ['SE1', 'SE2', 'SE3', 'SE4']

# Neighbor zones (price-based import/export)
NEIGHBOR_ZONES = ['NO1', 'NO3', 'NO4', 'FI', 'DK1', 'DK2', 'PL', 'LT', 'DE']

# All zones
ALL_ZONES = SWEDISH_ZONES + NEIGHBOR_ZONES

# Neighbor prices - will be loaded from neighbor_prices.csv
NEIGHBOR_PRICES = {}

# Large capacity for neighbor import/export (effectively unlimited)
NEIGHBOR_CAPACITY = 50000  # MW

print("=" * 70)
print("POMATO JANUARY 2024 ANALYSIS")
print("FBMC vs ATC - Winter Week Comparison")
print("Swedish Electricity Market - January 8-14, 2024")
print("=" * 70)

# ============================================================================
# Load Data
# ============================================================================

def load_data():
    """Load all input data from the January period directory"""
    print("\nLoading input data from periods/january_2024/data/...")

    # Load January-specific data
    demand_df = pd.read_csv(DATA_DIR / "demand_el.csv")
    plants_df = pd.read_csv(DATA_DIR / "plants.csv")
    avail_df = pd.read_csv(DATA_DIR / "availability.csv")
    nodes_df = pd.read_csv(DATA_DIR / "nodes.csv")
    lines_df = pd.read_csv(DATA_DIR / "lines.csv")
    neighbor_prices_df = pd.read_csv(DATA_DIR / "neighbor_prices.csv")

    # Convert demand format for optimization
    demand_melted = demand_df.melt(id_vars=['timestep'], var_name='node', value_name='demand_el')

    # Convert availability format
    avail_melted = avail_df.melt(id_vars=['timestep'], var_name='plant', value_name='availability')

    print(f"  Demand: {len(demand_df)} timesteps × 4 zones = {len(demand_melted)} records")
    print(f"  Plants: {len(plants_df)} plants")
    print(f"  Availability: {len(avail_df)} timesteps")
    print(f"  Nodes: {len(nodes_df)} zones")
    print(f"  Lines: {len(lines_df)} corridors")

    # Populate global NEIGHBOR_PRICES from CSV
    global NEIGHBOR_PRICES
    NEIGHBOR_PRICES = {row['zone']: row['price'] for _, row in neighbor_prices_df.iterrows()}

    print("\nNeighbor prices (EUR/MWh) - January 2024:")
    for _, row in neighbor_prices_df.iterrows():
        print(f"  {row['zone']}: {row['price']:.2f}")

    print(f"\nTotal Swedish demand: {demand_df[['SE1','SE2','SE3','SE4']].sum().sum():,.0f} MWh")
    print(f"Mean hourly demand: {demand_df[['SE1','SE2','SE3','SE4']].sum(axis=1).mean():,.0f} MW")

    return demand_melted, plants_df, avail_melted, nodes_df, lines_df, neighbor_prices_df


# ============================================================================
# PTDF Calculation
# ============================================================================

def calculate_ptdf(lines_df, nodes_df):
    """Calculate PTDF matrix for the 13-node network"""
    print("\n" + "=" * 70)
    print("Calculating PTDF Matrix")
    print("=" * 70)

    n_nodes = len(nodes_df)
    n_lines = len(lines_df)

    nodes = nodes_df['index'].tolist()
    node_idx = {n: i for i, n in enumerate(nodes)}

    # Slack bus (SE3)
    slack_node = 'SE3'
    slack_idx = node_idx[slack_node]

    # Build B matrix (susceptance)
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

    # Expand back to full size
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

    # Create DataFrame
    ptdf_df = pd.DataFrame(PTDF, columns=nodes, index=lines_df['index'])

    print(f"  PTDF matrix: {n_lines} lines × {n_nodes} nodes")

    return ptdf_df


# ============================================================================
# Merit Order Dispatch (Fallback)
# ============================================================================

def merit_order_dispatch(plants_df, avail, demand, plant_zone):
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

def run_fbmc(demand_df, plants_df, avail_df, lines_df, nodes_df, ptdf_df):
    """Run FBMC market clearing with PTDF-based constraints"""
    print("\n" + "=" * 70)
    print("Running FBMC Market Clearing")
    print("=" * 70)

    plants_list = plants_df['index'].tolist()
    lines = lines_df['index'].tolist()

    n_plants = len(plants_list)
    n_neighbors = len(NEIGHBOR_ZONES)
    n_vars = n_plants + n_neighbors

    # Mappings
    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    dispatch_records = []
    flow_records = []
    price_records = []
    import_records = []
    total_cost = 0.0
    total_import_cost = 0.0
    lp_failures = 0

    # Neighbor capacities from line data
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
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            c[n_plants + j] = NEIGHBOR_PRICES[neighbor]

        # Upper bounds for plants
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])

        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in NEIGHBOR_ZONES:
            cap = neighbor_caps[neighbor]
            bounds.append((-cap, cap))

        # System balance constraint
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

            # Build PTDF contribution
            ptdf_row = np.zeros(n_vars)

            # Swedish plant contributions
            for j, plant in enumerate(plants_list):
                zone = plant_zone[plant]
                if zone in ptdf_df.columns:
                    ptdf_row[j] = ptdf_df.loc[line, zone]

            # Neighbor import contributions
            for j, neighbor in enumerate(NEIGHBOR_ZONES):
                swedish_zone = neighbor_to_swedish.get(neighbor)
                if swedish_zone and swedish_zone in ptdf_df.columns:
                    ptdf_row[n_plants + j] = ptdf_df.loc[line, swedish_zone]

            # Account for demand
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

        # Solve LP
        try:
            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                           bounds=bounds, method='highs')

            if result.success:
                gen = {plants_list[j]: result.x[j] for j in range(n_plants)}
                imports = {NEIGHBOR_ZONES[j]: result.x[n_plants + j] for j in range(n_neighbors)}
                t_cost = sum(gen[p] * plant_mc[p] for p in plants_list)
                t_import_cost = sum(imports[n] * NEIGHBOR_PRICES[n] for n in NEIGHBOR_ZONES)
            else:
                lp_failures += 1
                gen, t_cost = merit_order_dispatch(plants_df, avail, demand, plant_zone)
                imports = {n: 0.0 for n in NEIGHBOR_ZONES}
                t_import_cost = 0.0
        except Exception as e:
            lp_failures += 1
            gen, t_cost = merit_order_dispatch(plants_df, avail, demand, plant_zone)
            imports = {n: 0.0 for n in NEIGHBOR_ZONES}
            t_import_cost = 0.0

        total_cost += t_cost
        total_import_cost += t_import_cost

        # Calculate flows
        net_pos = {}
        for zone in SWEDISH_ZONES:
            zone_plants = [p for p in plants_list if plant_zone[p] == zone]
            zone_gen = sum(gen[p] for p in zone_plants)
            zone_import = sum(imports[n] for n in NEIGHBOR_ZONES
                            if neighbor_to_swedish.get(n) == zone)
            net_pos[zone] = zone_gen + zone_import - demand.get(zone, 0)

        for neighbor in NEIGHBOR_ZONES:
            net_pos[neighbor] = -imports[neighbor]

        line_flows = {}
        for line in lines:
            flow = sum(ptdf_df.loc[line, zone] * net_pos.get(zone, 0)
                      for zone in ALL_ZONES if zone in ptdf_df.columns)
            line_flows[line] = flow

        # Store results
        for plant_id, g in gen.items():
            dispatch_records.append({
                'timestep': t, 'plant': plant_id, 'generation_mw': round(g, 2)
            })

        for line_id, flow in line_flows.items():
            capacity = line_cap[line_id]
            utilization = abs(flow) / capacity * 100 if capacity > 0 else 0
            flow_records.append({
                'timestep': t, 'line': line_id, 'flow_mw': round(flow, 2),
                'capacity_mw': capacity, 'utilization_pct': round(min(utilization, 100), 2)
            })

        for neighbor, imp in imports.items():
            import_records.append({
                'timestep': t, 'neighbor': neighbor, 'flow_mw': round(imp, 2),
                'direction': 'import' if imp > 0 else 'export',
                'cost_eur': round(imp * NEIGHBOR_PRICES[neighbor], 2)
            })

        for zone in SWEDISH_ZONES:
            zone_plants_df = plants_df[plants_df['zone'] == zone]
            running = zone_plants_df[zone_plants_df['index'].isin([p for p, g in gen.items() if g > 0.1])]
            if len(running) > 0:
                price = running['mc_el'].max()
            else:
                price = min(NEIGHBOR_PRICES.values())
            price_records.append({
                'timestep': t, 'zone': zone, 'price_eur_mwh': round(price, 2)
            })

    dispatch_df = pd.DataFrame(dispatch_records)
    flows_df = pd.DataFrame(flow_records)
    prices_df = pd.DataFrame(price_records)
    imports_df = pd.DataFrame(import_records)

    print(f"\n  Swedish generation cost: {total_cost:,.2f} EUR")
    print(f"  Net import cost: {total_import_cost:,.2f} EUR")
    print(f"  Total system cost: {total_cost + total_import_cost:,.2f} EUR")
    print(f"  LP failures: {lp_failures}")

    # Save results
    dispatch_df.to_csv(RESULTS_DIR / "fbmc_dispatch.csv", index=False)
    flows_df.to_csv(RESULTS_DIR / "fbmc_flows.csv", index=False)
    prices_df.to_csv(RESULTS_DIR / "fbmc_prices.csv", index=False)
    imports_df.to_csv(RESULTS_DIR / "fbmc_imports.csv", index=False)

    return dispatch_df, flows_df, prices_df, imports_df, total_cost, total_import_cost


# ============================================================================
# ATC Market Clearing
# ============================================================================

def run_atc(demand_df, plants_df, avail_df, lines_df, nodes_df):
    """Run ATC market clearing with independent NTC limits"""
    print("\n" + "=" * 70)
    print("Running ATC Market Clearing")
    print("=" * 70)

    plants_list = plants_df['index'].tolist()
    n_plants = len(plants_list)
    n_neighbors = len(NEIGHBOR_ZONES)
    n_vars = n_plants + n_neighbors

    # Mappings
    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    dispatch_records = []
    flow_records = []
    price_records = []
    import_records = []
    total_cost = 0.0
    total_import_cost = 0.0
    lp_failures = 0

    # Neighbor capacities
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
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            c[n_plants + j] = NEIGHBOR_PRICES[neighbor]

        # Bounds
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])
        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in NEIGHBOR_ZONES:
            cap = neighbor_caps[neighbor]
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

        # SE1-SE2 constraint
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

        # SE2-SE3 constraint
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

        # SE3-SE4 constraint
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

        # Solve LP
        try:
            result = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                           bounds=bounds, method='highs')

            if result.success:
                gen = {plants_list[j]: result.x[j] for j in range(n_plants)}
                imports = {NEIGHBOR_ZONES[j]: result.x[n_plants + j] for j in range(n_neighbors)}
                t_cost = sum(gen[p] * plant_mc[p] for p in plants_list)
                t_import_cost = sum(imports[n] * NEIGHBOR_PRICES[n] for n in NEIGHBOR_ZONES)
            else:
                lp_failures += 1
                gen, t_cost = merit_order_dispatch(plants_df, avail, demand, plant_zone)
                imports = {n: 0.0 for n in NEIGHBOR_ZONES}
                t_import_cost = 0.0
        except Exception as e:
            lp_failures += 1
            gen, t_cost = merit_order_dispatch(plants_df, avail, demand, plant_zone)
            imports = {n: 0.0 for n in NEIGHBOR_ZONES}
            t_import_cost = 0.0

        total_cost += t_cost
        total_import_cost += t_import_cost

        # Calculate flows
        net_pos = {}
        for zone in SWEDISH_ZONES:
            zone_plants = [p for p in plants_list if plant_zone[p] == zone]
            zone_gen = sum(gen[p] for p in zone_plants)
            zone_import = sum(imports[n] for n in NEIGHBOR_ZONES
                            if neighbor_to_swedish.get(n) == zone)
            net_pos[zone] = zone_gen + zone_import - demand.get(zone, 0)

        line_flows = {
            'L_SE1_SE2': net_pos.get('SE1', 0),
            'L_SE2_SE3': net_pos.get('SE1', 0) + net_pos.get('SE2', 0),
            'L_SE3_SE4': -net_pos.get('SE4', 0)
        }

        # Cross-border flows
        for neighbor in NEIGHBOR_ZONES:
            imp = imports[neighbor]
            for line_id, (ni, nj) in line_nodes.items():
                if neighbor in [ni, nj]:
                    line_flows[line_id] = imp if neighbor == ni else -imp
                    break

        # Store results
        for plant_id, g in gen.items():
            dispatch_records.append({
                'timestep': t, 'plant': plant_id, 'generation_mw': round(g, 2)
            })

        for line_id, flow in line_flows.items():
            capacity = line_cap.get(line_id, 0)
            utilization = abs(flow) / capacity * 100 if capacity > 0 else 0
            flow_records.append({
                'timestep': t, 'line': line_id, 'flow_mw': round(flow, 2),
                'capacity_mw': capacity, 'utilization_pct': round(min(utilization, 100), 2)
            })

        for neighbor, imp in imports.items():
            import_records.append({
                'timestep': t, 'neighbor': neighbor, 'flow_mw': round(imp, 2),
                'direction': 'import' if imp > 0 else 'export',
                'cost_eur': round(imp * NEIGHBOR_PRICES[neighbor], 2)
            })

        for zone in SWEDISH_ZONES:
            zone_plants_df = plants_df[plants_df['zone'] == zone]
            running = zone_plants_df[zone_plants_df['index'].isin([p for p, g in gen.items() if g > 0.1])]
            if len(running) > 0:
                price = running['mc_el'].max()
            else:
                price = min(NEIGHBOR_PRICES.values())
            price_records.append({
                'timestep': t, 'zone': zone, 'price_eur_mwh': round(price, 2)
            })

    dispatch_df = pd.DataFrame(dispatch_records)
    flows_df = pd.DataFrame(flow_records)
    prices_df = pd.DataFrame(price_records)
    imports_df = pd.DataFrame(import_records)

    print(f"\n  Swedish generation cost: {total_cost:,.2f} EUR")
    print(f"  Net import cost: {total_import_cost:,.2f} EUR")
    print(f"  Total system cost: {total_cost + total_import_cost:,.2f} EUR")
    print(f"  LP failures: {lp_failures}")

    # Save results
    dispatch_df.to_csv(RESULTS_DIR / "atc_dispatch.csv", index=False)
    flows_df.to_csv(RESULTS_DIR / "atc_flows.csv", index=False)
    prices_df.to_csv(RESULTS_DIR / "atc_prices.csv", index=False)
    imports_df.to_csv(RESULTS_DIR / "atc_imports.csv", index=False)

    return dispatch_df, flows_df, prices_df, imports_df, total_cost, total_import_cost


# ============================================================================
# Main Analysis
# ============================================================================

def main():
    # Load data
    demand_df, plants_df, avail_df, nodes_df, lines_df, neighbor_prices_df = load_data()

    # Calculate PTDF
    ptdf_df = calculate_ptdf(lines_df, nodes_df)

    # Run FBMC
    fbmc_dispatch, fbmc_flows, fbmc_prices, fbmc_imports, fbmc_gen_cost, fbmc_import_cost = \
        run_fbmc(demand_df, plants_df, avail_df, lines_df, nodes_df, ptdf_df)

    fbmc_total = fbmc_gen_cost + fbmc_import_cost

    # Run ATC
    atc_dispatch, atc_flows, atc_prices, atc_imports, atc_gen_cost, atc_import_cost = \
        run_atc(demand_df, plants_df, avail_df, lines_df, nodes_df)

    atc_total = atc_gen_cost + atc_import_cost

    # Calculate results
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY - January 8-14, 2024")
    print("=" * 70)

    savings = atc_total - fbmc_total
    savings_pct = (savings / atc_total * 100) if atc_total != 0 else 0

    print(f"\n{'Metric':<35} {'FBMC':>15} {'ATC':>15} {'Diff':>15}")
    print("-" * 80)
    print(f"{'Swedish Gen Cost (EUR)':<35} {fbmc_gen_cost:>15,.0f} {atc_gen_cost:>15,.0f} {fbmc_gen_cost-atc_gen_cost:>+15,.0f}")
    print(f"{'Net Import Cost (EUR)':<35} {fbmc_import_cost:>15,.0f} {atc_import_cost:>15,.0f} {fbmc_import_cost-atc_import_cost:>+15,.0f}")
    print(f"{'Total System Cost (EUR)':<35} {fbmc_total:>15,.0f} {atc_total:>15,.0f} {fbmc_total-atc_total:>+15,.0f}")
    print("-" * 80)
    print(f"{'FBMC Savings (EUR)':<35} {'-':>15} {'-':>15} {savings:>15,.0f}")
    print(f"{'FBMC Savings (%)':<35} {'-':>15} {'-':>15} {savings_pct:>14.2f}%")

    # Line utilization
    print(f"\n{'SE2-SE3 Line Utilization':}")
    fbmc_se23 = fbmc_flows[fbmc_flows['line'] == 'L_SE2_SE3']['utilization_pct'].mean()
    atc_se23 = atc_flows[atc_flows['line'] == 'L_SE2_SE3']['utilization_pct'].mean()
    print(f"  FBMC: {fbmc_se23:.1f}%")
    print(f"  ATC:  {atc_se23:.1f}%")

    # Save summary
    summary_data = {
        'metric': ['Swedish Gen Cost', 'Net Import Cost', 'Total Cost', 'FBMC Savings', 'FBMC Savings %', 'SE2-SE3 Utilization FBMC', 'SE2-SE3 Utilization ATC'],
        'fbmc': [fbmc_gen_cost, fbmc_import_cost, fbmc_total, None, None, fbmc_se23, None],
        'atc': [atc_gen_cost, atc_import_cost, atc_total, None, None, None, atc_se23],
        'difference': [fbmc_gen_cost-atc_gen_cost, fbmc_import_cost-atc_import_cost, fbmc_total-atc_total, savings, savings_pct, None, None]
    }
    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(RESULTS_DIR / "summary.csv", index=False)
    print(f"\nSaved: periods/january_2024/results/summary.csv")

    # Return key metrics for comparison
    return {
        'period': 'January 2024',
        'fbmc_total': fbmc_total,
        'atc_total': atc_total,
        'fbmc_gen_cost': fbmc_gen_cost,
        'atc_gen_cost': atc_gen_cost,
        'fbmc_import_cost': fbmc_import_cost,
        'atc_import_cost': atc_import_cost,
        'savings': savings,
        'savings_pct': savings_pct,
        'se23_fbmc_util': fbmc_se23,
        'se23_atc_util': atc_se23
    }


if __name__ == "__main__":
    results = main()

    # Print comparison with December (base case)
    print("\n" + "=" * 70)
    print("COMPARISON: January 2024 vs December 2024 (Base Case)")
    print("=" * 70)

    # December results (from previous analysis)
    dec_results = {
        'savings_pct': 6.54,
        'se23_util': 88,
        'no4_price': 7.15
    }

    print(f"\n{'Metric':<35} {'December 2024':>15} {'January 2024':>15}")
    print("-" * 65)
    print(f"{'FBMC Savings (%)':<35} {dec_results['savings_pct']:>14.2f}% {results['savings_pct']:>14.2f}%")
    print(f"{'SE2-SE3 Congestion (FBMC)':<35} {dec_results['se23_util']:>14.1f}% {results['se23_fbmc_util']:>14.1f}%")
    print(f"{'NO4 Import Price (EUR/MWh)':<35} {dec_results['no4_price']:>15.2f} {NEIGHBOR_PRICES['NO4']:>15.2f}")
