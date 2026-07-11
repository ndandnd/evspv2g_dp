"""
Gurobi backends for the EVSP-V2G restricted master -- drop-in replacements for the
HiGHS (LP) and CBC (MILP) solvers in master.py, used by the solver comparison.

The model is replicated *exactly* from master.py (same variables, constraints,
costs, and sign conventions) so that:
  * the LP objective and duals match HiGHS to numerical tolerance, and
  * column generation behaves identically regardless of the LP backend.

Dual sign convention (to match scipy.optimize.linprog's `marginals`, which are
shadow prices d(obj)/d(rhs)):
    alpha_i = Pi(coverage_i)         # equality
    mu_t    = -Pi(balance_t)         # <= constraint  -> Pi <= 0  -> mu >= 0
    nu_t    = -Pi(chargecap_t)       # <= constraint

This module is imported lazily (only when solver="gurobi" is requested), so the
rest of the repo runs fine on machines without gurobipy installed.
"""
from __future__ import annotations
import numpy as np
from instance import Instance
import master as _master
from master import Column, RMPSolution


def _build(inst: Instance, cols: list[Column], integer: bool, battery_allowed: bool,
           time_limit: float | None = None, soc_mode: str = "cyclic",
           mip_gap: float | None = None):
    """Build the restricted master in Gurobi. Returns (model, x, g, chg, dis, s, Nb,
    cover, bal, cc) so callers can read solution values and duals."""
    import gurobipy as gp
    from gurobipy import GRB

    n, T, R = inst.n_trips, inst.T, len(cols)
    G   = inst.G   if battery_allowed else 0.0      # no stationary battery -> bounds force Nb dispatch to 0
    rho = inst.rho if battery_allowed else 0.0
    eta, eps = inst.eta, inst.eps_pen
    vtype = GRB.INTEGER if integer else GRB.CONTINUOUS

    m = gp.Model("rmp")
    m.Params.OutputFlag = 0
    if time_limit is not None:
        m.Params.TimeLimit = float(time_limit)
    if integer and mip_gap is not None:
        m.Params.MIPGap = float(mip_gap)

    x  = m.addVars(R, lb=0.0, vtype=vtype, name="x")
    caps_t = np.broadcast_to(np.asarray(inst.gen_cap, dtype=float), (T,))
    g  = m.addVars(T, lb=0.0, name="g")
    for t in range(T):
        if np.isfinite(caps_t[t]):
            g[t].UB = float(caps_t[t])
    chg = m.addVars(T, lb=0.0, name="chg")
    dis = m.addVars(T, lb=0.0, name="dis")
    s  = m.addVars(T + 1, lb=0.0, name="s")
    Nb = m.addVar(lb=0.0, vtype=(GRB.INTEGER if integer else GRB.CONTINUOUS), name="Nb")
    _fb = getattr(inst, "fuel_budget", float("inf"))
    if np.isfinite(_fb):                      # daily fossil-fuel stock (endurance studies)
        m.addConstr(gp.quicksum(g[t] for t in range(T)) <= float(_fb), name="fuel_budget")
    _mt = getattr(inst, "max_trucks", float("inf"))
    if np.isfinite(_mt):                      # truck-count cap (two-stage studies)
        m.addConstr(gp.quicksum(x[r] for r in range(R)) <= float(_mt), name="max_trucks")
    _nbf = getattr(inst, "nb_fixed", -1.0)
    if _nbf is not None and _nbf >= 0:        # fixed battery count (two-stage studies)
        m.addConstr(Nb == float(_nbf), name="nb_fixed")

    m.setObjective(
        gp.quicksum(cols[r].cost(eps) * x[r] for r in range(R))
        + gp.quicksum(inst.c_g * g[t] for t in range(T))
        + gp.quicksum(eps * chg[t] + (eps + getattr(inst, "deg_cost", 0.0)) * dis[t]
                      for t in range(T))
        + inst.c_b * Nb,
        GRB.MINIMIZE,
    )

    # coverage (set partitioning) -- equalities
    def _cov(i):
        expr = gp.quicksum(cols[r].a[i] * x[r] for r in range(R) if cols[r].a[i] > 0.5)
        return m.addConstr(expr >= 1.0 if _master.COVERING else expr == 1.0, name=f"cov_{i}")
    cover = [_cov(i) for i in range(n)]

    # SoC dynamics + cyclic boundary (equalities)
    for t in range(T):
        m.addConstr(s[t + 1] == s[t] + (1 - eta) * chg[t] - dis[t], name=f"soc_{t}")
    if soc_mode == "free":
        m.addConstr(s[0] == G * Nb, name="free_full_start")   # original arXiv setting
    else:
        m.addConstr(s[T] == s[0], name="cyclic")

    # power balance (<=):  sum_r e_rt x_r - g_t + chg_t - dis_t <= -Delta_t
    bal = [m.addConstr(gp.quicksum(cols[r].e[t] * x[r]
                                   for r in range(R) if abs(cols[r].e[t]) > 1e-9)
                       - g[t] + chg[t] - dis[t] <= -float(inst.Delta[t]), name=f"bal_{t}")
           for t in range(T)]

    # battery sizing/rate (<=)
    for k in range(T + 1):
        m.addConstr(s[k] <= G * Nb, name=f"scap_{k}")
    for t in range(T):
        m.addConstr(chg[t] <= rho * Nb, name=f"crate_{t}")
        m.addConstr(dis[t] <= rho * Nb, name=f"drate_{t}")

    # charging-congestion cap (<=), only if finite
    cc = None
    if np.isfinite(inst.charge_cap):
        cc = [m.addConstr(gp.quicksum((cols[r].e[t] if cols[r].e[t] > 0 else 0.0) * x[r]
                                      for r in range(R) if cols[r].e[t] > 1e-9) + chg[t]
                          <= float(inst.charge_cap), name=f"cc_{t}") for t in range(T)]

    m.optimize()
    return m, x, g, chg, dis, s, Nb, cover, bal, cc


def solve_lp_gurobi(inst: Instance, cols: list[Column], battery_allowed: bool = True,
                    soc_mode: str = "cyclic") -> RMPSolution:
    from gurobipy import GRB
    n, T, R = inst.n_trips, inst.T, len(cols)
    m, x, g, chg, dis, s, Nb, cover, bal, cc = _build(inst, cols, integer=False,
                                                      battery_allowed=battery_allowed,
                                                      soc_mode=soc_mode)
    if m.Status != GRB.OPTIMAL:
        return RMPSolution("infeasible", np.inf, np.zeros(R), np.zeros(T),
                           np.zeros(n), np.zeros(T), False, nu=np.zeros(T))
    xv = np.array([x[r].X for r in range(R)])
    gv = np.array([g[t].X for t in range(T)])
    cv = np.array([chg[t].X for t in range(T)])
    dv = np.array([dis[t].X for t in range(T)])
    alpha = np.array([cover[i].Pi for i in range(n)])
    mu = np.array([-bal[t].Pi for t in range(T)])
    nu = np.array([-cc[t].Pi for t in range(T)]) if cc is not None else np.zeros(T)
    return RMPSolution("optimal", m.ObjVal, xv, gv, alpha, mu, False, Nb.X, cv, dv, nu)


def solve_milp_gurobi(inst: Instance, cols: list[Column], time_limit: float = 120.0,
                      battery_allowed: bool = True, soc_mode: str = "cyclic",
                      mip_gap: float | None = None) -> RMPSolution:
    from gurobipy import GRB
    n, T, R = inst.n_trips, inst.T, len(cols)
    m, x, g, chg, dis, s, Nb, cover, bal, cc = _build(inst, cols, integer=True,
                                                      battery_allowed=battery_allowed,
                                                      time_limit=time_limit, soc_mode=soc_mode,
                                                      mip_gap=mip_gap)
    if m.SolCount == 0:                       # no feasible integer solution found (e.g. time-out)
        return RMPSolution("milp_failed", np.inf, np.zeros(R), np.zeros(T),
                           np.zeros(n), np.zeros(T), True)
    import gurobipy as _grb
    status = "optimal" if m.Status == _grb.GRB.OPTIMAL else "feasible"
    xv = np.array([x[r].X for r in range(R)])
    gv = np.array([g[t].X for t in range(T)])
    cv = np.array([chg[t].X for t in range(T)])
    dv = np.array([dis[t].X for t in range(T)])
    sol = RMPSolution(status, m.ObjVal, xv, gv, np.zeros(n), np.zeros(T),
                      True, Nb.X, cv, dv)
    try:
        sol.solver_bound = float(m.ObjBound)
    except Exception:
        sol.solver_bound = None
    return sol
