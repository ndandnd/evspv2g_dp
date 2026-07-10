"""
Overnight-9: reruns and two-stage studies (24-36 h window). Conventions as
overnight3-8 (atomic per-row checkpoints, idx%K shards, seed-outermost).

  ENDUR2   : ENDURANCE rerun with the fuel budget now enforced in the LP path
             and integer-master infeasibility detected (the overnight7
             endurance data is invalid: the budget was missing from the CG
             LP, so charge-only fleets were recorded feasible at 5% fuel).
  OUTAGE2  : two-stage N-1 stress test. Stage 1 sizes the fleet on the normal
             day (cap 1.5x no-fleet peak); stage 2 FIXES those assets
             (truck-count cap + battery count) and re-solves the outage day
             (evening derates 2/3, 1/3, 0). Separates "the owned fleet
             survives" from overnight7's "you may buy your way out"
             (greenfield design view, kept for contrast).
  SATFIX2  : two-stage concavity. Stage 1 sizes assets at pv=2.0; stage 2
             sweeps pv 1.00-4.00 with assets fixed, giving Theorem 1's
             fixed-network diminishing returns (endogenous assets made both
             earlier attempts linear-to-the-floor).
  SCHED2   : seeds 3-5 for the retiming study (error bars for Fig 8.18).
  WCITIES  : the 365-day weather study on four additional climates (Gulf
             desert, Tromso, London, Seoul; data/ghi_2023_*.csv), same array
             everywhere: each city's hourly GHI is scaled by the SoCal
             calibration factor, so climates differ in yield and shape,
             not panel count. pv in {2.0, 3.0}, solar vs v2g.

Run:   OVERNIGHT9_STUDIES="ENDUR2,OUTAGE2,SATFIX2,SCHED2,WCITIES" \
       OVERNIGHT9_SHARD="i/K" python3 overnight9.py
"""
from __future__ import annotations
import os, sys, json, time, csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from overnight3 import ckpt, save, solve, rand_trips
from overnight8 import _tasks as sched_tasks, FAMILIES
from profile_robustness import base_curves
from solar_ensemble import load_days

STUDIES = os.environ.get("OVERNIGHT9_STUDIES",
                         "ENDUR2,OUTAGE2,SATFIX2,SCHED2,WCITIES").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT9_SHARD", "0/1").split("/"))
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "results", "arxiv")


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


def endur2():
    rows, path = ckpt(f"overnight9_endur_s{SH_I}of{SH_K}.json")
    done = {(r["frac"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    FRACS = [1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
    cells = [(sd, n, pv, f) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for f in FRACS]
    print(f"ENDUR2: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, f) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        baseline = float(np.maximum(inst0.Delta, 0.0).sum())
        base = {"frac": f, "pv": pv, "n_tasks": n, "seed": sd,
                "budget_units": round(f * baseline, 1), **_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (f, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.fuel_budget = f * baseline
            rows.append(_row(base, scen, solve(inst, scen, tl=120.0)))
            save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def outage2():
    rows, path = ckpt(f"overnight9_outage2_s{SH_I}of{SH_K}.json")
    done = {(r["derate"], r["win"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    DER = [1.0, 2/3, 1/3, 0.0]
    WINS = {"eve4h": (34, 42), "eve8h": (28, 44)}
    cells = [(sd, n, pv, w, scen) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for w in WINS for scen in ("solar", "v2g_fleet", "v2g")]
    print(f"OUTAGE2 (two-stage): {len(cells)} bases, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, w, scen) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if all((round(d, 3), w, pv, n, sd, scen) in done for d in DER):
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        peak_def = float(np.maximum(inst0.Delta, 0.0).max())
        base_cap = 1.5 * peak_def
        a, b = WINS[w]
        # stage 1: size the fleet on the normal (no-outage) day
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.gen_cap = np.full(inst.T, base_cap)
        s1 = solve(inst, scen, tl=120.0)
        if s1 is None:
            for d in DER:
                if (round(d, 3), w, pv, n, sd, scen) not in done:
                    rows.append({"derate": round(d, 3), "win": w, "pv": pv, "n_tasks": n,
                                 "seed": sd, "scenario": scen, "feasible": False,
                                 "stage1_feasible": False})
            save(rows, path); continue
        for d in DER:
            if (round(d, 3), w, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            caps = np.full(inst.T, base_cap); caps[a:b] = d * base_cap
            inst.gen_cap = caps
            inst.max_trucks = s1["trucks"]          # fixed assets, re-schedulable
            inst.nb_fixed = float(s1["batteries"])
            r = solve(inst, scen, tl=120.0)
            base = {"derate": round(d, 3), "win": w, "pv": pv, "n_tasks": n, "seed": sd,
                    "base_cap": round(base_cap, 2), "stage1_trucks": s1["trucks"],
                    "stage1_batteries": s1["batteries"],
                    "stage1_total": round(s1["total"], 1), **_stats(inst0)}
            rows.append(_row(base, scen, r))
            save(rows, path)
        if idx % 8 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def satfix2():
    rows, path = ckpt(f"overnight9_satfix2_s{SH_I}of{SH_K}.json")
    done = {(r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    PVS = [round(1.0 + 0.25 * k, 2) for k in range(13)]
    cells = [(sd, n, scen) for sd in (0, 1, 2) for n in (20, 60)
             for scen in ("solar", "v2g")]
    print(f"SATFIX2 (two-stage): {len(cells)} bases x {len(PVS)} pv, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, scen) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if all((pv, n, sd, scen) in done for pv in PVS):
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.0)
        s1 = solve(inst, scen, tl=120.0)
        if s1 is None:
            continue
        for pv in PVS:
            if (pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.max_trucks = s1["trucks"]
            inst.nb_fixed = float(s1["batteries"])
            r = solve(inst, scen, tl=120.0)
            base = {"pv": pv, "n_tasks": n, "seed": sd,
                    "stage1_trucks": s1["trucks"], "stage1_batteries": s1["batteries"],
                    **_stats(inst)}
            rows.append(_row(base, scen, r))
            save(rows, path)
        print(f"  [{idx + 1}/{len(cells)} bases, {len(rows)} rows]", flush=True)


def sched2():
    rows, path = ckpt(f"overnight8_sched_sX{SH_I}of{SH_K}.json")
    done = {(r["sched"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    cells = [(sd, n, pv, sc) for sd in (3, 4, 5) for n in (20, 60, 120)
             for pv in (1.0, 1.5, 2.0, 2.5, 3.0) for sc in FAMILIES]
    print(f"SCHED2: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, sc) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = sched_tasks(n, sd, sc)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"sched": sc, "pv": pv, "n_tasks": n, "seed": sd, **_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (sc, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            rows.append(_row(base, scen, solve(inst, scen, tl=120.0)))
            save(rows, path)
        if idx % 15 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def _load_city_days(key):
    path = os.path.join(ROOT, "data", f"ghi_2023_{key}.csv")
    days = []
    with open(path) as f:
        rd = csv.reader(l for l in f if not l.startswith('"#'))
        header = next(rd)
        for row in rd:
            days.append((row[0], np.array([float(x) for x in row[1:25]])))
    return days


def wcities():
    rows, path = ckpt(f"overnight9_wcities_s{SH_I}of{SH_K}.json")
    done = {(r["city"], r["date"], r["pv"], r["scenario"]) for r in rows}
    CITIES = ["gulf_desert", "tromso", "london", "seoul", "keflavik"]
    D, S = base_curves()
    socal_mean = np.mean([d[1].sum() for d in load_days()])   # SoCal calibration factor
    fleet = rand_trips(3, 60, 0, salt=50_000)
    cells = [(city, k) for city in CITIES for k in range(365)]
    PVS = [2.0, 3.0]
    print(f"WCITIES: {len(cells)} city-days x {len(PVS)} pv x 2, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    city_days = {c: _load_city_days(c) for c in CITIES}
    for idx, (city, k) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if k >= len(city_days[city]):
            continue
        date, ghi = city_days[city][k]
        for pv in PVS:
            S_d = ghi * (S.sum() * pv / socal_mean)           # same array, different sky
            dh = np.round(D - S_d).astype(int)
            inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, delta_hourly=dh)
            base = {"city": city, "date": date, "pv": pv, **_stats(inst0)}
            for scen in ("solar", "v2g"):
                if (city, date, pv, scen) in done:
                    continue
                inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, delta_hourly=dh)
                rows.append(_row(base, scen, solve(inst, scen, tl=60.0)))
                save(rows, path)
        if idx % 40 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    FN = {"ENDUR2": endur2, "OUTAGE2": outage2, "SATFIX2": satfix2,
          "SCHED2": sched2, "WCITIES": wcities}
    _known = {s.strip().upper() for s in FN}
    _bad = [s for s in STUDIES if s.strip().upper() not in _known]
    if _bad:
        sys.exit(f"unknown OVERNIGHT9_STUDIES entries: {_bad} -- known: {sorted(FN)}")
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time(); FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
