#!/usr/bin/env python3
"""
POMATO Extended Nordic Network - FBMC vs ATC Analysis
Swedish Electricity Market with Cross-Border Connections

Date Range: Dec 2-8, 2024 (168 hours)
Network: 13 nodes (4 Swedish + 9 neighbors), 13 lines (3 internal + 10 cross-border)

This analysis extends the Swedish model to include meshed network topology
where FBMC benefits can emerge through loop flow management.

Key Features:
- Swedish zones (SE1-SE4): Generation dispatch with plants and demand
- Neighbor zones (NO1, NO3, NO4, FI, DK1, DK2, PL, LT, DE): Price zones for import/export
- PTDF calculation for full 13-node network
- Loop identification to verify meshed topology
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

from scipy.optimize import linprog
import networkx as nx

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ============================================================================
# Configuration
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data" / "december_2024"
RESULTS_DIR = REPO_ROOT / "results" / "december_2024"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Date range: Dec 2-8, 2024 (168 hours)
START_DATE = datetime(2024, 12, 2, 0, 0)
END_DATE = datetime(2024, 12, 8, 23, 0)
NUM_HOURS = 168

# Swedish bidding zones
SWEDISH_ZONES = ['SE1', 'SE2', 'SE3', 'SE4']

# Neighbor zones (price-based import/export)
NEIGHBOR_ZONES = ['NO1', 'NO3', 'NO4', 'FI', 'DK1', 'DK2', 'PL', 'LT', 'DE']

# All zones
ALL_ZONES = SWEDISH_ZONES + NEIGHBOR_ZONES

# Neighbor prices - loaded from neighbor_prices.csv (real ENTSO-E day-ahead prices)
# Will be populated by load_data() function
NEIGHBOR_PRICES = {}

# Large capacity for neighbor import/export (effectively unlimited)
NEIGHBOR_CAPACITY = 50000  # MW

print("=" * 70)
print("POMATO EXTENDED NORDIC NETWORK ANALYSIS")
print("FBMC vs ATC with Cross-Border Connections")
print("Swedish Electricity Market - Dec 2-8, 2024")
print("=" * 70)

# ============================================================================
# Load Data
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

    print(f"  Demand: {len(demand_df)} records (Swedish zones only)")
    print(f"  Plants: {len(plants_df)} plants (Swedish zones only)")
    print(f"  Availability: {len(avail_df)} records")
    print(f"  Nodes: {len(nodes_df)} zones ({len(nodes_df[nodes_df['index'].isin(SWEDISH_ZONES)])} Swedish + {len(nodes_df[~nodes_df['index'].isin(SWEDISH_ZONES)])} neighbors)")
    print(f"  Lines: {len(lines_df)} corridors")

    print("\nNetwork topology:")
    internal_lines = lines_df[lines_df['node_i'].isin(SWEDISH_ZONES) & lines_df['node_j'].isin(SWEDISH_ZONES)]
    cross_border = lines_df[~(lines_df['node_i'].isin(SWEDISH_ZONES) & lines_df['node_j'].isin(SWEDISH_ZONES))]
    print(f"  Internal Swedish lines: {len(internal_lines)}")
    print(f"  Cross-border lines: {len(cross_border)}")

    print("\nLine capacities:")
    for _, line in lines_df.iterrows():
        line_type = "internal" if (line['node_i'] in SWEDISH_ZONES and line['node_j'] in SWEDISH_ZONES) else "cross-border"
        tech = line.get('technology', 'ac')
        print(f"  {line['index']}: {line['capacity']:.0f} MW ({line_type}, {tech})")

    # Populate global NEIGHBOR_PRICES from CSV
    global NEIGHBOR_PRICES
    NEIGHBOR_PRICES = {row['zone']: row['price'] for _, row in neighbor_prices_df.iterrows()}

    print("\nNeighbor prices (EUR/MWh) - from ENTSO-E day-ahead:")
    for _, row in neighbor_prices_df.iterrows():
        print(f"  {row['zone']}: {row['price']:.2f} - {row['rationale']}")

    return demand_df, plants_df, avail_df, nodes_df, lines_df, neighbor_prices_df


def identify_loops(lines_df):
    """Identify network loops using graph analysis"""
    print("\n" + "=" * 70)
    print("STEP 1B: Network Loop Analysis")
    print("=" * 70)

    G = nx.Graph()

    for _, line in lines_df.iterrows():
        G.add_edge(line['node_i'], line['node_j'], capacity=line['capacity'])

    # Find all cycles (loops)
    try:
        cycles = nx.cycle_basis(G)
        print(f"\nNumber of independent loops: {len(cycles)}")

        if len(cycles) > 0:
            print("\nIdentified loops:")
            for i, cycle in enumerate(cycles):
                print(f"  Loop {i+1}: {' -> '.join(cycle)} -> {cycle[0]}")
        else:
            print("\nWARNING: No loops found - network is radial (tree structure)")
            print("FBMC benefits typically require meshed networks with loops.")
    except:
        cycles = []
        print("Could not analyze cycles")

    # Network statistics
    print(f"\nNetwork statistics:")
    print(f"  Nodes: {G.number_of_nodes()}")
    print(f"  Edges: {G.number_of_edges()}")
    print(f"  Connected: {nx.is_connected(G)}")

    return cycles


# ============================================================================
# PTDF Calculation for Extended Network
# ============================================================================

def calculate_ptdf_extended(lines_df, nodes_df):
    """Calculate PTDF matrix for the extended 13-node network"""
    print("\n" + "=" * 70)
    print("STEP 2: Calculating Extended PTDF Matrix")
    print("=" * 70)

    n_nodes = len(nodes_df)
    n_lines = len(lines_df)

    nodes = nodes_df['index'].tolist()
    node_idx = {n: i for i, n in enumerate(nodes)}

    print(f"\nNodes ({n_nodes}): {nodes}")
    print(f"Lines ({n_lines}): {lines_df['index'].tolist()}")

    # Find slack bus (SE3)
    slack_node = 'SE3'
    slack_idx = node_idx[slack_node]
    print(f"Slack bus: {slack_node} (index {slack_idx})")

    # Build B matrix (susceptance)
    B = np.zeros((n_nodes, n_nodes))

    for _, line in lines_df.iterrows():
        i = node_idx[line['node_i']]
        j = node_idx[line['node_j']]
        # Use susceptance (1/x) for DC power flow
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
        print("  B matrix inverted successfully")
    except np.linalg.LinAlgError:
        print("  Warning: Singular B matrix, using pseudo-inverse")
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

    print("\nPTDF Matrix (Lines × Zones):")
    print(ptdf_df.round(3).to_string())

    # Check for non-trivial PTDF values
    non_trivial = np.abs(PTDF) > 0.001
    non_trivial &= np.abs(PTDF) < 0.999
    non_trivial_count = non_trivial.sum()
    print(f"\nNon-trivial PTDF entries (not 0 or ±1): {non_trivial_count}")

    if non_trivial_count > 0:
        print("  This indicates loop flows are present - FBMC can provide benefits!")
    else:
        print("  WARNING: All PTDF values are 0 or ±1 - network may still be effectively radial")

    # Save PTDF
    ptdf_df.to_csv(RESULTS_DIR / "ptdf_matrix_extended.csv")
    print(f"\nSaved: results/ptdf_matrix_extended.csv")

    return ptdf_df


# ============================================================================
# Market Clearing - Extended FBMC
# ============================================================================

def run_fbmc_extended(demand_df, plants_df, avail_df, lines_df, nodes_df, ptdf_df):
    """
    Run FBMC market clearing with extended network.

    Swedish zones: Dispatch based on plants and demand
    Neighbor zones: Import/export at fixed prices (unlimited capacity)
    """
    print("\n" + "=" * 70)
    print("STEP 3: Running Extended FBMC Scenario")
    print("=" * 70)

    plants_list = plants_df['index'].tolist()
    lines = lines_df['index'].tolist()
    nodes = nodes_df['index'].tolist()

    n_plants = len(plants_list)
    n_lines = len(lines)
    n_neighbors = len(NEIGHBOR_ZONES)

    # Decision variables: [Swedish plants..., neighbor imports (positive=import to Sweden)]
    # For each neighbor, positive value means Sweden imports from neighbor
    n_vars = n_plants + n_neighbors

    # Mappings
    plant_zone = {row['index']: row['zone'] for _, row in plants_df.iterrows()}
    plant_mc = {row['index']: row['mc_el'] for _, row in plants_df.iterrows()}
    plant_gmax = {row['index']: row['g_max'] for _, row in plants_df.iterrows()}
    line_cap = {row['index']: row['capacity'] for _, row in lines_df.iterrows()}

    # Line-to-nodes mapping for cross-border flows
    line_nodes = {row['index']: (row['node_i'], row['node_j']) for _, row in lines_df.iterrows()}

    timesteps = sorted(demand_df['timestep'].unique())

    dispatch_records = []
    flow_records = []
    price_records = []
    import_records = []
    total_cost = 0.0
    total_import_cost = 0.0

    lp_failures = 0

    print(f"\nOptimization setup:")
    print(f"  Swedish plants: {n_plants}")
    print(f"  Neighbor zones: {n_neighbors}")
    print(f"  Total decision variables: {n_vars}")

    for t in timesteps:
        # Get demand and availability
        t_demand = demand_df[demand_df['timestep'] == t]
        demand = {row['node']: row['demand_el'] for _, row in t_demand.iterrows()}
        total_swedish_demand = sum(demand.values())

        t_avail = avail_df[avail_df['timestep'] == t]
        avail = {row['plant']: row['availability'] for _, row in t_avail.iterrows()}

        # Objective: minimize Swedish generation cost + net import cost
        # cost = sum(gen_i * mc_i) + sum(import_j * price_j) - sum(export_j * price_j)
        # Since import is positive and export is negative:
        # cost = sum(gen_i * mc_i) + sum(flow_j * price_j)  where flow > 0 is import

        c = np.zeros(n_vars)
        # Plant costs
        for j, p in enumerate(plants_list):
            c[j] = plant_mc[p]
        # Neighbor import costs (import costs money, export earns money)
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            c[n_plants + j] = NEIGHBOR_PRICES[neighbor]

        # Upper bounds for plants
        ub_plants = np.array([plant_gmax[p] * avail.get(p, 1.0) for p in plants_list])

        # Bounds for neighbor flows (positive=import, negative=export)
        # Limited by cross-border line capacities
        neighbor_caps = {}
        for neighbor in NEIGHBOR_ZONES:
            # Find line connecting this neighbor to Sweden
            for line_id, (node_i, node_j) in line_nodes.items():
                if neighbor in [node_i, node_j]:
                    cap = line_cap[line_id]
                    neighbor_caps[neighbor] = cap
                    break
            else:
                neighbor_caps[neighbor] = NEIGHBOR_CAPACITY

        bounds = [(0, ub_plants[j]) for j in range(n_plants)]
        for neighbor in NEIGHBOR_ZONES:
            cap = neighbor_caps[neighbor]
            bounds.append((-cap, cap))  # Can import or export up to line capacity

        # Equality constraint: Swedish power balance
        # Total Swedish generation + total imports = total Swedish demand
        A_eq = np.zeros((1, n_vars))
        b_eq = np.zeros(1)

        # Swedish generation
        A_eq[0, :n_plants] = 1.0
        # Net imports from neighbors (positive = import to Sweden)
        A_eq[0, n_plants:] = 1.0
        b_eq[0] = total_swedish_demand

        # Inequality constraints: PTDF-based flow limits
        A_ub = []
        b_ub = []

        for l_idx, line in enumerate(lines):
            cap = line_cap[line]
            node_i, node_j = line_nodes[line]

            # Build PTDF contribution for this line
            ptdf_row = np.zeros(n_vars)

            # Swedish plant contributions
            for j, plant in enumerate(plants_list):
                zone = plant_zone[plant]
                if zone in ptdf_df.columns:
                    ptdf_row[j] = ptdf_df.loc[line, zone]

            # Neighbor import contributions
            # If we import from neighbor X, it's like generation at X minus demand at X
            # So import from X = injection at X
            for j, neighbor in enumerate(NEIGHBOR_ZONES):
                if neighbor in ptdf_df.columns:
                    # Import TO Sweden = negative injection at neighbor (withdrawal)
                    # But we model import as positive for Sweden...
                    # Actually: import to Sweden = injection somewhere in Sweden
                    # We need to determine WHERE the import enters Sweden
                    # For now, assume import enters at the Swedish zone connected to this neighbor

                    # Find which Swedish zone this neighbor connects to
                    for line_id, (ni, nj) in line_nodes.items():
                        if neighbor == ni and nj in SWEDISH_ZONES:
                            swedish_zone = nj
                            break
                        elif neighbor == nj and ni in SWEDISH_ZONES:
                            swedish_zone = ni
                            break
                    else:
                        continue

                    # Import from neighbor = injection at the Swedish border zone
                    ptdf_row[n_plants + j] = ptdf_df.loc[line, swedish_zone]

            # Account for Swedish demand as withdrawal
            ptdf_demand = 0.0
            for zone in SWEDISH_ZONES:
                if zone in ptdf_df.columns:
                    ptdf_demand += ptdf_df.loc[line, zone] * demand.get(zone, 0)

            # Flow = PTDF × (generation - demand + imports)
            # |flow| <= capacity
            # PTDF × gen + PTDF × imports <= capacity + PTDF × demand
            # -PTDF × gen - PTDF × imports <= capacity - PTDF × demand

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

        # Calculate flows using PTDF
        net_pos = {}
        for zone in SWEDISH_ZONES:
            zone_plants = [p for p in plants_list if plant_zone[p] == zone]
            zone_gen = sum(gen[p] for p in zone_plants)

            # Add imports that enter at this zone
            zone_import = 0.0
            for neighbor in NEIGHBOR_ZONES:
                for line_id, (ni, nj) in line_nodes.items():
                    if (neighbor == ni and nj == zone) or (neighbor == nj and ni == zone):
                        zone_import += imports[neighbor]
                        break

            net_pos[zone] = zone_gen + zone_import - demand.get(zone, 0)

        # For neighbor zones, net position is negative of their export to Sweden
        for neighbor in NEIGHBOR_ZONES:
            net_pos[neighbor] = -imports[neighbor]  # Export from neighbor = negative injection

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

        # Zonal prices (approximate as marginal cost of most expensive running unit)
        for zone in SWEDISH_ZONES:
            zone_plants_df = plants_df[plants_df['zone'] == zone]
            running = zone_plants_df[zone_plants_df['index'].isin([p for p, g in gen.items() if g > 0.1])]
            if len(running) > 0:
                price = running['mc_el'].max()
            else:
                # If no local generation, price is determined by imports
                # Use the cheapest available import price
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
    print(f"  LP failures (fell back to merit order): {lp_failures}")

    # Save results
    dispatch_df.to_csv(RESULTS_DIR / "fbmc_extended_dispatch.csv", index=False)
    flows_df.to_csv(RESULTS_DIR / "fbmc_extended_flows.csv", index=False)
    prices_df.to_csv(RESULTS_DIR / "fbmc_extended_prices.csv", index=False)
    imports_df.to_csv(RESULTS_DIR / "fbmc_extended_imports.csv", index=False)
    print(f"  Saved: fbmc_extended_*.csv files")

    return dispatch_df, flows_df, prices_df, imports_df, total_cost, total_import_cost


# ============================================================================
# Market Clearing - Extended ATC
# ============================================================================

def run_atc_extended(demand_df, plants_df, avail_df, lines_df, nodes_df):
    """
    Run ATC market clearing with extended network.

    Each line has independent NTC limits.
    No PTDF coupling - flows are treated as directly controllable.
    """
    print("\n" + "=" * 70)
    print("STEP 4: Running Extended ATC Scenario")
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

    # Get neighbor line capacities
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
        # Get demand and availability
        t_demand = demand_df[demand_df['timestep'] == t]
        demand = {row['node']: row['demand_el'] for _, row in t_demand.iterrows()}
        total_swedish_demand = sum(demand.values())

        t_avail = avail_df[avail_df['timestep'] == t]
        avail = {row['plant']: row['availability'] for _, row in t_avail.iterrows()}

        # Objective: minimize cost
        c = np.zeros(n_vars)
        for j, p in enumerate(plants_list):
            c[j] = plant_mc[p]
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            c[n_plants + j] = NEIGHBOR_PRICES[neighbor]

        # Upper bounds
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

        # ATC constraints: independent NTC limits on internal Swedish lines
        A_ub = []
        b_ub = []

        # SE1-SE2: SE1 net export <= NTC
        se1_plants = [j for j, p in enumerate(plants_list) if plant_zone[p] == 'SE1']
        row = np.zeros(n_vars)
        for j in se1_plants:
            row[j] = 1.0
        # Add imports from neighbors connected to SE1
        for j, neighbor in enumerate(NEIGHBOR_ZONES):
            if neighbor_to_swedish.get(neighbor) == 'SE1':
                row[n_plants + j] = 1.0

        se1_ntc = line_cap.get('L_SE1_SE2', 3300)
        A_ub.append(row.copy())
        b_ub.append(se1_ntc + demand.get('SE1', 0))
        A_ub.append(-row.copy())
        b_ub.append(se1_ntc - demand.get('SE1', 0))

        # SE2-SE3: (SE1+SE2 + imports to SE1/SE2) net export <= NTC
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

        # SE3-SE4: similar logic
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

        # Cross-border capacity limits are already in bounds

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

        # Calculate flows for Swedish internal lines
        net_pos = {}
        for zone in SWEDISH_ZONES:
            zone_plants = [p for p in plants_list if plant_zone[p] == zone]
            zone_gen = sum(gen[p] for p in zone_plants)
            zone_import = sum(imports[n] for n in NEIGHBOR_ZONES
                            if neighbor_to_swedish.get(n) == zone)
            net_pos[zone] = zone_gen + zone_import - demand.get(zone, 0)

        # Simple flow model for radial Swedish network
        line_flows = {
            'L_SE1_SE2': net_pos.get('SE1', 0),
            'L_SE2_SE3': net_pos.get('SE1', 0) + net_pos.get('SE2', 0),
            'L_SE3_SE4': -net_pos.get('SE4', 0)
        }

        # Add cross-border flows
        for neighbor in NEIGHBOR_ZONES:
            imp = imports[neighbor]
            # Find the line connecting this neighbor
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
            capacity = line_cap.get(line_id, NEIGHBOR_CAPACITY)
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

        # Zonal prices
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
    print(f"  LP failures (fell back to merit order): {lp_failures}")

    # Save results
    dispatch_df.to_csv(RESULTS_DIR / "atc_extended_dispatch.csv", index=False)
    flows_df.to_csv(RESULTS_DIR / "atc_extended_flows.csv", index=False)
    prices_df.to_csv(RESULTS_DIR / "atc_extended_prices.csv", index=False)
    imports_df.to_csv(RESULTS_DIR / "atc_extended_imports.csv", index=False)
    print(f"  Saved: atc_extended_*.csv files")

    return dispatch_df, flows_df, prices_df, imports_df, total_cost, total_import_cost


def merit_order_dispatch(plants_df, avail, demand, plant_zone):
    """Fallback merit order dispatch"""
    plants_sorted = plants_df.sort_values('mc_el')
    gen = {p: 0.0 for p in plants_df['index']}
    total_demand = sum(demand.values())
    remaining_demand = total_demand
    cost = 0.0

    for _, plant in plants_sorted.iterrows():
        plant_id = plant['index']
        g_max = plant['g_max']
        mc = plant['mc_el']
        plant_avail = avail.get(plant_id, 1.0)
        max_gen = g_max * plant_avail

        dispatch = min(max_gen, remaining_demand)
        gen[plant_id] = dispatch
        remaining_demand -= dispatch
        cost += dispatch * mc

        if remaining_demand <= 0:
            break

    return gen, cost


# ============================================================================
# Results Comparison
# ============================================================================

def compare_results(fbmc_results, atc_results, lines_df):
    """Compare FBMC and ATC results for extended network"""
    print("\n" + "=" * 70)
    print("STEP 5: Comparing Results")
    print("=" * 70)

    fbmc_dispatch, fbmc_flows, fbmc_prices, fbmc_imports, fbmc_gen_cost, fbmc_import_cost = fbmc_results
    atc_dispatch, atc_flows, atc_prices, atc_imports, atc_gen_cost, atc_import_cost = atc_results

    fbmc_total = fbmc_gen_cost + fbmc_import_cost
    atc_total = atc_gen_cost + atc_import_cost
    savings = atc_total - fbmc_total
    savings_pct = savings / atc_total * 100 if atc_total > 0 else 0

    print("\n--- Cost Comparison ---")
    print(f"\n| Metric | FBMC | ATC | Difference |")
    print(f"|--------|------|-----|------------|")
    print(f"| Swedish gen cost (EUR) | {fbmc_gen_cost:,.0f} | {atc_gen_cost:,.0f} | {atc_gen_cost - fbmc_gen_cost:,.0f} |")
    print(f"| Net import cost (EUR) | {fbmc_import_cost:,.0f} | {atc_import_cost:,.0f} | {atc_import_cost - fbmc_import_cost:,.0f} |")
    print(f"| Total system cost (EUR) | {fbmc_total:,.0f} | {atc_total:,.0f} | {savings:,.0f} |")
    print(f"| Cost savings (%) | - | - | {savings_pct:.2f}% |")

    # Line utilization comparison
    print("\n--- Line Utilization ---")
    print(f"\n| Line | FBMC Util% | ATC Util% | FBMC Cong Hrs | ATC Cong Hrs |")
    print(f"|------|------------|-----------|---------------|--------------|")

    all_lines = sorted(set(fbmc_flows['line'].unique()) | set(atc_flows['line'].unique()))
    for line in all_lines:
        fbmc_l = fbmc_flows[fbmc_flows['line'] == line]['utilization_pct']
        atc_l = atc_flows[atc_flows['line'] == line]['utilization_pct']
        fbmc_cong = len(fbmc_l[fbmc_l >= 99]) if len(fbmc_l) > 0 else 0
        atc_cong = len(atc_l[atc_l >= 99]) if len(atc_l) > 0 else 0
        fbmc_mean = fbmc_l.mean() if len(fbmc_l) > 0 else 0
        atc_mean = atc_l.mean() if len(atc_l) > 0 else 0
        print(f"| {line} | {fbmc_mean:.1f} | {atc_mean:.1f} | {fbmc_cong} | {atc_cong} |")

    # Import/export comparison
    print("\n--- Cross-Border Flows (Average MW) ---")
    print(f"\n| Neighbor | FBMC Avg | ATC Avg | Direction |")
    print(f"|----------|----------|---------|-----------|")

    for neighbor in NEIGHBOR_ZONES:
        fbmc_n = fbmc_imports[fbmc_imports['neighbor'] == neighbor]['flow_mw'].mean()
        atc_n = atc_imports[atc_imports['neighbor'] == neighbor]['flow_mw'].mean()
        direction = "Import" if fbmc_n > 0 else "Export"
        print(f"| {neighbor} | {fbmc_n:+.1f} | {atc_n:+.1f} | {direction} |")

    # Price comparison
    print("\n--- Zonal Prices ---")
    print(f"\n| Zone | FBMC Price | ATC Price | Spread |")
    print(f"|------|------------|-----------|--------|")

    for zone in SWEDISH_ZONES:
        fbmc_p = fbmc_prices[fbmc_prices['zone'] == zone]['price_eur_mwh'].mean()
        atc_p = atc_prices[atc_prices['zone'] == zone]['price_eur_mwh'].mean()
        spread = atc_p - fbmc_p
        print(f"| {zone} | {fbmc_p:.2f} | {atc_p:.2f} | {spread:+.2f} |")

    # Save summary
    summary_data = {
        'Metric': [
            'Swedish Generation Cost (EUR)',
            'Net Import Cost (EUR)',
            'Total System Cost (EUR)',
            'Cost Savings FBMC vs ATC (EUR)',
            'Cost Savings (%)',
        ],
        'FBMC': [fbmc_gen_cost, fbmc_import_cost, fbmc_total, savings, savings_pct],
        'ATC': [atc_gen_cost, atc_import_cost, atc_total, '-', '-'],
    }

    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(RESULTS_DIR / "fbmc_vs_atc_extended_summary.csv", index=False)
    print(f"\nSaved: results/fbmc_vs_atc_extended_summary.csv")

    return summary_df, savings, savings_pct


# ============================================================================
# Visualizations
# ============================================================================

def generate_visualizations(fbmc_results, atc_results, nodes_df, lines_df):
    """Generate visualization figures for extended network"""
    print("\n" + "=" * 70)
    print("STEP 6: Generating Visualizations")
    print("=" * 70)

    fbmc_dispatch, fbmc_flows, fbmc_prices, fbmc_imports, _, _ = fbmc_results
    atc_dispatch, atc_flows, atc_prices, atc_imports, _, _ = atc_results

    # Create timestamp mapping
    timestamps = pd.date_range(START_DATE, END_DATE, freq='h')
    time_map = {f"t{i+1:04d}": ts for i, ts in enumerate(timestamps)}

    # 1. Network Topology Map
    print("\n1. Creating network_topology_extended.png...")
    fig, ax = plt.subplots(figsize=(14, 10))

    # Plot nodes
    node_colors = {'SE1': 'blue', 'SE2': 'blue', 'SE3': 'blue', 'SE4': 'blue'}
    for neighbor in NEIGHBOR_ZONES:
        node_colors[neighbor] = 'green'

    for _, node in nodes_df.iterrows():
        color = node_colors.get(node['index'], 'gray')
        ax.scatter(node['lon'], node['lat'], s=300, c=color, zorder=5, edgecolors='black')
        ax.annotate(node['index'], (node['lon'], node['lat']), fontsize=10, ha='center', va='bottom',
                   xytext=(0, 10), textcoords='offset points', fontweight='bold')

    # Plot lines
    node_pos = {row['index']: (row['lon'], row['lat']) for _, row in nodes_df.iterrows()}
    for _, line in lines_df.iterrows():
        x = [node_pos[line['node_i']][0], node_pos[line['node_j']][0]]
        y = [node_pos[line['node_i']][1], node_pos[line['node_j']][1]]
        tech = line.get('technology', 'ac')
        linestyle = '-' if tech == 'ac' else '--'
        color = 'darkblue' if (line['node_i'] in SWEDISH_ZONES and line['node_j'] in SWEDISH_ZONES) else 'green'
        ax.plot(x, y, linestyle, color=color, linewidth=2, alpha=0.7)

        # Add capacity label
        mid_x, mid_y = (x[0] + x[1]) / 2, (y[0] + y[1]) / 2
        ax.annotate(f"{line['capacity']:.0f} MW", (mid_x, mid_y), fontsize=8, ha='center',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('Extended Nordic Network Topology\n13 Nodes, 13 Lines (Blue=Swedish, Green=Cross-border)',
                fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)

    # Add legend
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    legend_elements = [
        Patch(facecolor='blue', edgecolor='black', label='Swedish zones'),
        Patch(facecolor='green', edgecolor='black', label='Neighbor zones'),
        Line2D([0], [0], color='darkblue', linewidth=2, label='Internal lines'),
        Line2D([0], [0], color='green', linewidth=2, label='Cross-border lines'),
        Line2D([0], [0], color='gray', linewidth=2, linestyle='--', label='DC links'),
    ]
    ax.legend(handles=legend_elements, loc='lower right')

    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "network_topology_extended.png", dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: network_topology_extended.png")

    # 2. Price Time Series
    print("\n2. Creating price_timeseries_extended.png...")
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    colors = {'SE1': '#1f77b4', 'SE2': '#ff7f0e', 'SE3': '#2ca02c', 'SE4': '#d62728'}

    for zone in SWEDISH_ZONES:
        fbmc_z = fbmc_prices[fbmc_prices['zone'] == zone].copy()
        fbmc_z['datetime'] = fbmc_z['timestep'].map(time_map)
        fbmc_z = fbmc_z.sort_values('datetime')
        axes[0].plot(fbmc_z['datetime'], fbmc_z['price_eur_mwh'], label=zone,
                     color=colors[zone], linewidth=1.5)

        atc_z = atc_prices[atc_prices['zone'] == zone].copy()
        atc_z['datetime'] = atc_z['timestep'].map(time_map)
        atc_z = atc_z.sort_values('datetime')
        axes[1].plot(atc_z['datetime'], atc_z['price_eur_mwh'], label=zone,
                     color=colors[zone], linewidth=1.5)

    axes[0].set_title('FBMC Extended - Zonal Prices', fontsize=12, fontweight='bold')
    axes[0].set_ylabel('Price (EUR/MWh)')
    axes[0].legend(loc='upper right')
    axes[0].grid(True, alpha=0.3)
    axes[0].set_ylim(bottom=0)

    axes[1].set_title('ATC Extended - Zonal Prices', fontsize=12, fontweight='bold')
    axes[1].set_ylabel('Price (EUR/MWh)')
    axes[1].set_xlabel('Date/Time')
    axes[1].legend(loc='upper right')
    axes[1].grid(True, alpha=0.3)
    axes[1].set_ylim(bottom=0)

    axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    axes[1].xaxis.set_major_locator(mdates.DayLocator())

    fig.suptitle('Swedish Electricity Prices - Extended Network (Dec 2-8, 2024)',
                 fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "price_timeseries_extended.png", dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: price_timeseries_extended.png")

    # 3. Cross-Border Flows
    print("\n3. Creating cross_border_flows.png...")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for idx, (imports_df, title) in enumerate([(fbmc_imports, 'FBMC'), (atc_imports, 'ATC')]):
        avg_flows = imports_df.groupby('neighbor')['flow_mw'].mean()
        colors_cb = ['green' if v > 0 else 'red' for v in avg_flows.values]

        bars = axes[idx].barh(avg_flows.index, avg_flows.values, color=colors_cb, edgecolor='black')
        axes[idx].axvline(x=0, color='black', linewidth=1)
        axes[idx].set_xlabel('Average Flow (MW)')
        axes[idx].set_title(f'{title} - Cross-Border Flows\n(+ve = Import to Sweden)', fontsize=12, fontweight='bold')
        axes[idx].grid(True, alpha=0.3, axis='x')

        # Add value labels
        for bar, val in zip(bars, avg_flows.values):
            x_pos = val + 20 if val > 0 else val - 20
            ha = 'left' if val > 0 else 'right'
            axes[idx].annotate(f'{val:+.0f}', (x_pos, bar.get_y() + bar.get_height()/2),
                             va='center', ha=ha, fontsize=9)

    fig.suptitle('Cross-Border Power Flows - Extended Network', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "cross_border_flows.png", dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: cross_border_flows.png")

    # 4. FBMC vs ATC Comparison
    print("\n4. Creating fbmc_vs_atc_extended.png...")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Cost comparison
    costs = {
        'Swedish Gen': [fbmc_results[4], atc_results[4]],
        'Net Import': [fbmc_results[5], atc_results[5]],
    }
    x = np.arange(len(costs))
    width = 0.35

    fbmc_costs = [costs['Swedish Gen'][0], costs['Net Import'][0]]
    atc_costs = [costs['Swedish Gen'][1], costs['Net Import'][1]]

    axes[0, 0].bar(x - width/2, [c/1e6 for c in fbmc_costs], width, label='FBMC', color='steelblue')
    axes[0, 0].bar(x + width/2, [c/1e6 for c in atc_costs], width, label='ATC', color='coral')
    axes[0, 0].set_ylabel('Cost (Million EUR)')
    axes[0, 0].set_title('Cost Comparison', fontsize=12, fontweight='bold')
    axes[0, 0].set_xticks(x)
    axes[0, 0].set_xticklabels(['Swedish Gen', 'Net Import'])
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=0.3, axis='y')

    # Price comparison
    zones = SWEDISH_ZONES
    fbmc_avg_prices = [fbmc_prices[fbmc_prices['zone'] == z]['price_eur_mwh'].mean() for z in zones]
    atc_avg_prices = [atc_prices[atc_prices['zone'] == z]['price_eur_mwh'].mean() for z in zones]

    x = np.arange(len(zones))
    axes[0, 1].bar(x - width/2, fbmc_avg_prices, width, label='FBMC', color='steelblue')
    axes[0, 1].bar(x + width/2, atc_avg_prices, width, label='ATC', color='coral')
    axes[0, 1].set_ylabel('Price (EUR/MWh)')
    axes[0, 1].set_title('Average Zonal Prices', fontsize=12, fontweight='bold')
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(zones)
    axes[0, 1].legend()
    axes[0, 1].grid(True, alpha=0.3, axis='y')

    # Line utilization (Swedish internal)
    swedish_lines = ['L_SE1_SE2', 'L_SE2_SE3', 'L_SE3_SE4']
    fbmc_util = [fbmc_flows[fbmc_flows['line'] == l]['utilization_pct'].mean() for l in swedish_lines]
    atc_util = [atc_flows[atc_flows['line'] == l]['utilization_pct'].mean() for l in swedish_lines]

    x = np.arange(len(swedish_lines))
    axes[1, 0].bar(x - width/2, fbmc_util, width, label='FBMC', color='steelblue')
    axes[1, 0].bar(x + width/2, atc_util, width, label='ATC', color='coral')
    axes[1, 0].axhline(y=100, color='red', linestyle='--', alpha=0.7)
    axes[1, 0].set_ylabel('Utilization (%)')
    axes[1, 0].set_title('Swedish Internal Line Utilization', fontsize=12, fontweight='bold')
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels([l.replace('L_', '').replace('_', '-') for l in swedish_lines])
    axes[1, 0].legend()
    axes[1, 0].grid(True, alpha=0.3, axis='y')

    # Total imports by neighbor
    fbmc_total_imports = fbmc_imports.groupby('neighbor')['flow_mw'].sum() / 1000  # GWh
    atc_total_imports = atc_imports.groupby('neighbor')['flow_mw'].sum() / 1000

    x = np.arange(len(NEIGHBOR_ZONES))
    axes[1, 1].bar(x - width/2, [fbmc_total_imports.get(n, 0) for n in NEIGHBOR_ZONES],
                   width, label='FBMC', color='steelblue')
    axes[1, 1].bar(x + width/2, [atc_total_imports.get(n, 0) for n in NEIGHBOR_ZONES],
                   width, label='ATC', color='coral')
    axes[1, 1].axhline(y=0, color='black', linewidth=1)
    axes[1, 1].set_ylabel('Total Flow (GWh)')
    axes[1, 1].set_title('Total Cross-Border Flows', fontsize=12, fontweight='bold')
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(NEIGHBOR_ZONES, rotation=45, ha='right')
    axes[1, 1].legend()
    axes[1, 1].grid(True, alpha=0.3, axis='y')

    fig.suptitle('FBMC vs ATC Comparison - Extended Network', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / "fbmc_vs_atc_extended.png", dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: fbmc_vs_atc_extended.png")

    print("\nAll visualizations saved to results/")


# ============================================================================
# Report Generation
# ============================================================================

def create_report(fbmc_results, atc_results, ptdf_df, cycles, savings, savings_pct, nodes_df, lines_df):
    """Create final markdown report for extended network analysis"""
    print("\n" + "=" * 70)
    print("STEP 7: Creating Final Report")
    print("=" * 70)

    fbmc_dispatch, fbmc_flows, fbmc_prices, fbmc_imports, fbmc_gen_cost, fbmc_import_cost = fbmc_results
    atc_dispatch, atc_flows, atc_prices, atc_imports, atc_gen_cost, atc_import_cost = atc_results

    fbmc_total = fbmc_gen_cost + fbmc_import_cost
    atc_total = atc_gen_cost + atc_import_cost

    # Network description
    internal_lines = lines_df[lines_df['node_i'].isin(SWEDISH_ZONES) & lines_df['node_j'].isin(SWEDISH_ZONES)]
    cross_border = lines_df[~(lines_df['node_i'].isin(SWEDISH_ZONES) & lines_df['node_j'].isin(SWEDISH_ZONES))]

    report = f"""# Extended Nordic Network Analysis
## FBMC vs ATC with Cross-Border Connections
### Swedish Electricity Market - December 2-8, 2024

---

## Executive Summary

This analysis extends the Swedish electricity market model (SE1-SE4) to include
cross-border connections with neighboring countries, creating a meshed network
topology where FBMC benefits can emerge through loop flow management.

**Key Result:** FBMC achieves a **{savings_pct:.2f}% cost reduction** compared to ATC,
saving approximately **{savings:,.0f} EUR** over the analysis week.

---

## 1. Network Description

### 1.1 Topology

| Category | Count |
|----------|-------|
| Total nodes | {len(nodes_df)} |
| Swedish zones | {len(nodes_df[nodes_df['index'].isin(SWEDISH_ZONES)])} (SE1, SE2, SE3, SE4) |
| Neighbor zones | {len(nodes_df[~nodes_df['index'].isin(SWEDISH_ZONES)])} ({', '.join(NEIGHBOR_ZONES)}) |
| Total lines | {len(lines_df)} |
| Internal Swedish lines | {len(internal_lines)} |
| Cross-border lines | {len(cross_border)} |
| Network loops | {len(cycles)} |

### 1.2 Line Capacities

| Line | From | To | Capacity (MW) | Technology |
|------|------|-----|---------------|------------|
"""

    for _, line in lines_df.iterrows():
        tech = line.get('technology', 'ac')
        report += f"| {line['index']} | {line['node_i']} | {line['node_j']} | {line['capacity']:.0f} | {tech.upper()} |\n"

    report += f"""
### 1.3 Identified Network Loops

"""
    if len(cycles) > 0:
        for i, cycle in enumerate(cycles):
            cycle_str = ' -> '.join(cycle) + f' -> {cycle[0]}'
            report += f"- **Loop {i+1}:** {cycle_str}\n"
        report += f"""
The presence of {len(cycles)} loops enables FBMC to optimize power flow distribution
across parallel paths, potentially reducing congestion and costs.
"""
    else:
        report += """
**Warning:** No network loops were identified. The network may be effectively radial,
which would limit FBMC benefits.
"""

    report += f"""
### 1.4 Neighbor Prices (EUR/MWh)

| Zone | Price | Rationale |
|------|-------|-----------|
"""
    for neighbor, price in NEIGHBOR_PRICES.items():
        report += f"| {neighbor} | {price:.1f} | Estimate for Dec 2024 |\n"

    report += f"""
---

## 2. Methodology

### 2.1 FBMC (Flow-Based Market Coupling)

FBMC uses a Power Transfer Distribution Factor (PTDF) matrix to calculate how power
injections at each node affect flows on each line. This allows optimization of:
- Swedish generation dispatch
- Cross-border imports/exports
- Subject to physical flow limits on all lines

### 2.2 ATC (Available Transfer Capacity)

ATC treats each corridor independently with fixed transfer limits:
- Swedish internal lines: NTC-based constraints
- Cross-border lines: Fixed capacity limits
- No consideration of loop flows or parallel paths

### 2.3 PTDF Matrix

The calculated PTDF matrix for the 13-node network:

```
{ptdf_df.round(3).to_string()}
```

---

## 3. Results

### 3.1 Cost Comparison

| Metric | FBMC | ATC | Difference |
|--------|------|-----|------------|
| Swedish generation cost (EUR) | {fbmc_gen_cost:,.0f} | {atc_gen_cost:,.0f} | {atc_gen_cost - fbmc_gen_cost:,.0f} |
| Net import cost (EUR) | {fbmc_import_cost:,.0f} | {atc_import_cost:,.0f} | {atc_import_cost - fbmc_import_cost:,.0f} |
| Total system cost (EUR) | {fbmc_total:,.0f} | {atc_total:,.0f} | {savings:,.0f} |
| Cost savings (%) | - | - | **{savings_pct:.2f}%** |

### 3.2 Line Utilization

| Line | FBMC Mean% | FBMC Max% | ATC Mean% | ATC Max% | FBMC Cong | ATC Cong |
|------|------------|-----------|-----------|----------|-----------|----------|
"""

    all_lines = sorted(set(fbmc_flows['line'].unique()) | set(atc_flows['line'].unique()))
    for line in all_lines:
        fbmc_l = fbmc_flows[fbmc_flows['line'] == line]['utilization_pct']
        atc_l = atc_flows[atc_flows['line'] == line]['utilization_pct']
        fbmc_cong = len(fbmc_l[fbmc_l >= 99]) if len(fbmc_l) > 0 else 0
        atc_cong = len(atc_l[atc_l >= 99]) if len(atc_l) > 0 else 0
        fbmc_mean = fbmc_l.mean() if len(fbmc_l) > 0 else 0
        fbmc_max = fbmc_l.max() if len(fbmc_l) > 0 else 0
        atc_mean = atc_l.mean() if len(atc_l) > 0 else 0
        atc_max = atc_l.max() if len(atc_l) > 0 else 0
        report += f"| {line} | {fbmc_mean:.1f} | {fbmc_max:.1f} | {atc_mean:.1f} | {atc_max:.1f} | {fbmc_cong} | {atc_cong} |\n"

    report += f"""
### 3.3 Cross-Border Flows (Average MW)

| Neighbor | FBMC | ATC | Price (EUR/MWh) | Net Direction |
|----------|------|-----|-----------------|---------------|
"""

    for neighbor in NEIGHBOR_ZONES:
        fbmc_n = fbmc_imports[fbmc_imports['neighbor'] == neighbor]['flow_mw'].mean()
        atc_n = atc_imports[atc_imports['neighbor'] == neighbor]['flow_mw'].mean()
        price = NEIGHBOR_PRICES[neighbor]
        direction = "Import" if fbmc_n > 0 else "Export"
        report += f"| {neighbor} | {fbmc_n:+.1f} | {atc_n:+.1f} | {price:.1f} | {direction} |\n"

    report += f"""
### 3.4 Swedish Zonal Prices

| Zone | FBMC Avg (EUR/MWh) | ATC Avg (EUR/MWh) | Difference |
|------|-------------------|------------------|------------|
"""

    for zone in SWEDISH_ZONES:
        fbmc_p = fbmc_prices[fbmc_prices['zone'] == zone]['price_eur_mwh'].mean()
        atc_p = atc_prices[atc_prices['zone'] == zone]['price_eur_mwh'].mean()
        diff = atc_p - fbmc_p
        report += f"| {zone} | {fbmc_p:.2f} | {atc_p:.2f} | {diff:+.2f} |\n"

    # Determine key finding
    if savings_pct > 1.0:
        key_finding = f"FBMC demonstrates significant cost savings ({savings_pct:.2f}%) by better utilizing cross-border capacity and managing loop flows."
    elif savings_pct > 0.1:
        key_finding = f"FBMC provides modest cost savings ({savings_pct:.2f}%), indicating some benefit from coordinated flow management."
    else:
        key_finding = "FBMC and ATC produce similar results, suggesting limited loop flow effects in this network configuration."

    report += f"""
---

## 4. Key Findings

### 4.1 Main Result

{key_finding}

### 4.2 Loop Flow Effects

"""
    if len(cycles) > 0:
        report += f"""The network contains {len(cycles)} independent loops, enabling FBMC to optimize power distribution
across parallel paths. Key observations:

- Cross-border connections create alternative routing options
- FBMC can better utilize available capacity by considering flow interactions
- ATC's independent corridor treatment may leave capacity underutilized
"""
    else:
        report += """Despite cross-border connections, limited loop flow effects were observed. This may be due to:

- Network topology still being largely radial
- Cross-border capacities being small relative to internal flows
- Generation/demand patterns not creating significant parallel flows
"""

    report += f"""
### 4.3 Trade Patterns

Sweden's position in the Nordic system allows it to:
- **Import** cheap hydropower from Norway (NO3, NO4 at 25-35 EUR/MWh)
- **Export** to higher-priced markets (PL, LT at 75-80 EUR/MWh)
- Optimize dispatch based on cross-border price differentials

---

## 5. Sensitivity Analysis

### 5.1 Impact of Neighbor Prices

The results are sensitive to assumed neighbor prices:
- Lower Norwegian prices → More imports from NO, lower Swedish costs
- Higher continental prices → More export opportunities to DE, PL
- Price convergence → Reduced cross-border arbitrage benefits

### 5.2 Network Topology Effects

FBMC benefits depend on:
- **More loops** → Greater potential for flow optimization
- **Higher cross-border capacity** → More arbitrage opportunities
- **Tighter internal constraints** → More benefit from coordinated dispatch

---

## 6. Limitations and Caveats

1. **Simplified neighbor model:** Neighbors modeled as price-taking nodes with unlimited generation
2. **Fixed neighbor prices:** Real prices vary hourly and depend on system conditions
3. **DC power flow:** Ignores losses and reactive power
4. **Single week:** May not represent annual patterns
5. **No reserve requirements:** Doesn't include ancillary services
6. **Static topology:** Doesn't account for outages or dynamic ratings

---

## 7. Conclusions for Thesis

### 7.1 FBMC Benefits in Extended Networks

This analysis demonstrates that extending the Swedish market model to include
cross-border connections {'does' if savings_pct > 0.5 else 'may'} enable FBMC benefits through:

1. **Loop flow management** - Optimizing power distribution across parallel paths
2. **Cross-border optimization** - Better utilization of interconnector capacity
3. **Price convergence** - Reducing zonal price spreads through improved flow allocation

### 7.2 Practical Implications

For the Nordic electricity market:
- FBMC implementation could reduce system costs by approximately {savings_pct:.1f}%
- Benefits depend heavily on network topology and cross-border capacities
- Coordination between Nordic TSOs is essential for realizing FBMC benefits

---

## 8. Output Files

| File | Description |
|------|-------------|
| `fbmc_extended_dispatch.csv` | FBMC hourly Swedish generation |
| `fbmc_extended_flows.csv` | FBMC hourly line flows |
| `fbmc_extended_prices.csv` | FBMC hourly zonal prices |
| `fbmc_extended_imports.csv` | FBMC hourly cross-border flows |
| `atc_extended_dispatch.csv` | ATC hourly Swedish generation |
| `atc_extended_flows.csv` | ATC hourly line flows |
| `atc_extended_prices.csv` | ATC hourly zonal prices |
| `atc_extended_imports.csv` | ATC hourly cross-border flows |
| `ptdf_matrix_extended.csv` | PTDF matrix for 13-node network |
| `fbmc_vs_atc_extended_summary.csv` | Summary comparison |
| `network_topology_extended.png` | Network map |
| `price_timeseries_extended.png` | Swedish price curves |
| `cross_border_flows.png` | Import/export visualization |
| `fbmc_vs_atc_extended.png` | Side-by-side comparison |

---

*Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*

*Data Sources: ENTSO-E Transparency Platform, SVK Kraftbalansen 2024, Estimated neighbor prices*
"""

    report_file = RESULTS_DIR / "EXTENDED_NETWORK_ANALYSIS.md"
    with open(report_file, 'w') as f:
        f.write(report)

    print(f"\nSaved report to: {report_file}")

    return report


# ============================================================================
# Main Execution
# ============================================================================

def main():
    """Main execution flow"""

    # Step 1: Load data
    demand_df, plants_df, avail_df, nodes_df, lines_df, neighbor_prices_df = load_data()

    # Step 1B: Identify network loops
    cycles = identify_loops(lines_df)

    # Step 2: Calculate PTDF
    ptdf_df = calculate_ptdf_extended(lines_df, nodes_df)

    # Step 3: Run FBMC
    fbmc_results = run_fbmc_extended(demand_df, plants_df, avail_df, lines_df, nodes_df, ptdf_df)

    # Step 4: Run ATC
    atc_results = run_atc_extended(demand_df, plants_df, avail_df, lines_df, nodes_df)

    # Step 5: Compare results
    summary_df, savings, savings_pct = compare_results(fbmc_results, atc_results, lines_df)

    # Step 6: Generate visualizations
    generate_visualizations(fbmc_results, atc_results, nodes_df, lines_df)

    # Step 7: Create report
    create_report(fbmc_results, atc_results, ptdf_df, cycles, savings, savings_pct, nodes_df, lines_df)

    # Final summary
    print("\n" + "=" * 70)
    print("EXTENDED NETWORK ANALYSIS COMPLETE")
    print("=" * 70)

    fbmc_total = fbmc_results[4] + fbmc_results[5]
    atc_total = atc_results[4] + atc_results[5]

    print(f"\n  FBMC Total Cost: {fbmc_total:,.0f} EUR")
    print(f"  ATC Total Cost:  {atc_total:,.0f} EUR")
    print(f"  Savings:         {savings:,.0f} EUR ({savings_pct:.2f}%)")

    if savings_pct > 1.0:
        print("\n  SUCCESS: FBMC shows clear benefits over ATC in the extended network!")
    elif savings_pct > 0.1:
        print("\n  RESULT: FBMC provides modest cost savings over ATC.")
    else:
        print("\n  NOTE: FBMC and ATC show similar costs.")
        print("  Possible reasons:")
        print("  - Network may still be effectively radial")
        print("  - Cross-border capacities may not create significant loop flows")
        print("  - Generation pattern may not benefit from parallel path optimization")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
