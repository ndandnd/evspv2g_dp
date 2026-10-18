# Plug-limit integer rerun under the agreed protocol: results (18 October 2026)

Protocol: `experiments/opte_plugs_protocol_20261017/PROTOCOL.md`. CG runs to pricing convergence, then the restricted MIP over the generated routes gets 1,800 s. The direct arc-flow MIP gets 1,800 s from model construction. Gurobi 12.0.3, one thread, EPYC 9654. All 36 integer arms finished. The LP columns come unchanged from `output/opte-plugs-final-20261015/`.

## Files

- `raw/`: rsync of `unicorn:opte-plugs-protocol-20261017/results/` (without `*.npz`, `*.json.gz`, CG logs)
- `collected/`: output of the hashed collector, unedited (`protocol_table.md`, `protocol_results.json`, `protocol_arms.csv`)
- `summarize_plugs_protocol.py` → `summary/summary_table.md`, `summary/summary.json`. It is not part of the hashed collector. It handles the two collector nits (below) and adds truck/battery counts, single-task route counts, old values and a bracket on the optimal cost change.

## Checks (measured)

The collector ran with no rejected check. All 18 instance hashes and plug capacities match the original study. Code hashes match the cluster preflight. Every arm reports Gurobi 12.0.3, EPYC 9654 and one bound CPU. No arm was requeued. Every reported schedule passed the matrix check and the route replay, with plug violation 0. CG priced out in all 18 blocks in 104–633 s. The new CG LP values match the original LP to within 1.3e-15 (relative).

Hosts: all CG arms ran on cdses-compute-01 except block 0 (samitha-compute-01). Direct arms ran on samitha-compute-01 for blocks 0–9 and portal-compute-04 for blocks 10–17. The original study ran everything on cdses-compute-01, with the four arms of a block running at the same time.

Collector nits, handled in `summarize_plugs_protocol.py`:
1. Best cost now uses only the 1,800 s readings. No number changes: the final direct incumbent equals the ≤1,800 s incumbent in all 10 direct arms that have one.
2. In blocks 7 and 8, the direct root LP did not finish, so Gurobi reported bound 0.00. The summary shows "—" there. LB* in those blocks already came from CG, so LB* is unchanged.

## Table

T/B = trucks / stationary batteries in the reported schedule. "1-task" = number of routes that serve a single task. Gap = 100(U − LB*)/U. Opt. Δ = bracket on (optimum with plug limit)/(optimum unlimited) − 1, computed from LB* and the ≤1,800 s incumbents of both policies. "[all 1-task]" marks a direct incumbent that uses one truck per task.

| Blk | Input | Policy | LP Δ vs unl. | LB* (src) | CG-pool cost (status) | T/B (1-task routes) | Gap | Direct cost ≤1,800 s (status) | T/B | Gap | Opt. Δ vs unl. (interval) | Old CG-pool | Old direct |
|---:|---|---|---:|---:|---|---|---:|---|---|---:|---|---:|---:|
| 0 | 100/15/25, s0 | unlimited | +0.000% | 6,315.19 (direct) | 6,372.88 (optimal) | 20/4 (1) | 0.91% | 6,315.19 (optimal) | 20/3 | 0.00% | — | 6,372.88 | 6,315.19 |
| 1 | 100/15/25, s0 | loose (2/5) | +0.000% | 6,315.19 (direct) | 6,474.01 (optimal) | 21/5 (2) | 2.45% | 6,315.19 (optimal) | 20/3 | 0.00% | +0.000% (proven) | 6,474.01 | 6,315.19 |
| 2 | 100/15/25, s0 | tight (1/3) | +1.555% | 6,392.15 (direct) | 7,692.06 (time_limit) | 28/9 (13) | 16.90% | 6,392.15 (optimal) | 19/5 | 0.00% | +1.219% (proven) | 7,692.06 | 6,392.15 |
| 3 | 100/15/25, s1 | unlimited | +0.000% | 6,382.15 (direct) | 6,430.71 (optimal) | 19/1 (0) | 0.76% | 6,382.16 (time_limit) | 19/0 | 0.00% | — | 6,430.71 | 6,382.16 |
| 4 | 100/15/25, s1 | loose (2/5) | +0.000% | 6,382.15 (direct) | 6,451.20 (optimal) | 18/2 (0) | 1.07% | 6,382.31 (time_limit) | 19/0 | 0.00% | [−0.000%, +0.003%] | 6,451.20 | 6,382.31 |
| 5 | 100/15/25, s1 | tight (1/3) | +0.244% | 6,388.15 (direct) | 7,487.77 (time_limit) | 27/4 (12) | 14.69% | 6,413.09 (time_limit) | 18/1 | 0.39% | [+0.094%, +0.485%] | 7,487.77 | 6,413.09 |
| 6 | 100/15/12.5, s0 | unlimited | +0.000% | 6,098.83 (direct) | 6,178.74 (optimal) | 17/4 (0) | 1.29% | 18,237.47 [all 1-task] (time_limit) | 100/0 | 66.56% | — | 6,178.74 | 18,237.47 |
| 7 | 100/15/12.5, s0 | loose (2/5) | +0.000% | 6,098.83 (CG) | 6,407.92 (time_limit) | 19/4 (3) | 4.82% | — (time_limit; root LP unfinished) | — | — | [−1.293%, +5.068%] | 6,407.92 | — |
| 8 | 100/15/12.5, s0 | tight (1/3) | +0.264% | 6,114.90 (CG) | 7,905.97 (time_limit) | 29/7 (15) | 22.65% | — (time_limit; root LP unfinished) | — | — | [−1.033%, +29.631%] | 7,991.00 | — |
| 9 | 100/15/12.5, s1 | unlimited | +0.000% | 6,089.05 (direct) | 6,156.04 (optimal) | 20/3 (0) | 1.09% | 17,242.31 [all 1-task] (time_limit) | 100/0 | 64.69% | — | 6,156.04 | 6,114.87 |
| 10 | 100/15/12.5, s1 | loose (2/5) | +0.000% | 6,089.05 (direct) | 6,426.62 (time_limit) | 23/4 (3) | 5.25% | — (time_limit) | — | — | [−1.088%, +5.544%] | 6,426.62 | — |
| 11 | 100/15/12.5, s1 | tight (1/3) | +1.100% | 6,156.04 (direct) | 7,896.18 (time_limit) | 32/8 (17) | 22.04% | — (time_limit) | — | — | [+0.000%, +29.678%] | 7,896.18 | — |
| 12 | 200/30/25, s0 | unlimited | +0.000% | 13,015.67 (direct) | 13,862.44 (time_limit) | 40/2 (10) | 6.11% | 32,424.73 [all 1-task] (time_limit) | 200/0 | 59.86% | — | 14,032.00 | 32,424.73 |
| 13 | 200/30/25, s0 | loose (2/10) | +0.000% | 13,015.67 (direct) | 14,695.24 (time_limit) | 45/5 (15) | 11.43% | — (time_limit) | — | — | [−6.108%, +12.904%] | 14,695.24 | — |
| 14 | 200/30/25, s0 | tight (1/5) | +0.000% | 13,015.67 (direct) | 17,001.82 (time_limit) | 65/1 (37) | 23.45% | — (time_limit) | — | — | [−6.108%, +30.626%] | — (CG cap) | — |
| 15 | 200/30/25, s1 | unlimited | +0.000% | 12,662.44 (direct) | 14,006.58 (time_limit) | 41/2 (12) | 9.60% | 12,662.44 (optimal) | 31/0 | 0.00% | — | 14,006.58 | 12,662.44 |
| 16 | 200/30/25, s1 | loose (2/10) | +0.000% | 12,662.44 (direct) | 14,330.35 (time_limit) | 47/1 (18) | 11.64% | — (time_limit) | — | — | [+0.000%, +13.172%] | 14,330.35 | — |
| 17 | 200/30/25, s1 | tight (1/5) | +0.011% | 12,663.86 (direct) | 17,814.94 (time_limit) | 70/4 (49) | 28.91% | — (time_limit) | — | — | [+0.011%, +40.691%] | — (CG cap) | — |

The collector's own table (`collected/protocol_table.md`) has a "Best cost Δ vs unlimited" column with +3.7% to +40.7% on blocks 7, 8, 10, 11, 13, 14, 16, 17. Those numbers compare a restricted-pool schedule with the unlimited best schedule, which on blocks 15/16/17 comes from the direct MIP. They are not the cost of the plug limit. Do not quote them.

## Findings

**Which method found schedules (measured).** The CG-pool MIP found a schedule in 18/18 blocks (original study: 16/18). The direct MIP had a schedule by 1,800 s in 10/18. Three of those (blocks 6, 9, 12) are the trivial one-truck-per-task starts found at 11–14 s. In 8 of the 12 plug-limited blocks, the direct MIP found no schedule: all limited blocks on the 12.5 kWh and 200-task inputs. Good direct schedules (gap ≤ 0.39%) exist only on the two 100-task/25 kWh inputs (blocks 0–5) and on block 15.

**Optimal cost change vs unlimited (measured; proven where stated).**
- Input s0, 100 tasks, 25 kWh. All three policies were solved to optimality. Loose: 6,315.19, unchanged. Tight: 6,392.15, +1.219%. The LP rose by +1.555%.
- Input s1, 100 tasks, 25 kWh. These are bracketed by bounds. Loose: between −0.0002% and +0.003%, so essentially unchanged. Tight: +0.094% to +0.485%.
- Across these four plug-limited cases, the optimum rose by at most 1.22%.
- The other four inputs give no usable bracket: the intervals in the table are wide.

**Restricted MIP weakness (measured).**
- In blocks where the direct MIP proved the optimum, the CG-pool cost lies above it: block 0 +0.91%, block 1 +2.51%, block 2 +20.34%, block 15 +10.62%.
- With tight limits, every CG-pool schedule hits the time limit, with gaps to LB* of 14.7–28.9%. The MIP's own gap within the pool is 14.4–28.4%. These schedules use 12–49 single-task routes.
- On block 2, the restricted-pool bound (6,569.41) is 2.77% above the direct optimum. Even a fully solved restricted MIP would miss the optimum there.
- With loose limits, the gaps are 1.07–11.64%.
- Same-method change from unlimited to tight (CG-pool vs CG-pool): +16% to +28%. This is the restricted MIP's weakness. It is not the plug effect: where the optimum is known, tight costs +1.2% (block 2).

**Trucks vs batteries (measured; two data points).**
- Direct schedules, unlimited → loose → tight. Input s0 (all optimal): 20/3 → 20/3 → 19/5. Input s1 (block 5 is 0.39% from optimal): 19/0 → 19/0 → 18/1. So the tight limit shifts the schedule to one truck fewer and one or two more stationary batteries.
- In the model, stationary-battery dispatch occupies no plug (`runtime/plug_problem.py` docstring: "Waiting/travel/tasks and stationary BESS dispatch occupy none"; only truck charge/discharge arcs and seed cells enter the plug rows). So this substitution partly follows from that modelling choice. A reviewer could ask whether stationary batteries need plugs too.
- CG-pool schedules under tight limits use 27–70 trucks, against 17–41 unlimited (1.4–1.7×), mainly by adding single-task routes. Battery counts vary (1–9).

**Effect of the protocol on the CG arm (measured).** CG converged everywhere. In the 16 blocks where the original CG also converged, the number of generated columns is identical (old `cg.columns` = new `cg_columns_total`; for example, block 3 has 1,019 and block 5 has 1,609), and the CG LP values match. CG-pool costs are identical to the original in 14 blocks. Block 8 improved (7,991.00 → 7,905.97), block 12 improved (14,032.00 → 13,862.44), and blocks 14 and 17 now have schedules (17,001.82; 17,814.94). In the original study, CG in blocks 14 and 17 hit its 600 s cap.

**Direct arm vs the original study (measured; same budget and clock).** Most values are unchanged, with these exceptions:
- Blocks 7 and 8: the root LP did not finish within 1,800 s. In the original, the bound was available at about 1,560–1,580 s.
- Block 9: only the trivial 17,242.31 incumbent. The original found 6,114.87 between 1,784 s and 1,800 s.
- Block 5: the final bound is weaker (6,388.15 vs 6,398.63). The incumbent is the same.

Root-LP times are longer on samitha-compute-01: blocks 6/9 took 1,457/1,320 s, against ≤1,180/≤1,110 s originally (from a 30 s trace grid). Proven solves took 789/1,105/865 s, against 590/905/687 s in the original. On portal-compute-04 the times were within about 0–8% of the original (block 17 was faster). *Inferred:* the differences come from host speed or placement (same CPU model, different node; the incumbent/bound callback may also add overhead). They do not come from the protocol, since the direct budget is unchanged. This means the direct column carries machine-to-machine variance near the 1,800 s limit.

Memory: direct peak RSS was 1.5–1.8 GB on the 100-task/25 kWh inputs and 4.3–4.8 GB on the others. CG arms used ≤ 0.38 GB.
