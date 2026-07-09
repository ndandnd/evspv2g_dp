"""
Overnight-10: the siesta stress test and the stochastic-deployment study.

  SCHED3 : does "siesta never wins" survive the confounds? The overnight8
           design confounded window PLACEMENT with window WIDTH (siesta had 10
           start-hours vs uniform's 14, mechanically forcing parallelism).
           SCHED3 orthogonalizes them -- uniform14/uniform10/siesta14/siesta10
           plus midday6 -- and crosses the corners where the folk intuition
           should win if it ever does: no stationary storage (v2g_fleet,
           solar) and a tight charging cap (0.5x peak surplus), where idle
           trucks during the surplus are the only absorption capacity.
  THEORY : the mechanism check. Claim: with ample storage and uncapped
           charging, the energy layer is timetable-invariant and schedules
           differ ONLY through fleet size x deadhead overhead. Prediction:
           setting deadhead energy = 0 and truck cost = 0 collapses the fuel
           spread across ALL families to ~0. If confirmed, this becomes a
           Remark; if refuted, the story is wrong.
  STOCH  : Anna's request. Net demand made stochastic via the 365 real 2023
           days. First stage (committed day-ahead): truck routes WITH their
           charging plans, and the battery count -- solved on a candidate
           design day (annual mean or one of 12 monthly means). Recourse:
           only the stationary battery dispatch and fossil generation adapt
           (the master LP re-solved with the committed columns and nb_fixed).
           Reported per candidate: E[cost], p10/p90, regret vs the
           wait-and-see bound, and the "average deployment" pick = the
           candidate minimizing mean cost across the year.

Run: OVERNIGHT10_STUDIES="SCHED3,THEORY,STOCH" OVERNIGHT10_SHARD="i/K" python3 overnight10.py
"""
from __future__ import annotations
import os, sys, json, time, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from colgen import column_generation, SCENARIOS
from master import solve_lp, solve_milp
from overnight3 import ckpt, save, solve, rand_trips, CG_COST, CB_COST, RHO, CV, MILP_SOLVER
from profile_robustness import base_curves
from solar_ensemble import load_days

STUDIES = os.environ.get("OVERNIGHT10_STUDIES", "SCHED3,THEORY,STOCH").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT10_SHARD", "0/1").split("/"))
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "results", "arxiv")

FAM3 = {"uniform14": [(6, 20)], "uniform10": [(8, 18)],
        "siesta14": [(2, 9), (16, 23)], "siesta10": [(4, 9), (18, 23)],
        "midday6": [(9, 15)]}


def _tasks3(n, seed, fam):
    rng_loc = np.random.default_rng(120_000 + 1_000 * seed + n)   # same geography as SCHED
    rng_t = np.random.default_rng(140_000 + 1_000 * seed + n
                                  + 10_007 * list(FAM3).index(fam))
    wins = FAM3[fam]
    out = []
    for _ in range(n):
        i = int(rng_loc.integers(1, 4)); j = int(rng_loc.integers(1, 4))
        while j == i:
            j = int(rng_loc.integers(1, 4))
        a, b = wins[int(rng_t.integers(0, len(wins)))]
        out.append((i, j, int(rng_t.integers(a, b))))
    return out


def _stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3)}


def _row(base, scen, r, **extra):
    if r is None:
        return {**base, "scenario": scen, "feasible": False, **extra}
    return {**base, "scenario": scen, "feasible": True, "total": round(r["total"], 1),
            "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
            "batteries": r["batteries"], "gap_pct": round(r["gap"], 3), **extra}


def sched3():
    rows, path = ckpt(f"overnight10_sched3_s{SH_I}of{SH_K}.json")
    done = {(r["fam"], r["kcap"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    cells = [(sd, n, pv, kc, fam, scen) for sd in (0, 1, 2) for n in (40, 80)
             for pv in (1.5, 2.5) for kc in (float("inf"), 0.5)
             for fam in FAM3 for scen in ("solar", "v2g_fleet", "v2g")]
    print(f"SCHED3: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, kc, fam, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (fam, kc, pv, n, sd, scen) in done:
            continue
        fleet = _tasks3(n, sd, fam)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"fam": fam, "kcap": kc, "pv": pv, "n_tasks": n, "seed": sd, **_stats(inst)}
        if np.isfinite(kc):
            inst.charge_cap = kc * float(np.maximum(-inst.Delta, 0.0).max())
        rows.append(_row(base, scen, solve(inst, scen, tl=120.0)))
        save(rows, path)
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def theory():
    """epd=0, cv=0, storage on, charging uncapped: fuel spread should collapse."""
    rows, path = ckpt(f"overnight10_theory_s{SH_I}of{SH_K}.json")
    done = {(r["fam"], r["n_tasks"], r["seed"]) for r in rows}
    cells = [(sd, n, fam) for sd in (0, 1, 2) for n in (40, 80) for fam in FAM3]
    print(f"THEORY: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, fam) in enumerate(cells):
        if idx % SH_K != SH_I or (fam, n, sd) in done:
            continue
        fleet = _tasks3(n, sd, fam)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
        inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, 0.0
        inst.energy_per_dist = 0.0                     # no deadhead energy
        res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                enrich=25, max_iter=max(2000, 5 * n))
        if res["lp_obj"] == float("inf"):
            continue
        mip = solve_milp(inst, res["cols"], time_limit=120.0,
                         battery_allowed=True, solver=MILP_SOLVER)
        if getattr(mip, "status", "optimal") != "optimal" or not np.isfinite(mip.obj):
            continue
        rows.append({"fam": fam, "n_tasks": n, "seed": sd, **_stats(inst),
                     "total": round(mip.obj, 1), "g_units": round(float(mip.g.sum()), 2),
                     "trucks": int(sum(round(x) for x in mip.x)),
                     "batteries": int(round(mip.nb))})
        save(rows, path)
        print(f"  {fam} n={n} sd={sd}: g={rows[-1]['g_units']}", flush=True)


def stoch():
    rows, path = ckpt(f"overnight10_stoch_s{SH_I}of{SH_K}.json")
    done = {(r["kind"], r["cand"], r.get("date", "-"), r["pv"]) for r in rows}
    days = load_days()
    D, S = base_curves()
    socal_mean = np.mean([d[1].sum() for d in days])
    by_m = collections.defaultdict(list)
    for d, g in days:
        by_m[d[5:7]].append(g)
    cands = {"annual": np.mean([g for _, g in days], axis=0)}
    for m, gs in sorted(by_m.items()):
        cands[f"m{m}"] = np.mean(gs, axis=0)
    fleet = rand_trips(3, 60, 0, salt=50_000)

    def dh_of(ghi, pv):
        return np.round(D - ghi * (S.sum() * pv / socal_mean)).astype(int)

    PVS = [2.0, 3.0]
    cells = ([("ws", "-", date, pv) for pv in PVS for date, _ in days]
             + [("cand", c, "-", pv) for pv in PVS for c in cands])
    print(f"STOCH: {len(cells)} stage-1/WS cells + evals, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (kind, cand, date, pv) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if kind == "ws":
            if ("ws", "-", date, pv) in done:
                continue
            ghi = dict(days)[date]
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, delta_hourly=dh_of(ghi, pv))
            rows.append(_row({"kind": "ws", "cand": "-", "date": date, "pv": pv,
                              **_stats(inst)}, "v2g", solve(inst, "v2g", tl=60.0)))
            save(rows, path)
        else:
            # stage 1 on the candidate design day, then 365 recourse evaluations
            if all(("eval", cand, d, pv) in done for d, _ in days) \
               and ("cand", cand, "-", pv) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet,
                                  delta_hourly=dh_of(cands[cand], pv))
            s1 = solve(inst, "v2g", tl=180.0)
            if s1 is None:
                continue
            sel = [c for c, x in zip(s1["cols"], s1["mip"].x) if x > 0.5]
            nb1 = float(s1["batteries"])
            if ("cand", cand, "-", pv) not in done:
                rows.append(_row({"kind": "cand", "cand": cand, "date": "-", "pv": pv,
                                  **_stats(inst)}, "v2g", s1))
                save(rows, path)
            for d2, ghi2 in days:
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
                             "total": (round(lp.obj, 1) if ok else None),
                             "g_units": (round(float(lp.g.sum()), 2) if ok else None)})
                save(rows, path)
            print(f"  cand {cand} pv={pv}: evals done ({len(rows)} rows)", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    FN = {"SCHED3": sched3, "THEORY": theory, "STOCH": stoch}
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time(); FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
