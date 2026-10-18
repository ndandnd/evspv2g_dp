"""Copy of the frozen pricing DP core (cyclic/full-recharge mode only) with a
rounding switch and route-trace recording. The frozen file
experiments/opte_equal_mip_20261015/runtime/frozen/vendor/pricing_truck.py is
NOT modified; this module is swapped in at run time via colgen.price_truck_dp.

rounding="nearest"      : identical index rules to the frozen DP
                          (rate floor, traction int(round(x/step)), nL=round(G/step)+1)
rounding="conservative" : traction ceil(x/step), rate floor, capacity floor
                          (traction is never under-counted, but the recorded grid
                          profile can push the exact SoC above G: at a 20 kWh step
                          all 1,715 columns did. replay() clips that charge and
                          reports feasibility AFTER clipping; see
                          dp_cols_need_charge_clip in sweep_results.json)
"""
from __future__ import annotations
import math
import numpy as np
from master import Column

INF = np.inf


def _idx(x, step, rounding):
    if rounding == "nearest":
        return int(round(x / step))
    return int(math.ceil(x / step - 1e-9))


def make_pricer(rounding: str):
    def price(inst, alpha, mu, step=None, tol=1e-6, allow_charge=True, allow_discharge=True,
              ice=False, nu=None, soc_mode="cyclic"):
        assert soc_mode == "cyclic" and not ice
        return _core(inst, alpha, mu, step=step, tol=tol, allow_charge=allow_charge,
                     allow_discharge=allow_discharge, nu=nu, rounding=rounding)
    return price


def _core(inst, alpha, mu, step=None, tol=1e-6, allow_charge=True, allow_discharge=True,
          nu=None, rounding="nearest"):
    if step is None:
        step = getattr(inst, "soc_step", 5.0)
    T = inst.T
    eta, rho, G = inst.eta, inst.rho, inst.G
    eps = inst.eps_pen
    epd = inst.energy_per_dist
    origin = inst.depot
    nLoc = inst.dist.shape[0]
    if rounding == "nearest":
        nL = int(round(G / step)) + 1
        up = int(np.floor((1 - eta) * rho / step))
        dn = int(np.floor(rho / step))
    else:
        nL = int(math.floor(G / step + 1e-9)) + 1
        up = int(math.floor((1 - eta) * rho / step + 1e-9))
        dn = int(math.floor(rho / step + 1e-9))
    Gidx = nL - 1
    if nu is None:
        nu = np.zeros(T)
    slope_c = (mu + nu + eps) * step / (1 - eta)
    deg = getattr(inst, "deg_cost", 0.0)
    slope_d = (eps + deg - mu) * step

    dd_time = np.zeros((nLoc, nLoc), dtype=int)
    de_idx = np.zeros((nLoc, nLoc), dtype=int)
    for a_ in range(nLoc):
        for b_ in range(nLoc):
            dd_time[a_, b_] = int(round(inst.dist[a_, b_]))
            de_idx[a_, b_] = _idx(inst.dist[a_, b_] * epd, step, rounding)
    trips_at = {}
    eps_idx = {}
    for tr in inst.trips:
        trips_at.setdefault((tr.start, tr.sloc), []).append(tr)
        eps_idx[tr.idx] = _idx(tr.energy, step, rounding)

    si0 = Gidx
    dp = np.full((T + 1, nLoc, nL, 2), INF)
    dp[0, origin, si0, 0] = 0.0
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

    best_si = Gidx
    best = dp[T, origin, Gidx, 1]
    rc = inst.c_v + best
    if not np.isfinite(best) or rc >= -tol:
        return []

    e_prof = np.zeros(T); a = np.zeros(inst.n_trips)
    trace = []                                # backward list of events
    trips_end = {}
    for tr in inst.trips:
        trips_end.setdefault((tr.end, tr.eloc), []).append(tr)
    t, loc, si, k = T, origin, best_si, 1
    guard = 0
    while not (t == 0 and loc == origin and si == si0 and k == 0) and guard < 12 * T:
        guard += 1
        v = dp[t, loc, si, k]; found = False
        if t >= 1 and abs(dp[t - 1, loc, si, k] - v) < 1e-5:
            t = t - 1; found = True; continue
        if loc in stations and t >= 1:
            if allow_charge:
                for d in range(1, up + 1):
                    pi = si - d
                    if pi >= 0 and abs(dp[t - 1, loc, pi, k] + slope_c[t - 1] * d - v) < 1e-5:
                        e = (d * step) / (1 - eta)
                        e_prof[t - 1] += e; trace.append(("grid", t - 1, loc, e))
                        t, si = t - 1, pi; found = True; break
            if not found and allow_discharge:
                for d in range(1, dn + 1):
                    pi = si + d
                    if pi < nL and abs(dp[t - 1, loc, pi, k] + slope_d[t - 1] * d - v) < 1e-5:
                        e = -(d * step)
                        e_prof[t - 1] += e; trace.append(("grid", t - 1, loc, e))
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
                        a[tr.idx] = 1.0; trace.append(("task", tr.start, tr.idx, float(tr.energy)))
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
                trace.append(("dead", pt, (fl, loc), float(inst.dist[fl, loc] * epd)))
                t, loc, si = pt, fl, pi; found = True; break
        if not found:
            break
    complete = (t == 0 and loc == origin and si == si0 and k == 0)
    dis_total = float(np.maximum(-e_prof, 0.0).sum())
    col = Column("truck", a, e_prof, inst.c_v + deg * dis_total, f"truck[{int(a.sum())}trips]")
    col.trace = list(reversed(trace))
    col.trace_complete = complete
    col.rounding = rounding
    return [(col, rc)]


def replay(inst, col, tol=1e-7):
    """Physical replay of a DP column with exact task/deadhead energies.

    Continuous SoC starts at G (full recharge), must stay in [0, G], must end at G,
    and every grid action must satisfy |e| <= rho. Charging that would push SoC
    above G is clipped (a cheaper, dominated repair: less grid draw); the clipped
    amount is reported. A column is physically feasible after repair iff the SoC
    never goes negative, the rate holds and the terminal SoC equals G.
    Every DP arc advances time, so a single route never has two events that
    start in the same block; ordering by start block is exact.
    """
    if not getattr(col, "trace_complete", False):
        return {"ok": None, "reason": ["trace_incomplete"]}
    G = inst.G; s = G; min_s = s; max_rate = 0.0; clipped = 0.0
    for ev in sorted(col.trace, key=lambda ev: ev[1]):
        if ev[0] == "grid":
            e = ev[3]
            max_rate = max(max_rate, abs(e))
            if e > 0:
                gain = (1 - inst.eta) * e
                room = max(G - s, 0.0)
                if gain > room + tol:
                    clipped += gain - room
                    gain = room
                s += gain
            else:
                s += e
        else:
            s -= ev[3]
        min_s = min(min_s, s)
    reasons = [r for r, bad in (("negative_soc", min_s < -tol),
                                ("terminal_shortfall", s < G - tol),
                                ("rate", max_rate > inst.rho + tol)) if bad]
    return {"ok": not reasons, "reason": reasons, "clipped_kwh": clipped * 100,
            "final_kwh": s * 100, "min_soc_kwh": min_s * 100,
            "shortfall_kwh": max(G - s, 0.0) * 100,
            "ok_without_repair": (not reasons) and clipped <= tol}


def repaired_profile(inst, col, tol=1e-7):
    """Grid profile after clipping charge that would push exact SoC above G."""
    G = inst.G; s = G; e_new = np.zeros(inst.T)
    for ev in sorted(col.trace, key=lambda ev: ev[1]):
        if ev[0] == "grid":
            e = ev[3]
            if e > 0:
                gain = min((1 - inst.eta) * e, max(G - s, 0.0))
                s += gain; e_new[ev[1]] += gain / (1 - inst.eta)
            else:
                s += e; e_new[ev[1]] += e
        else:
            s -= ev[3]
    return e_new


def make_repaired_pricer():
    """Conservative lattice DP; each returned column carries the physically exact
    (clipped) grid profile instead of the lattice profile."""
    base = make_pricer("conservative")

    def price(inst, alpha, mu, **kw):
        out = []
        for col, rc in base(inst, alpha, mu, **kw):
            e = repaired_profile(inst, col)
            dis = float(np.maximum(-e, 0.0).sum())
            new = Column("truck", col.a, e, inst.c_v + getattr(inst, "deg_cost", 0.0) * dis, col.label + "|rep")
            new.trace = [ev if ev[0] != "grid" else ("grid", ev[1], ev[2], float(e[ev[1]])) for ev in col.trace]
            new.trace_complete = col.trace_complete
            out.append((new, rc))
        return out
    return price
