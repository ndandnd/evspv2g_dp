"""
Overnight-6: two follow-ups from the figure review. Same conventions as
overnight3/4/5 (atomic per-row checkpoints, idx%K shards, seed-outermost).

  CAPS3  : charging-cap resolution + seeds for Fig 8.16(b). chg_c in
           {0.35,0.5,0.7,1.0,1.4,inf} at UNCAPPED generation, n in {20,60,120},
           seeds 0-5, solar vs v2g. Dedups against CAPS/CAPS2 grids. Gives the
           matched value-vs-charging-cap lines proper resolution and error bars.
  SATFIX : the true concavity view that Fig 8.6 failed to show: FIXED fleet
           and duty, fine solar ladder (pv 1.00-4.00 step 0.25), so absorption
           saturates through the fleet+storage capacity rather than being
           bought away. Feeds a fuel-vs-solar curve whose marginal displacement
           shrinks (Theorem 1's signature), n in {20,60}, seeds 0-2.

Run:   OVERNIGHT6_STUDIES="CAPS3,SATFIX" OVERNIGHT6_SHARD="i/K" python3 overnight6.py
"""
from __future__ import annotations
import os, sys, json, time, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from overnight3 import ckpt, save, solve, rand_trips

STUDIES = os.environ.get("OVERNIGHT6_STUDIES", "CAPS3,SATFIX").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT6_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")


def _stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3)}


def caps3():
    rows, path = ckpt(f"overnight4_caps3_s{SH_I}of{SH_K}.json")
    done = {(r["gen_m"], r["chg_c"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    for p in glob.glob(os.path.join(OUT, "overnight4_caps_s*.json")) + \
             glob.glob(os.path.join(OUT, "overnight4_caps2_s*.json")):
        for r in json.load(open(p)):
            done.add((r["gen_m"], r["chg_c"], r["n_tasks"], r["seed"], r["scenario"]))
    PV = 2.5
    CHG = [0.35, 0.5, 0.7, 1.0, 1.4, float("inf")]
    cells = [(sd, n, c) for sd in range(6) for n in (20, 60, 120) for c in CHG]
    print(f"CAPS3: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, c) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=PV)
        peak_sur = float(np.maximum(-inst0.Delta, 0.0).max())
        base = {"gen_m": float("inf"), "chg_c": c, "pv": PV, "n_tasks": n, "seed": sd,
                "charge_cap": (round(c * peak_sur, 2) if np.isfinite(c) else None), **_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (float("inf"), c, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=PV)
            inst.charge_cap = c * peak_sur if np.isfinite(c) else float("inf")
            r = solve(inst, scen, tl=120.0)
            if r is None:
                rows.append({**base, "scenario": scen, "feasible": False})
            else:
                rows.append({**base, "scenario": scen, "feasible": True,
                             "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                             "trucks": r["trucks"], "batteries": r["batteries"],
                             "gap_pct": round(r["gap"], 3)})
            save(rows, path)
        if idx % 15 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def satfix():
    rows, path = ckpt(f"overnight6_satfix_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    PVS = [round(1.0 + 0.25 * k, 2) for k in range(13)]      # 1.00 .. 4.00
    cells = [(sd, n, pv) for sd in (0, 1, 2) for n in (20, 60) for pv in PVS]
    print(f"SATFIX: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"pv": pv, "n_tasks": n, "seed": sd, **_stats(inst0),
                "baseline_mwh": round(float(np.maximum(inst0.Delta, 0.0).sum()) / 10, 2)}
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
        if idx % 15 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    FN = {"CAPS3": caps3, "SATFIX": satfix}
    _known = {s.strip().upper() for s in FN}
    _bad = [s for s in STUDIES if s.strip().upper() not in _known]
    if _bad:
        sys.exit(f"unknown OVERNIGHT6_STUDIES entries: {_bad} -- known: {sorted(FN)}")
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time(); FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
