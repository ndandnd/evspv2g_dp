"""
Legacy battery-schedule pricing: full initial charge and free terminal SoC.

These helpers are not the current aggregate cyclic-storage master. The LP is
continuous; the DP is exact only for its explicitly validated SoC grid.

Given duals (alpha unused for batteries, mu_t the generation price), find the energy
profile e_t minimizing the reduced cost
    rc = c_b + eps*sum_t(charge_t + discharge_t) + deg*sum_t discharge_t
         + sum_t mu_t (charge_t - discharge_t)
subject to the state-of-charge dynamics
    s_{t+1} = s_t + (1-eta) charge_t - discharge_t,   0<=s_t<=G,
    0<=charge_t,discharge_t<=rho,    s_1 = G.

Two implementations:
  * price_battery_lp : exact LP (HiGHS) -- the reference.
  * price_battery_dp : SoC-discretized dynamic program -- demonstrates the DP route
    and matches the LP only when the continuous optimum is representable on its grid.
Net grid energy e_t = charge_t - discharge_t (>0 draw, <0 inject).
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import linprog
from instance import Instance
from master import Column
from pricing_contract import validate_storage, validate_duals, check_reconstructed_cost


def price_battery_lp(inst: Instance, mu: np.ndarray):
    """Legacy continuous LP, full start/free end. Returns (Column, reduced_cost).
    Raise if simultaneous charge/discharge cannot be represented by a net-energy
    Column; this can occur for price inputs outside the original nonnegative case.
    """
    _, mu, _ = validate_duals(inst, np.zeros(inst.n_trips), mu, None)
    if not (np.isfinite(inst.G) and inst.G >= 0 and np.isfinite(inst.rho) and inst.rho >= 0
            and np.isfinite(inst.eta) and 0 <= inst.eta < 1):
        raise ValueError("battery capacity/rate must be nonnegative and eta in [0,1)")
    if not np.isfinite(inst.c_b):
        raise ValueError("battery fixed cost must be finite")
    deg = getattr(inst, "deg_cost", 0.0)
    T = inst.T
    eta, rho, G, eps = inst.eta, inst.rho, inst.G, inst.eps_pen
    # vars: charge_0..charge_{T-1}, discharge_0..., s_0..s_T  (T+1 SoC nodes; s_t = SoC entering block t)
    nvar = T + T + (T + 1)
    C = slice(0, T); Dd = slice(T, 2 * T); S = slice(2 * T, 2 * T + T + 1)

    c = np.zeros(nvar)
    c[C] = eps + mu                      # charge: pay price mu_t + penalty
    c[Dd] = eps + deg - mu                     # discharge: earn -mu_t (reward) + penalty
    # SoC dynamics as equalities for EVERY block t=0..T-1: s_{t+1} - s_t - (1-eta) charge_t + discharge_t = 0
    rows, b_eq = [], []
    for t in range(T):
        row = np.zeros(nvar)
        row[S][t + 1] = 1.0
        row[S][t] = -1.0
        row[C][t] = -(1 - eta)
        row[Dd][t] = 1.0
        rows.append(row); b_eq.append(0.0)
    # initial SoC = G
    r0 = np.zeros(nvar); r0[S][0] = 1.0; rows.append(r0); b_eq.append(G)
    A_eq = np.array(rows); b_eq = np.array(b_eq)

    bounds = [(0, rho)] * T + [(0, rho)] * T + [(0, G)] * (T + 1)
    res = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        return None, np.inf
    charge = res.x[C]; discharge = res.x[Dd]
    if np.any(np.minimum(charge, discharge) > 1e-8):
        raise RuntimeError("legacy battery LP uses simultaneous charge/discharge; net Column cannot represent this solution")
    e = charge - discharge
    col = Column("battery", np.zeros(inst.n_trips), e, inst.c_b + deg * float(discharge.sum()), "batt-LP")
    rc = inst.c_b + res.fun
    terms = (col.cost(inst.eps_pen), float(e @ mu))
    check_reconstructed_cost(rc, sum(terms), terms, T)
    return col, rc


def price_battery_dp(inst: Instance, mu: np.ndarray, step: float = 5.0):
    """SoC-discretized DP (dense, vectorized). Returns (Column, reduced_cost).
    Battery starts full; pure arbitrage at origin -- same structure as the truck DP
    restricted to charge/discharge only."""
    T, step, nL, up, dn = validate_storage(inst, step)
    _, mu, _ = validate_duals(inst, np.zeros(inst.n_trips), mu, None)
    eta, rho, G, eps = inst.eta, inst.rho, inst.G, inst.eps_pen
    if not np.isfinite(inst.c_b):
        raise ValueError("battery fixed cost must be finite")
    deg = getattr(inst, "deg_cost", 0.0)
    Gidx = nL - 1
    slope_c = (mu + eps) * step / (1 - eta)
    slope_d = (eps + deg - mu) * step
    INF = np.inf

    dp = np.full((T + 1, nL), INF)
    dp[0, Gidx] = 0.0
    for t in range(T):
        cur = dp[t]
        np.minimum(dp[t + 1], cur, out=dp[t + 1])            # wait
        cand = np.full(nL, INF)
        for d in range(1, up + 1):
            np.minimum(cand[d:], cur[:nL - d] + slope_c[t] * d, out=cand[d:])
        for d in range(1, dn + 1):
            np.minimum(cand[:nL - d], cur[d:] + slope_d[t] * d, out=cand[:nL - d])
        np.minimum(dp[t + 1], cand, out=dp[t + 1])
    end = int(np.argmin(dp[T]))
    best = dp[T, end]
    # backward reconstruction of e profile
    e = np.zeros(T)
    si = end
    for t in range(T, 0, -1):
        v = dp[t, si]
        if dp[t - 1, si] == v:                    # wait
            continue
        done = False
        for d in range(1, up + 1):                            # charged d levels
            pi = si - d
            if pi >= 0 and dp[t - 1, pi] + slope_c[t - 1] * d == v:
                e[t - 1] = (d * step) / (1 - eta); si = pi; done = True; break
        if done:
            continue
        for d in range(1, dn + 1):                            # discharged d levels
            pi = si + d
            if pi < nL and dp[t - 1, pi] + slope_d[t - 1] * d == v:
                e[t - 1] = -(d * step); si = pi; done = True; break
        if not done:
            raise RuntimeError(f"battery reconstruction has no exact predecessor at {(t, si)}")
    if si != Gidx:
        raise RuntimeError("battery reconstruction did not reach its full initial source")
    col = Column("battery", np.zeros(inst.n_trips), e,
                 inst.c_b + deg * float(np.maximum(-e, 0).sum()), "batt-DP")
    rc = inst.c_b + best
    terms = (col.cost(eps), float(e @ mu))
    check_reconstructed_cost(rc, sum(terms), terms, T)
    return col, float(rc)


if __name__ == "__main__":
    from instance import make_instance
    from master import solve_lp, Column, reduced_cost
    inst = make_instance(n_trips=20, n_locations=3, eps=2.0, seed=2)
    # seed with single-trip truck columns to get a sensible dual vector
    T = inst.T
    cols = []
    for i in range(inst.n_trips):
        a = np.zeros(inst.n_trips); a[i] = 1
        cols.append(Column("truck", a, np.zeros(T), inst.c_v, f"t{i}"))
    sol = solve_lp(inst, cols)
    print("RMP obj", round(sol.obj, 1), " mu range", round(sol.mu.min(), 3), round(sol.mu.max(), 3))

    col_lp, rc_lp = price_battery_lp(inst, sol.mu)
    col_dp, rc_dp = price_battery_dp(inst, sol.mu, step=inst.G / 140)
    print(f"battery pricing  LP rc = {rc_lp:.3f}   DP rc = {rc_dp:.3f}   |diff| = {abs(rc_lp-rc_dp):.3f}")
    # independent check: reduced cost recomputed via master formula on the LP column
    print("LP column rc via master formula:", round(reduced_cost(col_lp, sol, inst), 3))
    chg = np.where(col_lp.e > 1e-6)[0]; dis = np.where(col_lp.e < -1e-6)[0]
    print("LP column charges at blocks", list(chg), " discharges at", list(dis))
    print("mu at charge blocks:", np.round(sol.mu[chg], 2), " mu at discharge blocks:", np.round(sol.mu[dis], 2))
