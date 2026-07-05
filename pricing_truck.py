"""
Truck-route pricing by a label-setting dynamic program (the methodological centerpiece).

Time-space-state-of-charge DAG; state = (time t, location loc, SoC level s). Forward
pass is exact (DAG handles the negative arc costs from coverage rewards -alpha and
discharge rewards that Dijkstra could not). Dense numpy with vectorized charge/discharge
relaxations; backward reconstruction without stored parents.

Arcs out of (t, loc, s), t < T:
  wait      : (t+1, loc, s)                    cost 0
  charge/dis: (t+1, origin, s')  [origin]      cost mu_t e + eps|e|,  s' = s + (1-eta)charge - discharge
  travel    : (t+dist, loc2, s - dist*epd)     cost 0
  trip j    : (te_j, eloc_j, s - eps_j)        cost -alpha_j   (only at (ts_j, sloc_j))
Terminal: t == T, loc == origin.  Route reduced cost = c_v + accumulated cost.
"""
from __future__ import annotations
import numpy as np
from instance import Instance
from master import Column

INF = np.inf


def price_truck_dp(inst: Instance, alpha: np.ndarray, mu: np.ndarray,
                   step: float = None, tol: float = 1e-6,
                   allow_charge: bool = True, allow_discharge: bool = True,
                   ice: bool = False, nu: np.ndarray = None, soc_mode: str = "cyclic"):
    """Mode flags:
       ice=True            -> ICE truck: no grid coupling, traction is fuel (energy
                              constraints disabled), pure time-feasible coverage (VSP).
       allow_discharge=False -> EV with charge-only (no V2G), as in EVSP-Solar.
    """
    if step is None:                                 # per-instance SoC lattice (default 5 kWh)
        step = getattr(inst, "soc_step", 5.0)
    T = inst.T
    eta, rho, G = inst.eta, inst.rho, inst.G
    eps = inst.eps_pen
    epd = inst.energy_per_dist
    origin = inst.depot
    nLoc = inst.dist.shape[0]
    nL = int(round(G / step)) + 1
    Gidx = nL - 1
    if ice:                                          # ICE: energy non-binding, no charge/discharge
        allow_charge = allow_discharge = False
        epd = 0.0
    up = int(np.floor((1 - eta) * rho / step))      # max SoC-up levels per charge block
    dn = int(np.floor(rho / step))                  # max SoC-down levels per discharge block

    if nu is None:
        nu = np.zeros(T)
    slope_c = (mu + nu + eps) * step / (1 - eta)     # charging also pays the charger-capacity price nu
    deg = getattr(inst, "deg_cost", 0.0)             # cycling degradation on discharge
    slope_d = (eps + deg - mu) * step                # cost per -level when discharging, per block

    # deadhead level shifts and time
    dd_time = np.zeros((nLoc, nLoc), dtype=int)
    de_idx = np.zeros((nLoc, nLoc), dtype=int)
    for a_ in range(nLoc):
        for b_ in range(nLoc):
            dd_time[a_, b_] = int(round(inst.dist[a_, b_]))
            de_idx[a_, b_] = int(round(inst.dist[a_, b_] * epd / step))
    trips_at = {}
    eps_idx = {}
    for tr in inst.trips:
        trips_at.setdefault((tr.start, tr.sloc), []).append(tr)
        eps_idx[tr.idx] = 0 if ice else int(round(tr.energy / step))

    # extra binary dimension k in {0,1}: whether the route has covered >=1 trip.
    # A deployed truck is only worthwhile if it covers a trip (pure arbitrage is
    # dominated by a cheaper battery schedule), so the terminal requires k = 1.
    dp = np.full((T + 1, nLoc, nL, 2), INF)
    dp[0, origin, Gidx, 0] = 0.0

    for t in range(T):
        cur = dp[t]                                  # (nLoc, nL, 2)
        np.minimum(dp[t + 1], cur, out=dp[t + 1])    # wait (preserves loc, s, k)
        # charge / discharge at origin (preserves k)
        o = cur[origin]                              # (nL, 2)
        if (allow_charge or allow_discharge) and np.isfinite(o).any():
            cand = np.full((nL, 2), INF)
            if allow_charge:
                for d in range(1, up + 1):
                    np.minimum(cand[d:], o[:nL - d] + slope_c[t] * d, out=cand[d:])
            if allow_discharge:
                for d in range(1, dn + 1):
                    np.minimum(cand[:nL - d], o[d:] + slope_d[t] * d, out=cand[:nL - d])
            np.minimum(dp[t + 1, origin], cand, out=dp[t + 1, origin])
        # travel (deadhead, preserves k)
        for a_ in range(nLoc):
            src = cur[a_]
            if not np.isfinite(src).any():
                continue
            for b_ in range(nLoc):
                if b_ == a_:
                    continue
                dd = dd_time[a_, b_]; sh = de_idx[a_, b_]
                if dd <= 0 or t + dd > T or sh >= nL:
                    continue
                np.minimum(dp[t + dd, b_, :nL - sh], src[sh:], out=dp[t + dd, b_, :nL - sh])
        # trips starting here -> set k = 1
        for (st, sl), trs in trips_at.items():
            if st != t:
                continue
            srcmin = np.minimum(cur[sl, :, 0], cur[sl, :, 1])    # min over incoming k
            if not np.isfinite(srcmin).any():
                continue
            for tr in trs:
                sh = eps_idx[tr.idx]
                if tr.end > T or sh >= nL:
                    continue
                np.minimum(dp[tr.end, tr.eloc, :nL - sh, 1], srcmin[sh:] - alpha[tr.idx],
                           out=dp[tr.end, tr.eloc, :nL - sh, 1])

    # terminal: cyclic = return to full SoC (the revised model, no free energy);
    # free = end at any SoC (the original arXiv setting: the full initial charge is free).
    if soc_mode == "free":
        term = dp[T, origin, :, 1]
        best_si = int(np.argmin(term)); best = float(term[best_si])
    else:
        best_si = Gidx
        best = dp[T, origin, Gidx, 1]
    rc = inst.c_v + best
    if not np.isfinite(best) or rc >= -tol:
        return []

    # ----- backward reconstruction (no stored parents) -----
    e_prof = np.zeros(T); a = np.zeros(inst.n_trips)
    trips_end = {}
    for tr in inst.trips:
        trips_end.setdefault((tr.end, tr.eloc), []).append(tr)
    t, loc, si, k = T, origin, best_si, 1
    guard = 0
    while not (t == 0 and loc == origin and si == Gidx and k == 0) and guard < 12 * T:
        guard += 1
        v = dp[t, loc, si, k]; found = False
        # wait (preserves k)
        if t >= 1 and abs(dp[t - 1, loc, si, k] - v) < 1e-5:
            t = t - 1; found = True; continue
        # charge / discharge (origin, preserves k)
        if loc == origin and t >= 1:
            if allow_charge:
                for d in range(1, up + 1):
                    pi = si - d
                    if pi >= 0 and abs(dp[t - 1, origin, pi, k] + slope_c[t - 1] * d - v) < 1e-5:
                        e_prof[t - 1] += (d * step) / (1 - eta); t, si = t - 1, pi; found = True; break
            if not found and allow_discharge:
                for d in range(1, dn + 1):
                    pi = si + d
                    if pi < nL and abs(dp[t - 1, origin, pi, k] + slope_d[t - 1] * d - v) < 1e-5:
                        e_prof[t - 1] += -(d * step); t, si = t - 1, pi; found = True; break
            if found:
                continue
        # trip ending here (only when k == 1; predecessor k may be 0 or 1)
        if k == 1:
            for tr in trips_end.get((t, loc), []):
                pi = si + eps_idx[tr.idx]
                if pi >= nL:
                    continue
                for pk in (0, 1):
                    if abs(dp[tr.start, tr.sloc, pi, pk] - alpha[tr.idx] - v) < 1e-5:
                        a[tr.idx] = 1.0; t, loc, si, k = tr.start, tr.sloc, pi, pk
                        found = True; break
                if found:
                    break
            if found:
                continue
        # travel ending here (preserves k)
        for fl in range(nLoc):
            if fl == loc:
                continue
            dd = dd_time[fl, loc]; sh = de_idx[fl, loc]; pt = t - dd; pi = si + sh
            if pt >= 0 and pi < nL and dd > 0 and abs(dp[pt, fl, pi, k] - v) < 1e-5:
                t, loc, si = pt, fl, pi; found = True; break
        if not found:
            break
    dis_total = float(np.maximum(-e_prof, 0.0).sum())
    col = Column("truck", a, e_prof, inst.c_v + deg * dis_total,   # degradation folded into
                 f"truck[{int(a.sum())}trips]")                    # the column fixed cost
    return [(col, rc)]


def _dp_cost_via_networkx(inst, alpha, mu, step=5.0):
    """Independent shortest-path on the same DAG (Bellman-Ford) -- coding cross-check."""
    import networkx as nx
    T = inst.T; eta, rho, G = inst.eta, inst.rho, inst.G
    eps = inst.eps_pen; epd = inst.energy_per_dist; origin = inst.depot
    nLoc = inst.dist.shape[0]; nL = int(round(G / step)) + 1
    def sidx(v): return int(round(v / step))
    Gidx = nL - 1
    up = int(np.floor((1 - eta) * rho / step)); dn = int(np.floor(rho / step))
    trips_at = {}
    for tr in inst.trips:
        trips_at.setdefault((tr.start, tr.sloc), []).append(tr)
    Gr = nx.DiGraph(); SRC = ("S",); SNK = ("K",)
    Gr.add_edge(SRC, (0, origin, Gidx), weight=0.0)
    for t in range(T):
        for loc in range(nLoc):
            for si in range(nL):
                u = (t, loc, si); s = si * step
                Gr.add_edge(u, (t + 1, loc, si), weight=0.0)
                if loc == origin:
                    for dl in range(-dn, up + 1):
                        sj = si + dl
                        if sj < 0 or sj >= nL: continue
                        ds = dl * step
                        e = ds / (1 - eta) if ds >= 0 else ds
                        Gr.add_edge(u, (t + 1, origin, sj), weight=mu[t] * e + eps * abs(e))
                for loc2 in range(nLoc):
                    if loc2 == loc: continue
                    dd = int(round(inst.dist[loc, loc2]))
                    if dd <= 0 or t + dd > T: continue
                    s2 = s - inst.dist[loc, loc2] * epd
                    if s2 < -1e-9: continue
                    Gr.add_edge(u, (t + dd, loc2, sidx(s2)), weight=0.0)
                for tr in trips_at.get((t, loc), []):
                    s2 = s - tr.energy
                    if s2 < -1e-9 or tr.end > T: continue
                    Gr.add_edge(u, (tr.end, tr.eloc, sidx(s2)), weight=-alpha[tr.idx])
    for si in range(nL):
        if (T, origin, si) in Gr:
            Gr.add_edge((T, origin, si), SNK, weight=0.0)
    return inst.c_v + nx.bellman_ford_path_length(Gr, SRC, SNK)


if __name__ == "__main__":
    import time
    from instance import make_instance
    from master import solve_lp, reduced_cost
    inst = make_instance(n_trips=8, n_locations=3, eps=2.0, seed=5)
    T = inst.T
    cols = [Column("truck", np.eye(inst.n_trips)[i], np.zeros(T), inst.c_v, f"t{i}")
            for i in range(inst.n_trips)]
    sol = solve_lp(inst, cols)
    t0 = time.time(); out = price_truck_dp(inst, sol.alpha, sol.mu); dt = time.time() - t0
    print(f"truck DP time: {dt:.3f}s")
    if out:
        col, rc = out[0]
        print(f"covers {int(col.a.sum())} trips, rc(DP)={rc:.3f}")
        print(f"  rc via master formula = {reduced_cost(col, sol, inst):.3f}")
        print(f"  rc via Bellman-Ford   = {_dp_cost_via_networkx(inst, sol.alpha, sol.mu):.3f}")
