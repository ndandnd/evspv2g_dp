"""
Overnight-7: the two Tier-1 resilience experiments from the design review.
Conventions as overnight3-6 (atomic per-row checkpoints, idx%K shards,
seed-outermost cells).

  OUTAGE    : N-1 generator-contingency ladder. Baseline generation cap
              1.5x the no-fleet peak deficit (loose enough that all fleets
              operate at the no-outage reference); during an evening outage window
              the cap is derated to d in {2/3, 1/3, 0} of baseline (one of
              three generators lost, two lost, total loss), plus the no-outage
              reference d=1. Hypothesis: V2G fleets keep the base and task set
              feasible at outage depths where charge-only fleets fail,
              recasting the feasibility cliff as named contingencies.
              Figure: percent-feasible ladder + price-of-resilience curve.
  ENDURANCE : fuel-convoy interruption. A daily fossil budget F = frac x (the
              no-fleet baseline burn) for frac in {1.0 .. 0.05}. F_min(config)
              = smallest feasible budget; days of autonomy on a stock S is
              S / F_min. Hypothesis: V2G lowers F_min well below the
              charge-only fleet's (and below the base's own baseline burn),
              materially extending days-of-autonomy on a fixed fuel stock.
              Figure: feasibility ladder -> days-of-autonomy vs stock.

Run:   OVERNIGHT7_STUDIES="OUTAGE,ENDURANCE" OVERNIGHT7_SHARD="i/K" python3 overnight7.py
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from overnight3 import ckpt, save, solve, rand_trips

STUDIES = os.environ.get("OVERNIGHT7_STUDIES", "OUTAGE,ENDURANCE").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT7_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")


def _stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3),
            "baseline_units": round(float(np.maximum(inst.Delta, 0.0).sum()), 1)}


def outage():
    rows, path = ckpt(f"overnight7_outage_s{SH_I}of{SH_K}.json")
    done = {(r["derate"], r["win"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    DER = [1.0, 2/3, 1/3, 0.0]
    WINS = {"eve4h": (34, 42), "eve8h": (28, 44)}   # half-blocks: 17-21h, 14-22h
    cells = [(sd, n, pv, w, d) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for w in WINS for d in DER]
    print(f"OUTAGE: {len(cells)} cells x 3, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, w, d) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        peak_def = float(np.maximum(inst0.Delta, 0.0).max())
        base_cap = 1.5 * peak_def
        a, b = WINS[w]
        base = {"derate": round(d, 3), "win": w, "pv": pv, "n_tasks": n, "seed": sd,
                "base_cap": round(base_cap, 2), **_stats(inst0)}
        for scen in ("solar", "v2g_fleet", "v2g"):
            if (round(d, 3), w, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            caps = np.full(inst.T, base_cap)
            caps[a:b] = d * base_cap
            inst.gen_cap = caps
            r = solve(inst, scen, tl=120.0)
            if r is None:
                rows.append({**base, "scenario": scen, "feasible": False})
            else:
                rows.append({**base, "scenario": scen, "feasible": True,
                             "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                             "trucks": r["trucks"], "batteries": r["batteries"],
                             "gap_pct": round(r["gap"], 3)})
            save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def endurance():
    rows, path = ckpt(f"overnight7_endurance_s{SH_I}of{SH_K}.json")
    done = {(r["frac"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    FRACS = [1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
    cells = [(sd, n, pv, f) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for f in FRACS]
    print(f"ENDURANCE: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, f) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        baseline = float(np.maximum(inst0.Delta, 0.0).sum())   # no-fleet daily burn (units)
        base = {"frac": f, "pv": pv, "n_tasks": n, "seed": sd,
                "budget_units": round(f * baseline, 1), **_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (f, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.fuel_budget = f * baseline
            r = solve(inst, scen, tl=120.0)
            if r is None:
                rows.append({**base, "scenario": scen, "feasible": False})
            else:
                rows.append({**base, "scenario": scen, "feasible": True,
                             "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                             "trucks": r["trucks"], "batteries": r["batteries"],
                             "gap_pct": round(r["gap"], 3)})
            save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    FN = {"OUTAGE": outage, "ENDURANCE": endurance}
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time(); FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
