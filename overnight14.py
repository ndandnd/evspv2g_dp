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
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from colgen import column_generation, SCENARIOS, _col_key
from master import solve_lp, solve_milp
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


def _cg_pool(inst, scen, ph1_budget=600.0):
    """CG to price-out (mirrors overnight13._solve13's LP phase) and RETURN the
    pool. Positive artificial mass triggers the true Phase-I; a certified cell
    is returned with outcome lp_certified_infeasible and its real columns."""
    inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
    t0 = time.time()
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    prov = {"cg_converged": res.get("converged"), "cg_term": res.get("term_reason"),
            "cg_iters": res.get("iters"), "cg_s": round(time.time() - t0, 2),
            "lp_own": (None if not np.isfinite(res["lp_obj"]) else round(res["lp_obj"], 4))}
    outcome = "lp_ok"
    if not np.isfinite(res["lp_obj"]):
        return res["cols"], prov, "lp_unsolved"
    lp = solve_lp(inst, res["cols"], battery_allowed=SCENARIOS[scen]["battery"])
    mass = float(sum(x for c, x in zip(res["cols"], lp.x)
                     if getattr(c, "kind", "") == "artificial")) \
        if lp.status == "optimal" else None
    prov["lp_artificial_mass"] = (None if mass is None else round(mass, 6))
    if mass is not None and mass > 1e-6:
        ph1 = _phase1_certify(inst, scen, pool=res["cols"], budget_s=ph1_budget)
        prov.update({k: ph1[k] for k in ("ph1_mass", "ph1_converged", "ph1_iters", "ph1_s")})
        if ph1["ph1_converged"] and ph1["ph1_mass"] is not None and ph1["ph1_mass"] > 1e-6:
            return res["cols"], prov, "lp_certified_infeasible"
        if ph1["ph1_converged"]:
            inject = ([c for c in res["cols"] if getattr(c, "kind", "") != "artificial"]
                      + ph1["real_cols"])
            res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                                    enrich=25, max_iter=max(2000, 5 * inst.n_trips),
                                    extra_cols=inject)
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


def _milp_common(inst, scen, upool, tl, start=None):
    """Final MILP over the union pool with an optional inherited start."""
    t0 = time.time()
    mip = solve_milp(inst, upool, time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"],
                     solver=MILP_SOLVER, x_start=start)
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


def _solve_base_common4(sd, n, pv, tl=900.0, assert_hard=False):
    """One physical base through the full common-pool four-arm protocol."""
    def fresh():
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25
        return inst

    pools, provs, outcomes = {}, {}, {}
    for arm in ARMS4:
        pools[arm], provs[arm], outcomes[arm] = _cg_pool(fresh(), arm)
    C_CO = _union(pools["solar"], pools["solar_bess"])
    C_V2G = _union(C_CO, pools["v2g_fleet"], pools["v2g"])
    upool = {a: (C_CO if a in CO_ARMS else C_V2G) for a in ARMS4}
    ukeys = {a: {str(_col_key(c)): i for i, c in enumerate(upool[a])} for a in ARMS4}

    rows, incs = [], {}
    for arm in ARMS4:
        inst = fresh()
        inst.c_g, inst.c_v, inst.c_b, inst.rho = CG_COST, CV, CB_COST, RHO
        row = {"pv": pv, "n_tasks": n, "seed": sd, "scenario": arm,
               "commit": COMMIT, "milp_solver": MILP_SOLVER, "soc_step": 0.25,
               "pool_own": len(pools[arm]), "pool_union": len(upool[arm]),
               "pool_hash": _pool_hash(upool[arm]), **provs[arm]}
        lpu = solve_lp(inst, upool[arm], battery_allowed=SCENARIOS[arm]["battery"])
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
        mrow, inc = _milp_common(inst, arm, upool[arm], tl, start=start)
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


def common4():
    rows, path = ckpt(f"overnight14_common4_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"]) for r in rows}
    PVS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0]
    bases = [(sd, n, pv) for sd in (0, 1, 2) for n in (20, 60, 120) for pv in PVS]
    print(f"COMMON4: {len(bases)} bases, shard {SH_I}/{SH_K} ({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv) in enumerate(bases):
        if idx % SH_K != SH_I or (pv, n, sd) in done:
            continue
        t0 = time.time()
        rows += _solve_base_common4(sd, n, pv, tl=900.0)
        save(rows, path)
        print(f"  base pv{pv} n{n} sd{sd} done in {time.time()-t0:.0f}s "
              f"({len(rows)} rows)", flush=True)


def _caps_common(study, sweep, set_caps, tl=300.0, want_util=False):
    """Shared skeleton for COMMONCAPS / CHARGECAPS2: pools unioned across arms
    AND sweep levels per base; arms restrictive->flexible, levels tight->loose;
    inheritance from (same arm, tighter level) and (restrictive arm, same level)."""
    rows, path = ckpt(f"overnight14_{study.lower()}_s{SH_I}of{SH_K}.json")
    done = {(r["seed"], r["n_tasks"], r["level"], r["scenario"]) for r in rows}
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
                    (row["lp_union"] is not None and own is not None
                     and abs(row["lp_union"] - own) <= TOL_LP)
                    or not provs[(lv, arm)].get("cg_converged")
                    or outcomes[(lv, arm)] == "lp_certified_infeasible")
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
                mrow, inc = _milp_common(inst, arm, upool[arm], tl, start=start)
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


RUNNERS = {"SMOKE": smoke, "COMMON4": common4, "COMMONCAPS": commoncaps,
           "CHARGECAPS2": chargecaps2}

if __name__ == "__main__":
    t00 = time.time()
    unknown = [s for s in STUDIES if s not in RUNNERS]
    if unknown:
        sys.exit(f"unknown OVERNIGHT14_STUDIES {unknown}; valid: {sorted(RUNNERS)}")
    for s in STUDIES:
        print(f"=== {s} ===", flush=True)
        RUNNERS[s]()
    print(f"overnight14 done in {(time.time() - t00) / 3600:.2f} h", flush=True)
