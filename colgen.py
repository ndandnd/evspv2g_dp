"""
Column generation for the covering-plus-arbitrage EVSP-V2G.

Trucks are priced by the labeling DP (pricing_truck); the stationary battery fleet
is an aggregate block solved inside the RMP, so CG only needs to price trucks
(coverage). Dual stabilization (smoothing) with a true-dual fallback controls the
tail while keeping termination correct.
"""
from __future__ import annotations
import time
import numpy as np
from instance import Instance, make_instance
from master import Column, solve_lp, solve_milp, reduced_cost
from pricing_truck import price_truck_dp


def _col_key(c: Column):
    return (tuple(np.flatnonzero(c.a > 0.5).tolist()), tuple(np.round(c.e, 2).tolist()))


SCENARIOS = {                          # (ice, allow_charge, allow_discharge, battery)
    "vsp":   dict(ice=True,  allow_charge=False, allow_discharge=False, battery=False),
    "ev":    dict(ice=False, allow_charge=True,  allow_discharge=False, battery=False,
                  flat_price=True),     # plain EVSP (original mode 1): solar-blind, every
                                        # charged kWh pays c_g flat; fleet does not touch
                                        # the power balance (energy folded into route cost)
    "solar": dict(ice=False, allow_charge=True,  allow_discharge=False, battery=False),
    "solar_bess": dict(ice=False, allow_charge=True, allow_discharge=False, battery=True),
                                        # charge-only trucks WITH purchasable stationary
                                        # storage -- the missing factorial arm (V1G+BESS)
    "v2g":   dict(ice=False, allow_charge=True,  allow_discharge=True,  battery=True),
    "v2g_fleet": dict(ice=False, allow_charge=True, allow_discharge=True, battery=False),
                                        # V2G-capable fleet at a depot WITHOUT stationary
                                        # storage -- isolates what the fleet alone can do
}


def _flatten_col(col: Column, inst: Instance) -> Column:
    """Flat-price scenario: fold energy cost (c_g per drawn unit) into the fixed
    cost and zero the profile, so the master's balance neither sees nor credits it."""
    draw = float(np.maximum(col.e, 0.0).sum())
    if draw <= 1e-12:
        return col
    return Column(col.kind, col.a, np.zeros(inst.T), col.fixed_cost + inst.c_g * draw,
                  col.label + "|flat")


def single_trip_column(inst: Instance, tr, ice: bool = False, free_start: bool = False) -> Column:
    """Exactly-feasible single-trip truck column. Cyclic: recharge the traction
    energy from the grid during idle at-origin blocks (SoC returns to full, no free
    energy). Free-start (original arXiv setting): the initial full charge is free,
    so no recharge is needed (e = 0). ICE (VSP): traction is fuel, e = 0."""
    a = np.zeros(inst.n_trips); a[tr.idx] = 1.0
    e = np.zeros(inst.T)
    o0 = inst.depot
    if tr.start - inst.deadhead_time(o0, tr.sloc) < 0 or \
       tr.end + inst.deadhead_time(tr.eloc, o0) > inst.T:
        return None                                   # cannot pull out and return in-horizon
    if not ice and not free_start:
        o = inst.depot
        trac = tr.energy + inst.deadhead_energy(o, tr.sloc) + inst.deadhead_energy(tr.eloc, o)
        need = trac / (1 - inst.eta)
        dep = tr.start - inst.deadhead_time(o, tr.sloc)
        ret = tr.end + inst.deadhead_time(tr.eloc, o)
        # AFTER-return blocks only: the vehicle starts FULL, so charging before
        # departure would overfill the battery. A seed is returned ONLY if the
        # trip departs after t=0, returns to the depot within the horizon, and the
        # post-return window can restore the full charge; otherwise the task has
        # no feasible single-trip column and the caller must fall back to a
        # Phase-I artificial column (an infeasible seed must never enter the pool).
        if dep < 0 or ret > inst.T:
            return None
        idle = list(range(min(inst.T, ret), inst.T))
        cap = len(idle) * inst.rho
        if cap < need - 1e-9:
            return None
        if idle:
            if np.isfinite(inst.charge_cap):       # spread uniformly so the initial pool
                per = min(inst.rho, need / len(idle))   # respects the charging cap
                for t in idle:
                    e[t] = per
            else:                                  # no cap: charge at full rate, fewest blocks
                left = need
                for t in idle:
                    if left <= 1e-9:
                        break
                    e[t] = min(inst.rho, left)
                    left -= e[t]
    return Column("truck", a, e, inst.c_v, f"single[{tr.idx}]")


def dp_greedy_columns(inst: Instance, caps: dict, rounds: int = 40, rng=None,
                      soc_mode: str = "cyclic") -> list[Column]:
    """Multi-trip covering columns via repeated DP: reward uncovered trips, forbid
    re-covering already-covered ones, peel off a route each round. With an rng, the
    per-trip reward is randomized so repeated calls yield distinct full covers."""
    cols = []
    remaining = set(range(inst.n_trips))
    mu = np.full(inst.T, 0.0)
    for _ in range(rounds):
        if not remaining:
            break
        alpha = np.full(inst.n_trips, -1e6)
        for i in remaining:
            alpha[i] = (rng.uniform(2.0, 4.0) if rng is not None else 3.0) * inst.c_v
        out = price_truck_dp(inst, alpha, mu, allow_charge=caps["allow_charge"],
                             allow_discharge=caps["allow_discharge"], ice=caps["ice"],
                             soc_mode=soc_mode)
        if not out:
            break
        col = out[0][0]
        covered = set(np.flatnonzero(col.a > 0.5).tolist()) & remaining
        if not covered:
            break
        cols.append(col)
        remaining -= covered
    return cols


ARTIFICIAL_COST = 1e5                    # Phase-I penalty: any selected artificial
                                         # column flags an individually infeasible task

def artificial_column(inst: Instance, tr) -> Column:
    a = np.zeros(inst.n_trips); a[tr.idx] = 1.0
    return Column("artificial", a, np.zeros(inst.T), ARTIFICIAL_COST, label=f"art[{tr.idx}]")


def initial_columns(inst: Instance, start: str, caps: dict,
                    soc_mode: str = "cyclic") -> list[Column]:
    base = []
    for tr in inst.trips:
        c = single_trip_column(inst, tr, ice=caps["ice"], free_start=(soc_mode == "free"))
        base.append(c if c is not None else artificial_column(inst, tr))
    if start == "cold":
        return base
    extra = dp_greedy_columns(inst, caps, soc_mode=soc_mode)
    seen = set(_col_key(c) for c in base)
    return base + [c for c in extra if _col_key(c) not in seen]


def column_generation(inst: Instance, scenario: str = "v2g", start: str = "warm",
                      tol: float = 1e-6, rc_stop: float = 0.0, beta: float = 0.5,
                      max_iter: int = 1000, do_milp: bool = True, verbose: bool = False,
                      enrich: int = 25, lp_solver: str = "highs", milp_solver: str = "cbc",
                      soc_mode: str = "cyclic"):
    caps = SCENARIOS[scenario]
    batt = caps["battery"]
    flat = caps.get("flat_price", False)
    cols = initial_columns(inst, start, caps, soc_mode=soc_mode)
    if flat:
        cols = [_flatten_col(c, inst) for c in cols]
        mu_flat = np.full(inst.T, inst.c_g)   # every charged unit pays c_g, always
    keys = set(_col_key(c) for c in cols)
    t0 = time.time()
    pricing_t = 0.0                       # cumulative DP-pricing wall-clock (for pricing-share stats)
    prev = None
    lp = solve_lp(inst, cols, battery_allowed=batt, solver=lp_solver, soc_mode=soc_mode)
    iters = 0
    stop = max(tol, rc_stop)

    def price(a, m, nv):
        if flat:                               # solar-blind: constant energy price, no nu
            m, nv = mu_flat, np.zeros(inst.T)
        out = price_truck_dp(inst, a, m, allow_charge=caps["allow_charge"],
                             allow_discharge=caps["allow_discharge"], ice=caps["ice"], nu=nv,
                             soc_mode=soc_mode)
        return [(_flatten_col(tc, inst), rc) for tc, rc in out] if flat else out

    for it in range(max_iter):
        iters = it + 1
        lp = solve_lp(inst, cols, battery_allowed=batt, solver=lp_solver, soc_mode=soc_mode)
        if lp.status != "optimal":
            break
        nu_cur = lp.nu if lp.nu is not None else np.zeros(inst.T)
        if prev is None:
            al, mu, nu = lp.alpha, lp.mu, nu_cur
        else:
            al = beta * prev[0] + (1 - beta) * lp.alpha
            mu = beta * prev[1] + (1 - beta) * lp.mu
            nu = beta * prev[2] + (1 - beta) * nu_cur
        prev = (lp.alpha.copy(), lp.mu.copy(), nu_cur.copy())

        added, best_true = 0, 0.0
        tp = time.time(); cand = price(al, mu, nu); pricing_t += time.time() - tp
        for tc, _ in cand:
            rc = reduced_cost(tc, lp, inst); best_true = min(best_true, rc)
            if rc < -stop and _col_key(tc) not in keys:
                cols.append(tc); keys.add(_col_key(tc)); added += 1
        if added == 0:
            tp = time.time(); cand = price(lp.alpha, lp.mu, nu_cur); pricing_t += time.time() - tp
            for tc, _ in cand:
                rc = reduced_cost(tc, lp, inst); best_true = min(best_true, rc)
                if rc < -stop and _col_key(tc) not in keys:
                    cols.append(tc); keys.add(_col_key(tc)); added += 1
        if verbose and (iters % 10 == 0 or added == 0):
            print(f"  it {iters:3d} LP={lp.obj:9.1f} cols={len(cols):4d} best_rc={best_true:8.1f} added={added}")
        if added == 0:
            converged, term_reason = True, "priced_out"
            break
    else:
        converged, term_reason = False, "max_iter"
    if lp.status != "optimal":
        converged, term_reason = False, "lp_" + lp.status
    # pool enrichment: price at perturbed duals to add diverse covering columns,
    # which shrinks the restricted-master integrality gap (the LP bound is unchanged).
    if enrich > 0 and lp.status == "optimal":
        nu0 = lp.nu if lp.nu is not None else np.zeros(inst.T)
        rng = np.random.default_rng(0)
        for _ in range(enrich):
            af = lp.alpha * rng.uniform(0.7, 1.3, size=lp.alpha.shape)
            mf = lp.mu * rng.uniform(0.7, 1.3, size=lp.mu.shape)
            nf = nu0 * rng.uniform(0.7, 1.3, size=nu0.shape)
            tp = time.time(); cand = price(af, mf, nf); pricing_t += time.time() - tp
            for tc, _ in cand:
                if _col_key(tc) not in keys:
                    cols.append(tc); keys.add(_col_key(tc))
    lp_time = time.time() - t0
    mip = solve_milp(inst, cols, time_limit=120.0, battery_allowed=batt,
                     solver=milp_solver, soc_mode=soc_mode) if do_milp else None
    return {"scenario": scenario, "lp_obj": lp.obj, "mip_obj": (mip.obj if mip else None),
            "iters": iters, "n_cols": len(cols), "time": lp_time, "pricing_time": pricing_t,
            "lp": lp, "mip": mip, "cols": cols,
            "converged": converged, "term_reason": term_reason,
            "artificial_selected": None}


def summarize(inst: Instance, res: dict) -> dict:
    mip = res["mip"]; cols = res["cols"]; x = mip.x
    trucks = int(sum(round(x[r]) for r in range(len(cols))))
    fossil = float(mip.g.sum())
    # ICE (VSP): traction is fuel, add it; EV scenarios: traction already in g_t via charging
    traction_fuel = sum(tr.energy for tr in inst.trips) if res["scenario"] == "vsp" else 0.0
    return {"trucks": trucks, "batteries": int(round(mip.nb)),
            "fuel_kwh": round(fossil + traction_fuel, 1), "obj": round(mip.obj, 1)}


if __name__ == "__main__":
    inst = make_instance(n_trips=12, n_locations=3, eps=2.0, seed=7)
    for scen in ("vsp", "solar", "v2g"):
        t = time.time(); res = column_generation(inst, scenario=scen, start="warm", do_milp=True)
        dt = time.time() - t
        gap = (res["mip_obj"] - res["lp_obj"]) / abs(res["mip_obj"]) * 100
        print(f"{scen:6s}: iters={res['iters']:2d} cols={res['n_cols']:3d} gap={gap:.2f}% "
              f"time={dt:.1f}s -> {summarize(inst, res)}")
