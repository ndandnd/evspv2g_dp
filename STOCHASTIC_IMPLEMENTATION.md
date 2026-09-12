# Sparse and persistent stochastic LP implementation

`stochastic_master.py` implements the common-profile SAA and finite-scenario minimax formulations from the immutable `method_union_v8` campaign worker, with a sparse reusable scenario template and an optional persistent Gurobi restricted LP. It imports only this candidate's model modules. The frozen reference and campaign sources remain untouched.

The first-stage variables are the same truck weights, battery count `Nb`, and common initial BESS SoC `s0`. Each scenario has its own continuous generation, BESS charging/discharging, and remaining SoC trajectory. Truck energy profiles remain common across scenarios. Expected operating costs use the supplied probabilities; minimax uses one unweighted epigraph inequality per scenario. Phase I retains the release's uniform `1/S` penalty on energy deficits and unit penalty on artificial coverage columns, even when economic probabilities are nonuniform.

## Integration API

The tuple builders match the release worker's eight-item order:

```python
from stochastic_master import expected_model, model, phase_model, lp

m = expected_model(cfg, deltas, cols, fixed=None)
m = model(cfg, deltas, cols, fixed=None)  # cfg['method'] selects minimax
m = phase_model(cfg, deltas, cols, cap)
result = lp(m)
# m = (c, A_ub, b_ub, A_eq, b_eq, lb, ub, meta)
```

Their default instance factory reproduces the worker with the candidate's local `build_instance(points, 2., BREAKS2, delta_hourly=...)`, `rho=1.75`, `soc_step=.25`, `c_g=40`, and the same optional `cap_factor` conversion. An `instance_factory=worker.instance` keyword can supply an explicit factory. The module never adjusts `sys.path` to a frozen reference checkout.

For CG, construct the template once, avoiding factory calls and static assembly each iteration:

```python
from stochastic_master import StochasticTemplate, PersistentStochasticLP, lp

instances = [instance(cfg, delta) for delta in deltas]
template = StochasticTemplate(
    instances,
    battery_allowed=SCENARIOS[cfg['arm']]['battery'],
    weights=cfg.get('weights'),
    method=cfg.get('method', 'saa'),
)

# Portable SciPy path; sparse static rows are reused.
m = template.build(cols, phase_cap=None, forbid_artificials=True)
result = lp(m, time_limit=120)

# Persistent economic CG path; append full columns and retain the native LP.
with PersistentStochasticLP(template, cols, forbid_artificials=True,
                            threads=1, time_limit=120) as session:
    session.sync(cols)  # full ordered pool; unchanged prefix is authenticated
    result = session.solve(time_limit=120)
    if not result.success:
        raise RuntimeError(result.message)
    duals = template.pricing_duals(result)
    alpha, mu, nu = duals['alpha'], duals['mu'], duals['nu']
    fleet_price = duals['fleet_price']
```

For Phase I construct a separate session with `phase_cap=cap` and `forbid_artificials=False`. After its feasibility certificate, close it and construct the economic session with `forbid_artificials=True`. The template may be shared because the phase transformation is session-specific, but the Gurobi session cannot be changed in place between phases. A new session is also required for changed fixed commitments, weights, physics, scenarios, objective mode, or boundary convention.

`fixed` is the release's complete `[x_0,...,x_R-1,Nb,s0]` vector. Its length is therefore pool-specific; a persistent fixed-policy evaluation session cannot append routes. The portable builder accepts a new fixed vector on each independent build.

A reused template can also be passed to a tuple wrapper through `template=...`. That path regenerates instances solely to authenticate the supplied configuration and scenario identity; direct `template.build()` avoids this repeated factory cost and is preferred in CG.

## Exact ordering and dual semantics

Canonical variables are `[routes, Nb, s0, (g,c,d,s1..sT) for each scenario, optional minimax z, optional Phase-I deficits]`. All inequality and equality rows and `meta` balance/cap offsets match the release. Native Gurobi static variables are created first and truck variables appended later; `solve()` explicitly maps the primal vector back to canonical order. Native row order is unchanged.

`result` exposes SciPy-style `success`, `status`, `fun`, `x`, `eqlin.marginals`, `ineqlin.marginals`, and residuals. Only native `OPTIMAL` returns a success and priced primal/dual solution. Infeasible, unbounded, limited, or unresolved LPs return no primal/dual certificate. Successful persistent solves independently check all original row/bound residuals and reconstructed objective against the native objective.

`template.pricing_duals(result)` **sums raw scenario balance and charge-cap duals without multiplying by probabilities again**. Economic probabilities are already in the LP objective. It also sums the price of all finite truck-count rows as `fleet_price = -sum(raw <= row duals)`. A real truck's RC is

```text
column_cost - a @ alpha + e @ mu + positive_charging_coefficients @ nu + fleet_price
```

Artificial columns do not consume a fleet slot. In Phase I, a real truck's objective coefficient is zero and an artificial's is one. `template.reduced_cost(col, result, phase=True/False)` supplies the complete current formula for independent checks. This is an LP column RC, excluding variable-bound marginals; fixed-policy evaluations should not interpret a negative RC on a bound-fixed variable as failed pricing.

Charging-cap coefficients retain every positive energy coefficient (`e[t] > 0`), matching the repaired deterministic master and pricing formula. This intentionally repairs the release's `1e-9` filtering on tiny valid SoC grids; the standard `.25`-grid frozen-pool coefficients remain identical. Signed energy enters balance rows at its full coefficient. The module supports scenario-varying recourse caps and fixed battery-count rows, while requiring common trip physics and cost coefficients. It explicitly implements equality coverage and does not use the mutable `master.COVERING` switch.

## Reuse and mutation guarantees

The static template is built directly as sparse triplets; it does not allocate an intermediate dense scenario matrix or call `_build_lp` for every scenario. Static BESS, generation, epigraph, RHS, and row metadata are independent of the route pool. A portable build creates only the route block and assembles it with the stored static block. Persistent synchronization generates `gp.Column` coefficients only for new routes and reoptimizes the same Gurobi model.

`template.identity` is a SHA-256 fingerprint of every supplied instance field, actual scenario probabilities, battery flag, method, and boundary. Each reuse checks it, so in-place changes to array-valued caps, Delta inputs, trip physics, or probabilities are rejected rather than silently sharing stale matrices. Arrays and sparse matrices returned by `build()` are independent of the private static template. There is no global cross-experiment cache.

The persistent route prefix is checked using exact `kind`, `a`, `e`, and `fixed_cost`, with no rounded incidence-only key. Removal, replacement, cost changes, and direct mutation of an added column raise `StructuralMutationError`. Labels do not enter matrix identity. Same-trip columns with distinct energy schedules remain distinct full columns. Fixed/phase flags are also guarded; changed models require explicit reconstruction.

`template.stats` records static build time and nonzeros, pool-build count, last pool-build time, and pool size. `session.stats` records native model creation, synchronization and solve times, synchronization count, and added-column count. These separate assembly from optimizer work; they make no end-to-end performance claim by themselves.

## Validation

Run from the candidate:

```bash
PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_stochastic_master.py
```

The coefficient tests compile only the three pure builder functions from the frozen worker and the pure dense builder from the frozen reference into an isolated test namespace. They do not import the worker, install signal handlers, or write any frozen artifacts. `V2G_REVIEW_ROOT` can identify that immutable evidence directory on another host. Tests requiring the external known pools skip if it is unavailable; the adapter has no such dependency.

Coverage includes the nine known snapshot pool/scenario cells (three arms × 8/24/64 actual sampled training days), exact matrix/objective/RHS/bound/meta equality, nonuniform economic probabilities, evaluation probability fallback, finite/varying caps, finite truck-count and fixed-battery rows, Phase I, minimax, fixed commitments, array/column mutation guards, no-certificate infeasibility, and persistent batch insertion. Tiny persistent SAA, minimax, and Phase-I solves are compared with SciPy on the same matrices. Degenerate LPs can yield different valid dual optima, so each backend's own coefficient-based RC and primal residuals are checked instead of requiring identical dual vectors.

The local environment was extended with `pytest 9.1.1` and `gurobipy 13.0.3`; its restricted Gurobi license is sufficient for the tiny adapter tests. Larger production-sized persistent solves still need the separately allocated licensed environment. No cluster job or frozen release was changed by this implementation.

Local result on 2026-09-12: **35 passed in the targeted stochastic suite**, including the tiny positive charging-cap regression and all optional tiny Gurobi tests (no license skips). Larger end-to-end timing and campaign integration remain the parent task's validation scope.
