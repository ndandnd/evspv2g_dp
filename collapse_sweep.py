"""
Randomized design sweep: densify the savings-vs-R cloud.

The R-collapse figure previously leaned on a coarse grid (20/60/120 tasks x a
few pv levels). Now that instances solve in seconds, this script samples the
design space at random -- task count, task energy, PV size, network size, and
the trip set itself -- and solves every sampled base twice (charge-only vs
V2G) at the fixed base prices. Each sample is one gray dot; no configuration
gets special treatment.

Sampled per base (uniform unless noted):
    points   in {2, 3, 4}              network size
    n_tasks  in [TASKS[0], TASKS[1]]   fleet workload
    eps      in {0.5,...,2.5}          task energy, 50-250 kWh (duty cycle)
    pv       in [0.75, 3.25]           PV sizing
    trip set random (start hours in the breaks windows, random O-D pairs)

Also reports the collapse quality: median absolute deviation of the points
from a rolling-median curve through them.

Run: python3 collapse_sweep.py   (Gurobi if available, else CBC; ~15-30 min
for 120 samples -- trim N_SAMPLES to go faster; results accumulate as it runs)
Output: results/arxiv/collapse_sweep.json / .csv
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI
from solar_ensemble import sample_trips
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
N_SAMPLES   = 120
SEED        = 1
TASKS       = (20, 180)
EPS_CHOICES = [0.5, 1.0, 1.5, 2.0, 2.5]
PV_RANGE    = (0.75, 3.25)
POINTS_CHOICES = [2, 3, 4]
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def run_one(inst, scen):
    inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    return {"total": mip.obj, "batteries": int(round(mip.nb)),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def main():
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(SEED)
    rows, t0 = [], time.time()
    print(f"collapse sweep: {N_SAMPLES} randomized bases x 2 regimes  (MILP: {MILP_SOLVER})\n")
    print(f"{'#':>4} {'tasks':>6} {'eps':>4} {'pv':>5} {'R':>6} {'save%':>7} {'batt':>5} {'s':>6}")
    for k in range(N_SAMPLES):
        points = int(rng.choice(POINTS_CHOICES))
        n_tasks = int(rng.integers(TASKS[0], TASKS[1] + 1))
        eps = float(rng.choice(EPS_CHOICES))
        pv = float(np.round(rng.uniform(*PV_RANGE), 2))
        trips = sample_trips(rng, points, n_tasks)
        t1 = time.time()
        inst0 = build_instance(points, eps, BREAKS, pv_scale=pv, trip_list=trips)
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        rec = {"k": k, "points": points, "n_tasks": n_tasks, "eps": eps, "pv": pv,
               "ratio": round(surplus / max(traction, 1e-9), 3),
               "surplus_mwh": round(surplus / 10, 1), "traction_mwh": round(traction / 10, 1)}
        ok = True
        for scen in ("solar", "v2g"):
            inst = build_instance(points, eps, BREAKS, pv_scale=pv, trip_list=trips)
            r = run_one(inst, scen)
            if r is None:
                ok = False
                break
            rec[f"{scen}_total"] = round(r["total"], 1)
            rec[f"{scen}_batteries"] = r["batteries"]
            rec[f"{scen}_gap_pct"] = round(r["gap"], 3)
        if ok:
            rec["v2g_vs_solar_pct"] = round(
                100 * (rec["solar_total"] - rec["v2g_total"]) / rec["solar_total"], 2)
            print(f"{k:4d} {n_tasks:6d} {eps:4.1f} {pv:5.2f} {rec['ratio']:6.2f} "
                  f"{rec['v2g_vs_solar_pct']:7.1f} {rec['v2g_batteries']:5d} "
                  f"{time.time() - t1:6.1f}", flush=True)
        rows.append(rec)
        json.dump(rows, open(os.path.join(OUT, "collapse_sweep.json"), "w"), indent=2)
    keys = sorted(set().union(*[set(r) for r in rows]), key=str)
    with open(os.path.join(OUT, "collapse_sweep.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    # collapse quality: deviation from a rolling-median curve
    okr = sorted([(r["ratio"], r["v2g_vs_solar_pct"]) for r in rows if "v2g_vs_solar_pct" in r])
    if len(okr) >= 10:
        xs = np.array([p[0] for p in okr]); ys = np.array([p[1] for p in okr])
        w = max(3, len(okr) // 10)
        med = np.array([np.median(ys[max(0, i - w):i + w]) for i in range(len(okr))])
        mad = float(np.median(np.abs(ys - med)))
        print(f"\ncollapse quality: median |deviation| from the rolling-median curve = {mad:.1f} pts "
              f"over {len(okr)} bases (R in [{xs.min():.2f}, {xs.max():.2f}])")
    print(f"total {time.time() - t0:.1f}s; output: results/arxiv/collapse_sweep.json / .csv")


if __name__ == "__main__":
    main()
