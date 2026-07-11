"""
Overnight-13: the correction round, finalized for the 48h+ weekend.
Every study records honest solver status, CG convergence, Phase-I artificial
counts, git commit, solver names, lattice step, and SoC boundary.
Headline studies run at delta = 25 kWh (exact lattice for the lossless family,
Corollary 1). Universal Phase-I coverage means the initial RMP is always
feasible: infeasibility is certified by artificials in the priced-out LP,
never by seed accidents.

  GATE      : BLOCKING pre-launch oracle gate (DP vs independent Bellman-Ford
              vs master reduced-cost formula across boundary/loss/station
              variants; fails loud). Requires networkx. ~120 comparisons.
  FOURARM   : V2G x BESS factorial, 324 solves (3 draws x 3 sizes x 9 pv x 4
              arms), 25 kWh, tl 900.
  FOURARMX  : +336 solves, draws 3-9 in the activation region pv 1.5-2.5.
  FOURCAPS  : generation-cap frontier, all 4 arms, 216 solves, 25 kWh, tl 300.
  ALIGN     : lattice/theorem alignment, 56 solves: matched 50/25/12.5 lossless
              (LP must tie at 25 vs 12.5 by Corollary 1) + eta=0.15 refinement.
  DIAG2     : corrected integer diagnostics on the U6 maps, 24 cells, tl 1800.
              Stays at 50 kWh BY DESIGN (multi-station energies divide no lattice)
              and is labeled a coarse-lattice scalability study. Shard 24 ways:
              one hard cell per scaglione job.
  AUDIT     : CBC vs Gurobi on identical column pools, 8 matched cells.
  PERIODIC  : full-recharge vs periodic boundary, 32 cells, 25 kWh.
  W2        : weather year on repaired BREAKS2, 3 arms x 5 pv x 365d, 25 kWh.
  EXPORT2   : repaired export table, 70 solves, 25 kWh.
  REGIME2   : regime ladder, 162 solves (3 draws x 3 sizes x 3 pv x 6 scen).
  SPINE25   : one-factor spine, 456 solves (4 arms), 25 kWh.
  ETA125    : loss sweep at 12.5 kWh, 192 solves (4 arms).
  HOLDOUT22 : 2023-design vs 2022-test commitment study.
  SUN2      : DEFERRED this weekend: needs the max_trucks dual in pricing,
              stage-1 persistence, and sunk-cost accounting before its rows are
              publication-grade. Do not launch.
  CHARGECAPS: charging-cap panel, corrected: 4 arms, generation uncapped,
              25 kWh, peak-utilization recorded. 216 cells. Replaces fig (b).
  PACK4     : fresh tight-gap pack x workload cells (G x {120,200} x 6 draws,
              25 kWh, tl 1800). Replaces the legacy-schema PACK3.

Run: OVERNIGHT13_STUDIES="..." OVERNIGHT13_SHARD="i/K" python3 overnight13.py
All studies checkpoint per row (atomic) and skip done cells: preemption/requeue
safe on default_partition.
"""
from __future__ import annotations
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, BREAKS2
from colgen import column_generation, SCENARIOS
from master import solve_milp, solve_lp
from overnight3 import ckpt, save, rand_trips, CG_COST, CB_COST, RHO, CV, MILP_SOLVER

import subprocess
try:
    COMMIT = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                     cwd=os.path.dirname(os.path.abspath(__file__)),
                                     text=True).strip()
except Exception:
    COMMIT = "unknown"

STUDIES = os.environ.get("OVERNIGHT13_STUDIES", "FOURARM").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT13_SHARD", "0/1").split("/"))
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "results", "arxiv")

ARMS4 = ["solar", "solar_bess", "v2g_fleet", "v2g"]


def _stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3)}


def _solve13(inst, scen, tl=300.0, soc_mode="cyclic", c_b=None, rho=None,
             want_profile=False):
    """Full-status solve: CG + restricted MILP.
    Outcome classes (never conflated):
      feasible                 artificial-free incumbent (feasible=True)
      lp_certified_infeasible  converged lattice LP still uses artificials
                               (valid certificate: the 1e6 penalty provably
                               dominates any real schedule cost at our scale,
                               which is bounded above by ~1e5) (feasible=False)
      no_real_incumbent        MILP returned only artificial-bearing solutions
                               over the generated pool (feasible=None)
      no_incumbent             MILP failed / timed out with nothing (feasible=None)
    """
    inst.c_g, inst.c_v = CG_COST, CV
    inst.c_b = CB_COST if c_b is None else c_b
    inst.rho = RHO if rho is None else rho
    t0 = time.time()
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips),
                            soc_mode=soc_mode)
    cg_s = time.time() - t0
    out = {"cg_converged": res.get("converged"), "cg_term": res.get("term_reason"),
           "cg_s": round(cg_s, 2), "cg_iters": res.get("iters"),
           "cols": res.get("n_cols"), "pricing_s": round(res.get("pricing_time", 0.0), 2),
           "lp_obj": (None if not np.isfinite(res["lp_obj"]) else round(res["lp_obj"], 2)),
           "commit": COMMIT, "milp_solver": MILP_SOLVER, "lp_solver": "highs",
           "soc_step": float(getattr(inst, "soc_step", 0.5)), "soc_mode": soc_mode}
    if not np.isfinite(res["lp_obj"]):
        out.update({"feasible": None, "outcome": "lp_unsolved", "milp_status": "none"})
        return out
    # LP artificial mass on the final pool (the certificate lives at the LP level)
    from master import solve_lp as _slp
    lp = _slp(inst, res["cols"], battery_allowed=SCENARIOS[scen]["battery"],
              soc_mode=soc_mode)
    art_mass = float(sum(x for c, x in zip(res["cols"], lp.x)
                         if getattr(c, "kind", "") == "artificial")) \
        if lp.status == "optimal" else None
    out["lp_artificial_mass"] = (None if art_mass is None else round(art_mass, 6))
    if art_mass is not None and art_mass > 1e-6 and res.get("converged"):
        out.update({"feasible": False, "outcome": "lp_certified_infeasible",
                    "milp_status": "skipped"})
        return out
    t1 = time.time()
    mip = solve_milp(inst, res["cols"], time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"],
                     solver=MILP_SOLVER, soc_mode=soc_mode)
    out["milp_s"] = round(time.time() - t1, 2)
    out["milp_status"] = mip.status
    if mip.status == "milp_failed" or not np.isfinite(mip.obj):
        out.update({"feasible": None, "outcome": "no_incumbent"})
        return out
    n_art = sum(1 for c, x in zip(res["cols"], mip.x)
                if x > 0.5 and getattr(c, "kind", "") == "artificial")
    out.update({"artificials": n_art,
                "feasible": (True if n_art == 0 else None),
                "outcome": ("feasible" if n_art == 0 else "no_real_incumbent"),
                "total": round(mip.obj, 1), "g_units": round(float(mip.g.sum()), 2),
                "trucks": int(sum(round(x) for c, x in zip(res["cols"], mip.x)
                                  if x > 0.5 and getattr(c, "kind", "") == "truck")),
                "batteries": int(round(mip.nb)),
                "solver_bound": getattr(mip, "solver_bound", None),
                "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)})
    if want_profile and n_art == 0:
        chg = np.zeros(inst.T)
        for c, x in zip(res["cols"], mip.x):
            if x > 0.5:
                chg += np.maximum(c.e, 0.0) * round(x)
        if getattr(mip, "charge", None) is not None:
            chg += mip.charge
        cap = float(getattr(inst, "charge_cap", float("inf")))
        out["charge_total_units"] = round(float(chg.sum()), 2)
        out["chargecap_util"] = (None if not np.isfinite(cap)
                                 else round(float(chg.max()) / cap, 4))
    return out


def fourarm():
    rows, path = ckpt(f"overnight13_fourarm_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    PVS = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0]
    cells = [(sd, n, pv, arm) for sd in (0, 1, 2) for n in (20, 60, 120)
             for pv in PVS for arm in ARMS4]
    print(f"FOURARM: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, arm) in enumerate(cells):
        if idx % SH_K != SH_I or (pv, n, sd, arm) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25                    # exact lattice for the lossless family
        rows.append({"pv": pv, "n_tasks": n, "seed": sd, "scenario": arm,
                     **_stats(inst), **_solve13(inst, arm, tl=900.0)})
        save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def fourcaps():
    rows, path = ckpt(f"overnight13_fourcaps_s{SH_I}of{SH_K}.json")
    done = {(r["gen_m"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    GENM = [1.0, 1.05, 1.1, 1.2, 1.3, float("inf")]
    cells = [(sd, n, m, arm) for sd in (0, 1, 2) for n in (20, 60, 120)
             for m in GENM for arm in ARMS4]
    print(f"FOURCAPS: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, m, arm) in enumerate(cells):
        if idx % SH_K != SH_I or ((m if np.isfinite(m) else None), n, sd, arm) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
        peak_def = float(np.maximum(inst.Delta, 0.0).max())
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.gen_cap = m * peak_def if np.isfinite(m) else float("inf")
        inst.charge_cap = 0.7 * peak_sur
        inst.soc_step = 0.25
        rows.append({"gen_m": (m if np.isfinite(m) else None), "n_tasks": n, "seed": sd,
                     "scenario": arm, "pv": 2.5, **_stats(inst),
                     **_solve13(inst, arm, tl=300.0)})
        save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def _days(fname):
    days = []
    with open(os.path.join(ROOT, "data", fname)) as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#") or row[0] == "date" or row[0].startswith('"'):
                continue
            days.append((row[0], np.array([float(x) for x in row[1:25]])))
    return days


def w2():
    from profile_robustness import base_curves
    from solar_ensemble import load_days
    rows, path = ckpt(f"overnight13_w2_s{SH_I}of{SH_K}.json")
    done = {(r["date"], r["pv"], r["scenario"]) for r in rows}
    days = load_days()
    D, S = base_curves()
    mean_daily = np.mean([d[1].sum() for d in days])
    PVS = [1.0, 1.5, 2.0, 2.5, 3.0]
    cells = [(k, pv, arm) for k in range(len(days)) for pv in PVS
             for arm in ("solar", "solar_bess", "v2g")]
    print(f"W2: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (k, pv, arm) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        date, ghi = days[k]
        if (date, pv, arm) in done:
            continue
        dh = np.round(D - ghi * (S.sum() * pv / mean_daily)).astype(int)
        inst = build_instance(3, 2.0, BREAKS2, delta_hourly=dh)
        inst.soc_step = 0.25
        rows.append({"date": date, "pv": pv, "scenario": arm, **_stats(inst),
                     **_solve13(inst, arm, tl=60.0)})
        save(rows, path)
        if idx % 60 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def export2():
    from overnight2 import sample_fleet
    rows, path = ckpt(f"overnight13_export2_s{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["pv"]) for r in rows}
    cells = [(n, pv) for n in range(20, 201, 20)
             for pv in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)]
    print(f"EXPORT2: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (n, pv) in enumerate(cells):
        if idx % SH_K != SH_I or (n, pv) in done:
            continue
        fleet = sample_fleet(np.random.default_rng(40 + n), 3, n, BREAKS2)
        inst = build_instance(3, 2.0, BREAKS2, pv_scale=pv, trip_list=fleet)
        inst.soc_step = 0.25
        baseline = float(np.maximum(inst.Delta, 0.0).sum())
        r = _solve13(inst, "v2g", tl=300.0)
        incr = (None if not r.get("feasible") else round((r["g_units"] - baseline) / 10, 2))
        rows.append({"n_tasks": n, "pv": pv, "baseline_mwh": round(baseline / 10, 1),
                     "incr_mwh": incr, **_stats(inst), **r})
        save(rows, path)
    print("EXPORT2 done", flush=True)


def regime2():
    from overnight2 import sample_fleet
    rows, path = ckpt(f"overnight13_regime2_s{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["pv"], r["seed"], r["scenario"]) for r in rows}
    SCENS = ["vsp", "ev", "solar", "solar_bess", "v2g_fleet", "v2g"]
    cells = [(sd, n, pv, sc) for sd in (0, 1, 2) for n in (20, 60, 120)
             for pv in (1.0, 2.0, 3.0) for sc in SCENS]
    print(f"REGIME2: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, sc) in enumerate(cells):
        if idx % SH_K != SH_I or (n, pv, sd, sc) in done:
            continue
        fleet = sample_fleet(np.random.default_rng(100 * sd + n), 3, n, BREAKS2)
        inst = build_instance(3, 2.0, BREAKS2, pv_scale=pv, trip_list=fleet)
        inst.soc_step = 0.25
        rows.append({"n_tasks": n, "pv": pv, "seed": sd, "scenario": sc, **_stats(inst),
                     **_solve13(inst, sc, tl=300.0)})
        save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}]", flush=True)


def spine25():
    rows, path = ckpt(f"overnight13_spine25_s{SH_I}of{SH_K}.json")
    done = {(r["factor"], str(r["value"]), r["seed"], r["scenario"]) for r in rows}
    arms = ([("pv", v) for v in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0)]
            + [("n", v) for v in (20, 40, 60, 80, 100, 120)]
            + [("eta", v) for v in (0.0, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3)]
            + [("G", v) for v in (3.5, 7.0, 10.5, 14.0)]
            + [("rho", v) for v in (0.5, 1.0, 1.75, 2.5)]
            + [("genm", v) for v in (1.0, 1.1, 1.3, float("inf"))]
            + [("chgc", v) for v in (0.35, 0.7, 1.4, float("inf"))])
    cells = [(sd, f, v, scen) for sd in (0, 1, 2) for (f, v) in arms
             for scen in ARMS4]
    print(f"SPINE25: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, f, v, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (f, str(v), sd, scen) in done:
            continue
        n = int(v) if f == "n" else 60
        pv = float(v) if f == "pv" else 2.0
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25
        base = {"factor": f, "value": ("inf" if not np.isfinite(v) else v),
                "n_tasks": n, "pv": pv, "seed": sd, **_stats(inst)}
        c_b = rho = None
        if f == "eta":
            inst.eta = v
        elif f == "G":
            inst.G = v
            c_b = CB_COST * v / 7.0
        elif f == "rho":
            rho = v
        elif f == "genm":
            peak_def = float(np.maximum(inst.Delta, 0.0).max())
            inst.gen_cap = v * peak_def if np.isfinite(v) else float("inf")
        elif f == "chgc":
            peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
            inst.charge_cap = v * peak_sur if np.isfinite(v) else float("inf")
        rows.append({**base, "scenario": scen,
                     **_solve13(inst, scen, tl=300.0, c_b=c_b, rho=rho)})
        save(rows, path)
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)}]", flush=True)


def eta125():
    rows, path = ckpt(f"overnight13_eta125_s{SH_I}of{SH_K}.json")
    done = {(r["eta"], r["n_tasks"], r["seed"], r["scenario"], r["pv"]) for r in rows}
    cells = [(sd, n, e, scen) for sd in (0, 1) for n in (20, 60)
             for e in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3)
             for scen in ARMS4]
    print(f"ETA125: {len(cells)} cells x pv{{1,2.5}}, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, e, scen) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        for pv in (1.0, 2.5):
            if (e, n, sd, scen, pv) in done:
                continue
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.soc_step = 0.125
            inst.eta = e
            rows.append({"eta": e, "n_tasks": n, "seed": sd, "pv": pv, "scenario": scen,
                         **_stats(inst), **_solve13(inst, scen, tl=300.0)})
            save(rows, path)
        if idx % 8 == 0:
            print(f"  [{idx + 1}/{len(cells)}]", flush=True)


def periodic():
    from overnight2 import sample_fleet
    rows, path = ckpt(f"overnight13_periodic_s{SH_I}of{SH_K}.json")
    done = {(r["cell"], r["scenario"]) for r in rows}
    cells = ([(f"exp_n{n}_pv{pv}", ("export", n, pv, 0, "v2g"))
              for n in (20, 60, 100, 140) for pv in (1.0, 1.5, 2.0, 2.5, 3.0)]
             + [(f"ref_sd{sd}_{arm}", ("ref", 60, 2.0, sd, arm))
                for sd in (0, 1, 2) for arm in ARMS4])
    print(f"PERIODIC: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (name, (kind, n, pv, sd, arm)) in enumerate(cells):
        if idx % SH_K != SH_I or (name, arm) in done:
            continue
        if kind == "export":
            fleet = sample_fleet(np.random.default_rng(40 + n), 3, n, BREAKS2)
            inst = build_instance(3, 2.0, BREAKS2, pv_scale=pv, trip_list=fleet)
        else:
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25                   # same lattice as the matched controls
        baseline = float(np.maximum(inst.Delta, 0.0).sum())
        r = _solve13(inst, arm, tl=600.0, soc_mode="periodic")
        rows.append({"cell": name, "kind": kind, "n_tasks": n, "pv": pv, "seed": sd,
                     "scenario": arm, "baseline_mwh": round(baseline / 10, 1),
                     **_stats(inst), **r})
        save(rows, path)
        print(f"  {name}/{arm}: {r.get('total')} ({r.get('milp_status')})", flush=True)


def holdout22():
    from profile_robustness import base_curves
    from solar_ensemble import load_days
    rows, path = ckpt(f"overnight13_holdout22_s{SH_I}of{SH_K}.json")
    done = {(r["kind"], r["cand"], r.get("date", "-"), r["pv"]) for r in rows}
    days23 = load_days()
    days22 = _days("ghi_2022_socal.csv")
    D, S = base_curves()
    socal_mean23 = np.mean([d[1].sum() for d in days23])
    import collections
    by_m = collections.defaultdict(list)
    for d, g in days23:
        by_m[d[5:7]].append(g)
    cands = {"annual": np.mean([g for _, g in days23], axis=0)}
    for m, gs in sorted(by_m.items()):
        cands[f"m{m}"] = np.mean(gs, axis=0)
    fleet = rand_trips(3, 60, 0, salt=50_000)

    def dh_of(ghi, pv):
        return np.round(D - ghi * (S.sum() * pv / socal_mean23)).astype(int)

    PVS = [2.0, 3.0]
    cells = ([("ws", "-", date, pv) for pv in PVS for date, _ in days22]
             + [("cand", c, "-", pv) for pv in PVS for c in cands])
    print(f"HOLDOUT22: {len(cells)} stage-1/WS cells + evals, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (kind, cand, date, pv) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if kind == "ws":
            if ("ws", "-", date, pv) in done:
                continue
            ghi = dict(days22)[date]
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet,
                                  delta_hourly=dh_of(ghi, pv))
            inst.soc_step = 0.25
            r = _solve13(inst, "v2g", tl=60.0)
            rows.append({"kind": "ws", "cand": "-", "date": date, "pv": pv,
                         **_stats(inst), **r})
            save(rows, path)
        else:
            if all(("eval", cand, d, pv) in done for d, _ in days22) \
               and ("cand", cand, "-", pv) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet,
                                  delta_hourly=dh_of(cands[cand], pv))
            inst.soc_step = 0.25
            inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
            res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                    enrich=25, max_iter=2000)
            mip = solve_milp(inst, res["cols"], time_limit=180.0,
                             battery_allowed=True, solver=MILP_SOLVER)
            if mip.status == "milp_failed" or not np.isfinite(mip.obj):
                continue
            sel = [c for c, x in zip(res["cols"], mip.x) if x > 0.5]
            nb1 = float(mip.nb)
            if ("cand", cand, "-", pv) not in done:
                rows.append({"kind": "cand", "cand": cand, "date": "-", "pv": pv,
                             "total": round(mip.obj, 1), "milp_status": mip.status,
                             "cg_converged": res.get("converged"), "commit": COMMIT,
                             "soc_step": 0.25, "milp_solver": MILP_SOLVER,
                             "batteries": int(round(nb1)), **_stats(inst)})
                save(rows, path)
            for d2, ghi2 in days22:
                if ("eval", cand, d2, pv) in done:
                    continue
                inst2 = build_instance(3, 2.0, BREAKS, trip_list=fleet,
                                       delta_hourly=dh_of(ghi2, pv))
                inst2.c_g, inst2.c_b, inst2.rho, inst2.c_v = CG_COST, CB_COST, RHO, CV
                inst2.nb_fixed = nb1
                lp = solve_lp(inst2, sel, battery_allowed=True)
                ok = (lp.status == "optimal")
                rows.append({"kind": "eval", "cand": cand, "date": d2, "pv": pv,
                             "feasible": ok,
                             "total": (round(float(lp.obj), 1) if ok else None)})
                save(rows, path)
    print("HOLDOUT22 done", flush=True)


def gate():
    """Pre-launch oracle gate: DP vs independent Bellman-Ford on small instances
    across boundary/loss/station variants, plus reduced-cost replay. FAILS LOUD."""
    from pricing_truck import price_truck_dp, _dp_cost_via_networkx
    from master import solve_lp, Column, reduced_cost
    rows, path = ckpt(f"overnight13_gate_s{SH_I}of{SH_K}.json")
    rng = np.random.default_rng(7)
    n_cmp, n_col, worst = 0, 0, 0.0
    for k in range(120):
        if k % SH_K != SH_I:
            continue
        sd = int(rng.integers(0, 10_000))
        n = int(rng.integers(4, 9))
        eta = float(rng.choice([0.0, 0.1]))
        mode = str(rng.choice(["cyclic", "free", "periodic"]))
        allow_dis = bool(rng.choice([True, False]))
        use_nu = bool(rng.choice([True, False]))
        stations = rng.choice([None, "all"])
        fleet = rand_trips(3, n, sd, salt=11_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.0,
                              stations=(None if stations is None else "all"))
        inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
        inst.eta = eta
        cols = [Column("truck", np.eye(inst.n_trips)[i], np.zeros(inst.T), inst.c_v, f"t{i}")
                for i in range(inst.n_trips)]
        sol = solve_lp(inst, cols)
        if sol.status != "optimal":
            continue
        nu = (np.abs(rng.normal(0, 0.3, inst.T)) if use_nu else None)
        out = price_truck_dp(inst, sol.alpha, sol.mu, step=inst.soc_step, soc_mode=mode,
                             nu=nu, allow_discharge=allow_dis)
        from pricing_truck import _dp_cost_via_networkx_periodic, _dp_cost_via_networkx_at
        if mode == "periodic":
            rc_bf = _dp_cost_via_networkx_periodic(inst, sol.alpha, sol.mu,
                                                   step=inst.soc_step, nu=nu,
                                                   allow_discharge=allow_dis)
        elif mode == "cyclic":
            rc_bf = _dp_cost_via_networkx_at(inst, sol.alpha, sol.mu, step=inst.soc_step,
                                             nu=nu, allow_discharge=allow_dis)
        else:
            rc_bf = (_dp_cost_via_networkx(inst, sol.alpha, sol.mu, step=inst.soc_step,
                                           soc_mode="free")
                     if (nu is None and allow_dis) else None)
        if rc_bf is None:
            continue
        n_cmp += 1
        if out:
            col, rc_dp = out[0]
            rc_master = (reduced_cost(col, sol, inst) if nu is None else rc_dp)
            d1 = abs(rc_dp - rc_bf)
            d2 = abs(rc_dp - rc_master)
            worst = max(worst, d1, d2)
            n_col += 1
            if d1 > 1e-5 or d2 > 1e-5:
                sys.exit(f"GATE FAIL k={k} sd={sd} n={n} eta={eta} mode={mode} "
                         f"stations={stations}: rc_dp={rc_dp:.6f} rc_bf={rc_bf:.6f} "
                         f"rc_master={rc_master:.6f}")
        else:
            if rc_bf < -1e-5:
                sys.exit(f"GATE FAIL k={k}: DP found no column but BF found rc={rc_bf:.6f}")
    rows.append({"comparisons": n_cmp, "columns_checked": n_col,
                 "worst_abs_diff": worst, "commit": COMMIT, "status": "PASS"})
    save(rows, path)
    print(f"GATE PASS: {n_cmp} comparisons, {n_col} columns, worst |diff| {worst:.2e}", flush=True)


def align():
    """Lattice/theorem alignment: matched 50/25/12.5 kWh lossless solves (LP must
    agree at 25 vs 12.5 by Corollary 1) plus eta>0 refinement (12.5 vs 6.25)."""
    rows, path = ckpt(f"overnight13_align_s{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["pv"], r["seed"], r["scenario"], r["soc_step"], r["eta"])
            for r in rows}
    cells = []
    for sd in (0, 1):
        for n in (20, 60):
            for pv in (1.5, 2.5):
                for step in (0.5, 0.25, 0.125):
                    for scen in ("solar", "v2g"):
                        cells.append((sd, n, pv, 0.0, step, scen))
    for sd in (0, 1):
        for n in (20, 60):
            for step in (0.125, 0.0625):
                cells.append((sd, n, 2.5, 0.15, step, "v2g"))
    print(f"ALIGN: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, eta, step, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (n, pv, sd, scen, step, eta) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = step
        inst.eta = eta
        rows.append({"n_tasks": n, "pv": pv, "seed": sd, "eta": eta, "scenario": scen,
                     **_stats(inst), **_solve13(inst, scen, tl=600.0)})
        save(rows, path)
        print(f"  [{idx + 1}/{len(cells)}] n{n} pv{pv} eta{eta} step{step} {scen}", flush=True)


def diag2():
    """Corrected integer diagnostics on the U6 maps: incumbents preserved, full
    provenance, fresh checkpoint schema. Shard finely (12 shards = 2 cells each)."""
    from overnight3 import POOL
    rows, path = ckpt(f"overnight13_diag2_s{SH_I}of{SH_K}.json")
    done = {(r["L"], r["n_tasks"], r["seed"]) for r in rows}
    cells = [(L, n, sd) for L in (4, 15) for n in (100, 200, 400, 600, 800, 1000)
             for sd in (0, 1)]
    print(f"DIAG2: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (L, n, sd) in enumerate(cells):
        if idx % SH_K != SH_I or (L, n, sd) in done:
            continue
        fleet = rand_trips(L, n, 200 + sd)
        inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                              coords_override=POOL[:L], stations="all", pv_scale=2.0)
        r = _solve13(inst, "v2g", tl=1800.0)
        rows.append({"L": L, "n_tasks": n, "seed": sd, **r})
        save(rows, path)
        print(f"  L={L} n={n} sd={sd}: lp {r.get('lp_obj')} ip {r.get('total')} "
              f"({r.get('milp_status')})", flush=True)


def audit():
    """Solver audit: same column pool, final MILP solved by BOTH CBC and Gurobi,
    on a matched hard/easy subset. Records incumbents, bounds, times."""
    from overnight3 import POOL
    rows, path = ckpt(f"overnight13_audit_s{SH_I}of{SH_K}.json")
    done = {r["cell"] for r in rows}
    cells = [("bench_n60", 3, 60, 0, 2.0, None, 0.0), ("bench_n120", 3, 120, 0, 2.0, None, 0.0),
             ("cap_n60", 3, 60, 0, 2.5, "cap", 0.0), ("eta_n60", 3, 60, 0, 2.5, None, 0.15),
             ("ms_L4_n100", 4, 100, 0, 2.0, "ms", 0.0), ("ms_L15_n100", 15, 100, 0, 2.0, "ms", 0.0),
             ("ms_L4_n200", 4, 200, 0, 2.0, "ms", 0.0), ("bench_n20", 3, 20, 0, 2.0, None, 0.0)]
    print(f"AUDIT: {len(cells)} cells x 2 solvers, shard {SH_I}/{SH_K}", flush=True)
    for idx, (name, L, n, sd, pv, kind, eta) in enumerate(cells):
        if idx % SH_K != SH_I or name in done:
            continue
        if kind == "ms":
            fleet = rand_trips(L, n, 200 + sd)
            inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                                  coords_override=POOL[:L], stations="all", pv_scale=pv)
        else:
            fleet = rand_trips(3, n, sd, salt=50_000)
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.soc_step = 0.25
            inst.eta = eta
            if kind == "cap":
                inst.gen_cap = 1.1 * float(np.maximum(inst.Delta, 0.0).max())
        inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
        res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                enrich=25, max_iter=max(2000, 5 * inst.n_trips))
        row = {"cell": name, "lp_obj": round(res["lp_obj"], 2), "commit": COMMIT,
               "cg_converged": res.get("converged")}
        for solver in ("cbc", "gurobi"):
            t0 = time.time()
            try:
                mip = solve_milp(inst, res["cols"], time_limit=1800.0,
                                 battery_allowed=True, solver=solver)
                row[solver] = {"obj": (None if not np.isfinite(mip.obj) else round(mip.obj, 2)),
                               "status": mip.status,
                               "bound": getattr(mip, "solver_bound", None),
                               "time_s": round(time.time() - t0, 1)}
            except Exception as ex:
                row[solver] = {"error": str(ex)[:200]}
        rows.append(row)
        save(rows, path)
        print(f"  {name}: cbc {row.get('cbc')} | grb {row.get('gurobi')}", flush=True)


def fourarmx():
    """Extra task draws (seeds 3-9) in the activation region gamma ~ 0.2-0.6."""
    rows, path = ckpt(f"overnight13_fourarmx_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    cells = [(sd, n, pv, arm) for sd in range(3, 10) for n in (20, 60, 120)
             for pv in (1.5, 1.75, 2.0, 2.5) for arm in ARMS4]
    print(f"FOURARMX: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, arm) in enumerate(cells):
        if idx % SH_K != SH_I or (pv, n, sd, arm) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25
        rows.append({"pv": pv, "n_tasks": n, "seed": sd, "scenario": arm,
                     **_stats(inst), **_solve13(inst, arm, tl=900.0)})
        save(rows, path)
        if idx % 16 == 0:
            print(f"  [{idx + 1}/{len(cells)}]", flush=True)


def sun2():
    """Solar-shortfall ladder, corrected: four arms, 25 kWh lattice, honest statuses."""
    from profile_robustness import base_curves
    rows, path = ckpt(f"overnight13_sun2_s{SH_I}of{SH_K}.json")
    done = {(r["kind"], str(r["level"]), r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    D, S = base_curves()
    UNI = [0.9, 0.8, 0.7, 0.6, 0.5, 0.3, 0.1]
    CLOUD = {"c10_12": (10, 12), "c12_14": (12, 14), "c14_16": (14, 16),
             "c10_14": (10, 14), "c12_16": (12, 16)}
    arms = [("uniform", u) for u in UNI] + [("cloud", w) for w in CLOUD]
    cells = [(sd, n, pv, scen) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for scen in ARMS4]
    print(f"SUN2: {len(cells)} bases x {len(arms)} arms, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, scen) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if all((k, str(v), pv, n, sd, scen) in done for k, v in arms):
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        dh0 = np.round(D - pv * S).astype(int)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, delta_hourly=dh0)
        inst0.soc_step = 0.25
        base_cap = 1.5 * float(np.maximum(inst0.Delta, 0.0).max())
        inst0.gen_cap = base_cap
        s1 = _solve13(inst0, scen, tl=300.0)
        if not s1.get("feasible"):
            continue
        for kind, v in arms:
            if (kind, str(v), pv, n, sd, scen) in done:
                continue
            Sd = pv * S.copy()
            if kind == "uniform":
                Sd = v * Sd
            else:
                a, b = CLOUD[v]
                Sd[a:b] = 0.0
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet,
                                  delta_hourly=np.round(D - Sd).astype(int))
            inst.soc_step = 0.25
            inst.gen_cap = base_cap
            inst.max_trucks = s1["trucks"]
            inst.nb_fixed = float(s1["batteries"])
            r = _solve13(inst, scen, tl=300.0)
            rows.append({"kind": kind, "level": v, "pv": pv, "n_tasks": n, "seed": sd,
                         "scenario": scen, "stage1_trucks": s1["trucks"],
                         "stage1_batteries": s1["batteries"],
                         "stage1_total": s1["total"], **_stats(inst0), **r})
            save(rows, path)
        if idx % 8 == 0:
            print(f"  [{idx + 1}/{len(cells)}]", flush=True)


def chargecaps():
    """Charging-cap panel, corrected: four arms, generation uncapped, 25 kWh,
    with peak charging-cap utilization recorded. Replaces fig capsfrontier(b)."""
    rows, path = ckpt(f"overnight13_chargecaps_s{SH_I}of{SH_K}.json")
    done = {(str(r["chg_c"]), r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    CHG = [0.35, 0.5, 0.7, 1.0, 1.4, float("inf")]
    cells = [(sd, n, c, arm) for sd in (0, 1, 2) for n in (20, 60, 120)
             for c in CHG for arm in ARMS4]
    print(f"CHARGECAPS: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, c, arm) in enumerate(cells):
        key_c = "inf" if not np.isfinite(c) else c
        if idx % SH_K != SH_I or (str(key_c), n, sd, arm) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
        inst.soc_step = 0.25
        peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
        inst.charge_cap = c * peak_sur if np.isfinite(c) else float("inf")
        rows.append({"chg_c": key_c, "n_tasks": n, "seed": sd, "scenario": arm,
                     "pv": 2.5, **_stats(inst),
                     **_solve13(inst, arm, tl=300.0, want_profile=True)})
        save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}]", flush=True)


def pack4():
    """Fresh tight-gap pack x workload cells (replaces the legacy-schema PACK3):
    G x n in {120,200}, six draws, v2g, 25 kWh, tl 1800."""
    rows, path = ckpt(f"overnight13_pack4_s{SH_I}of{SH_K}.json")
    done = {(r["G"], r["n_tasks"], r["seed"]) for r in rows}
    cells = [(sd, n, G) for sd in range(6) for n in (120, 200)
             for G in (3.5, 7.0, 10.5, 14.0)]
    print(f"PACK4: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, G) in enumerate(cells):
        if idx % SH_K != SH_I or (G, n, sd) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=90_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.0)
        inst.soc_step = 0.25
        inst.G = G
        rows.append({"G": G, "n_tasks": n, "seed": sd, "pv": 2.0, "scenario": "v2g",
                     **_stats(inst),
                     **_solve13(inst, "v2g", tl=1800.0, c_b=CB_COST * G / 7.0)})
        save(rows, path)
        print(f"  G={G} n={n} sd={sd}: {rows[-1].get('total')} ({rows[-1].get('outcome')})",
              flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    FN = {"FOURARM": fourarm, "FOURCAPS": fourcaps, "W2": w2, "EXPORT2": export2,
          "REGIME2": regime2, "SPINE25": spine25, "ETA125": eta125,
          "PERIODIC": periodic, "HOLDOUT22": holdout22, "GATE": gate, "ALIGN": align,
          "DIAG2": diag2, "AUDIT": audit, "FOURARMX": fourarmx, "SUN2": sun2,
          "CHARGECAPS": chargecaps, "PACK4": pack4}
    _known = {s.strip().upper() for s in FN}
    _bad = [s for s in STUDIES if s.strip().upper() not in _known]
    if _bad:
        sys.exit(f"unknown OVERNIGHT13_STUDIES entries: {_bad} -- known: {sorted(FN)}")
    for s in STUDIES:
        s = s.strip().upper()
        print(f"=== {s} ===", flush=True)
        FN[s]()
    print(f"overnight13 done in {(time.time() - t0) / 3600:.2f} h", flush=True)
