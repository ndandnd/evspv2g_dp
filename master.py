"""
Restricted master problem (RMP) for the covering-plus-arbitrage EVSP-V2G.

Trucks are columns (set partitioning); the stationary battery fleet is an AGGREGATE
block (integer count N_b, continuous dispatch) -- identical units differ only in
schedule, so one aggregate is exact and avoids the integer-multiplicity gap.

    min  c_g sum_t g_t + sum_r c_r x_r + c_b N_b + eps sum_t(chg_t+dis_t)
    s.t. sum_r a_ir x_r = 1                                  for all trips i   (alpha_i)
         g_t - sum_r e_rt x_r - chg_t + dis_t >= Delta_t      for all t        (mu_t >= 0)
         s_{t+1} = s_t + (1-eta) chg_t - dis_t                t = 0..T-1
         s_0 = G N_b
         0 <= s_t <= G N_b,   chg_t <= rho N_b,   dis_t <= rho N_b
         g_t,chg_t,dis_t >= 0,  x_r >= 0 (LP) / Z>=0 (MILP),  N_b >= 0 (LP) / Z>=0 (MILP)

Truck reduced cost:  rc_r = c_r - sum_i a_ir alpha_i + sum_t mu_t e_rt.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog
from scipy import sparse
from time import perf_counter
from instance import Instance


@dataclass
class Column:
    kind: str
    a: np.ndarray
    e: np.ndarray
    fixed_cost: float
    label: str = ""

    def throughput(self) -> float:
        return float(np.abs(self.e).sum())

    def cost(self, eps_pen: float) -> float:
        return self.fixed_cost + eps_pen * self.throughput()


@dataclass
class RMPSolution:
    status: str
    obj: float
    x: np.ndarray
    g: np.ndarray
    alpha: np.ndarray
    mu: np.ndarray
    integral: bool
    nb: float = 0.0
    charge: np.ndarray = None
    discharge: np.ndarray = None
    nu: np.ndarray = None            # charge-congestion-cap dual (>=0)
    fleet_dual: float = 0.0          # native marginal for sum(truck x) <= max_trucks
    native_status: int | str | None = None
    native_solution_status: int | str | None = None
    message: str = ""
    termination_reason: str = ""
    has_incumbent: bool = False
    solver_bound: float | None = None
    gap: float | None = None
    validation_max_violation: float | None = None
    soc: np.ndarray = None
    vector: np.ndarray = None
    timings: dict = None


# Coverage sense: False = set partitioning (== 1, the revised model); True = set
# covering (>= 1), matching the ORIGINAL master's trip_coverage constraints.
# Module-level on purpose: it is a temporary alignment switch for head-to-head
# tests (set `master.COVERING = True`), not a modeling knob of the revision.
COVERING = False


def _layout(inst: Instance, R: int):
    T = inst.T
    oX, oG, oC, oD = 0, R, R + T, R + 2 * T
    oS, oNb = R + 3 * T, R + 4 * T + 1
    nvar = oNb + 1
    return T, oX, oG, oC, oD, oS, oNb, nvar


def _build_lp(inst: Instance, cols: list[Column], battery_allowed: bool = True,
              soc_mode: str = "cyclic"):
    if soc_mode not in ("cyclic", "free", "periodic"):
        if not isinstance(soc_mode, str) or not soc_mode.startswith("pin"):
            raise ValueError("unknown SoC boundary mode")
        try:
            level = float(soc_mode[3:])
        except ValueError as exc:
            raise ValueError("invalid pinned truck SoC") from exc
        if not np.isfinite(level) or not 0 <= level <= inst.G:
            raise ValueError("pinned truck SoC must lie within battery capacity")
    # periodic/pin affect truck pricing; stationary BESS stays cyclic, matching
    # the reference formulation. Pricing separately validates the pin's grid.
    n, T, R = inst.n_trips, inst.T, len(cols)
    T, oX, oG, oC, oD, oS, oNb, nvar = _layout(inst, R)
    n_slack = n if COVERING else 0   # covering: zero-cost surplus slack per trip (>= 1)
    nvar += n_slack
    G, rho, eta, eps = inst.G, inst.rho, inst.eta, inst.eps_pen
    if not battery_allowed:
        rho = 0.0; G = 0.0          # forces N_b-scaled bounds to 0 -> no stationary battery

    c = np.zeros(nvar)
    for r, col in enumerate(cols):
        c[oX + r] = col.cost(eps)
    c[oG:oG + T] = inst.c_g
    c[oC:oC + T] = eps
    c[oD:oD + T] = eps + getattr(inst, "deg_cost", 0.0)   # cycling degradation on discharge
    c[oNb] = inst.c_b

    # equalities: coverage (n) + SoC dynamics (T) + s0 (1)
    Aeq = np.zeros((n + T + 1, nvar)); beq = np.zeros(n + T + 1)
    for r, col in enumerate(cols):
        Aeq[:n, oX + r] = col.a
    beq[:n] = 1.0
    for i in range(n_slack):                            # covering: sum a x - s_i = 1, s_i >= 0
        Aeq[i, nvar - n_slack + i] = -1.0
    for t in range(T):                                  # SoC dynamics
        row = n + t
        Aeq[row, oS + t + 1] = 1.0
        Aeq[row, oS + t] = -1.0
        Aeq[row, oC + t] = -(1 - eta)
        Aeq[row, oD + t] = 1.0
    if soc_mode == "free":                               # original arXiv: battery starts FULL, free
        Aeq[n + T, oS + 0] = 1.0; Aeq[n + T, oNb] = -G
    else:                                                # cyclic: s_T = s_0 (no free energy)
        Aeq[n + T, oS + T] = 1.0; Aeq[n + T, oS + 0] = -1.0

    # inequalities (<=): balance (T) + SoC upper (T+1) + rate chg (T) + rate dis (T)
    #                    [+ charge-congestion cap (T) if finite]
    cc_active = np.isfinite(inst.charge_cap)
    nub = T + (T + 1) + T + T + (T if cc_active else 0)
    Aub = np.zeros((nub, nvar)); bub = np.zeros(nub)
    for t in range(T):                                  # balance row t (first T rows)
        for r, col in enumerate(cols):
            Aub[t, oX + r] = col.e[t]
        Aub[t, oG + t] = -1.0
        Aub[t, oC + t] = 1.0
        Aub[t, oD + t] = -1.0
        bub[t] = -inst.Delta[t]
    base = T
    for k in range(T + 1):                              # s_k <= G Nb
        Aub[base + k, oS + k] = 1.0; Aub[base + k, oNb] = -G
    base += T + 1
    for t in range(T):                                  # chg_t <= rho Nb
        Aub[base + t, oC + t] = 1.0; Aub[base + t, oNb] = -rho
    base += T
    for t in range(T):                                  # dis_t <= rho Nb
        Aub[base + t, oD + t] = 1.0; Aub[base + t, oNb] = -rho
    base += T
    _fb = getattr(inst, "fuel_budget", float("inf"))
    _mt = getattr(inst, "max_trucks", float("inf"))
    extra = int(np.isfinite(_fb)) + int(np.isfinite(_mt))
    if extra:
        Aub = np.vstack([Aub, np.zeros((extra, nvar))]); bub = np.append(bub, np.zeros(extra))
        k = -extra
        if np.isfinite(_fb):                            # daily fossil-fuel stock
            Aub[k, oG:oG + T] = 1.0; bub[k] = float(_fb); k += 1
        if np.isfinite(_mt):                            # truck-count cap (two-stage);
            for r, col in enumerate(cols):              # ONLY real trucks count (an
                if getattr(col, "kind", "") == "truck":  # artificial must not consume
                    Aub[k, oX + r] = 1.0                 # a fleet slot)
            bub[k] = float(_mt)
    _nbf = getattr(inst, "nb_fixed", -1.0)
    if _nbf is not None and _nbf >= 0:                  # fix battery count (two-stage)
        Aeq = np.vstack([Aeq, np.zeros((1, nvar))]); beq = np.append(beq, float(_nbf))
        Aeq[-1, oNb] = 1.0
    cc_start = None
    if cc_active:                                       # total charging power per block <= charge_cap
        cc_start = base
        for t in range(T):
            for r, col in enumerate(cols):
                ce = col.e[t] if col.e[t] > 0 else 0.0
                if ce > 0.0:
                    Aub[base + t, oX + r] = ce
            Aub[base + t, oC + t] = 1.0                  # battery charge counts too
            bub[base + t] = inst.charge_cap

    bounds = [(0, None)] * nvar
    caps_t = np.broadcast_to(np.asarray(inst.gen_cap, dtype=float), (T,))
    for t in range(T):                                   # generation capacity per block
        if np.isfinite(caps_t[t]):
            bounds[oG + t] = (0, float(caps_t[t]))
    return c, Aub, bub, Aeq, beq, bounds, (oX, oG, oC, oD, oS, oNb), n, T, R, cc_start


@dataclass
class CanonicalRMP:
    """Common matrix contract. Equalities precede <= rows in `matrix`."""
    c: np.ndarray
    Aub: sparse.csr_matrix
    bub: np.ndarray
    Aeq: sparse.csr_matrix
    beq: np.ndarray
    bounds: list
    off: tuple
    n: int
    T: int
    R: int
    cc_start: int | None
    fleet_row: int | None

    @property
    def matrix(self):
        return sparse.vstack((self.Aeq, self.Aub), format="csr")

    @property
    def integer_indices(self):
        return list(range(self.R)) + [self.off[-1]]


def canonical_model(inst, cols, battery_allowed=True, soc_mode="cyclic"):
    """Reference matrix for all backends; the dense legacy builder stays callable.

    The persistent adapter builds this only for its static zero-column block.
    Cold backends intentionally retain the same reference implementation.
    """
    for col in cols:
        if np.shape(col.a) != (inst.n_trips,) or np.shape(col.e) != (inst.T,):
            raise ValueError("column dimensions do not match instance")
        if not (np.all(np.isfinite(col.a)) and np.all(np.isfinite(col.e))
                and np.isfinite(col.fixed_cost)):
            raise ValueError("column coefficients/cost must be finite")
    c, au, bu, ae, be, bounds, off, n, T, R, cc = _build_lp(
        inst, cols, battery_allowed, soc_mode)
    if not all(np.all(np.isfinite(a)) for a in (c, au, bu, ae, be)):
        raise ValueError("master coefficients and right-hand sides must be finite")
    fleet_row = len(bu) - 1 if np.isfinite(inst.max_trucks) else None
    return CanonicalRMP(c, sparse.csr_matrix(au), bu, sparse.csr_matrix(ae),
                        be, bounds, off, n, T, R, cc, fleet_row)


def validate_vector(model, vector, integer=False, objective=None, tolerance=1e-6):
    """Reject populated infeasible solver vectors; no missing value is silently zero.

    Absolute residuals are intentional: units agree with the physical model.
    Objective verification has a separate floating summation tolerance.
    """
    if vector is None:
        return False, float("inf"), "no primal vector"
    z = np.asarray(vector, dtype=float)
    if z.shape != model.c.shape or not np.all(np.isfinite(z)):
        return False, float("inf"), "missing/nonfinite primal values"
    residuals = [0.0]
    if model.Aeq.shape[0]:
        residuals.append(float(np.max(np.abs(model.Aeq @ z - model.beq))))
    if model.Aub.shape[0]:
        residuals.append(float(np.max(model.Aub @ z - model.bub)))
    for j, (lb, ub) in enumerate(model.bounds):
        if lb is not None:
            residuals.append(float(lb - z[j]))
        if ub is not None:
            residuals.append(float(z[j] - ub))
    if integer:
        v = z[model.integer_indices]
        residuals.append(float(np.max(np.abs(v - np.rint(v)), initial=0)))
    worst = max(residuals)
    if worst > tolerance:
        return False, worst, "primal/integrality residual exceeds tolerance"
    value = float(model.c @ z)
    if objective is not None and (not np.isfinite(objective) or
            abs(value - objective) > max(1e-5, 1e-9 * max(abs(value), abs(objective)))):
        return False, worst, "reported objective does not match primal vector"
    return True, worst, "verified primal vector"


def solution_from_vector(model, vector, integer=False, status="optimal", **metadata):
    """Construct only from a validated vector; callers gate native incumbent status."""
    valid, residual, reason = validate_vector(model, vector, integer,
                                               metadata.pop("objective", None))
    metadata["validation_max_violation"] = residual
    if not valid:
        metadata["message"] = (metadata.get("message", "") + "; " + reason).strip("; ")
        return empty_solution(model, "invalid_incumbent", integer, **metadata)
    z = np.asarray(vector, dtype=float).copy()
    ox, og, oc, od, os, onb = model.off
    sol = RMPSolution(status, float(model.c @ z), z[ox:ox + model.R],
        z[og:og + model.T], np.zeros(model.n), np.zeros(model.T), integer,
        float(z[onb]), z[oc:oc + model.T], z[od:od + model.T], np.zeros(model.T),
        has_incumbent=True, soc=z[os:os + model.T + 1], vector=z, **metadata)
    return sol


def empty_solution(model, status, integer=False, **metadata):
    return RMPSolution(status, np.inf, np.zeros(model.R), np.zeros(model.T),
        np.zeros(model.n), np.zeros(model.T), integer, charge=np.zeros(model.T),
        discharge=np.zeros(model.T), nu=np.zeros(model.T), **metadata)


def solve_lp(inst: Instance, cols: list[Column], battery_allowed: bool = True,
             solver: str = "highs", soc_mode: str = "cyclic") -> RMPSolution:
    if solver == "gurobi":
        from gurobi_master import solve_lp_gurobi
        return solve_lp_gurobi(inst, cols, battery_allowed, soc_mode=soc_mode)
    if solver != "highs":
        raise ValueError("solve_lp solver must be 'highs' or 'gurobi'; use a session for persistent LP")
    started = perf_counter()
    model = canonical_model(inst, cols, battery_allowed, soc_mode)
    built = perf_counter()
    res = linprog(model.c, A_ub=model.Aub, b_ub=model.bub, A_eq=model.Aeq,
                  b_eq=model.beq, bounds=model.bounds, method="highs")
    solved = perf_counter()
    reason = {0:"optimal", 1:"limit", 2:"infeasible", 3:"unbounded", 4:"numerical_error"}.get(
        res.status, "solver_error")
    meta = dict(native_status=int(res.status), message=str(res.message), termination_reason=reason,
                timings=dict(build_seconds=built-started, solve_seconds=solved-built,
                             rows=model.Aeq.shape[0]+model.Aub.shape[0], columns=len(model.c)))
    if res.x is None or reason in ("infeasible", "unbounded", "numerical_error", "solver_error"):
        return empty_solution(model, reason, **meta)
    sol = solution_from_vector(model, res.x, status="optimal" if res.success else "feasible",
                               objective=res.fun, **meta)
    if sol.status == "optimal":
        sol.alpha = np.asarray(res.eqlin.marginals[:model.n])
        sol.mu = -np.asarray(res.ineqlin.marginals[:model.T])
        if model.cc_start is not None:
            sol.nu = -np.asarray(res.ineqlin.marginals[model.cc_start:model.cc_start + model.T])
        if model.fleet_row is not None:
            sol.fleet_dual = float(res.ineqlin.marginals[model.fleet_row])
        sol.solver_bound = sol.obj
        sol.gap = 0.0
    return sol


def reduced_cost(col: Column, sol: RMPSolution, inst: Instance) -> float:
    rc = col.cost(inst.eps_pen) - float(col.a @ sol.alpha) + float(col.e @ sol.mu)
    if sol.nu is not None:
        rc += float(np.maximum(col.e, 0.0) @ sol.nu)
    if col.kind == "truck":
        rc -= sol.fleet_dual
    return rc


def solve_milp(inst: Instance, cols: list[Column], time_limit: float = 120.0,
               battery_allowed: bool = True, solver: str = "cbc",
               soc_mode: str = "cyclic", mip_gap: float | None = None,
               x_start: dict | None = None) -> RMPSolution:
    """Return a verified incumbent only when both native status and residuals permit it.

    A finite-pool MIP bound is explicitly a statement about this restricted pool.
    `x_start` is a hint, not a certificate of feasibility for this model.
    """
    if solver == "gurobi":
        from gurobi_master import solve_milp_gurobi
        return solve_milp_gurobi(inst, cols, time_limit, battery_allowed,
                                 soc_mode=soc_mode, mip_gap=mip_gap, x_start=x_start)
    if solver != "cbc":
        raise ValueError("MILP solver must be 'cbc' or 'gurobi'")
    import pulp
    model = canonical_model(inst, cols, battery_allowed, soc_mode)
    p = pulp.LpProblem("rmp", pulp.LpMinimize)
    integers = set(model.integer_indices)
    v = [pulp.LpVariable(f"v_{j}", lowBound=lb, upBound=ub,
         cat="Integer" if j in integers else "Continuous") for j, (lb, ub) in enumerate(model.bounds)]
    p += pulp.lpSum(float(c) * v[j] for j, c in enumerate(model.c) if c)
    for matrix, rhs, eq in ((model.Aeq, model.beq, True), (model.Aub, model.bub, False)):
        for k in range(matrix.shape[0]):
            a, b = matrix.indptr[k:k+2]
            expr = pulp.lpSum(float(c) * v[int(j)] for j, c in zip(matrix.indices[a:b], matrix.data[a:b]))
            p += expr == float(rhs[k]) if eq else expr <= float(rhs[k])
    kwargs = {"msg": 0, "timeLimit": time_limit}
    if mip_gap is not None:
        kwargs["gapRel"] = mip_gap
    if x_start:
        start = {int(k): value for k, value in x_start.get("x", {}).items()}
        for j in range(model.R):
            v[j].setInitialValue(int(round(start.get(j, 0))))
        v[model.off[-1]].setInitialValue(int(round(x_start.get("nb", 0))))
        kwargs["warmStart"] = True
    try:
        st = p.solve(pulp.PULP_CBC_CMD(**kwargs))
    except pulp.PulpSolverError as exc:
        return empty_solution(model, "solver_error", True, message=str(exc), termination_reason="solver_error")
    sol_st = getattr(p, "sol_status", None)
    native_name = pulp.LpStatus.get(st, "Unknown")
    solution_name = pulp.LpSolution.get(sol_st, "Unknown")
    reason = {-1:"infeasible", -2:"unbounded", -3:"undefined", 0:"not_solved"}.get(st, "stopped")
    optimal = st == pulp.LpStatusOptimal and sol_st == pulp.LpSolutionOptimal
    feasible = (st not in (pulp.LpStatusInfeasible, pulp.LpStatusUnbounded, pulp.LpStatusUndefined)
                and sol_st in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible))
    if optimal:
        reason = "optimal"
    elif feasible:
        reason = "stopped_with_incumbent"  # PuLP does not expose CBC's exact stop reason.
    meta = dict(native_status=st, native_solution_status=sol_st,
                message=f"CBC/PuLP problem: {native_name}; solution: {solution_name}",
                termination_reason=reason)
    if not feasible:
        return empty_solution(model, reason, True, **meta)
    values = [var.value() for var in v]
    # PuLP may omit variables absent from every row/objective. Give only these
    # unconstrained zero-cost variables their known feasible lower bound.
    used = np.asarray(abs(model.matrix).sum(axis=0)).ravel() + np.abs(model.c)
    for j, val in enumerate(values):
        if val is None and used[j] == 0:
            values[j] = model.bounds[j][0] or 0.0
    sol = solution_from_vector(model, values, True,
        status="optimal" if optimal else "feasible", objective=pulp.value(p.objective), **meta)
    # PuLP does not expose CBC's best bound/gap. Even a native 'Optimal'
    # classification can mean the configured relative gap was reached; do not
    # manufacture a zero gap or set the bound equal to the incumbent.
    return sol
