"""
Truck-route pricing by a label-setting dynamic program (the methodological centerpiece).

Time-space-state-of-charge DAG; state = (time t, location loc, SoC level s). Forward
pass is exact (DAG handles the negative arc costs from coverage rewards -alpha and
discharge rewards that Dijkstra could not). Dense numpy with vectorized charge/discharge
relaxations; exact-label backward reconstruction without stored parents.

Arcs out of (t, loc, s), t < T:
  wait      : (t+1, loc, s)                    cost 0
  charge/dis: (t+1, h, s')  [h in H0]          cost mu_t e + eps|e|,  s' = s + (1-eta)charge - discharge
  travel    : (t+dist, loc2, s - dist*epd)     cost 0
  trip j    : (te_j, eloc_j, s - eps_j)        cost -alpha_j   (only at (ts_j, sloc_j))
Terminal: t == T, loc == origin.  Route reduced cost = c_v + accumulated cost.
H0 = inst.charge_locs (default: the depot alone -- the single-station special
case; the copper-plate bus keeps the energy profile e_prof global either way).
"""
from __future__ import annotations
import numpy as np
from instance import Instance
from master import Column
from pricing_contract import (checked_prepared, prepare_pricing, grid_index,
                              validate_duals, check_reconstructed_cost)

INF = np.inf


def price_truck_dp(inst: Instance, alpha: np.ndarray, mu: np.ndarray,
                   step: float = None, tol: float = 1e-6,
                   allow_charge: bool = True, allow_discharge: bool = True,
                   ice: bool = False, nu: np.ndarray = None, soc_mode: str = "cyclic",
                   *, prepared=None, use_cache: bool = True):
    """Mode flags:
       ice=True            -> ICE truck: no grid coupling, traction is fuel (energy
                              constraints disabled), pure time-feasible coverage (VSP).
       allow_discharge=False -> EV with charge-only (no V2G), as in EVSP-Solar.
       soc_mode="periodic" -> steady-state convention s0 = sT with the repeated level
                              free: the core DP runs once per start level and the best
                              negative-reduced-cost candidates over all levels are
                              returned (full-recharge s0 = sT = G is the special case
                              of the single top level).
    """
    prepared = checked_prepared(inst, step, ice, prepared, use_cache)
    alpha, mu, nu = validate_duals(inst, alpha, mu, nu)
    if not np.isfinite(tol) or tol < 0:
        raise ValueError("pricing tol must be finite and nonnegative")
    if soc_mode not in ("cyclic", "free", "periodic") and not soc_mode.startswith("pin"):
        raise ValueError(f"unknown SoC boundary mode: {soc_mode}")
    if soc_mode == "periodic":
        nL = prepared.nlevels
        out = []
        for s0 in range(nL):
            out += _price_truck_dp_core(inst, alpha, mu, step=step, tol=tol,
                                        allow_charge=allow_charge,
                                        allow_discharge=allow_discharge, ice=ice,
                                        nu=nu, soc_mode="periodic", s0_idx=s0, prepared=prepared)
        return sorted(out, key=lambda cr: cr[1])
    if soc_mode.startswith("pin"):
        # pinned steady state s0 = sT = c for a FIXED level c (model units in
        # the mode string, e.g. "pin3.5"): one core sweep, i.e. the single-level
        # special case of the periodic loop above (cheap boundary comparison)
        st = prepared.step
        kwh = float(soc_mode[3:])
        s0 = grid_index(kwh, st, "pinned SoC")
        if not (0 <= kwh <= inst.G):
            raise ValueError(f"pinned level {kwh} not on the {st} SoC grid")
        return _price_truck_dp_core(inst, alpha, mu, step=step, tol=tol,
                                    allow_charge=allow_charge,
                                    allow_discharge=allow_discharge, ice=ice,
                                    nu=nu, soc_mode="periodic", s0_idx=s0, prepared=prepared)
    return _price_truck_dp_core(inst, alpha, mu, step=step, tol=tol,
                                allow_charge=allow_charge,
                                allow_discharge=allow_discharge, ice=ice,
                                nu=nu, soc_mode=soc_mode, s0_idx=None, prepared=prepared)


def _price_truck_dp_core(inst: Instance, alpha: np.ndarray, mu: np.ndarray,
                         step: float = None, tol: float = 1e-6,
                         allow_charge: bool = True, allow_discharge: bool = True,
                         ice: bool = False, nu: np.ndarray = None,
                         soc_mode: str = "cyclic", s0_idx: int = None, prepared=None):
    # Public entry validates the identity once, including for periodic sweeps.
    if prepared is None:
        prepared = checked_prepared(inst, step, ice)
        alpha, mu, nu = validate_duals(inst, alpha, mu, nu)
    step, T, origin = prepared.step, prepared.T, prepared.origin
    nLoc, nL = prepared.nloc, prepared.nlevels
    Gidx = nL - 1
    eta, eps = inst.eta, inst.eps_pen
    if ice:
        allow_charge = allow_discharge = False
    up, dn = prepared.up, prepared.down
    slope_c = (mu + nu + eps) * step / (1 - eta)
    deg = getattr(inst, "deg_cost", 0.0)
    slope_d = (eps + deg - mu) * step

    # extra binary dimension k in {0,1}: whether the route has covered >=1 trip.
    # The admitted route family requires at least one covered trip. This is a
    # model restriction, not a dominance proof when stationary storage is absent.
    si0 = Gidx if s0_idx is None else int(s0_idx)
    dp = np.full((T + 1, nLoc, nL, 2), INF)
    dp[0, origin, si0, 0] = 0.0

    stations = prepared.stations

    for t in range(T):
        cur = dp[t]                                  # (nLoc, nL, 2)
        np.minimum(dp[t + 1], cur, out=dp[t + 1])    # wait (preserves loc, s, k)
        # charge / discharge at any station h in H0 (preserves k)
        for h in stations:
            o = cur[h]                               # (nL, 2)
            if (allow_charge or allow_discharge) and np.isfinite(o).any():
                cand = np.full((nL, 2), INF)
                if allow_charge:
                    for d in range(1, up + 1):
                        np.minimum(cand[d:], o[:nL - d] + slope_c[t] * d, out=cand[d:])
                if allow_discharge:
                    for d in range(1, dn + 1):
                        np.minimum(cand[:nL - d], o[d:] + slope_d[t] * d, out=cand[:nL - d])
                np.minimum(dp[t + 1, h], cand, out=dp[t + 1, h])
        # travel (deadhead, preserves k)
        for a_ in range(nLoc):
            src = cur[a_]
            if not np.isfinite(src).any():
                continue
            for b_, dd, sh in prepared.outgoing[a_]:
                if t + dd > T:
                    continue
                np.minimum(dp[t + dd, b_, :nL - sh], src[sh:], out=dp[t + dd, b_, :nL - sh])
        # Direct time lookup avoids scanning every trip start group at each block.
        for sl, trs in enumerate(prepared.trips_start[t]):
            if not trs:
                continue
            srcmin = np.minimum(cur[sl, :, 0], cur[sl, :, 1])
            if not np.isfinite(srcmin).any():
                continue
            for tr in trs:
                sh = tr.shift
                np.minimum(dp[tr.end, tr.eloc, :nL - sh, 1], srcmin[sh:] - alpha[tr.idx],
                           out=dp[tr.end, tr.eloc, :nL - sh, 1])

    # terminal: cyclic = return to full SoC (the revised model, no free energy);
    # free = end at any SoC (the original arXiv setting: the full initial charge is free).
    if soc_mode == "free":
        term = dp[T, origin, :, 1]
        best_si = int(np.argmin(term)); best = float(term[best_si])
    elif soc_mode == "periodic":
        best_si = si0                             # end exactly at the (free) start level
        best = dp[T, origin, si0, 1]
    else:
        best_si = Gidx
        best = dp[T, origin, Gidx, 1]
    rc = inst.c_v + best
    if not np.isfinite(best) or rc >= -tol:
        return []

    # Recompute the exact same floating-point arc expression used in the
    # forward minimum. A near-tied, more expensive predecessor is never accepted.
    e_prof = np.zeros(T); a = np.zeros(inst.n_trips)
    t, loc, si, k = T, origin, best_si, 1
    source = (0, origin, si0, 0)
    for _ in range(T + 1):
        if (t, loc, si, k) == source:
            break
        v = dp[t, loc, si, k]; found = False
        if t >= 1 and dp[t - 1, loc, si, k] == v:
            t -= 1
            continue
        if loc in stations and t >= 1:
            if allow_charge:
                for d in range(1, up + 1):
                    pi = si - d
                    if pi >= 0 and dp[t - 1, loc, pi, k] + slope_c[t - 1] * d == v:
                        e_prof[t - 1] = (d * step) / (1 - eta)
                        t, si = t - 1, pi; found = True; break
            if not found and allow_discharge:
                for d in range(1, dn + 1):
                    pi = si + d
                    if pi < nL and dp[t - 1, loc, pi, k] + slope_d[t - 1] * d == v:
                        e_prof[t - 1] = -(d * step)
                        t, si = t - 1, pi; found = True; break
            if found:
                continue
        if k == 1:
            for tr in prepared.trips_end[t][loc]:
                pi = si + tr.shift
                if pi >= nL:
                    continue
                for pk in (0, 1):
                    if dp[tr.start, tr.sloc, pi, pk] - alpha[tr.idx] == v:
                        if a[tr.idx]:
                            raise RuntimeError("pricing reconstruction repeated a trip")
                        a[tr.idx] = 1.0
                        t, loc, si, k = tr.start, tr.sloc, pi, pk
                        found = True; break
                if found:
                    break
            if found:
                continue
        for fl, dd, sh in prepared.incoming[loc]:
            pt, pi = t - dd, si + sh
            if pt >= 0 and pi < nL and dp[pt, fl, pi, k] == v:
                t, loc, si = pt, fl, pi; found = True; break
        if not found:
            raise RuntimeError(f"pricing reconstruction has no exact predecessor at {(t, loc, si, k)}")
    if (t, loc, si, k) != source:
        raise RuntimeError("pricing reconstruction did not reach its exact source")
    dis_total = float(np.maximum(-e_prof, 0.0).sum())
    col = Column("truck", a, e_prof, inst.c_v + deg * dis_total,   # degradation folded into
                 f"truck[{int(a.sum())}trips]")                    # the column fixed cost
    terms = (col.cost(eps), -float(a @ alpha), float(e_prof @ mu),
             float(np.maximum(e_prof, 0) @ nu))
    direct = sum(terms)
    check_reconstructed_cost(rc, direct, terms, T)
    return [(col, float(rc))]


def _dp_cost_via_networkx(inst, alpha, mu, step=5.0, soc_mode="cyclic"):
    """Independent shortest-path on the same DAG (Bellman-Ford) -- coding cross-check."""
    import networkx as nx
    prepared = checked_prepared(inst, step)
    T = inst.T; eta, rho, G = inst.eta, inst.rho, inst.G
    eps = inst.eps_pen; epd = inst.energy_per_dist; origin = inst.depot
    nLoc = inst.dist.shape[0]; nL = int(round(G / step)) + 1
    def sidx(v): return int(round(v / step))
    Gidx = nL - 1
    up, dn = prepared.up, prepared.down
    trips_at = {}
    for tr in inst.trips:
        trips_at.setdefault((tr.start, tr.sloc), []).append(tr)
    stations = list(getattr(inst, "charge_locs", None) or [origin])
    # node = (t, loc, si, k); k = 1 once >= 1 trip is covered (mirrors the DP's
    # requirement that a deployed truck covers at least one task)
    Gr = nx.DiGraph(); SRC = ("S",); SNK = ("K",)

    def _add(u, v, w):
        # DiGraph.add_edge overwrites: parallel transitions (e.g. two trips with
        # the same state move, or a trip colliding with a relocation) must keep
        # the MINIMUM weight, as the production DP does.
        d = Gr.get_edge_data(u, v)
        if d is None or w < d["weight"]:
            Gr.add_edge(u, v, weight=w)

    _add(SRC, (0, origin, Gidx, 0), 0.0)
    for t in range(T):
        for loc in range(nLoc):
            for si in range(nL):
                for k in (0, 1):
                    u = (t, loc, si, k); s = si * step
                    _add(u, (t + 1, loc, si, k), 0.0)
                    if loc in stations:
                        for dl in range(-dn, up + 1):
                            sj = si + dl
                            if sj < 0 or sj >= nL: continue
                            ds = dl * step
                            e = ds / (1 - eta) if ds >= 0 else ds
                            _add(u, (t + 1, loc, sj, k), mu[t] * e + eps * abs(e) + getattr(inst, "deg_cost", 0.0) * max(-e, 0.0))
                    for loc2 in range(nLoc):
                        if loc2 == loc: continue
                        dd = int(round(inst.dist[loc, loc2]))
                        if dd <= 0 or t + dd > T: continue
                        s2 = s - inst.dist[loc, loc2] * epd
                        if s2 < -1e-9: continue
                        _add(u, (t + dd, loc2, sidx(s2), k), 0.0)
                    for tr in trips_at.get((t, loc), []):
                        s2 = s - tr.energy
                        if s2 < -1e-9 or tr.end > T: continue
                        _add(u, (tr.end, tr.eloc, sidx(s2), 1), -alpha[tr.idx])
    if soc_mode == "free":
        for si in range(nL):
            if (T, origin, si, 1) in Gr:
                Gr.add_edge((T, origin, si, 1), SNK, weight=0.0)
    else:                                       # cyclic full recharge: terminal s = G only
        if (T, origin, Gidx, 1) in Gr:
            Gr.add_edge((T, origin, Gidx, 1), SNK, weight=0.0)
    return inst.c_v + nx.bellman_ford_path_length(Gr, SRC, SNK)


def _dp_cost_via_networkx_periodic(inst, alpha, mu, step=5.0, nu=None,
                                   allow_discharge=True):
    """Independent periodic (s0 = sT free) check: min over repeated start levels
    of the per-level full-recharge-style graph with start = end = s0."""
    best = INF
    nL = checked_prepared(inst, step).nlevels
    for s0 in range(nL):
        v = _dp_cost_via_networkx_at(inst, alpha, mu, step=step, s0=s0, nu=nu,
                                     allow_discharge=allow_discharge)
        best = min(best, v)
    return best


def _dp_cost_via_networkx_at(inst, alpha, mu, step=5.0, s0=None, nu=None,
                             allow_discharge=True, soc_mode="cyclic"):
    """Bellman-Ford cross-check with explicit start level s0 (defaults to full).
    Terminal: cyclic/periodic-at-s0 fixes the terminal to s0; soc_mode="free"
    starts full and accepts any terminal level (the free-start diagnostic)."""
    import networkx as nx
    prepared = checked_prepared(inst, step)
    T = inst.T; eta, rho, G = inst.eta, inst.rho, inst.G
    eps = inst.eps_pen; epd = inst.energy_per_dist; origin = inst.depot
    nLoc = inst.dist.shape[0]; nL = int(round(G / step)) + 1
    if nu is None:
        nu = np.zeros(T)
    def sidx(v): return int(round(v / step))
    Gidx = nL - 1
    si0 = Gidx if s0 is None else int(s0)
    up, dn = prepared.up, prepared.down
    if not allow_discharge:
        dn = 0
    trips_at = {}
    for tr in inst.trips:
        trips_at.setdefault((tr.start, tr.sloc), []).append(tr)
    stations = list(getattr(inst, "charge_locs", None) or [origin])
    Gr = nx.DiGraph(); SRC = ("S",); SNK = ("K",)

    def _add(u, v, w):
        # keep the MIN over parallel transitions (DiGraph.add_edge overwrites)
        d = Gr.get_edge_data(u, v)
        if d is None or w < d["weight"]:
            Gr.add_edge(u, v, weight=w)

    _add(SRC, (0, origin, si0, 0), 0.0)
    for t in range(T):
        for loc in range(nLoc):
            for si in range(nL):
                for k in (0, 1):
                    u = (t, loc, si, k); s = si * step
                    _add(u, (t + 1, loc, si, k), 0.0)
                    if loc in stations:
                        for dl in range(-dn, up + 1):
                            if dl == 0:
                                continue
                            sj = si + dl
                            if sj < 0 or sj >= nL:
                                continue
                            ds = dl * step
                            e = ds / (1 - eta) if ds >= 0 else ds
                            w = mu[t] * e + eps * abs(e) + getattr(inst, "deg_cost", 0.0) * max(-e, 0.0)
                            if ds >= 0:
                                w += nu[t] * e
                            _add(u, (t + 1, loc, sj, k), w)
                    for loc2 in range(nLoc):
                        if loc2 == loc:
                            continue
                        dd = int(round(inst.dist[loc, loc2]))
                        if dd <= 0 or t + dd > T:
                            continue
                        s2 = s - inst.dist[loc, loc2] * epd
                        if s2 < -1e-9:
                            continue
                        _add(u, (t + dd, loc2, sidx(s2), k), 0.0)
                    for tr in trips_at.get((t, loc), []):
                        s2 = s - tr.energy
                        if s2 < -1e-9 or tr.end > T:
                            continue
                        _add(u, (tr.end, tr.eloc, sidx(s2), 1), -alpha[tr.idx])
    if soc_mode == "free":
        for si in range(nL):
            if (T, origin, si, 1) in Gr:
                _add((T, origin, si, 1), SNK, 0.0)
    elif (T, origin, si0, 1) in Gr:
        _add((T, origin, si0, 1), SNK, 0.0)
    try:
        return inst.c_v + nx.bellman_ford_path_length(Gr, SRC, SNK)
    except nx.NetworkXNoPath:
        return INF


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
