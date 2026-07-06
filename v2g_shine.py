"""
Where does V2G shine? Small fleets under generous sun.

Fig 8.9's 1x panel shows EVSP-Solar and EVSP-V2G coinciding -- the R < 0.4
dead zone. This study maps the opposite corner: tiny fleets (4-20 tasks) whose
traction energy is small next to the site's PV, sweeping BOTH solar intensity
(panel build-out 0.75x-4x) and solar duration (a summer day: longer daylight,
1.6x energy at 1x panels, scaled by the same build-out factor). Each cell uses
the SAME trip set across all solar levels/shapes and is solved three ways:

    solar     : charge-only fleet, no stationary storage
    v2g_fleet : bidirectional trucks only (vehicle-to-grid proper)
    v2g       : full tech stack (bidirectional trucks + stationary batteries)

so a figure can show when adding V2G technology beats simply buying more
panels, and how much of that value the trucks deliver on their own.
Prices match overnight2/S12 (c_g 40, c_b 36, rho 1.75, c_v 45) so results sit
on the same footing as Fig 8.9.

Run: python3 v2g_shine.py    (tiny instances; ~20-40 min for the full grid)
Env: V2G_SHINE_TASKS="4,8,12,16,20"  V2G_SHINE_PVS="0.75,1.0,1.5,2.0,3.0,4.0"
     V2G_SHINE_SEEDS=3  V2G_SHINE_SHARD="i/K"
Output: results/arxiv/v2g_shine.json  (per-row checkpoint; safe to kill/rerun)
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI
from profile_robustness import base_curves
from solar_ensemble import sample_trips
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
TASKS  = [int(x) for x in os.environ.get("V2G_SHINE_TASKS", "4,8,12,16,20").split(",")]
PVS    = [float(x) for x in os.environ.get("V2G_SHINE_PVS", "0.75,1.0,1.5,2.0,3.0,4.0").split(",")]
SHAPES = ["std", "summer"]
N_SEEDS = int(os.environ.get("V2G_SHINE_SEEDS", "3"))
SCENS  = ["solar", "v2g_fleet", "v2g"]
EPS, POINTS = 2.0, 3
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
SH_I, SH_K = (int(x) for x in os.environ.get("V2G_SHINE_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def summer_delta(pv):
    """Hourly demand-minus-solar for a longer, brighter day at build-out pv:
    same bell as overnight2/S12 (peak 13h, sd 4.2h, lit 4.5-21.5h), carrying
    1.6x the standard day's solar energy, times the build-out factor."""
    Dh, Sh = base_curves()
    hh = np.arange(24)
    bell = np.exp(-0.5 * ((hh - 13.0) / 4.2) ** 2)
    bell[(hh < 4.5) | (hh > 21.5)] = 0.0
    return np.round(Dh - bell * (Sh.sum() * 1.6 * pv / bell.sum())).astype(int)


def make_inst(shape, pv, fleet):
    if shape == "summer":
        return build_instance(POINTS, EPS, BREAKS, delta_hourly=summer_delta(pv),
                              trip_list=fleet)
    return build_instance(POINTS, EPS, BREAKS, pv_scale=pv, trip_list=fleet)


def solve(inst, scen):
    inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    return {"total": mip.obj, "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)), "g_units": float(mip.g.sum()),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "v2g_shine.json" if SH_K == 1
                        else f"v2g_shine_s{SH_I}of{SH_K}.json")
    rows = json.load(open(path)) if os.path.exists(path) else []
    done = {(r["n_tasks"], r["seed"], r["shape"], r["pv"], r["scenario"]) for r in rows}
    cells = [(n, sd, sh, pv) for n in TASKS for sd in range(N_SEEDS)
             for sh in SHAPES for pv in PVS]
    print(f"v2g_shine: {len(cells)} cells x {len(SCENS)} regimes, "
          f"shard {SH_I}/{SH_K} ({len(done)} rows done)  MILP: {MILP_SOLVER}", flush=True)
    t0 = time.time()
    for idx, (n, seed, shape, pv) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        # SAME trips for every (solar level, shape, regime) at this (n, seed)
        fleet = sample_trips(np.random.default_rng(900 + 1000 * seed + n), POINTS, n)
        inst0 = make_inst(shape, pv, fleet)
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        base = {"n_tasks": n, "seed": seed, "shape": shape, "pv": pv,
                "surplus_mwh": round(surplus / 10, 2),
                "traction_mwh": round(traction / 10, 2),
                "ratio": round(surplus / max(traction, 1e-9), 2),
                "baseline_mwh": round(float(np.maximum(inst0.Delta, 0.0).sum()) / 10, 2)}
        for scen in SCENS:
            if (n, seed, shape, pv, scen) in done:
                continue
            r = solve(make_inst(shape, pv, fleet), scen)
            if r is None:
                continue
            rows.append({**base, "scenario": scen,
                         "total": round(r["total"], 1), "trucks": r["trucks"],
                         "batteries": r["batteries"],
                         "fossil_mwh": round(r["g_units"] / 10, 2),
                         "gap_pct": round(r["gap"], 3)})
            json.dump(rows, open(path, "w"))
        if idx % 10 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows, "
                  f"{(time.time() - t0) / 60:.1f} min]", flush=True)
    print(f"done: {len(rows)} rows in {(time.time() - t0) / 60:.1f} min -> {path}")


if __name__ == "__main__":
    main()
