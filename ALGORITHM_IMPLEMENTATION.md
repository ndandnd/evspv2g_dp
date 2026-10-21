# Implemented algorithm priorities

Candidate branch `codex/algorithm-efficiency-20260912`, based on GitHub reference `f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0`. The original reference and all existing experimental releases remain unchanged. The candidate keeps vehicle-profile column generation followed by a real-column finite-pool MIP.

| Priority | Implemented behavior | Verification |
|---|---|---|
| Physical and pricing safeguards | Shared grid contract, feasible seeds, independent profile replay, exact reconstruction/source check, signed-energy/cost keys, exact current-dual fallback | Near-tie, capacity, off-grid, high-rate and tiny-energy regressions;128 exhaustive tiny cases |
| Feasibility initialization | True Phase I for coverage and energy shortages; verified real-only pool before economic CG | Repairs an initially infeasible RMP when a valid V2G route exists; economic artificials do not prove infeasibility |
| Native master status | CBC/Gurobi incumbent/vector checks, distinct native exits, finite-fleet dual in reduced costs | Infeasibility, missing vectors, integrality, caps, losses, fleet and boundary cases |
| Scenario assembly | Direct sparse reusable scenario template; shared commitments and weighted recourse | Nine existing frozen-pool/scenario coefficient comparisons; weighted/capped SAA/minimax/Phase-I/fixed-policy cases |
| Persistent LP | Resident deterministic/stochastic Gurobi rows and recourse; sparse appended columns; full identity guards | Cold/persistent matrix/objective/reduced-cost parity; mutation/reordering rejection |
| Pricing preparation | Bounded immutable physical-transition cache; fresh dual-dependent costs/labels | Cached/uncached exhaustive parity and changed-instance/dual tests |
| Warm imports | Accepted-column, scan and time limits; full-profile replay and current-cost checks | Invalid profile rejection, scan limits, cache-setting propagation and crash-resilient lifetime warm caps |
| CG/MIP separation | Final MIPs exclude artificials; explicit LP/MIP proof scope; total/component timing | Certificate, zero-iteration, Phase-I, native-MIP and recovery regressions |

Read [pricing details](PRICING_IMPLEMENTATION.md), [master details](MASTER_IMPLEMENTATION.md) and [stochastic interfaces](STOCHASTIC_IMPLEMENTATION.md). Run `python -m pytest tests -q` here; the research environment is the parent `.venv`. Gurobi parity tests require a working license. Preserve actual runtime versions and skipped checks with results.

Local pricing microbenchmarks showed1.13–1.34× gains against reference; the earlier template prototype showed larger assembly-only gains. These are not end-to-end CG/MIP claims. Separately registered `algorithm_efficiency_wave9` compares selectable variants on matched workloads/hardware and solves final frozen pools on Scaglione. Optimizations remain individually selectable until results are validated.

Exactness concerns the admitted time/SoC lattice and required service. Periodic/pinned truck conventions retain cyclic BESS as before. Flattened-energy and legacy covering modes receive no new true-Phase-I/full-family claims. The legacy battery helper remains full-start/free-terminal and is not the aggregate BESS formulation. A CG LP certificate does not prove full-route integer optimality. Restart reconstructs the LP from durable columns; MIP search trees are not resumed.
