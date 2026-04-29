# Extended Nordic Network Analysis
## FBMC vs ATC with Cross-Border Connections
### Swedish Electricity Market - December 2-8, 2024

---

## Executive Summary

This analysis extends the Swedish electricity market model (SE1-SE4) to include
cross-border connections with neighboring countries, creating a meshed network
topology where FBMC benefits can emerge through loop flow management.

**Key Result:** FBMC achieves a **0.00% cost reduction** compared to ATC,
saving approximately **4,367,261 EUR** over the analysis week.

---

## 1. Network Description

### 1.1 Topology

| Category | Count |
|----------|-------|
| Total nodes | 13 |
| Swedish zones | 4 (SE1, SE2, SE3, SE4) |
| Neighbor zones | 9 (NO1, NO3, NO4, FI, DK1, DK2, PL, LT, DE) |
| Total lines | 13 |
| Internal Swedish lines | 3 |
| Cross-border lines | 10 |
| Network loops | 1 |

### 1.2 Line Capacities

| Line | From | To | Capacity (MW) | Technology |
|------|------|-----|---------------|------------|
| L_SE1_SE2 | SE1 | SE2 | 3300 | AC |
| L_SE2_SE3 | SE2 | SE3 | 7300 | AC |
| L_SE3_SE4 | SE3 | SE4 | 5300 | AC |
| L_NO4_SE1 | NO4 | SE1 | 600 | AC |
| L_NO3_SE2 | NO3 | SE2 | 1000 | AC |
| L_NO1_SE3 | NO1 | SE3 | 2145 | AC |
| L_FI_SE1 | FI | SE1 | 1500 | DC |
| L_FI_SE3 | FI | SE3 | 1200 | DC |
| L_DK1_SE3 | DK1 | SE3 | 740 | DC |
| L_DK2_SE4 | DK2 | SE4 | 1700 | AC |
| L_PL_SE4 | PL | SE4 | 600 | DC |
| L_LT_SE4 | LT | SE4 | 700 | DC |
| L_DE_SE4 | DE | SE4 | 615 | DC |

### 1.3 Identified Network Loops

- **Loop 1:** SE2 -> SE1 -> FI -> SE3 -> SE2

The presence of 1 loops enables FBMC to optimize power flow distribution
across parallel paths, potentially reducing congestion and costs.

### 1.4 Neighbor Prices (EUR/MWh)

| Zone | Price | Rationale |
|------|-------|-----------|
| NO1 | 61.4 | Estimate for Dec 2024 |
| NO3 | 24.2 | Estimate for Dec 2024 |
| NO4 | 7.2 | Estimate for Dec 2024 |
| FI | 59.1 | Estimate for Dec 2024 |
| DK1 | 96.3 | Estimate for Dec 2024 |
| DK2 | 98.7 | Estimate for Dec 2024 |
| PL | 141.3 | Estimate for Dec 2024 |
| LT | 107.8 | Estimate for Dec 2024 |
| DE | 113.2 | Estimate for Dec 2024 |

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
             SE1    SE2  SE3  SE4  NO1    NO3    NO4     FI  DK1  DK2   PL   LT   DE
index                                                                               
L_SE1_SE2  0.817 -0.129  0.0  0.0  0.0 -0.129  0.817  0.408  0.0  0.0  0.0  0.0  0.0
L_SE2_SE3  0.817  0.871  0.0  0.0  0.0  0.871  0.817  0.408  0.0  0.0  0.0  0.0  0.0
L_SE3_SE4  0.000  0.000  0.0 -1.0  0.0  0.000  0.000  0.000  0.0 -1.0 -1.0 -1.0 -1.0
L_NO4_SE1  0.000  0.000  0.0  0.0  0.0  0.000  1.000  0.000  0.0  0.0  0.0  0.0  0.0
L_NO3_SE2 -0.000  0.000  0.0  0.0  0.0  1.000  0.000  0.000  0.0  0.0  0.0  0.0  0.0
L_NO1_SE3  0.000  0.000  0.0  0.0  1.0  0.000  0.000  0.000  0.0  0.0  0.0  0.0  0.0
L_FI_SE1  -0.183 -0.129  0.0  0.0  0.0 -0.129 -0.183  0.408  0.0  0.0  0.0  0.0  0.0
L_FI_SE3   0.183  0.129  0.0  0.0  0.0  0.129  0.183  0.592  0.0  0.0  0.0  0.0  0.0
L_DK1_SE3  0.000  0.000  0.0  0.0  0.0  0.000  0.000  0.000  1.0  0.0  0.0  0.0  0.0
L_DK2_SE4  0.000  0.000  0.0 -0.0  0.0  0.000  0.000  0.000  0.0  1.0  0.0  0.0  0.0
L_PL_SE4   0.000  0.000  0.0 -0.0  0.0  0.000  0.000  0.000  0.0 -0.0  1.0  0.0  0.0
L_LT_SE4   0.000  0.000  0.0 -0.0  0.0  0.000  0.000  0.000  0.0 -0.0 -0.0  1.0  0.0
L_DE_SE4   0.000  0.000  0.0 -0.0  0.0  0.000  0.000  0.000  0.0 -0.0  0.0  0.0  1.0
```

---

## 3. Results

### 3.1 Cost Comparison

| Metric | FBMC | ATC | Difference |
|--------|------|-----|------------|
| Swedish generation cost (EUR) | 31,348,923 | 31,402,300 | 53,377 |
| Net import cost (EUR) | -102,461,951 | -98,148,067 | 4,313,884 |
| Total system cost (EUR) | -71,113,028 | -66,745,767 | 4,367,261 |
| Cost savings (%) | - | - | **0.00%** |

### 3.2 Line Utilization

| Line | FBMC Mean% | FBMC Max% | ATC Mean% | ATC Max% | FBMC Cong | ATC Cong |
|------|------------|-----------|-----------|----------|-----------|----------|
| L_DE_SE4 | 100.0 | 100.0 | 100.0 | 100.0 | 168 | 168 |
| L_DK1_SE3 | 100.0 | 100.0 | 98.9 | 100.0 | 168 | 159 |
| L_DK2_SE4 | 99.3 | 100.0 | 99.3 | 100.0 | 160 | 160 |
| L_FI_SE1 | 23.6 | 64.0 | 99.4 | 100.0 | 0 | 161 |
| L_FI_SE3 | 99.8 | 100.0 | 0.0 | 0.0 | 166 | 0 |
| L_LT_SE4 | 100.0 | 100.0 | 100.0 | 100.0 | 168 | 168 |
| L_NO1_SE3 | 74.4 | 100.0 | 58.7 | 100.0 | 83 | 49 |
| L_NO3_SE2 | 93.7 | 100.0 | 48.1 | 100.0 | 141 | 33 |
| L_NO4_SE1 | 100.0 | 100.0 | 100.0 | 100.0 | 168 | 168 |
| L_PL_SE4 | 100.0 | 100.0 | 100.0 | 100.0 | 168 | 168 |
| L_SE1_SE2 | 19.1 | 65.4 | 41.0 | 98.0 | 0 | 0 |
| L_SE2_SE3 | 88.0 | 98.7 | 99.7 | 100.0 | 0 | 160 |
| L_SE3_SE4 | 18.6 | 40.2 | 84.6 | 100.0 | 0 | 9 |

### 3.3 Cross-Border Flows (Average MW)

| Neighbor | FBMC | ATC | Price (EUR/MWh) | Net Direction |
|----------|------|-----|-----------------|---------------|
| NO1 | -1409.8 | -673.7 | 61.4 | Export |
| NO3 | +936.9 | +326.0 | 24.2 | Import |
| NO4 | +600.0 | +600.0 | 7.2 | Import |
| FI | -1398.2 | -1490.5 | 59.1 | Export |
| DK1 | -740.0 | -732.2 | 96.3 | Export |
| DK2 | -1688.0 | -1688.0 | 98.7 | Export |
| PL | -600.0 | -600.0 | 141.3 | Export |
| LT | -700.0 | -700.0 | 107.8 | Export |
| DE | -615.0 | -615.0 | 113.2 | Export |

### 3.4 Swedish Zonal Prices

| Zone | FBMC Avg (EUR/MWh) | ATC Avg (EUR/MWh) | Difference |
|------|-------------------|------------------|------------|
| SE1 | 29.92 | 6.64 | -23.28 |
| SE2 | 29.07 | 7.66 | -21.41 |
| SE3 | 39.08 | 42.14 | +3.07 |
| SE4 | 46.73 | 48.12 | +1.40 |

---

## 4. Key Findings

### 4.1 Main Result

FBMC and ATC produce similar results, suggesting limited loop flow effects in this network configuration.

### 4.2 Loop Flow Effects

The network contains 1 independent loops, enabling FBMC to optimize power distribution
across parallel paths. Key observations:

- Cross-border connections create alternative routing options
- FBMC can better utilize available capacity by considering flow interactions
- ATC's independent corridor treatment may leave capacity underutilized

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
cross-border connections may enable FBMC benefits through:

1. **Loop flow management** - Optimizing power distribution across parallel paths
2. **Cross-border optimization** - Better utilization of interconnector capacity
3. **Price convergence** - Reducing zonal price spreads through improved flow allocation

### 7.2 Practical Implications

For the Nordic electricity market:
- FBMC implementation could reduce system costs by approximately 0.0%
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

*Report generated: 2026-04-28 21:25:09*

*Data Sources: ENTSO-E Transparency Platform, SVK Kraftbalansen 2024, Estimated neighbor prices*
