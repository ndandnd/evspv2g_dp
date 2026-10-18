"""Pricing DP on a SoC grid with an explicit rounding rule (full-recharge mode).

This is a copy of the frozen cyclic pricing core
(experiments/opte_equal_mip_20261015/runtime/frozen/vendor/pricing_truck.py,
_price_truck_dp_core with soc_mode="cyclic", ice=False), via the 15 Oct copy
output/opte-corollary1-check-20261015/dp_variants.py. Neither file is modified.
It is swapped in at run time through colgen.price_truck_dp.

Two rules:

rule="nearest"  : the frozen index rules, unchanged.
    levels      nL = round(G/step) + 1
    charge      up = floor((1-eta) rho / step)   (SoC gained per block)
    discharge   dn = floor(rho / step)
    traction    round(x/step)   (Python round: exact halves go to the even integer,
                                 so 50 kWh at a 20 kWh step -> round(2.5) = 2 -> 40 kWh)
    start/end   top level (full)

rule="conservative" : every energy quantity is rounded in the safe direction.
    energy used by a task or deadhead   ceil(x/step)              (UP)
    SoC gained by charging in a block   floor((1-eta) rho/step)    (DOWN)
    energy discharged in a block        floor(rho/step)            (DOWN: limit; the
                                         amount taken from the battery is exactly the
                                         grid amount, d*step, so nothing is hidden)
    usable capacity                     floor(G/step)              (DOWN)
    minimum SoC (reserve)               ceil(s_min/step)           (UP; s_min = 0 here)
    initial SoC                         floor(s_0/step)            (DOWN; s_0 = G here)
    required final SoC                  ceil(s_end/step)           (UP; s_end = G here)
    travel time / task times            unchanged (already whole blocks; no rounding)
  The full-recharge convention needs ceil(G/step) <= floor(G/step), i.e. G on the
  grid; otherwise a grid path cannot certify a physically full battery and the
  function raises ValueError instead of silently weakening the boundary.

Physical meaning of a conservative grid plan (see replay.py): follow the route,
discharge exactly the grid amount, and charge the grid amount but stop when the
battery is full. The real SoC then never falls below the grid SoC.

Each returned column carries a full event trace (kind, start, end, from, to,
task, grid amount, grid level before/after) for independent replay.
"""
from __future__ import annotations
import math
import numpy as np
from master import Column

INF = np.inf
TOL = 1e-9


def grid_spec(inst, step, rule):
    """Index rules for one (instance, step, rule). Returns a dict of grid levels and
    shifts plus a human-readable record of how each true quantity was mapped."""
    G, rho, eta, epd = inst.G, inst.rho, inst.eta, inst.energy_per_dist
    s_min = float(getattr(inst, "soc_min", 0.0))
    s_start = s_end = G                                   # full recharge
    nLoc = inst.dist.shape[0]
    if rule == "nearest":
        nL = int(round(G / step)) + 1
        up = int(np.floor((1 - eta) * rho / step))
        dn = int(np.floor(rho / step))
        trac = lambda x: int(round(x / step))
        Lmin, L0, Lend = 0, nL - 1, nL - 1
    elif rule == "conservative":
        nL = int(math.floor(G / step + TOL)) + 1
        up = int(math.floor((1 - eta) * rho / step + TOL))
        dn = int(math.floor(rho / step + TOL))
        trac = lambda x: int(math.ceil(x / step - TOL))
        Lmin = int(math.ceil(s_min / step - TOL))
        L0 = int(math.floor(s_start / step + TOL))
        Lend = int(math.ceil(s_end / step - TOL))
        if Lend > nL - 1 or L0 > nL - 1:
            raise ValueError("full-recharge level is off the grid; conservative grid "
                             "cannot certify a physically full battery")
    else:
        raise ValueError(rule)
    de_idx = np.zeros((nLoc, nLoc), dtype=int)
    dd_time = np.zeros((nLoc, nLoc), dtype=int)
    for a in range(nLoc):
        for b in range(nLoc):
            dd_time[a, b] = int(round(inst.dist[a, b]))
            de_idx[a, b] = trac(inst.dist[a, b] * epd)
    task_idx = {tr.idx: trac(tr.energy) for tr in inst.trips}
    # record of the mapping, in kWh (model unit = 100 kWh)
    dead_map = sorted({(round(inst.dist[a, b] * epd * 100, 6), round(de_idx[a, b] * step * 100, 6))
                       for a in range(nLoc) for b in range(nLoc) if a != b})
    task_map = sorted({(round(tr.energy * 100, 6), round(task_idx[tr.idx] * step * 100, 6))
                       for tr in inst.trips})
    record = {
        "rule": rule, "step_kwh": step * 100,
        "capacity_kwh": [G * 100, (nL - 1) * step * 100],
        "charge_gain_per_block_kwh": [(1 - eta) * rho * 100, up * step * 100],
        "discharge_per_block_kwh": [rho * 100, dn * step * 100],
        "min_soc_kwh": [s_min * 100, Lmin * step * 100],
        "initial_soc_kwh": [s_start * 100, L0 * step * 100],
        "final_soc_kwh": [s_end * 100, Lend * step * 100],
        "deadhead_kwh_true_to_grid": dead_map,
        "task_kwh_true_to_grid": task_map,
    }
    return dict(nL=nL, up=up, dn=dn, Lmin=Lmin, L0=L0, Lend=Lend, de_idx=de_idx,
                dd_time=dd_time, task_idx=task_idx, record=record)


def make_pricer(rule: str):
    def price(inst, alpha, mu, step=None, tol=1e-6, allow_charge=True, allow_discharge=True,
              ice=False, nu=None, soc_mode="cyclic"):
        assert soc_mode == "cyclic" and not ice
        return _core(inst, alpha, mu, step=step, tol=tol, allow_charge=allow_charge,
                     allow_discharge=allow_discharge, nu=nu, rule=rule)
    return price


def _core(inst, alpha, mu, step=None, tol=1e-6, allow_charge=True, allow_discharge=True,
          nu=None, rule="nearest"):
    if step is None:
        step = getattr(inst, "soc_step", 5.0)
    spec = grid_spec(inst, step, rule)
    T = inst.T
    eta = inst.eta
    eps = inst.eps_pen
    origin = inst.depot
    nLoc = inst.dist.shape[0]
    nL, up, dn = spec["nL"], spec["up"], spec["dn"]
    Lmin, L0, Lend = spec["Lmin"], spec["L0"], spec["Lend"]
    dd_time, de_idx, eps_idx = spec["dd_time"], spec["de_idx"], spec["task_idx"]
    if nu is None:
        nu = np.zeros(T)
    slope_c = (mu + nu + eps) * step / (1 - eta)
    deg = getattr(inst, "deg_cost", 0.0)
    slope_d = (eps + deg - mu) * step

    trips_at = {}
    for tr in inst.trips:
        trips_at.setdefault((tr.start, tr.sloc), []).append(tr)

    dp = np.full((T + 1, nLoc, nL, 2), INF)
    dp[0, origin, L0, 0] = 0.0
    stations = list(getattr(inst, "charge_locs", None) or [origin])

    for t in range(T):
        cur = dp[t]
        np.minimum(dp[t + 1], cur, out=dp[t + 1])
        for h in stations:
            o = cur[h]
            if (allow_charge or allow_discharge) and np.isfinite(o).any():
                cand = np.full((nL, 2), INF)
                if allow_charge:
                    for d in range(1, up + 1):
                        np.minimum(cand[d:], o[:nL - d] + slope_c[t] * d, out=cand[d:])
                if allow_discharge:
                    for d in range(1, dn + 1):
                        np.minimum(cand[:nL - d], o[d:] + slope_d[t] * d, out=cand[:nL - d])
                np.minimum(dp[t + 1, h], cand, out=dp[t + 1, h])
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
        for (st, sl), trs in trips_at.items():
            if st != t:
                continue
            srcmin = np.minimum(cur[sl, :, 0], cur[sl, :, 1])
            if not np.isfinite(srcmin).any():
                continue
            for tr in trs:
                sh = eps_idx[tr.idx]
                if tr.end > T or sh >= nL:
                    continue
                np.minimum(dp[tr.end, tr.eloc, :nL - sh, 1], srcmin[sh:] - alpha[tr.idx],
                           out=dp[tr.end, tr.eloc, :nL - sh, 1])
        if Lmin > 0:                                   # reserve: levels below Lmin forbidden
            dp[t + 1, :, :Lmin, :] = INF

    # terminal: at the depot, at least the required final level, k = 1
    term = dp[T, origin, Lend:, 1]
    if not np.isfinite(term).any():
        return []
    best_si = Lend + int(np.argmin(term))
    best = dp[T, origin, best_si, 1]
    rc = inst.c_v + best
    if rc >= -tol:
        return []

    e_prof = np.zeros(T); a = np.zeros(inst.n_trips)
    trace = []
    trips_end = {}
    for tr in inst.trips:
        trips_end.setdefault((tr.end, tr.eloc), []).append(tr)
    t, loc, si, k = T, origin, best_si, 1
    guard = 0
    while not (t == 0 and loc == origin and si == L0 and k == 0) and guard < 12 * T:
        guard += 1
        v = dp[t, loc, si, k]; found = False
        if t >= 1 and abs(dp[t - 1, loc, si, k] - v) < 1e-5:
            t = t - 1; continue
        if loc in stations and t >= 1:
            if allow_charge:
                for d in range(1, up + 1):
                    pi = si - d
                    if pi >= 0 and abs(dp[t - 1, loc, pi, k] + slope_c[t - 1] * d - v) < 1e-5:
                        e = (d * step) / (1 - eta)
                        e_prof[t - 1] += e
                        trace.append(dict(kind="grid", start=t - 1, end=t, frm=int(loc), to=int(loc),
                                          grid=float(e), lev_before=int(pi), lev_after=int(si)))
                        t, si = t - 1, pi; found = True; break
            if not found and allow_discharge:
                for d in range(1, dn + 1):
                    pi = si + d
                    if pi < nL and abs(dp[t - 1, loc, pi, k] + slope_d[t - 1] * d - v) < 1e-5:
                        e = -(d * step)
                        e_prof[t - 1] += e
                        trace.append(dict(kind="grid", start=t - 1, end=t, frm=int(loc), to=int(loc),
                                          grid=float(e), lev_before=int(pi), lev_after=int(si)))
                        t, si = t - 1, pi; found = True; break
            if found:
                continue
        if k == 1:
            for tr in trips_end.get((t, loc), []):
                pi = si + eps_idx[tr.idx]
                if pi >= nL:
                    continue
                for pk in (0, 1):
                    if abs(dp[tr.start, tr.sloc, pi, pk] - alpha[tr.idx] - v) < 1e-5:
                        a[tr.idx] = 1.0
                        trace.append(dict(kind="task", start=int(tr.start), end=int(tr.end),
                                          frm=int(tr.sloc), to=int(tr.eloc), task=int(tr.idx),
                                          lev_before=int(pi), lev_after=int(si)))
                        t, loc, si, k = tr.start, tr.sloc, pi, pk
                        found = True; break
                if found:
                    break
            if found:
                continue
        for fl in range(nLoc):
            if fl == loc:
                continue
            dd = dd_time[fl, loc]; sh = de_idx[fl, loc]; pt = t - dd; pi = si + sh
            if pt >= 0 and pi < nL and dd > 0 and abs(dp[pt, fl, pi, k] - v) < 1e-5:
                trace.append(dict(kind="dead", start=int(pt), end=int(t), frm=int(fl), to=int(loc),
                                  lev_before=int(pi), lev_after=int(si)))
                t, loc, si = pt, fl, pi; found = True; break
        if not found:
            break
    complete = (t == 0 and loc == origin and si == L0 and k == 0)
    dis_total = float(np.maximum(-e_prof, 0.0).sum())
    col = Column("truck", a, e_prof, inst.c_v + deg * dis_total, f"truck[{int(a.sum())}trips]")
    col.trace = list(reversed(trace))
    col.trace_complete = complete
    col.rule = rule
    col.step = step
    col.end_level = int(best_si)
    return [(col, rc)]
