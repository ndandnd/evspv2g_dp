"""
Battery-schedule pricing: the storage-arbitrage subproblem priced by the duals mu_t.

Given duals (alpha unused for batteries, mu_t the generation price), find the energy
profile e_t minimizing the reduced cost
    rc = c_b + eps*sum_t(charge_t + discharge_t) + sum_t mu_t (charge_t - discharge_t)
subject to the state-of-charge dynamics
    s_{t+1} = s_t + (1-eta) charge_t - discharge_t,   0<=s_t<=G,
    0<=charge_t,discharge_t<=rho,    s_1 = G.

Two implementations:
  * price_battery_lp : exact LP (HiGHS) -- the reference.
  * price_battery_dp : SoC-discretized dynamic program -- demonstrates the DP route
    and is validated to match the LP.
Net grid energy e_t = charge_t - discharge_t (>0 draw, <0 inject).
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import linprog
from instance import Instance
from master import Column


def price_battery_lp(inst: Instance, mu: np.ndarray):
    """Exact LP. Returns (Column, reduced_cost)."""
    T = inst.T
    eta, rho, G, eps = inst.eta, inst.rho, inst.G, inst.eps_pen
    # vars: charge_0..charge_{T-1}, discharge_0..., s_0..s_T  (T+1 SoC nodes; s_t = SoC entering block t)
    nvar = T + T + (T + 1)
    C = slice(0, T); Dd = slice(T, 2 * T); S = slice(2 * T, 2 * T + T + 1)

    c = np.zeros(nvar)
    c[C] = eps + mu                      # charge: pay price mu_t + penalty
    c[Dd] = eps - mu                     # discharge: earn -mu_t (reward) + penalty
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
    e = charge - discharge
    col = Column("battery", np.zeros(inst.n_trips), e, inst.c_b, "batt-LP")
    rc = inst.c_b + res.fun
    return col, rc


def price_battery_dp(inst: Instance, mu: np.ndarray, step: float = 5.0):
    """SoC-discretized DP (dense, vectorized). Returns (Column, reduced_cost).
    Battery starts full; pure arbitrage at origin -- same structure as the truck DP
    restricted to charge/discharge only."""
    T = inst.T
    eta, rho, G, eps = inst.eta, inst.rho, inst.G, inst.eps_pen
    nL = int(round(G / step)) + 1
    Gidx = nL - 1
    up = int(np.floor((1 - eta) * rho / step))
    dn = int(np.floor(rho / step))
    slope_c = (mu + eps) * step / (1 - eta)
    slope_d = (eps - mu) * step
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
        if abs(dp[t - 1, si] - v) < 1e-5:                    # wait
            continue
        done = False
        for d in range(1, up + 1):                            # charged d levels
            pi = si - d
            if pi >= 0 and abs(dp[t - 1, pi] + slope_c[t - 1] * d - v) < 1e-5:
                e[t - 1] = (d * step) / (1 - eta); si = pi; done = True; break
        if done:
            continue
        for d in range(1, dn + 1):                            # discharged d levels
            pi = si + d
            if pi < nL and abs(dp[t - 1, pi] + slope_d[t - 1] * d - v) < 1e-5:
                e[t - 1] = -(d * step); si = pi; done = True; break
    col = Column("battery", np.zeros(inst.n_trips), e, inst.c_b, "batt-DP")
    return col, inst.c_b + best


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
    col_dp, rc_dp = price_battery_dp(inst, sol.mu, n_levels=141)
    print(f"battery pricing  LP rc = {rc_lp:.3f}   DP rc = {rc_dp:.3f}   |diff| = {abs(rc_lp-rc_dp):.3f}")
    # independent check: reduced cost recomputed via master formula on the LP column
    print("LP column rc via master formula:", round(reduced_cost(col_lp, sol, inst), 3))
    chg = np.where(col_lp.e > 1e-6)[0]; dis = np.where(col_lp.e < -1e-6)[0]
    print("LP column charges at blocks", list(chg), " discharges at", list(dis))
    print("mu at charge blocks:", np.round(sol.mu[chg], 2), " mu at discharge blocks:", np.round(sol.mu[dis], 2))
