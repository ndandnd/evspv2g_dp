"""
Overnight-5: the (tasks x solar) boundary story + follow-ups from overnight-4.
Same conventions: per-row atomic checkpoints, idx%K sharding, seed-outermost
cell order. No time limits -- studies are sized to ~5-8 h per shard.

  BOUNDARY : densify the (n_tasks x solar) plane at pv in {1.25,1.5,1.75,2.5,3.5}
             (the levels U2 does NOT cover), n from 4 to 280, solar vs v2g,
             3 seeds. Every row records surplus/traction/R. Feeds the new
             Fig 8.14: the V2G>Solar advantage region in the (tasks, solar)
             plane, whose fade-out boundary is a level set of R (~0.4-0.5) --
             the same constant as Fig 8.5's computed enablement break-even.
             Analysis merges U2 (1x-4x, n<=200) + MODESX (3x/sum2x to 400).
  MODESX2  : completes Fig 8.9's panels -- 4x to 400 tasks (seeds 0,1) and a
             third seed for 3x/sum2x at 240-400. Writes overnight3_modes_sX2*
             (picked up by the existing Fig 8.9 glob).
  CAPS2    : densify the feasibility cliff found by overnight-4 CAPS: at a
             generation cap equal to the no-fleet peak, charge-only fleets are
             INFEASIBLE while V2G fleets still operate. gen_m in
             {1.0,1.05,1.1,1.2} x chg_c in {0.5,0.7,1.0} x n up to 120
             (plus an n=200 arm at chg_c=0.7), 3 seeds; dedups against the
             overnight-4 CAPS grid. Writes overnight4_caps2_s* (merged by the
             caps figure glob overnight4_caps*).

Run:   OVERNIGHT5_STUDIES="BOUNDARY,MODESX2,CAPS2" OVERNIGHT5_SHARD="i/K" \
       python3 overnight5.py
"""
from __future__ import annotations
import os, sys, json, time, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from overnight3 import ckpt, save, solve, rand_trips, sol_kwargs

# ============================== CONFIG -- EDIT ME ==============================
STUDIES = os.environ.get("OVERNIGHT5_STUDIES", "BOUNDARY,MODESX2,CAPS2").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT5_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def _base_stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3)}


def boundary():
    """(n x pv) densify at the pv levels U2 lacks; solar vs v2g; R recorded."""
    rows, path = ckpt(f"overnight5_boundary_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    PVS = [1.25, 1.5, 1.75, 2.5, 3.5]
    NT = list(range(4, 44, 4)) + list(range(50, 201, 10)) + [240, 280]
    cells = [(sd, pv, n) for sd in (0, 1, 2) for pv in PVS for n in NT]
    print(f"BOUNDARY: {len(cells)} cells x 2, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, pv, n) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)          # same family as U2/modes
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"pv": pv, "n_tasks": n, "seed": sd, **_base_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            r = solve(inst, scen, tl=120.0)
            if r is None:
                continue
            rows.append({**base, "scenario": scen, "total": round(r["total"], 1),
                         "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                         "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
            save(rows, path)
        if idx % 25 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows]", flush=True)


def modesx2():
    """Fig 8.9 completion: 4x to 400 (seeds 0,1) + seed 2 for 3x/sum2x 240-400."""
    rows, path = ckpt(f"overnight3_modes_sX2_{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["sol"], r["seed"], r["scenario"]) for r in rows}
    NT = [240, 280, 320, 360, 400]
    cells = ([(sd, n, "4x", scen) for sd in (0, 1) for n in NT
              for scen in ("vsp", "ev", "solar", "v2g")]
             + [(2, n, sol, scen) for n in NT for sol in ("3x", "sum2x")
                for scen in ("vsp", "ev", "solar", "v2g")])
    print(f"MODESX2: {len(cells)} cells, shard {SH_I}/{SH_K} "
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


def caps2():
    """Feasibility-cliff densify around gen_m ~ 1; dedups vs the overnight-4 grid."""
    rows, path = ckpt(f"overnight4_caps2_s{SH_I}of{SH_K}.json")
    done = {(r["gen_m"], r["chg_c"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    for p in glob.glob(os.path.join(OUT, "overnight4_caps_s*.json")):   # cross-file dedup
        for r in json.load(open(p)):
            done.add((r["gen_m"], r["chg_c"], r["n_tasks"], r["seed"], r["scenario"]))
    PV = 2.5
    GEN_M = [1.0, 1.05, 1.1, 1.2]
    CHG_C = [0.5, 0.7, 1.0]
    cells = ([(sd, n, m, c) for sd in (0, 1, 2) for n in (20, 60, 120)
              for m in GEN_M for c in CHG_C]
             + [(sd, 200, m, 0.7) for sd in (0, 1, 2) for m in GEN_M])
    print(f"CAPS2: {len(cells)} cells x 2, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, m, c) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=PV)
        peak_def = float(np.maximum(inst0.Delta, 0.0).max())
        peak_sur = float(np.maximum(-inst0.Delta, 0.0).max())
        base = {"gen_m": m, "chg_c": c, "pv": PV, "n_tasks": n, "seed": sd,
                "gen_cap": round(m * peak_def, 2), "charge_cap": round(c * peak_sur, 2),
                **_base_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (m, c, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=PV)
            inst.gen_cap = m * peak_def
            inst.charge_cap = c * peak_sur
            r = solve(inst, scen, tl=120.0)
            if r is None:
                rows.append({**base, "scenario": scen, "feasible": False})
                save(rows, path)
                continue
            mip = r["mip"]
            chg = np.zeros(inst.T)
            for col, x in zip(r["cols"], mip.x):
                if x > 0.5:
                    chg += np.maximum(col.e, 0.0) * round(x)
            if getattr(mip, "charge", None) is not None:
                chg += mip.charge
            rows.append({**base, "scenario": scen, "feasible": True,
                         "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                         "trucks": r["trucks"], "batteries": r["batteries"],
                         "gap_pct": round(r["gap"], 3),
                         "gen_util": round(float(mip.g.max()) / (m * peak_def), 3),
                         "chg_util": round(float(chg.max()) / (c * peak_sur), 3)})
            save(rows, path)
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows]", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    FN = {"BOUNDARY": boundary, "MODESX2": modesx2, "CAPS2": caps2}
    _known = {s.strip().upper() for s in FN}
    _bad = [s for s in STUDIES if s.strip().upper() not in _known]
    if _bad:
        sys.exit(f"unknown OVERNIGHT5_STUDIES entries: {_bad} -- known: {sorted(FN)}")
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time()
        FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
