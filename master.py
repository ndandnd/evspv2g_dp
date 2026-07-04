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
    c[oD:oD + T] = eps
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
    cc_start = None
    if cc_active:                                       # total charging power per block <= charge_cap
        cc_start = base
        for t in range(T):
            for r, col in enumerate(cols):
                ce = col.e[t] if col.e[t] > 0 else 0.0
                if ce > 1e-9:
                    Aub[base + t, oX + r] = ce
            Aub[base + t, oC + t] = 1.0                  # battery charge counts too
            bub[base + t] = inst.charge_cap

    bounds = [(0, None)] * nvar
    if np.isfinite(inst.gen_cap):                        # generation capacity per block
        for t in range(T):
            bounds[oG + t] = (0, inst.gen_cap)
    return c, Aub, bub, Aeq, beq, bounds, (oX, oG, oC, oD, oS, oNb), n, T, R, cc_start


def solve_lp(inst: Instance, cols: list[Column], battery_allowed: bool = True,
             solver: str = "highs", soc_mode: str = "cyclic") -> RMPSolution:
    if solver == "gurobi":
        from gurobi_master import solve_lp_gurobi
        return solve_lp_gurobi(inst, cols, battery_allowed, soc_mode=soc_mode)
    c, Aub, bub, Aeq, beq, bounds, off, n, T, R, cc_start = _build_lp(inst, cols, battery_allowed,
                                                                      soc_mode=soc_mode)
    oX, oG, oC, oD, oS, oNb = off
    res = linprog(c, A_ub=Aub, b_ub=bub, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    if not res.success:
        return RMPSolution("infeasible", np.inf, np.zeros(R), np.zeros(T),
                           np.zeros(n), np.zeros(T), False, nu=np.zeros(T))
    x = res.x[oX:oX + R]; g = res.x[oG:oG + T]
    chg = res.x[oC:oC + T]; dis = res.x[oD:oD + T]; nb = res.x[oNb]
    alpha = res.eqlin.marginals[:n]              # coverage shadow prices
    mu = -res.ineqlin.marginals[:T]              # generation price
    nu = np.zeros(T)                             # charge-congestion price (>=0)
    if cc_start is not None:
        nu = -res.ineqlin.marginals[cc_start:cc_start + T]
    return RMPSolution("optimal", res.fun, x, g, alpha, mu, False, nb, chg, dis, nu)


def reduced_cost(col: Column, sol: RMPSolution, inst: Instance) -> float:
    rc = col.cost(inst.eps_pen) - float(col.a @ sol.alpha) + float(col.e @ sol.mu)
    if sol.nu is not None:
        rc += float(np.maximum(col.e, 0.0) @ sol.nu)   # charger-capacity price on charging
    return rc


def solve_milp(inst: Instance, cols: list[Column], time_limit: float = 120.0,
               battery_allowed: bool = True, solver: str = "cbc",
               soc_mode: str = "cyclic", mip_gap: float | None = None) -> RMPSolution:
    if solver == "gurobi":
        from gurobi_master import solve_milp_gurobi
        return solve_milp_gurobi(inst, cols, time_limit, battery_allowed,
                                 soc_mode=soc_mode, mip_gap=mip_gap)
    import pulp
    n, T, R = inst.n_trips, inst.T, len(cols)
    G, rho, eta, eps = inst.G, inst.rho, inst.eta, inst.eps_pen
    if not battery_allowed:
        G = 0.0; rho = 0.0          # no stationary battery (forces N_b dispatch to 0)
    p = pulp.LpProblem("rmp", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x_{r}", lowBound=0, cat="Integer") for r in range(R)]
    Nb = pulp.LpVariable("Nb", lowBound=0, cat="Integer")
    g = [pulp.LpVariable(f"g_{t}", lowBound=0) for t in range(T)]
    chg = [pulp.LpVariable(f"c_{t}", lowBound=0) for t in range(T)]
    dis = [pulp.LpVariable(f"d_{t}", lowBound=0) for t in range(T)]
    s = [pulp.LpVariable(f"s_{t}", lowBound=0) for t in range(T + 1)]
    p += (pulp.lpSum(inst.c_g * g[t] for t in range(T))
          + pulp.lpSum(cols[r].cost(eps) * x[r] for r in range(R))
          + inst.c_b * Nb
          + eps * pulp.lpSum(chg[t] + dis[t] for t in range(T)))
    for i in range(n):
        cov = pulp.lpSum(cols[r].a[i] * x[r] for r in range(R) if cols[r].a[i] > 0.5)
        p += (cov >= 1) if COVERING else (cov == 1)
    for t in range(T):
        p += (g[t] - pulp.lpSum(cols[r].e[t] * x[r] for r in range(R) if abs(cols[r].e[t]) > 1e-9)
              - chg[t] + dis[t] >= inst.Delta[t])
        p += s[t + 1] == s[t] + (1 - eta) * chg[t] - dis[t]
        p += chg[t] <= rho * Nb
        p += dis[t] <= rho * Nb
        if np.isfinite(inst.gen_cap):
            p += g[t] <= inst.gen_cap                         # generation capacity
        if np.isfinite(inst.charge_cap):                      # charging-congestion cap
            p += (pulp.lpSum((cols[r].e[t] if cols[r].e[t] > 0 else 0.0) * x[r]
                             for r in range(R) if cols[r].e[t] > 1e-9) + chg[t] <= inst.charge_cap)
    if soc_mode == "free":
        p += s[0] == G * Nb                   # original arXiv: battery starts FULL, free
    else:
        p += s[T] == s[0]                     # cyclic battery (no free energy)
    for t in range(T + 1):
        p += s[t] <= G * Nb
    kwargs = {"msg": 0, "timeLimit": time_limit}
    if mip_gap is not None:
        kwargs["gapRel"] = mip_gap
    st = p.solve(pulp.PULP_CBC_CMD(**kwargs))
    if pulp.value(p.objective) is None:
        return RMPSolution("milp_failed", np.inf, np.zeros(R), np.zeros(T),
                           np.zeros(n), np.zeros(T), True)
    xv = np.array([v.value() or 0.0 for v in x])
    gv = np.array([v.value() or 0.0 for v in g])
    cv = np.array([v.value() or 0.0 for v in chg]); dv = np.array([v.value() or 0.0 for v in dis])
    return RMPSolution("optimal", pulp.value(p.objective), xv, gv, np.zeros(n), np.zeros(T),
                       True, Nb.value() or 0.0, cv, dv)


if __name__ == "__main__":
    from instance import make_instance
    inst = make_instance(n_trips=4, n_locations=2, eps=2.0, seed=3)
    T = inst.T
    cols = [Column("truck", np.eye(inst.n_trips)[i], np.zeros(T), inst.c_v, f"t{i}")
            for i in range(inst.n_trips)]
    sol = solve_lp(inst, cols)
    print("status", sol.status, "obj", round(sol.obj, 2), "Nb", round(sol.nb, 2))
    print("alpha", np.round(sol.alpha, 1), " mu in", (round(sol.mu.min(), 3), round(sol.mu.max(), 3)))
    rcs = [reduced_cost(c, sol, inst) for c in cols]
    print("basis reduced costs (expect ~0):", np.round(rcs, 6))
    print("battery in LP: Nb=%.2f, charge sum=%.0f, discharge sum=%.0f"
          % (sol.nb, sol.charge.sum(), sol.discharge.sum()))
