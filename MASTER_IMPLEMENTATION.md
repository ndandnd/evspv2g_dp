# Deterministic master candidate

This isolated candidate implements the first master safeguards and the persistent-LP improvement from the 12 September 2026 review. The source reference and existing experiment releases are unchanged. These are restricted-pool solver improvements; they do not implement branch-and-price or certify full-route integer optimality.

## Implemented behavior

| Change | Result and scope |
|---|---|
| CBC incumbent safeguard | A populated vector is accepted only if PuLP's native problem and solution status report an incumbent **and** independent matrix, bound, integrality and objective checks pass. The zero-generation infeasibility witness now returns `infeasible`, an infinite objective and `has_incumbent=False`. Missing values are never silently zeroed except an explicitly identified variable absent from every constraint and the objective. |
| Native status retention | `RMPSolution` preserves native status, native CBC solution status, message and termination reason. Limit exits, infeasibility, unboundedness and numerical failures remain distinct. Verified time-limited Gurobi incumbents return `feasible`, with native bound/gap; no-incumbent limits retain `time_limit`. PuLP does not expose the precise CBC stop reason or native best bound/gap, so these are not invented. CBC `optimal` is its native classification, including any requested MIP tolerance. |
| Canonical coefficients | `canonical_model` provides the common sparse matrix used by HiGHS, CBC and Gurobi. `_build_lp` retains its historical dense reference signature. Small positive charging-cap coefficients are retained exactly; prior CBC/Gurobi filtering of small balance or coverage coefficients is eliminated. |
| Fleet reduced cost | `fleet_dual` is the native nonpositive marginal of `sum(real truck x) <= max_trucks`. `reduced_cost` subtracts it for real truck columns. The executed cap-one example now returns reduced costs zero rather than minus three. Artificial columns consume no fleet slot. |
| Persistent LP | `PersistentGurobiMaster` creates stationary storage variables and all static rows once, then appends route variables through `gurobipy.Column`. Gurobi uses dual simplex and retains its basis across updates; no cold `reset()` is called. The sparse validation matrix uses the same row order and coefficients as the independent dense reference. |
| Identity guard | Every solve checks all instance fields, demand/solar, physics, SoC mode, battery permission and coverage convention. Existing columns must remain an exact ordered prefix. Column identity includes kind, trip coefficients, complete injection profile and fixed cost; labels are metadata. Removal, replacement, reordered columns and configuration mutation require a fresh session. Distinct energy profiles sharing trip incidence remain distinct. |
| Accounting | Cold HiGHS/Gurobi and persistent LP expose build/solve timing. Persistent LP also exposes identity/append/validation timing, native runtime and row/column counts. Its first returned build time includes session construction; later build times are zero. These are measurements, not demonstrated speedup claims. |

`periodic` and `pin<level>` change the truck boundary convention. The stationary BESS remains cyclic in these modes, preserving the original formulation. `free` starts the stationary BESS full. Pin values must be finite and within capacity; pricing independently verifies grid alignment.

## Integration interface

```python
from persistent_master import PersistentGurobiMaster

with PersistentGurobiMaster(inst, battery_allowed=True,
                            soc_mode="cyclic", threads=1) as session:
    solution = session.solve(initial_columns, inst=inst)
    solution = session.solve(initial_columns + new_columns, inst=inst)
```

A new session is required for changed scenarios, pools that remove/reorder columns, changed physics or a changed row sense. This deterministic session does not itself create a stochastic extensive form. It solves only LPs; final MIPs still use the cold, validated finite-pool backend. The parent CG integration handles physical route replay and exclusion of artificial columns from policy claims.

## Executed verification

Run from `algorithm_candidate_v11`:

```bash
../.venv/bin/python -m unittest discover -s tests -p 'test_master*.py' -v
```

The final local run passed all **13 tests**, including Gurobi tests, in about **0.51 seconds** (Python 3.12.2, SciPy 1.18.1, PuLP 3.3.2, gurobipy 13.0.3). Gurobi became available during the implementation; the earlier unavailable-runtime skips were superseded by this successful full run. A successful local runtime is not evidence of cluster execution.

The suites include:

- Actual CBC infeasibility and actual finite-fleet-dual witnesses.
- Independent rejection of missing/nonfinite/fractional/bound-violating or objective-inconsistent vectors.
- Native non-optimal LP exits and controlled Gurobi time-limit outcomes with a verified incumbent, no incumbent and an invalid candidate vector.
- **32** combinations of covering/partitioning, cyclic/free/periodic/pin boundaries, and allowed/disallowed BESS, with finite fleet, charging, fuel and generation caps, fixed battery count and charging losses. Each checks initial and appended pools against cold HiGHS and Gurobi, exact sparse/dense coefficient parity and native static variable/row identity.
- Additional same-trip/different-injection profiles, finite-pool MIP parity and actual Gurobi infeasibility.

No end-to-end runtime improvement is established yet. The next experiment should compare cold Gurobi and persistent Gurobi using the same fixed ordered pools and settings, then CG with identical pricing/initialization and total wall/CPU accounting. Different degenerate duals may change the CG path; compare objective, feasibility, pricing certificates and total budgets rather than requiring identical dual vectors.
