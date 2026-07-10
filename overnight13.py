"""
Overnight-13: the correction round. Every study records honest solver status
(optimal / feasible-incumbent), CG convergence, and Phase-I artificial counts.

  FOURARM   : the V2G x BESS factorial that identifies the treatment effects the
              two-arm design confounded: arms {solar, solar_bess, v2g_fleet, v2g}
              over pv {1..4} x n {20,60,120} x 3 draws. 324 bases. tl 900.
  FOURCAPS  : the generation-cap feasibility cliff re-run with all four arms
              (does charge-only + BESS survive tight caps?): gen_m {1.0,1.05,
              1.1,1.2,1.3,inf} x n {20,60,120} x 3 draws at pv 2.5, charging
              cap 0.7x trough. 216 cells. tl 300.
  W2        : weather-year rerun on the REPAIRED deterministic base (BREAKS2:
              all 60 tasks individually feasible): 365 days x pv {1,1.5,2,2.5,3}
              x arms {solar, solar_bess, v2g}. 5,475 solves. tl 60.
  EXPORT2   : honest-export table rerun on BREAKS2-window fleets:
              n 20..200 x pv 7 levels, v2g. 70 solves. tl 300.
  REGIME2   : regime ladder rerun on the repaired deterministic base:
              {vsp, ev, solar, solar_bess, v2g_fleet, v2g} x n {20,60,120}
              x pv {1,2,3}. 162 solves. tl 300.
  SPINE25   : the one-factor spine re-run at delta = 25 kWh (the step at which
              every energy and rate quantum divides, so the oracle is exact for
              the planning family). 240 cells. tl 300.
  ETA125    : the round-trip-loss sweep at delta = 12.5 kWh (minimizes the
              rate-quantization confound): eta {0,.05,.1,.15,.2,.3} x n {20,60}
              x 2 draws x {solar, v2g}. 144 cells. tl 300.
  PERIODIC  : the steady-state boundary robustness Anna asked for: truck
              s0 = sT with the level free (soc_mode="periodic"): export subgrid
              n {20,60,100,140} x pv {1,1.5,2,2.5,3} (v2g) + the reference-cell
              four arms x 3 draws. 32 solves, each ~15x pricing cost. tl 600.
  HOLDOUT22 : out-of-sample test of the committed-schedule study: candidates =
              2023 annual + monthly mean days (design year), evaluated on all
              365 days of 2022 (holdout year) at pv {2,3}, plus the 2022
              perfect-foresight floor. tl 180/60.

Run: OVERNIGHT13_STUDIES="..." OVERNIGHT13_SHARD="i/K" python3 overnight13.py
Suggested shards: FOURARM 6, FOURCAPS 2, W2 8, EXPORT2 1, REGIME2 1,
SPINE25 3, ETA125 2, PERIODIC 2, HOLDOUT22 3.
All studies checkpoint per row (atomic) and skip done cells, so they are
preemption/requeue safe on default_partition.
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


def _solve13(inst, scen, tl=300.0, soc_mode="cyclic", c_b=None, rho=None):
    """Full-status solve: CG + restricted MILP, honest statuses, artificial count."""
    inst.c_g, inst.c_v = CG_COST, CV
    inst.c_b = CB_COST if c_b is None else c_b
    inst.rho = RHO if rho is None else rho
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips),
                            soc_mode=soc_mode)
    out = {"cg_converged": res.get("converged"), "cg_term": res.get("term_reason"),
           "lp_obj": (None if not np.isfinite(res["lp_obj"]) else round(res["lp_obj"], 2))}
    if not np.isfinite(res["lp_obj"]):
        out.update({"feasible": False, "milp_status": "lp_infeasible"})
        return out
    mip = solve_milp(inst, res["cols"], time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"],
                     solver=MILP_SOLVER, soc_mode=soc_mode)
    out["milp_status"] = mip.status
    if mip.status == "milp_failed" or not np.isfinite(mip.obj):
        out["feasible"] = False
        return out
    n_art = sum(1 for c, x in zip(res["cols"], mip.x)
                if x > 0.5 and getattr(c, "kind", "") == "artificial")
    out.update({"artificials": n_art,
                "feasible": (n_art == 0),
                "total": round(mip.obj, 1), "g_units": round(float(mip.g.sum()), 2),
                "trucks": int(sum(round(x) for c, x in zip(res["cols"], mip.x)
                                  if x > 0.5 and getattr(c, "kind", "") == "truck")),
                "batteries": int(round(mip.nb)),
                "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)})
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
        baseline = float(np.maximum(inst.Delta, 0.0).sum())
        r = _solve13(inst, "v2g", tl=300.0)
        incr = (None if not r.get("feasible") else round((r["g_units"] - baseline) / 10, 2))
        rows.append({"n_tasks": n, "pv": pv, "baseline_mwh": round(baseline / 10, 1),
                     "incr_mwh": incr, **_stats(inst), **r})
        save(rows, path)
    print("EXPORT2 done", flush=True)


def regime2():
    rows, path = ckpt(f"overnight13_regime2_s{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["pv"], r["scenario"]) for r in rows}
    SCENS = ["vsp", "ev", "solar", "solar_bess", "v2g_fleet", "v2g"]
    cells = [(n, pv, sc) for n in (20, 60, 120) for pv in (1.0, 2.0, 3.0) for sc in SCENS]
    print(f"REGIME2: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (n, pv, sc) in enumerate(cells):
        if idx % SH_K != SH_I or (n, pv, sc) in done:
            continue
        inst = build_instance(3, 2.0, BREAKS2, pv_scale=pv)
        if n != 60:
            inst = build_instance(3, 2.0, BREAKS2, pv_scale=pv,
                                  trip_list=[(t.sloc, t.eloc, t.start / 2) for t in
                                             build_instance(3, 2.0, BREAKS2).trips][:n])
        rows.append({"n_tasks": inst.n_trips, "pv": pv, "scenario": sc, **_stats(inst),
                     **_solve13(inst, sc, tl=300.0)})
        save(rows, path)
    print("REGIME2 done", flush=True)


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
             for scen in ("solar", "v2g")]
    print(f"SPINE25: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, f, v, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (f, str(v), sd, scen) in done:
            continue
        n = int(v) if f == "n" else 60
        pv = float(v) if f == "pv" else 2.0
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.soc_step = 0.25
        base = {"factor": f, "value": (None if not np.isfinite(v) else v),
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
             for scen in ("solar", "v2g")]
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


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    FN = {"FOURARM": fourarm, "FOURCAPS": fourcaps, "W2": w2, "EXPORT2": export2,
          "REGIME2": regime2, "SPINE25": spine25, "ETA125": eta125,
          "PERIODIC": periodic, "HOLDOUT22": holdout22}
    _known = {s.strip().upper() for s in FN}
    _bad = [s for s in STUDIES if s.strip().upper() not in _known]
    if _bad:
        sys.exit(f"unknown OVERNIGHT13_STUDIES entries: {_bad} -- known: {sorted(FN)}")
    for s in STUDIES:
        s = s.strip().upper()
        print(f"=== {s} ===", flush=True)
        FN[s]()
    print(f"overnight13 done in {(time.time() - t0) / 3600:.2f} h", flush=True)
