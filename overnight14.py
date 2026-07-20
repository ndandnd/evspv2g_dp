"""
Overnight-14: common-column-pool integer repair.

The overnight13 four-arm integer comparisons solved each arm's final MILP over
its OWN generated pool. The exact priced-out LP values respect every dominance
relation, but the incumbents do not: 14 violations of feasible-set nesting in
FOURARM and 42 adjacent-cap monotonicity violations in FOURCAPS, all
pool-and-time-limit artifacts. This runner repairs the comparisons:

  For each physical instance,
      C_CO  = cols(solar) u cols(solar_bess)                (charge-only admissible)
      C_V2G = C_CO u cols(v2g_fleet) u cols(v2g)            (discharge admissible)
  Both charge-only arms solve their MILP over C_CO, both V2G arms over C_V2G.
  Arms solve restrictive -> flexible and caps tight -> loose, with every valid
  restrictive/tighter incumbent passed as a MIP start (a restrictive-arm or
  tighter-cap incumbent is feasible for the relaxation, so the final incumbent
  can only match or improve it -- nesting and monotonicity hold by
  construction, and any residual violation is a solver-level red flag that is
  recorded).
  Verifications per cell: union-pool LP equals the arm's own priced-out LP
  (they must -- a converged CG certifies no column anywhere prices negatively);
  start acceptance (final <= start + tol); nesting and cap monotonicity.
  Recorded per row: pool sizes and hash, contributing sources, start source
  and value, LP-own, LP-union, incumbent, solver bound, statuses, timings.

  SMOKE      : blocking pre-launch gate, 2 small bases through the full
               COMMON4 path with hard assertions; prints SMOKE PASS.
  COMMON4    : the 81 FOURARM bases (3 seeds x {20,60,120} x 9 pv), 4 arms,
               union pools + inherited starts, tl 900. Shard by base.
  COMMONCAPS : the 9 FOURCAPS bases (3 seeds x {20,60,120}), 6 generation-cap
               levels x 4 arms, pools unioned across arms AND caps,
               tight -> loose with inheritance, tl 300. Shard by base (9).
  CHARGECAPS2: charging-cap panel with the same machinery: 6 charge-cap
               levels x 4 arms, generation uncapped, utilization recorded
               from the incumbent profile, tl 300. Shard by base (9).

Run: OVERNIGHT14_STUDIES="..." OVERNIGHT14_SHARD="i/K" python3 overnight14.py
Per-base atomic checkpointing; requeue-safe.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from colgen import column_generation, SCENARIOS, _col_key
from master import Column, solve_lp, solve_milp
from overnight3 import ckpt, save, rand_trips, CG_COST, CB_COST, RHO, CV, MILP_SOLVER
from overnight13 import _phase1_certify

import subprocess
try:
    COMMIT = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                     cwd=os.path.dirname(os.path.abspath(__file__)),
                                     text=True).strip()
except Exception:
    COMMIT = "unknown"

STUDIES = os.environ.get("OVERNIGHT14_STUDIES", "SMOKE").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT14_SHARD", "0/1").split("/"))

ARMS4 = ["solar", "solar_bess", "v2g_fleet", "v2g"]      # restrictive -> flexible
CO_ARMS = ("solar", "solar_bess")
START_SOURCES = {"solar": [], "solar_bess": ["solar"],
                 "v2g_fleet": ["solar"], "v2g": ["solar_bess", "v2g_fleet"]}
TOL_LP = 0.01            # abs $ tolerance: union LP must equal own priced-out LP
TOL_NEST = 0.05          # abs $ tolerance on incumbent dominance checks


def _pool_hash(cols):
    keys = sorted(str(_col_key(c)) for c in cols)
    return hashlib.md5("|".join(keys).encode()).hexdigest()[:12]


def _union(*pools):
    out, seen = [], set()
    for p in pools:
        for c in p:
            k = _col_key(c)
            if k not in seen:
                out.append(c); seen.add(k)
    return out


def _cg_pool(inst, scen, ph1_budget=600.0, soc_mode="cyclic", cv=None):
    """CG to price-out (mirrors overnight13._solve13's LP phase) and RETURN the
    pool. Positive artificial mass triggers the true Phase-I; a certified cell
    is returned with outcome lp_certified_infeasible and its real columns."""
    inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, (CV if cv is None else cv), CB_COST, RHO
    t0 = time.time()
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips),
                            soc_mode=soc_mode)
    prov = {"cg_converged": res.get("converged"), "cg_term": res.get("term_reason"),
            "cg_iters": res.get("iters"), "cg_s": round(time.time() - t0, 2),
            "lp_own": (None if not np.isfinite(res["lp_obj"]) else round(res["lp_obj"], 4))}
    outcome = "lp_ok"
    if not np.isfinite(res["lp_obj"]):
        return res["cols"], prov, "lp_unsolved"
    lp = solve_lp(inst, res["cols"], battery_allowed=SCENARIOS[scen]["battery"],
                  soc_mode=soc_mode)
    mass = float(sum(x for c, x in zip(res["cols"], lp.x)
                     if getattr(c, "kind", "") == "artificial")) \
        if lp.status == "optimal" else None
    prov["lp_artificial_mass"] = (None if mass is None else round(mass, 6))
    if mass is not None and mass > 1e-6:
        ph1 = _phase1_certify(inst, scen, soc_mode=soc_mode, pool=res["cols"],
                              budget_s=ph1_budget)
        prov.update({k: ph1[k] for k in ("ph1_mass", "ph1_converged", "ph1_iters", "ph1_s")})
        if ph1["ph1_converged"] and ph1["ph1_mass"] is not None and ph1["ph1_mass"] > 1e-6:
            return res["cols"], prov, "lp_certified_infeasible"
        if ph1["ph1_converged"]:
            inject = ([c for c in res["cols"] if getattr(c, "kind", "") != "artificial"]
                      + ph1["real_cols"])
            res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                                    enrich=25, max_iter=max(2000, 5 * inst.n_trips),
                                    soc_mode=soc_mode, extra_cols=inject)
            prov.update({"ph1_resume": True, "cg_converged": res.get("converged"),
                         "lp_own": (None if not np.isfinite(res["lp_obj"])
                                    else round(res["lp_obj"], 4))})
        else:
            outcome = "positive_artificial_unresolved"
    return res["cols"], prov, outcome


def _start_from(inc, upool_keys):
    """Map an inherited incumbent {col_key: units} onto union-pool indices."""
    xmap = {}
    for k, v in inc["xmap"].items():
        if k not in upool_keys:
            return None                     # should not happen: union contains sources
        xmap[upool_keys[k]] = v
    return {"x": xmap, "nb": inc.get("nb", 0.0)}


def _milp_common(inst, scen, upool, tl, start=None, soc_mode="cyclic"):
    """Final MILP over the union pool with an optional inherited start."""
    t0 = time.time()
    mip = solve_milp(inst, upool, time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"],
                     solver=MILP_SOLVER, x_start=start, soc_mode=soc_mode)
    row = {"milp_s": round(time.time() - t0, 2), "milp_status": mip.status,
           "solver_bound": getattr(mip, "solver_bound", None)}
    if mip.status == "milp_failed" or not np.isfinite(mip.obj):
        row.update({"feasible": None, "outcome": "no_incumbent"})
        return row, None
    n_art = sum(1 for c, x in zip(upool, mip.x)
                if x > 0.5 and getattr(c, "kind", "") == "artificial")
    row.update({"artificials": n_art,
                "feasible": (True if n_art == 0 else None),
                "outcome": ("feasible" if n_art == 0 else "no_real_incumbent"),
                "total": round(mip.obj, 2), "g_units": round(float(mip.g.sum()), 2),
                "trucks": int(sum(round(x) for c, x in zip(upool, mip.x)
                                  if x > 0.5 and getattr(c, "kind", "") == "truck")),
                "batteries": int(round(mip.nb))})
    inc = None
    if n_art == 0:
        inc = {"obj": float(mip.obj), "nb": float(mip.nb),
               "xmap": {str(_col_key(c)): round(float(x))
                        for c, x in zip(upool, mip.x)
                        if x > 0.5 and getattr(c, "kind", "") != "artificial"}}
        row["_charge_profile"] = [round(float(v), 4) for v in
                                  (sum((np.maximum(c.e, 0.0) * round(x)
                                        for c, x in zip(upool, mip.x)
                                        if x > 0.5 and getattr(c, "kind", "") == "truck"),
                                       np.zeros(inst.T))
                                   + (mip.charge if getattr(mip, "charge", None) is not None
                                      else np.zeros(inst.T)))]
    return row, inc


def _solve_base_common4(sd, n, pv, tl=900.0, assert_hard=False, soc_mode="cyclic"):
    """One physical base through the full common-pool four-arm protocol."""
    def fresh():
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25
        return inst

    pools, provs, outcomes = {}, {}, {}
    for arm in ARMS4:
        pools[arm], provs[arm], outcomes[arm] = _cg_pool(fresh(), arm, soc_mode=soc_mode)
    C_CO = _union(pools["solar"], pools["solar_bess"])
    C_V2G = _union(C_CO, pools["v2g_fleet"], pools["v2g"])
    upool = {a: (C_CO if a in CO_ARMS else C_V2G) for a in ARMS4}
    ukeys = {a: {str(_col_key(c)): i for i, c in enumerate(upool[a])} for a in ARMS4}

    rows, incs = [], {}
    for arm in ARMS4:
        inst = fresh()
        inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
        row = {"pv": pv, "n_tasks": n, "seed": sd, "scenario": arm, "soc_mode": soc_mode,
               "commit": COMMIT, "milp_solver": MILP_SOLVER, "soc_step": 0.25,
               "pool_own": len(pools[arm]), "pool_union": len(upool[arm]),
               "pool_hash": _pool_hash(upool[arm]), **provs[arm]}
        lpu = solve_lp(inst, upool[arm], battery_allowed=SCENARIOS[arm]["battery"],
                       soc_mode=soc_mode)
        row["lp_union"] = (round(float(lpu.obj), 4) if lpu.status == "optimal" else None)
        lp_ok = (row["lp_union"] is not None and provs[arm].get("lp_own") is not None
                 and abs(row["lp_union"] - provs[arm]["lp_own"]) <= TOL_LP)
        row["lp_check_ok"] = bool(lp_ok or not provs[arm].get("cg_converged"))
        if outcomes[arm] == "lp_certified_infeasible":
            row.update({"feasible": False, "outcome": "lp_certified_infeasible",
                        "milp_status": "skipped"})
            rows.append(row); continue
        cands = [incs[s] for s in START_SOURCES[arm] if s in incs]
        start, src = None, None
        if cands:
            best = min(cands, key=lambda c: c["obj"])
            start = _start_from(best, ukeys[arm])
            src = best.get("_src")
        row["start_src"] = src
        row["start_obj"] = (round(best["obj"], 2) if cands and start else None)
        mrow, inc = _milp_common(inst, arm, upool[arm], tl, start=start, soc_mode=soc_mode)
        cp = mrow.pop("_charge_profile", None)
        row.update(mrow)
        row["start_accepted"] = (None if row["start_obj"] is None or row.get("total") is None
                                 else bool(row["total"] <= row["start_obj"] + TOL_NEST))
        if row.get("lp_union") is not None and row.get("total") is not None:
            row["gap_union_pct"] = round((row["total"] - row["lp_union"])
                                         / abs(row["total"]) * 100, 3)
        if inc:
            inc["_src"] = arm
            incs[arm] = inc
        rows.append(row)

    # dominance verification: flexible incumbent must not exceed restrictive
    tot = {r["scenario"]: r.get("total") for r in rows}
    viol = []
    for flex, restr in (("solar_bess", "solar"), ("v2g", "solar_bess"),
                        ("v2g_fleet", "solar"), ("v2g", "v2g_fleet")):
        if tot.get(flex) is not None and tot.get(restr) is not None \
           and tot[flex] > tot[restr] + TOL_NEST:
            viol.append(f"{flex}>{restr}")
    for r in rows:
        r["nesting_viol"] = ",".join(viol) if viol else ""
    if assert_hard:
        assert not viol, f"nesting violated: {viol}"
        for r in rows:
            assert r["lp_check_ok"], f"union LP != own LP: {r}"
            assert r.get("start_accepted") in (None, True), f"start rejected: {r}"
    return rows


def smoke():
    """Blocking gate: 2 small bases through the full protocol, hard assertions."""
    print("=== SMOKE (common-pool protocol) ===", flush=True)
    for sd, n, pv in ((0, 20, 1.5), (0, 20, 2.5)):
        rows = _solve_base_common4(sd, n, pv, tl=120.0, assert_hard=True)
        for r in rows:
            print(f"  pv{pv} {r['scenario']:11s} lp_own {r.get('lp_own')} "
                  f"lp_union {r.get('lp_union')} total {r.get('total')} "
                  f"start {r.get('start_src')} accepted {r.get('start_accepted')} "
                  f"outcome {r.get('outcome')}", flush=True)
    print("SMOKE PASS", flush=True)


def _run_common4(tag, seeds):
    """Shared COMMON4 runner (the checkpoint name for tag='common4' is
    unchanged from the original, so running jobs resume identically)."""
    rows, path = ckpt(f"overnight14_{tag}_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"]) for r in rows}
    PVS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0]
    bases = [(sd, n, pv) for sd in seeds for n in (20, 60, 120) for pv in PVS]
    print(f"{tag.upper()}: {len(bases)} bases, shard {SH_I}/{SH_K} ({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv) in enumerate(bases):
        if idx % SH_K != SH_I or (pv, n, sd) in done:
            continue
        t0 = time.time()
        rows += _solve_base_common4(sd, n, pv, tl=900.0)
        save(rows, path)
        print(f"  base pv{pv} n{n} sd{sd} done in {time.time()-t0:.0f}s "
              f"({len(rows)} rows)", flush=True)


def common4():
    _run_common4("common4", (0, 1, 2))


def common4x():
    """Breadth extension: four more seeds through the identical common-pool
    protocol (error bars for the conditional decomposition)."""
    _run_common4("common4x", (3, 4, 5, 6))


def common4y():
    """Final breadth: seeds 7-9 (brings the factorial to 10 seeds/cell)."""
    _run_common4("common4y", (7, 8, 9))


def periodic4():
    """Four-arm common-pool comparison under BOTH steady-state boundary
    conventions on a small matched ladder. Pools are never shared across
    conventions (a full-recharge column and a periodic column bake different
    boundary states); the union is across arms within each convention."""
    rows, path = ckpt(f"overnight14_periodic4_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r.get("soc_mode")) for r in rows}
    bases = [(sd, n, pv) for n in (20, 60) for pv in (1.5, 2.0, 2.5)
             for sd in (0, 1, 2)]
    print(f"PERIODIC4: {len(bases)} bases x 2 conventions, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        for mode in ("cyclic", "periodic"):
            if (pv, n, sd, mode) in done:
                continue
            t0 = time.time()
            rows += _solve_base_common4(sd, n, pv, tl=600.0, soc_mode=mode)
            save(rows, path)
            print(f"  base pv{pv} n{n} sd{sd} {mode} done in {time.time()-t0:.0f}s",
                  flush=True)


def boundaryladder():
    """Pinned steady-state boundary levels s0 = sT = c for fixed c (Anna's
    cheap comparison points between full recharge, c = G, and the free-level
    periodic convention). Same 18-base ladder and common-pool protocol as
    PERIODIC4; each pin costs one cyclic-style solve. Full-recharge and
    free-periodic rows come from the existing PERIODIC4 data at analysis."""
    rows, path = ckpt(f"overnight14_boundaryladder_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r.get("soc_mode")) for r in rows}
    bases = [(sd, n, pv) for n in (20, 60) for pv in (1.5, 2.0, 2.5)
             for sd in (0, 1, 2)]
    PINS = ("pin0", "pin1.75", "pin3.5", "pin5.25")   # model units (100 kWh each):
                                                      # 0, G/4, G/2, 3G/4 = 0/175/350/525 kWh
    print(f"BOUNDARYLADDER: {len(bases)} bases x {len(PINS)} pins, shard "
          f"{SH_I}/{SH_K} ({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        for mode in PINS:
            if (pv, n, sd, mode) in done:
                continue
            t0 = time.time()
            rows += _solve_base_common4(sd, n, pv, tl=600.0, soc_mode=mode)
            save(rows, path)
            print(f"  base pv{pv} n{n} sd{sd} {mode} done in {time.time()-t0:.0f}s",
                  flush=True)


def _pv_for_gamma(n, sd, target):
    """Bisect the pv scale so the endowment index gamma = surplus/traction hits
    the target for this fleet (surplus is monotone nondecreasing in pv)."""
    fleet = rand_trips(3, n, sd, salt=50_000)

    def ratio(pv):
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        surplus = float(np.maximum(-inst.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst.trips))
        return surplus / max(traction, 1e-9)

    lo, hi = 0.2, 14.0
    if ratio(hi) < target:
        return None                       # unreachable at sane pv
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if ratio(mid) < target:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 4)


def gamma4():
    """Gamma-matched conditional break-even: solar_bess baseline vs V2G+BESS
    with the bidirectional-charger premium INSIDE the optimization (a premium
    can change fleet size and routes, so post-hoc premium x trucks is not
    equivalent). Common pools across the four solves; premium arms recost
    every truck column to cv + premium (column feasibility is cost-free, so
    pools transfer exactly)."""
    rows, path = ckpt(f"overnight14_gamma4_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["n_tasks"], r["seed"], r["scenario"],
             r.get("premium")) for r in rows}
    GTS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
    PREMS = [0.0, 4.0, 8.0]
    bases = [(sd, n, gt) for sd in (3, 4, 5, 6, 7, 8, 9)
             for n in (20, 60, 120) for gt in GTS]
    print(f"GAMMA4: {len(bases)} bases, shard {SH_I}/{SH_K} ({len(rows)} rows done)", flush=True)
    for idx, (sd, n, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        arms = [("solar_bess", 0.0)] + [("v2g", p) for p in PREMS]
        if all((gt, n, sd, a, p) in done for a, p in arms):
            continue
        pv = _pv_for_gamma(n, sd, gt)
        if pv is None:
            rows.append({"gamma_target": gt, "n_tasks": n, "seed": sd,
                         "scenario": "unreachable", "premium": None,
                         "outcome": "gamma_unreachable", "commit": COMMIT})
            save(rows, path); continue

        def fresh():
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.soc_step = 0.25
            return inst

        pools, provs, outcomes = {}, {}, {}
        for scen, p in arms:
            pools[(scen, p)], provs[(scen, p)], outcomes[(scen, p)] = \
                _cg_pool(fresh(), scen, cv=CV + p)
        C_BESS = pools[("solar_bess", 0.0)]
        C_V2G = _union(C_BESS, *[pools[("v2g", p)] for p in PREMS])
        incs = {}
        totals = {}
        for scen, p in arms:
            inst = fresh()
            inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
            inst.c_v = CV + p
            if scen == "solar_bess":
                up = C_BESS
            else:                          # premium recosting of every truck column
                up = [(Column(c.kind, c.a, c.e, CV + p, c.label)
                       if getattr(c, "kind", "") == "truck" else c) for c in C_V2G]
            ukeys = {str(_col_key(c)): i for i, c in enumerate(up)}
            row = {"gamma_target": gt, "pv_used": pv, "n_tasks": n, "seed": sd,
                   "scenario": scen, "premium": p, "commit": COMMIT,
                   "milp_solver": MILP_SOLVER, "soc_step": 0.25,
                   "pool_own": len(pools[(scen, p)]), "pool_union": len(up),
                   "pool_hash": _pool_hash(up), **provs[(scen, p)]}
            lpu = solve_lp(inst, up, battery_allowed=SCENARIOS[scen]["battery"])
            row["lp_union"] = (round(float(lpu.obj), 4)
                               if lpu.status == "optimal" else None)
            own = provs[(scen, p)].get("lp_own")
            row["lp_check_ok"] = bool(
                (row["lp_union"] is not None and own is not None
                 and abs(row["lp_union"] - own) <= TOL_LP)
                or not provs[(scen, p)].get("cg_converged"))
            if outcomes[(scen, p)] == "lp_certified_infeasible":
                row.update({"feasible": False,
                            "outcome": "lp_certified_infeasible",
                            "milp_status": "skipped"})
                rows.append(row); save(rows, path); continue
            # starts: lower-premium v2g and the bess baseline, obj adjusted by
            # (premium delta) x (trucks in the start)
            cands = []
            if scen == "v2g":
                for p2 in [q for q in PREMS if q < p]:
                    if ("v2g", p2) in incs:
                        c0 = incs[("v2g", p2)]
                        cands.append({**c0, "obj": c0["obj"] + (p - p2) * c0["ntrucks"],
                                      "_src": f"v2g@{p2:g}"})
                if ("solar_bess", 0.0) in incs:
                    c0 = incs[("solar_bess", 0.0)]
                    cands.append({**c0, "obj": c0["obj"] + p * c0["ntrucks"],
                                  "_src": "solar_bess"})
            start, src, best = None, None, None
            if cands:
                best = min(cands, key=lambda c: c["obj"])
                start = _start_from(best, ukeys)
                src = best.get("_src")
            row["start_src"] = src
            row["start_obj"] = (round(best["obj"], 2) if best and start else None)
            mrow, inc = _milp_common(inst, scen, up, 600.0, start=start)
            mrow.pop("_charge_profile", None)
            row.update(mrow)
            row["start_accepted"] = (None if row["start_obj"] is None
                                     or row.get("total") is None
                                     else bool(row["total"] <= row["start_obj"]
                                               + TOL_NEST))
            if row.get("lp_union") is not None and row.get("total") is not None:
                row["gap_union_pct"] = round((row["total"] - row["lp_union"])
                                             / abs(row["total"]) * 100, 3)
            if inc:
                inc["ntrucks"] = int(sum(inc["xmap"].values()))
                incs[(scen, p)] = inc
            totals[(scen, p)] = row.get("total")
            rows.append(row); save(rows, path)
        # premium monotonicity: v2g cost must be nondecreasing in the premium
        viol = []
        for pa, pb in zip(PREMS, PREMS[1:]):
            ta, tb = totals.get(("v2g", pa)), totals.get(("v2g", pb))
            if ta is not None and tb is not None and tb < ta - TOL_NEST:
                viol.append(f"v2g@{pb:g}<v2g@{pa:g}")
        ta, tb = totals.get(("v2g", 0.0)), totals.get(("solar_bess", 0.0))
        if ta is not None and tb is not None and ta > tb + TOL_NEST:
            viol.append("v2g@0>solar_bess")
        if viol:
            print(f"  WARNING premium/dominance violation {viol} at "
                  f"gt{gt} n{n} sd{sd}", flush=True)


def w2common():
    """Annual weather ladder with common pools: solar / solar_bess / v2g per
    (day, pv), C_CO = solar u solar_bess, C_V2G = C_CO u v2g, inherited
    starts. Repairs the conditional V2G|BESS annual distribution (the
    overnight13 W2 incumbents at tl 60 carry gaps of the same order as the
    1-3% conditional differences)."""
    from profile_robustness import base_curves
    from solar_ensemble import load_days
    W2ARMS = ["solar", "solar_bess", "v2g"]
    W2SRC = {"solar": [], "solar_bess": ["solar"], "v2g": ["solar_bess"]}
    rows, path = ckpt(f"overnight14_w2common_s{SH_I}of{SH_K}.json")
    done = {(r["date"], r["pv"], r["scenario"]) for r in rows}
    days = load_days()
    D, S = base_curves()
    mean_daily = np.mean([d[1].sum() for d in days])
    PVS = [1.0, 1.5, 2.0, 2.5, 3.0]
    groups = [(k, pv) for k in range(len(days)) for pv in PVS]
    print(f"W2COMMON: {len(groups)} day/pv groups, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    from recreate_arxiv import BREAKS2
    for idx, (k, pv) in enumerate(groups):
        if idx % SH_K != SH_I:
            continue
        date, ghi = days[k]
        if all((date, pv, a) in done for a in W2ARMS):
            continue
        dh = np.round(D - ghi * (S.sum() * pv / mean_daily)).astype(int)

        def fresh():
            inst = build_instance(3, 2.0, BREAKS2, delta_hourly=dh)
            inst.soc_step = 0.25
            return inst

        pools, provs, outcomes = {}, {}, {}
        for a in W2ARMS:
            pools[a], provs[a], outcomes[a] = _cg_pool(fresh(), a, ph1_budget=120.0)
        C_CO = _union(pools["solar"], pools["solar_bess"])
        C_V2G = _union(C_CO, pools["v2g"])
        upool = {"solar": C_CO, "solar_bess": C_CO, "v2g": C_V2G}
        ukeys = {a: {str(_col_key(c)): i for i, c in enumerate(upool[a])}
                 for a in W2ARMS}
        incs = {}
        for a in W2ARMS:
            if (date, pv, a) in done:
                continue
            inst = fresh()
            inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
            row = {"date": date, "pv": pv, "scenario": a, "commit": COMMIT,
                   "milp_solver": MILP_SOLVER, "soc_step": 0.25,
                   "pool_own": len(pools[a]), "pool_union": len(upool[a]),
                   **provs[a]}
            lpu = solve_lp(inst, upool[a], battery_allowed=SCENARIOS[a]["battery"])
            row["lp_union"] = (round(float(lpu.obj), 4)
                               if lpu.status == "optimal" else None)
            own = provs[a].get("lp_own")
            row["lp_check_ok"] = bool(
                (row["lp_union"] is not None and own is not None
                 and abs(row["lp_union"] - own) <= TOL_LP)
                or not provs[a].get("cg_converged"))
            if outcomes[a] == "lp_certified_infeasible":
                row.update({"feasible": False,
                            "outcome": "lp_certified_infeasible",
                            "milp_status": "skipped"})
                rows.append(row); save(rows, path); continue
            cands = [incs[s] for s in W2SRC[a] if s in incs]
            start, src, best = None, None, None
            if cands:
                best = min(cands, key=lambda c: c["obj"])
                start = _start_from(best, ukeys[a])
                src = best.get("_src")
            row["start_src"] = src
            row["start_obj"] = (round(best["obj"], 2) if best and start else None)
            mrow, inc = _milp_common(inst, a, upool[a], 120.0, start=start)
            mrow.pop("_charge_profile", None)
            row.update(mrow)
            row["start_accepted"] = (None if row["start_obj"] is None
                                     or row.get("total") is None
                                     else bool(row["total"] <= row["start_obj"]
                                               + TOL_NEST))
            if row.get("lp_union") is not None and row.get("total") is not None:
                row["gap_union_pct"] = round((row["total"] - row["lp_union"])
                                             / abs(row["total"]) * 100, 3)
            if inc:
                inc["_src"] = a
                incs[a] = inc
            rows.append(row); save(rows, path)
        if idx % 40 == 0:
            print(f"  [{idx + 1}/{len(groups)}] ({len(rows)} rows)", flush=True)


def _caps_common(study, sweep, set_caps, tl=300.0, want_util=False,
                 bases=None, tl_fn=None):
    """Shared skeleton for COMMONCAPS / CHARGECAPS2: pools unioned across arms
    AND sweep levels per base; arms restrictive->flexible, levels tight->loose;
    inheritance from (same arm, tighter level) and (restrictive arm, same level)."""
    rows, path = ckpt(f"overnight14_{study.lower()}_s{SH_I}of{SH_K}.json")
    done = {(r["seed"], r["n_tasks"], r["level"], r["scenario"]) for r in rows}
    if bases is None:
        bases = [(sd, n) for sd in (0, 1, 2) for n in (20, 60, 120)]
    print(f"{study}: {len(bases)} bases x {len(sweep)} levels x 4 arms, "
          f"shard {SH_I}/{SH_K} ({len(rows)} rows done)", flush=True)
    for bidx, (sd, n) in enumerate(bases):
        if bidx % SH_K != SH_I:
            continue
        if all((sd, n, (lv if np.isfinite(lv) else None), a) in done
               for lv in sweep for a in ARMS4):
            continue

        def fresh(lv):
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
            set_caps(inst, lv)
            inst.soc_step = 0.25
            return inst

        pools, provs, outcomes = {}, {}, {}
        for lv in sweep:
            for arm in ARMS4:
                pools[(lv, arm)], provs[(lv, arm)], outcomes[(lv, arm)] = \
                    _cg_pool(fresh(lv), arm, ph1_budget=300.0)
        C_CO = _union(*[pools[(lv, a)] for lv in sweep for a in CO_ARMS])
        C_V2G = _union(C_CO, *[pools[(lv, a)] for lv in sweep
                               for a in ("v2g_fleet", "v2g")])
        upool = {a: (C_CO if a in CO_ARMS else C_V2G) for a in ARMS4}
        ukeys = {a: {str(_col_key(c)): i for i, c in enumerate(upool[a])} for a in ARMS4}

        incs = {}
        for arm in ARMS4:                                  # restrictive -> flexible
            for lv in sweep:                               # tight -> loose
                lvkey = (lv if np.isfinite(lv) else None)
                if (sd, n, lvkey, arm) in done:
                    continue
                inst = fresh(lv)
                inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
                row = {"seed": sd, "n_tasks": n, "level": lvkey, "scenario": arm,
                       "pv": 2.5, "commit": COMMIT, "milp_solver": MILP_SOLVER,
                       "soc_step": 0.25, "pool_own": len(pools[(lv, arm)]),
                       "pool_union": len(upool[arm]),
                       "pool_hash": _pool_hash(upool[arm]), **provs[(lv, arm)]}
                lpu = solve_lp(inst, upool[arm],
                               battery_allowed=SCENARIOS[arm]["battery"])
                row["lp_union"] = (round(float(lpu.obj), 4)
                                   if lpu.status == "optimal" else None)
                own = provs[(lv, arm)].get("lp_own")
                row["lp_check_ok"] = bool(
                    provs[(lv, arm)].get("cg_converged")
                    and row["lp_union"] is not None and own is not None
                    and abs(row["lp_union"] - own) <= TOL_LP) \
                    or outcomes[(lv, arm)] == "lp_certified_infeasible"
                if outcomes[(lv, arm)] == "lp_certified_infeasible":
                    row.update({"feasible": False,
                                "outcome": "lp_certified_infeasible",
                                "milp_status": "skipped"})
                    rows.append(row); save(rows, path); continue
                cands = []
                tighter = [l2 for l2 in sweep if l2 < lv]
                if tighter and (arm, max(tighter)) in incs:
                    cands.append(incs[(arm, max(tighter))])
                for src_arm in START_SOURCES[arm]:
                    if (src_arm, lv) in incs:
                        cands.append(incs[(src_arm, lv)])
                start, src = None, None
                best = None
                if cands:
                    best = min(cands, key=lambda c: c["obj"])
                    start = _start_from(best, ukeys[arm])
                    src = best.get("_src")
                row["start_src"] = src
                row["start_obj"] = (round(best["obj"], 2) if best and start else None)
                tl_cell = tl if tl_fn is None else tl_fn(sd, n, lvkey, arm)
                mrow, inc = _milp_common(inst, arm, upool[arm], tl_cell, start=start)
                cp = mrow.pop("_charge_profile", None)
                row.update(mrow)
                row["start_accepted"] = (None if row["start_obj"] is None
                                         or row.get("total") is None
                                         else bool(row["total"] <= row["start_obj"]
                                                   + TOL_NEST))
                if row.get("lp_union") is not None and row.get("total") is not None:
                    row["gap_union_pct"] = round((row["total"] - row["lp_union"])
                                                 / abs(row["total"]) * 100, 3)
                if want_util and cp is not None:
                    cap = float(getattr(inst, "charge_cap", float("inf")))
                    row["charge_total_units"] = round(float(np.sum(cp)), 2)
                    row["chargecap_util"] = (None if not np.isfinite(cap)
                                             else round(float(np.max(cp)) / cap, 4))
                if inc:
                    inc["_src"] = f"{arm}@{lvkey}"
                    incs[(arm, lv)] = inc
                rows.append(row); save(rows, path)
        print(f"  base sd{sd} n{n} complete ({len(rows)} rows)", flush=True)


def commoncaps():
    GENM = [1.0, 1.05, 1.1, 1.2, 1.3, float("inf")]

    def set_caps(inst, m):
        peak_def = float(np.maximum(inst.Delta, 0.0).max())
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.gen_cap = m * peak_def if np.isfinite(m) else float("inf")
        inst.charge_cap = 0.7 * peak_sur
    _caps_common("COMMONCAPS", GENM, set_caps, tl=300.0)


def chargecaps2():
    CCS = [0.35, 0.5, 0.7, 1.0, 1.4, float("inf")]

    def set_caps(inst, c):
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.gen_cap = float("inf")
        inst.charge_cap = c * peak_sur if np.isfinite(c) else float("inf")
    _caps_common("CHARGECAPS2", CCS, set_caps, tl=300.0, want_util=True)




def out4():
    """Outage ladder, corrected protocol (four factorial arms):
    stage 1 sizes assets at a flat 1.5x cap; the design is PERSISTED, and on
    requeue the saved truck/battery counts are reused (never re-solved), so
    one base has exactly one frozen portfolio.
    The stage-1 column pool is regenerated deterministically and INJECTED into
    every stage-2 solve, so the initial stage-2 master contains
    discharge-capable columns and an infeasible initial LP cannot masquerade
    as an outage result; artificials no longer consume fleet-cap slots
    (master fix).
    Stage-2 outcomes are feasibility-EXISTENCE classes only: lp_unsolved
    means UNRESOLVED (an elastic energy-balance Phase-I is future work), and
    no infeasibility certificates are claimed.
    Ownership accounting: stage1_trucks, deployed trucks, and cv are recorded,
    so owned cost = recorded + cv x (stage1_trucks - deployed)."""
    from overnight13 import _solve13
    rows, path = ckpt(f"overnight14_out4_s{SH_I}of{SH_K}.json")
    done = {(r["derate"], r["win"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows if r.get("kind") != "stage1"}
    s1saved = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]): r
               for r in rows if r.get("kind") == "stage1"}
    DER = [1.0, 0.8, 0.6, 0.5, 0.4, 0.2, 0.0]
    WINS = {"eve4h": (34, 42), "eve8h": (28, 44), "morn4h": (10, 18)}
    bases = [(sd, n, pv, scen) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for scen in ARMS4]
    print(f"OUT4: {len(bases)} stage-1 bases x {len(WINS)} windows x {len(DER)} derates, "
          f"shard {SH_I}/{SH_K} ({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv, scen) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        if all((round(d, 3), w, pv, n, sd, scen) in done for w in WINS for d in DER):
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)

        def fresh():
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.soc_step = 0.25
            return inst

        inst1 = fresh()
        base_cap = 1.5 * float(np.maximum(inst1.Delta, 0.0).max())
        inst1.gen_cap = np.full(inst1.T, base_cap)
        pool1, prov1, out1 = _cg_pool(inst1, scen)
        inject = [c for c in pool1 if getattr(c, "kind", "") != "artificial"]
        key1 = (pv, n, sd, scen)
        if key1 in s1saved:                       # PERSISTED design: never re-solve
            s1 = s1saved[key1]
        else:
            inst1b = fresh()
            inst1b.gen_cap = np.full(inst1b.T, base_cap)
            inst1b.c_g, inst1b.c_v, inst1b.c_b, inst1b.rho = CG_COST, CV, CB_COST, RHO
            mrow, inc = _milp_common(inst1b, scen, pool1, 300.0)
            mrow.pop("_charge_profile", None)
            s1 = {"kind": "stage1", "pv": pv, "n_tasks": n, "seed": sd,
                  "scenario": scen, "cv": CV, "commit": COMMIT, **prov1, **mrow}
            rows.append(s1); save(rows, path)
        if s1.get("outcome") != "feasible":
            print(f"  stage1 {scen} n{n} pv{pv} sd{sd}: {s1.get('outcome')} -- skip",
                  flush=True)
            continue
        for w, (a, b) in WINS.items():
            for d in DER:
                if (round(d, 3), w, pv, n, sd, scen) in done:
                    continue
                inst = fresh()
                caps = np.full(inst.T, base_cap); caps[a:b] = d * base_cap
                inst.gen_cap = caps
                inst.max_trucks = s1["trucks"]; inst.nb_fixed = float(s1["batteries"])
                r2 = _solve13(inst, scen, tl=180.0, extra_cols=inject)
                if r2.get("outcome") == "lp_unsolved":
                    r2["outcome"] = "unresolved_lp"   # NOT an infeasibility claim
                rows.append({"derate": round(d, 3), "win": w, "pv": pv, "n_tasks": n,
                             "seed": sd, "scenario": scen, "cv": CV,
                             "stage1_trucks": s1["trucks"],
                             "stage1_batteries": s1["batteries"],
                             "stage1_total": s1.get("total"), **r2})
                save(rows, path)
        print(f"  base {scen} n{n} pv{pv} sd{sd} complete ({len(rows)} rows)", flush=True)


def _gamma_cell(rows, path, sd, n, gt, arms, duration=2.0, tl=600.0,
                end_anchor=False):
    """One gamma-matched base solved across `arms` [(scenario, premium), ...] on
    SYMMETRIC common pools: charge-only arms receive, in addition to their own
    pools, every discharge-free truck column harvested from the V2G pools
    (recosted without the premium). This repairs the one-directional pool
    expansion of gammapkg, which gave only the flexible arms the union."""
    pv = _pv_for_gamma(n, sd, gt)
    if pv is None:
        rows.append({"gamma_target": gt, "n_tasks": n, "seed": sd,
                     "duration": duration, "end_anchor": end_anchor, "scenario": "unreachable",
                     "premium": None, "outcome": "gamma_unreachable",
                     "commit": COMMIT})
        save(rows, path)
        return

    def fresh():
        fleet = rand_trips(3, n, sd, salt=50_000)
        if end_anchor:
            fleet = [(t[0], t[1], t[2] + 2.0 - duration) for t in fleet]
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv,
                              duration=duration)
        inst.soc_step = 0.25
        return inst

    _i0 = fresh()
    g_ach = round(float(np.maximum(-_i0.Delta, 0).sum())
                  / max(float(sum(t.energy for t in _i0.trips)), 1e-9), 4)
    pools, provs, outcomes = {}, {}, {}
    for scen, p in arms:
        pools[(scen, p)], provs[(scen, p)], outcomes[(scen, p)] = \
            _cg_pool(fresh(), scen, cv=CV + p)
    co_pools = [pools[k] for k in pools if k[0] in ("solar", "solar_bess")]
    v2g_pools = [pools[k] for k in pools if k[0] in ("v2g", "v2g_fleet")]
    harvest = [c for P in v2g_pools for c in P
               if getattr(c, "kind", "") == "truck"
               and float(np.min(c.e)) >= -1e-9]
    C_CO = _union(*(co_pools + [harvest])) if co_pools else _union(*[harvest])
    C_ALL = _union(C_CO, *v2g_pools) if v2g_pools else C_CO
    incs = {}
    for scen, p in arms:
        inst = fresh()
        inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
        inst.c_v = CV + p
        base_set = C_CO if scen in ("solar", "solar_bess") else C_ALL
        up = [(Column(c.kind, c.a, c.e, CV + p, c.label)
               if getattr(c, "kind", "") == "truck" else c) for c in base_set]
        ukeys = {str(_col_key(c)): i for i, c in enumerate(up)}
        row = {"gamma_target": gt, "gamma_achieved": g_ach, "pv_used": pv,
               "n_tasks": n, "seed": sd, "duration": duration, "end_anchor": end_anchor,
               "scenario": scen, "premium": p, "commit": COMMIT,
               "milp_solver": MILP_SOLVER, "soc_step": 0.25,
               "pool_own": len(pools[(scen, p)]), "pool_union": len(up),
               "pool_harvest": len(harvest),
               **provs[(scen, p)]}
        lpu = solve_lp(inst, up, battery_allowed=SCENARIOS[scen]["battery"])
        row["lp_union"] = (round(float(lpu.obj), 4)
                           if lpu.status == "optimal" else None)
        own = provs[(scen, p)].get("lp_own")
        row["lp_check_ok"] = bool(
            provs[(scen, p)].get("cg_converged")
            and row["lp_union"] is not None and own is not None
            and row["lp_union"] <= own + TOL_LP)
        if outcomes[(scen, p)] == "lp_certified_infeasible":
            row.update({"feasible": False, "outcome": "lp_certified_infeasible",
                        "milp_status": "skipped"})
            rows.append(row); save(rows, path); continue
        cands = []
        for (s0, p0), c0 in incs.items():
            adm = (s0 in ("solar", "solar_bess")) or scen in ("v2g", "v2g_fleet")
            if s0 == "v2g_fleet" and scen == "solar_bess":
                adm = False
            if s0 in ("v2g", "v2g_fleet") and scen in ("solar", "solar_bess"):
                adm = False
            if adm:
                cands.append({**c0, "obj": c0["obj"] + (p - p0) * c0["ntrucks"],
                              "_src": f"{s0}@{p0:g}"})
        start, src, best = None, None, None
        if cands:
            best = min(cands, key=lambda c: c["obj"])
            start = _start_from(best, ukeys)
            src = best.get("_src")
        row["start_src"] = src
        row["start_obj"] = (round(best["obj"], 2) if best and start else None)
        mrow, inc = _milp_common(inst, scen, up, tl, start=start)
        cp = mrow.get("_charge_profile")
        if cp is not None:
            try:
                arr = np.asarray(cp, dtype=float)
                surplus = np.asarray(_i0.Delta) < 0
                row["chg_units"] = round(float(np.maximum(arr, 0).sum()), 2)
                row["dis_units"] = round(float(np.maximum(-arr, 0).sum()), 2)
                row["chg_in_surplus_units"] = round(
                    float(np.maximum(arr, 0)[surplus[:len(arr)]].sum()), 2)
            except Exception:
                pass
        mrow.pop("_charge_profile", None)
        row.update(mrow)
        if inc is not None:
            incs[(scen, p)] = {**inc, "ntrucks": mrow.get("trucks", 0)}
        rows.append(row)
        save(rows, path)


def gammadense():
    """Dense co-scaled break-even grid at the 60-task calibration (repairs the
    coarse five-point legacy interpolation behind the 0.31-0.35 sentence):
    gamma targets 0.10-0.80 in steps of 0.05, five seeds, premiums $0/$4/$8
    inside the optimization, symmetric common pools."""
    rows, path = ckpt(f"overnight14_gammadense_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["seed"], r["scenario"], r.get("premium"))
            for r in rows}
    GTS = [round(0.10 + 0.05 * i, 2) for i in range(15)]
    bases = [(sd, gt) for sd in (0, 1, 2, 3, 4) for gt in GTS]
    ARMS = [("solar", 0.0), ("v2g", 0.0), ("v2g", 4.0), ("v2g", 8.0)]
    print(f"GAMMADENSE: {len(bases)} bases, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        if all((gt, sd, a, p) in done for a, p in ARMS):
            continue
        t0 = time.time()
        _gamma_cell(rows, path, sd, 60, gt, ARMS)
        print(f"  gt{gt} sd{sd} done in {time.time()-t0:.0f}s", flush=True)


def gammapkg5():
    """GAMMAPKG4 rerun with the symmetric pool repair (the charge-only baseline
    previously solved on its own pool only). Same grid: seeds 3-9, fleet sizes
    20/60/120, gamma targets 0.10-0.50, premiums $0/$4/$8."""
    rows, path = ckpt(f"overnight14_gammapkg5_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["n_tasks"], r["seed"], r["scenario"],
             r.get("premium")) for r in rows}
    GTS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.50]
    bases = [(sd, n, gt) for sd in (3, 4, 5, 6, 7, 8, 9)
             for n in (20, 60, 120) for gt in GTS]
    ARMS = [("solar", 0.0), ("v2g", 0.0), ("v2g", 4.0), ("v2g", 8.0)]
    print(f"GAMMAPKG5: {len(bases)} bases, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        if all((gt, n, sd, a, p) in done for a, p in ARMS):
            continue
        t0 = time.time()
        _gamma_cell(rows, path, sd, n, gt, ARMS)
        print(f"  n{n} gt{gt} sd{sd} done in {time.time()-t0:.0f}s", flush=True)


def durladder():
    """Anna's mechanism test: hold per-task energy and gamma fixed, vary task
    DURATION (1h/2h/4h). Full configuration set plus an $8-premium arm, with
    charge/discharge diagnostics recorded from the incumbent profile."""
    rows, path = ckpt(f"overnight14_durladder_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["seed"], r.get("duration"), r["scenario"],
             r.get("premium")) for r in rows}
    GTS = (0.2, 0.35, 0.5, 0.8, 1.25, 2.0)
    DURS = (1.0, 2.0, 4.0)
    bases = [(sd, du, gt) for sd in (0, 1, 2, 3, 4) for du in DURS for gt in GTS]
    ARMS = [("solar", 0.0), ("solar_bess", 0.0), ("v2g_fleet", 0.0),
            ("v2g", 0.0), ("v2g", 8.0)]
    print(f"DURLADDER: {len(bases)} bases, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, du, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        if all((gt, sd, du, a, p) in done for a, p in ARMS):
            continue
        t0 = time.time()
        _gamma_cell(rows, path, sd, 60, gt, ARMS, duration=du)
        print(f"  dur{du} gt{gt} sd{sd} done in {time.time()-t0:.0f}s", flush=True)


def gammapkg(tag="gammapkg"):
    """Fixed-base PACKAGE crossing surface: solar (charge-only, no BESS) vs the
    full stack, gamma-matched across fleet sizes, charger premiums $0/$4/$8
    inside the optimization on the V2G side. GAMMAPKG4 (fresh tag) re-solves
    ALL arms per base over the shared expanded pool with inherited starts --
    the incremental \$4 top-up on the old checkpoint is NOT matched (skipped
    cells inherit nothing and saw a smaller pool)."""
    rows, path = ckpt(f"overnight14_{tag}_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["n_tasks"], r["seed"], r["scenario"],
             r.get("premium")) for r in rows}
    GTS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.50]
    bases = [(sd, n, gt) for sd in (3, 4, 5, 6, 7, 8, 9)
             for n in (20, 60, 120) for gt in GTS]
    print(f"GAMMAPKG: {len(bases)} bases, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        arms = [("solar", 0.0), ("v2g", 0.0), ("v2g", 4.0), ("v2g", 8.0)]
        if all((gt, n, sd, a, p) in done for a, p in arms):
            continue
        pv = _pv_for_gamma(n, sd, gt)
        if pv is None:
            rows.append({"gamma_target": gt, "n_tasks": n, "seed": sd,
                         "scenario": "unreachable", "premium": None,
                         "outcome": "gamma_unreachable", "commit": COMMIT})
            save(rows, path); continue

        def fresh():
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.soc_step = 0.25
            return inst

        _i0 = fresh()                     # ACHIEVED gamma (surplus is a step
        g_ach = round(float(np.maximum(-_i0.Delta, 0).sum())
                      / max(float(sum(t.energy for t in _i0.trips)), 1e-9), 4)
        pools, provs, outcomes = {}, {}, {}
        for scen, p in arms:
            pools[(scen, p)], provs[(scen, p)], outcomes[(scen, p)] = \
                _cg_pool(fresh(), scen, cv=CV + p)
        C_CO = pools[("solar", 0.0)]
        C_V2G = _union(C_CO, *[pools[k] for k in pools if k[0] == "v2g"])
        incs = {}
        for scen, p in arms:
            if (gt, n, sd, scen, p) in done:
                continue
            inst = fresh()
            inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
            inst.c_v = CV + p
            if scen == "solar":
                up = C_CO
            else:
                up = [(Column(c.kind, c.a, c.e, CV + p, c.label)
                       if getattr(c, "kind", "") == "truck" else c) for c in C_V2G]
            ukeys = {str(_col_key(c)): i for i, c in enumerate(up)}
            row = {"gamma_target": gt, "gamma_achieved": g_ach, "pv_used": pv,
                   "n_tasks": n, "seed": sd,
                   "scenario": scen, "premium": p, "commit": COMMIT,
                   "milp_solver": MILP_SOLVER, "soc_step": 0.25,
                   "pool_own": len(pools[(scen, p)]), "pool_union": len(up),
                   **provs[(scen, p)]}
            lpu = solve_lp(inst, up, battery_allowed=SCENARIOS[scen]["battery"])
            row["lp_union"] = (round(float(lpu.obj), 4)
                               if lpu.status == "optimal" else None)
            own = provs[(scen, p)].get("lp_own")
            row["lp_check_ok"] = bool(
                provs[(scen, p)].get("cg_converged")
                and row["lp_union"] is not None and own is not None
                and abs(row["lp_union"] - own) <= TOL_LP)
            if outcomes[(scen, p)] == "lp_certified_infeasible":
                row.update({"feasible": False, "outcome": "lp_certified_infeasible",
                            "milp_status": "skipped"})
                rows.append(row); save(rows, path); continue
            cands = []
            if scen == "v2g":
                if ("solar", 0.0) in incs:
                    c0 = incs[("solar", 0.0)]
                    cands.append({**c0, "obj": c0["obj"] + p * c0["ntrucks"],
                                  "_src": "solar"})
                if p > 0 and ("v2g", 0.0) in incs:
                    c0 = incs[("v2g", 0.0)]
                    cands.append({**c0, "obj": c0["obj"] + p * c0["ntrucks"],
                                  "_src": "v2g@0"})
            start, src, best = None, None, None
            if cands:
                best = min(cands, key=lambda c: c["obj"])
                start = _start_from(best, ukeys)
                src = best.get("_src")
            row["start_src"] = src
            row["start_obj"] = (round(best["obj"], 2) if best and start else None)
            mrow, inc = _milp_common(inst, scen, up, 600.0, start=start)
            mrow.pop("_charge_profile", None)
            row.update(mrow)
            row["start_accepted"] = (None if row["start_obj"] is None
                                     or row.get("total") is None
                                     else bool(row["total"] <= row["start_obj"]
                                               + TOL_NEST))
            if inc:
                inc["ntrucks"] = int(sum(inc["xmap"].values()))
                incs[(scen, p)] = inc
            rows.append(row); save(rows, path)


def w2cities():
    """Four-climate annual replay on COMMON pools (replaces the legacy-labeled
    package paragraph): solar / solar_bess / v2g per (city, day, pv)."""
    from profile_robustness import base_curves
    from overnight13 import _days
    CITY_FILES = {"gulf_desert": "ghi_2023_gulf_desert.csv",
                  "seoul": "ghi_2023_seoul.csv",
                  "keflavik": "ghi_2023_keflavik.csv",
                  "tromso": "ghi_2023_tromso.csv"}
    from solar_ensemble import load_days
    W2ARMS = ["solar", "solar_bess", "v2g"]
    W2SRC = {"solar": [], "solar_bess": ["solar"], "v2g": ["solar_bess"]}
    rows, path = ckpt(f"overnight14_w2cities_s{SH_I}of{SH_K}.json")
    done = {(r["city"], r["date"], r["pv"], r["scenario"]) for r in rows}
    D, S = base_curves()
    socal_mean = np.mean([d[1].sum() for d in load_days()])   # same array scaling as W2
    groups = []
    for city, fn in CITY_FILES.items():
        days = _days(fn)
        for k, (date, ghi) in enumerate(days):
            for pv in (2.0, 3.0):
                groups.append((city, date, ghi, pv))
    from recreate_arxiv import BREAKS2
    print(f"W2CITIES: {len(groups)} groups, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (city, date, ghi, pv) in enumerate(groups):
        if idx % SH_K != SH_I:
            continue
        if all((city, date, pv, a) in done for a in W2ARMS):
            continue
        dh = np.round(D - ghi * (S.sum() * pv / socal_mean)).astype(int)

        def fresh():
            inst = build_instance(3, 2.0, BREAKS2, delta_hourly=dh)
            inst.soc_step = 0.25
            return inst

        pools, provs, outcomes = {}, {}, {}
        for a in W2ARMS:
            pools[a], provs[a], outcomes[a] = _cg_pool(fresh(), a, ph1_budget=120.0)
        C_CO = _union(pools["solar"], pools["solar_bess"])
        C_V2G = _union(C_CO, pools["v2g"])
        upool = {"solar": C_CO, "solar_bess": C_CO, "v2g": C_V2G}
        ukeys = {a: {str(_col_key(c)): i for i, c in enumerate(upool[a])}
                 for a in W2ARMS}
        incs = {}
        for a in W2ARMS:
            if (city, date, pv, a) in done:
                continue
            inst = fresh()
            inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
            row = {"city": city, "date": date, "pv": pv, "scenario": a,
                   "commit": COMMIT, "milp_solver": MILP_SOLVER, "soc_step": 0.25,
                   **provs[a]}
            lpu = solve_lp(inst, upool[a], battery_allowed=SCENARIOS[a]["battery"])
            row["lp_union"] = (round(float(lpu.obj), 4)
                               if lpu.status == "optimal" else None)
            own = provs[a].get("lp_own")
            row["lp_check_ok"] = bool(
                provs[a].get("cg_converged")
                and row["lp_union"] is not None and own is not None
                and abs(row["lp_union"] - own) <= TOL_LP) \
                or outcomes[a] == "lp_certified_infeasible"
            if outcomes[a] == "lp_certified_infeasible":
                row.update({"feasible": False, "outcome": "lp_certified_infeasible",
                            "milp_status": "skipped"})
                rows.append(row); save(rows, path); continue
            cands = [incs[s] for s in W2SRC[a] if s in incs]
            start, src, best = None, None, None
            if cands:
                best = min(cands, key=lambda c: c["obj"])
                start = _start_from(best, ukeys[a])
                src = best.get("_src")
            row["start_src"] = src
            row["start_obj"] = (round(best["obj"], 2) if best and start else None)
            mrow, inc = _milp_common(inst, a, upool[a], 120.0, start=start)
            mrow.pop("_charge_profile", None)
            row.update(mrow)
            if inc:
                inc["_src"] = a
                incs[a] = inc
            rows.append(row); save(rows, path)
        if idx % 60 == 0:
            print(f"  [{idx + 1}/{len(groups)}] ({len(rows)} rows)", flush=True)


def cleanmisc():
    """Targeted cleanup: (a) the CHARGECAPS2 cell whose CG aborted
    (lp_infeasible), rerun fresh at a higher budget; (b) the inconclusive
    AUDIT cell with cross-starts; (c) the finest positive-loss ALIGN cell."""
    from overnight13 import _solve13
    rows, path = ckpt(f"overnight14_cleanmisc_s{SH_I}of{SH_K}.json")
    done = {r.get("tag") for r in rows}
    # (a) superseded by the CLEANCHARGE study (full common-pool base repair)
    # (b) AUDIT ms_L4_n200 cross-start, longer limit
    if "audit_ms_L4_n200" not in done:
        from overnight3 import POOL
        fleet = rand_trips(4, 200, 200)
        inst = build_instance(4, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                              coords_override=POOL[:4], stations="all", pv_scale=2.0)
        pool, prov, outc = _cg_pool(inst, "v2g")
        res = {}
        inc_prev = None
        for solver in ("cbc", "gurobi", "gurobi_xstart"):
            inst2 = build_instance(4, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                                   coords_override=POOL[:4], stations="all", pv_scale=2.0)
            inst2.c_g, inst2.c_v, inst2.c_b, inst2.rho = CG_COST, CV, CB_COST, RHO
            sv = "gurobi" if solver.startswith("gurobi") else "cbc"
            xs = inc_prev if solver == "gurobi_xstart" else None
            t0 = time.time()
            mip = solve_milp(inst2, pool, time_limit=3600.0, battery_allowed=True,
                             solver=sv, x_start=xs)
            res[solver] = {"obj": (None if not np.isfinite(mip.obj) else round(mip.obj, 2)),
                           "status": mip.status,
                           "bound": getattr(mip, "solver_bound", None),
                           "time_s": round(time.time() - t0, 1)}
            if solver == "cbc" and np.isfinite(mip.obj):
                inc_prev = {"x": {i: round(float(x)) for i, x in enumerate(mip.x) if x > 0.5},
                            "nb": float(mip.nb)}
        rows.append({"tag": "audit_ms_L4_n200", **prov, "results": res})
        save(rows, path); print("  (b) done", flush=True)
    # (c) finest positive-loss ALIGN refinement (LP level)
    for sd in (0, 1):
        for n in (20, 60):
            tag = f"align_eta15_{n}_{sd}"
            if tag in done:
                continue
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
            inst.eta = 0.15; inst.soc_step = 0.03125
            pool, prov, outc = _cg_pool(inst, "v2g")
            rows.append({"tag": tag, "n_tasks": n, "seed": sd, "eta": 0.15,
                         "soc_step": 0.03125, "outcome_lp": outc, **prov})
            save(rows, path); print(f"  (c) {tag} done", flush=True)


def _prior_outcomes(pattern):
    import glob as _g
    out = {}
    for f in _g.glob(os.path.join(ROOT if (ROOT := os.path.dirname(os.path.abspath(__file__))) else ".", "results", "arxiv", pattern)):
        for r in json.load(open(f)):
            if "level" in r and "scenario" in r:
                out[(r["seed"], r["n_tasks"], r["level"], r["scenario"])] = r.get("outcome")
    return out


def cleancaps():
    """Targeted COMMONCAPS repair: full common pools regenerated per base, but
    the long 1,800 s MILP budget is spent ONLY on cells whose overnight14
    outcome was no_real_incumbent; previously resolved cells re-solve at 120 s
    with inherited starts (fast, and re-anchors the inheritance chain).
    Bases: the three n=120 frontier bases plus the (0, 20) provenance base."""
    GENM = [1.0, 1.05, 1.1, 1.2, 1.3, float("inf")]

    def set_caps(inst, m):
        peak_def = float(np.maximum(inst.Delta, 0.0).max())
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.gen_cap = m * peak_def if np.isfinite(m) else float("inf")
        inst.charge_cap = 0.7 * peak_sur
    prior = _prior_outcomes("overnight14_commoncaps_s*.json")

    def tl_fn(sd, n, lvkey, arm):
        return 1800.0 if prior.get((sd, n, lvkey, arm)) == "no_real_incumbent" else 120.0
    _caps_common("CLEANCAPS", GENM, set_caps, tl=120.0,
                 bases=[(0, 20), (0, 120), (1, 120), (2, 120)], tl_fn=tl_fn)


def cleancharge():
    """Targeted CHARGECAPS2 repair for the (seed 2, n 120) base whose 0.35x
    v2g cell aborted (lp_infeasible in CG): full common-pool base rerun,
    1,800 s only where previously unresolved, utilization recorded."""
    CCS = [0.35, 0.5, 0.7, 1.0, 1.4, float("inf")]

    def set_caps(inst, c):
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.gen_cap = float("inf")
        inst.charge_cap = c * peak_sur if np.isfinite(c) else float("inf")
    prior = _prior_outcomes("overnight14_chargecaps2_s*.json")

    def tl_fn(sd, n, lvkey, arm):
        return 1800.0 if prior.get((sd, n, lvkey, arm)) in ("no_real_incumbent",
                                                            "no_incumbent") else 120.0
    _caps_common("CLEANCHARGE", CCS, set_caps, tl=120.0, want_util=True,
                 bases=[(2, 120)], tl_fn=tl_fn)


def charge035():
    """Dedicated Phase-I certification for the quarantined CHARGECAPS2 cell
    (seed 2, n 120, charge cap 0.35x, full V2G+BESS): seed Phase-I with the
    union of the other arms' pools at this cell and price it out. A strictly
    positive priced-out Phase-I mass certifies the coupled lattice LP
    infeasible, closing the quarantine with a certificate instead of an
    abort."""
    from overnight13 import _phase1_certify
    rows, path = ckpt(f"overnight14_charge035_s{SH_I}of{SH_K}.json")
    if any(r.get("tag") == "charge035" for r in rows):
        print("already done", flush=True); return
    sd, n = 2, 120

    def fresh():
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.gen_cap = float("inf"); inst.charge_cap = 0.35 * peak_sur
        inst.soc_step = 0.25
        return inst

    pools = []
    for arm in ("solar", "solar_bess", "v2g_fleet"):
        p, prov, outc = _cg_pool(fresh(), arm, ph1_budget=300.0)
        pools.append(p)
        print(f"  seed pool {arm}: {len(p)} cols ({outc})", flush=True)
    seed_pool = _union(*pools)
    inst = fresh()
    inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
    t0 = time.time()
    ph1 = _phase1_certify(inst, "v2g", pool=seed_pool, budget_s=1800.0)
    verdict = ("lp_certified_infeasible"
               if ph1["ph1_converged"] and (ph1["ph1_mass"] or 0) > 1e-6
               else ("feasible_lp" if ph1["ph1_converged"] else "unresolved"))
    rows.append({"tag": "charge035", "seed": sd, "n_tasks": n, "level": 0.35,
                 "scenario": "v2g", "seed_pool": len(seed_pool),
                 "verdict": verdict, "commit": COMMIT, "soc_step": 0.25,
                 "s": round(time.time() - t0, 1),
                 **{k: ph1[k] for k in ("ph1_mass", "ph1_converged", "ph1_iters", "ph1_s")}})
    save(rows, path)
    print(f"CHARGE035: {verdict} (mass {ph1['ph1_mass']}, converged {ph1['ph1_converged']})",
          flush=True)


def durladder2():
    """DURLADDER repair: the 4h leg of durladder was certified infeasible in
    every cell (unshifted starts push 4h tasks against the horizon/recharge
    boundary). Here every task keeps its 2h-baseline END block and duration
    extends BACKWARD (start = end - duration): the deadline structure is held
    fixed and only occupation length varies. 1h starts shift +1h, 2h
    reproduces durladder's baseline exactly, 4h starts 2h earlier."""
    rows, path = ckpt(f"overnight14_durladder2_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["seed"], r.get("duration"), r["scenario"],
             r.get("premium")) for r in rows}
    GTS = (0.2, 0.35, 0.5, 0.8, 1.25, 2.0)
    DURS = (1.0, 2.0, 4.0)
    bases = [(sd, du, gt) for sd in (0, 1, 2, 3, 4) for du in DURS for gt in GTS]
    ARMS = [("solar", 0.0), ("solar_bess", 0.0), ("v2g_fleet", 0.0),
            ("v2g", 0.0), ("v2g", 8.0)]
    print(f"DURLADDER2: {len(bases)} bases, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, du, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        if all((gt, sd, du, a, p) in done for a, p in ARMS):
            continue
        t0 = time.time()
        _gamma_cell(rows, path, sd, 60, gt, ARMS, duration=du, end_anchor=True)
        print(f"  dur{du} gt{gt} sd{sd} done in {time.time()-t0:.0f}s", flush=True)


def gamma5():
    """Symmetric-pool rerun of GAMMA4's fixed-base grid ABOVE 0.5 (GAMMA4's
    pools were one-directional, biasing v2g arms up, so its conditional
    crossing locations are suspect). Completes the symmetric surface started
    by GAMMAPKG5 (which covers 0.10-0.50): seeds 3-9, fleet sizes 20/60/120,
    gamma 0.5-2.0, all four configurations plus $4/$8 premium arms."""
    rows, path = ckpt(f"overnight14_gamma5_s{SH_I}of{SH_K}.json")
    done = {(r["gamma_target"], r["n_tasks"], r["seed"], r["scenario"],
             r.get("premium")) for r in rows}
    GTS = (0.5, 0.75, 1.0, 1.5, 2.0)
    bases = [(sd, n, gt) for sd in (3, 4, 5, 6, 7, 8, 9)
             for n in (20, 60, 120) for gt in GTS]
    ARMS = [("solar", 0.0), ("solar_bess", 0.0), ("v2g_fleet", 0.0),
            ("v2g", 0.0), ("v2g", 4.0), ("v2g", 8.0)]
    print(f"GAMMA5: {len(bases)} bases, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, gt) in enumerate(bases):
        if idx % SH_K != SH_I:
            continue
        if all((gt, n, sd, a, p) in done for a, p in ARMS):
            continue
        t0 = time.time()
        _gamma_cell(rows, path, sd, n, gt, ARMS)
        print(f"  n{n} gt{gt} sd{sd} done in {time.time()-t0:.0f}s", flush=True)


def boundaryfill():
    """Fill the (tasks x solar) plane gaps in figs 8.9/8.14: the 4x curve
    stops at 200 tasks and the fractional-pv boundary curves stop at 280,
    because the old MODESX2 study never ran. Part (a) = MODESX2 verbatim
    (4x to 400 for seeds 0-1, seed 2 for 3x/sum2x at 240-400, all four
    scenarios), written glob-compatible with overnight3_modes_s*. Part (b)
    = boundary-study tail (pv 1.25/1.5/1.75/2.5/3.5 at 320-400 plus pv 4.0
    at 240-400, seeds 0-2, solar/v2g), written glob-compatible with
    overnight5_boundary_s*; pv 4.0 pools with the modes '4x' label since
    sol_kwargs('4x') is exactly pv_scale=4.0 on the same fleet family.
    Protocol identical to overnight5.boundary/modesx2: warm CG + MILP
    tl=120s, full-recharge boundary, module MILP solver."""
    from overnight3 import sol_kwargs, solve
    from overnight5 import _base_stats
    NT = [240, 280, 320, 360, 400]
    rows, path = ckpt(f"overnight3_modes_sXF{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["sol"], r["seed"], r["scenario"]) for r in rows}
    cells = ([(sd, n, "4x", scen) for sd in (0, 1) for n in NT
              for scen in ("vsp", "ev", "solar", "v2g")]
             + [(2, n, sol, scen) for n in NT for sol in ("3x", "sum2x")
                for scen in ("vsp", "ev", "solar", "v2g")])
    print(f"BOUNDARYFILL/modes: {len(cells)} cells, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, sol, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (n, sol, sd, scen) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, **sol_kwargs(sol))
        traction = float(sum(tr.energy for tr in inst.trips))
        t0 = time.time()
        r = solve(inst, scen, tl=120.0)
        if r is None:
            print(f"  n={n} {sol} seed={sd} {scen}: no incumbent, skipped",
                  flush=True)
            continue
        fleet_paid = 0.0
        if scen == "ev":
            fleet_paid = sum((c.fixed_cost - inst.c_v) / inst.c_g * round(x)
                             for c, x in zip(r["cols"], r["mip"].x) if x > 0.5)
        rows.append({"n_tasks": n, "sol": sol, "seed": sd, "scenario": scen,
                     "g_units": round(r["g_units"], 2),
                     "traction_units": round(traction, 2),
                     "fleet_paid_units": round(fleet_paid, 2),
                     "trucks": r["trucks"], "batteries": r["batteries"],
                     "gap_pct": round(r["gap"], 3)})
        save(rows, path)
        print(f"  n={n} {sol} seed={sd} {scen}: {time.time() - t0:.0f}s "
              f"({len(rows)} rows)", flush=True)
    rows2, path2 = ckpt(f"overnight5_boundary_sF{SH_I}of{SH_K}.json")
    done2 = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows2}
    PVN = ([(pv, n) for pv in (1.25, 1.5, 1.75, 2.5, 3.5)
            for n in (320, 360, 400)] + [(4.0, n) for n in NT])
    cells2 = [(sd, pv, n) for sd in (0, 1, 2) for (pv, n) in PVN]
    print(f"BOUNDARYFILL/boundary: {len(cells2)} cells x 2, shard {SH_I}/{SH_K} "
          f"({len(rows2)} rows done)", flush=True)
    for idx, (sd, pv, n) in enumerate(cells2):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"pv": pv, "n_tasks": n, "seed": sd, **_base_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (pv, n, sd, scen) in done2:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            r = solve(inst, scen, tl=120.0)
            if r is None:
                print(f"  pv{pv} n={n} seed={sd} {scen}: no incumbent, skipped",
                      flush=True)
                continue
            rows2.append({**base, "scenario": scen, "total": round(r["total"], 1),
                          "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                          "batteries": r["batteries"],
                          "gap_pct": round(r["gap"], 3)})
            save(rows2, path2)
            print(f"  pv{pv} n={n} seed={sd} {scen} done ({len(rows2)} rows)",
                  flush=True)


def benchxl():
    """Extend the exp5 benchmark scalability ladder past 450 tasks (the paper's
    benchmark curves stop at 450 while the random-fleet family reaches 1,000):
    locations 9-15 give 360/450/550/660/780/910/1050 trips at both task
    energies (eps=2.0 -> 200 kWh/task, eps=1.5 -> 150 kWh/task). Points 9-10
    repeat the laptop rows on cluster hardware (cross-hardware calibration:
    gap_pct and cols should reproduce; wall-clocks give the cluster/laptop
    time ratio so the two curve segments can be related honestly).
    Protocol matches recreate_arxiv.exp5_scalability: v2g scenario, warm
    start, enrich=25, cyclic SoC, HiGHS master LP, CBC final integer master
    (the benchmark family's solver in the paper), 3-day MIP budget in place
    of exp5's 300 s. Rows record host/cpu so hardware claims in the paper
    are self-documenting."""
    import platform
    import socket

    from colgen import summarize
    from recreate_arxiv import ENRICH, GAL_PER_UNIT, SCAL, UNIT_KWH

    def _cpu_model():
        try:
            for line in open("/proc/cpuinfo"):
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
        try:
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        except Exception:
            return platform.processor() or platform.machine()

    rows, path = ckpt(f"overnight14_benchxl_s{SH_I}of{SH_K}.json")
    rows = [r for r in rows if "mip_obj" in r or r.get("feasible") is False]
    done = {(r["eps"], r["points"]) for r in rows}
    PTS = [int(x) for x in os.environ.get("OVERNIGHT14_BENCHXL_PTS",
                                          "9,10,11,12,13,14,15").split(",")]
    TL = float(os.environ.get("OVERNIGHT14_BENCHXL_TL", "259200"))
    cells = [(eps, p) for eps in (2.0, 1.5) for p in PTS]
    meta = {"host": socket.gethostname(), "machine": platform.machine(),
            "cpu": _cpu_model(), "ncpu": os.cpu_count(), "commit": COMMIT}
    print(f"BENCHXL: {len(cells)} cells, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done) on {meta['host']}", flush=True)
    for idx, (eps, pts) in enumerate(cells):
        if idx % SH_K != SH_I or (eps, pts) in done:
            continue
        print(f"  starting eps{eps} pts{pts}", flush=True)
        inst = build_instance(pts, eps, SCAL)
        t0 = time.time()
        res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                enrich=ENRICH, max_iter=max(2000, 5 * inst.n_trips),
                                soc_mode="cyclic")
        cg_s = time.time() - t0
        row = {"eps": eps, "points": pts, "trips": inst.n_trips,
               "scenario": "v2g", "cg_iters": res["iters"], "cols": res["n_cols"],
               "cg_s": round(cg_s, 2), "pricing_s": round(res["pricing_time"], 2),
               "pricing_pct": (round(100 * res["pricing_time"] / cg_s, 1)
                               if cg_s > 0 else 0.0),
               "lp_obj": round(res["lp_obj"], 2), "milp_tl": TL, **meta}
        if res["lp_obj"] == float("inf"):
            row["feasible"] = False
            rows.append(row)
            save(rows, path)
            raise SystemExit(f"BENCHXL eps{eps} pts{pts}: LP infeasible -- the "
                             "benchmark ladder must be feasible; investigate")
        row["feasible"] = True
        rows.append(row)
        save(rows, path)
        print(f"  eps{eps} pts{pts} ({inst.n_trips} trips): cg {cg_s:.0f}s, "
              f"{res['n_cols']} cols; starting CBC (tl {TL:.0f}s)", flush=True)
        t1 = time.time()
        mip = solve_milp(inst, res["cols"], time_limit=TL,
                         battery_allowed=SCENARIOS["v2g"]["battery"],
                         solver="cbc", soc_mode="cyclic")
        rows.pop()
        row["milp_s"] = round(time.time() - t1, 2)
        res["mip"] = mip
        s = summarize(inst, res)
        row.update({"mip_obj": round(mip.obj, 2),
                    "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                    "trucks": s["trucks"], "batteries": s["batteries"],
                    "fuel_kwh": round(s["fuel_kwh"] * UNIT_KWH, 1),
                    "fuel_gal": round(s["fuel_kwh"] * GAL_PER_UNIT, 2)})
        rows.append(row)
        save(rows, path)
        print(f"  eps{eps} pts{pts} ({inst.n_trips} trips): cg {cg_s:.0f}s, "
              f"milp {row['milp_s']:.0f}s, gap {row['gap_pct']}%", flush=True)


RUNNERS = {"SMOKE": smoke, "COMMON4": common4, "COMMONCAPS": commoncaps,
           "CHARGECAPS2": chargecaps2, "COMMON4X": common4x, "GAMMA4": gamma4,
           "PERIODIC4": periodic4, "BOUNDARYLADDER": boundaryladder,
           "W2COMMON": w2common, "OUT4": out4,
           "GAMMAPKG": gammapkg, "W2CITIES": w2cities, "CLEANMISC": cleanmisc,
           "CLEANCAPS": cleancaps, "CLEANCHARGE": cleancharge,
           "COMMON4Y": common4y, "GAMMAPKG4": (lambda: gammapkg("gammapkg4")),
           "GAMMADENSE": gammadense, "GAMMAPKG5": gammapkg5,
           "DURLADDER": durladder, "DURLADDER2": durladder2,
           "GAMMA5": gamma5, "BENCHXL": benchxl, "BOUNDARYFILL": boundaryfill,
           "CHARGE035": charge035}

if __name__ == "__main__":
    t00 = time.time()
    unknown = [s for s in STUDIES if s not in RUNNERS]
    if unknown:
        sys.exit(f"unknown OVERNIGHT14_STUDIES {unknown}; valid: {sorted(RUNNERS)}")
    for s in STUDIES:
        print(f"=== {s} ===", flush=True)
        RUNNERS[s]()
    print(f"overnight14 done in {(time.time() - t00) / 3600:.2f} h", flush=True)
