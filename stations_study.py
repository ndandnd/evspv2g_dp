"""
The multi-station 'desert base' frontier -- lots of labeled instance data.

Exercises the model extension the paper formulates but no prior experiment
used: charging/discharging at a SET of locations H0 (Sec. 3), not only the
depot. Map: depot at the origin plus L task locations on the quarter-lattice
pool below. Maps are NESTED and deterministic (the L=4 map is a subset of the
L=6 map, ...), so the location-count axis is not confounded by map randomness.
Deadheads: depot <= 45 min and pairwise <= 1 h for L <= 4, growing with the
map to <= 3 h at L = 15 (speed 1 Manhattan unit per hour, as everywhere).

SA 'stations frontier' (MILP): for every base, four arms --
        {depot-only, chargers-everywhere} x {solar, v2g}
    across L in {4,...,15}, solar regime {1x, 2x, summer, sum2x} (summer =
    longer daylight at 1.6x energy; sum2x = the same long day at 3.2x),
    n_tasks in {40..160}, 3 seeds. One-hour tasks on a full-day window:
    dense schedules are where charger placement matters (validated: chargers-
    everywhere cuts a dense-schedule V2G LP by ~11%).
SB 'warm start at complexity' (pure CG, no enrichment/MILP): warm-vs-cold
    ladder ON the multi-station model, L x n_tasks up to 600 x 3 seeds --
    does initialization start to matter when the network is rich?

Reproducibility: every row records (L, stations, scenario, sol, n_tasks,
seed); trips depend only on (L, n_tasks, seed) via the seeded rng below.

Run:    STATIONS_STUDIES="SA,SB" STATIONS_SHARD="i/K" python3 stations_study.py
Output: results/arxiv/stations_sa_s{i}of{K}.json, stations_sb_s{i}of{K}.json
        (per-row checkpoint; safe to kill and requeue)
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, HAVE_GUROBI, _COORDS
from profile_robustness import base_curves
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
STUDIES = os.environ.get("STATIONS_STUDIES", "SA,SB").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("STATIONS_SHARD", "0/1").split("/"))
LOCS      = [4, 6, 8, 10, 12, 15]
SOLS      = ["1x", "2x", "summer", "sum2x"]      # intensity and day length
NTASKS_A  = [40, 80, 120, 160]
LOCS_B    = [4, 8, 15]
NTASKS_B  = [100, 200, 400, 600]
N_SEEDS   = 3
EPS, DUR  = 1.0, 1.0                             # 1-hour tasks, 100 kWh each
WINDOW    = (6, 20)                              # full working day
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================

# nested map pool: _COORDS (12 quarter-lattice points) + 3 outer corners
POOL = list(_COORDS) + [(0.75, 0.75), (-0.75, 0.75), (0.75, -0.75)]


def sample_trips(L, n, seed):
    """Random 1-hour tasks between task locations 1..L (never the depot)."""
    rng = np.random.default_rng(20_000 + 1_000 * seed + 10 * L + n)
    out = []
    for _ in range(n):
        i = int(rng.integers(1, L + 1)); j = int(rng.integers(1, L + 1))
        while j == i:
            j = int(rng.integers(1, L + 1))
        out.append((i, j, int(rng.integers(WINDOW[0], WINDOW[1]))))
    return out


def sol_kwargs(sol):
    """pv_scale / delta_hourly for a solar regime."""
    if sol in ("summer", "sum2x"):
        Dh, Sh = base_curves()
        hh = np.arange(24)
        bell = np.exp(-0.5 * ((hh - 13.0) / 4.2) ** 2)
        bell[(hh < 4.5) | (hh > 21.5)] = 0.0
        f = 1.6 if sol == "summer" else 3.2
        return {"delta_hourly": np.round(Dh - bell * (Sh.sum() * f / bell.sum())).astype(int)}
    return {"pv_scale": {"1x": 1.0, "2x": 2.0}[sol]}


def make(L, sol, fleet, stations):
    inst = build_instance(L, EPS, [WINDOW], trip_list=fleet, duration=DUR,
                          coords_override=POOL[:L],
                          stations=("all" if stations == "all" else None),
                          **sol_kwargs(sol))
    inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
    return inst


def sa_frontier():
    path = os.path.join(OUT, f"stations_sa_s{SH_I}of{SH_K}.json")
    rows = json.load(open(path)) if os.path.exists(path) else []
    done = {(r["L"], r["sol"], r["n_tasks"], r["seed"], r["stations"], r["scenario"])
            for r in rows}
    cells = [(L, sol, n, sd) for L in LOCS for sol in SOLS
             for n in NTASKS_A for sd in range(N_SEEDS)]
    print(f"SA stations frontier: {len(cells)} bases x 4 arms, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)  MILP: {MILP_SOLVER}", flush=True)
    for idx, (L, sol, n, sd) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = sample_trips(L, n, sd)
        inst0 = make(L, sol, fleet, "depot")
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        base = {"L": L, "sol": sol, "n_tasks": n, "seed": sd,
                "surplus_units": round(surplus, 1), "traction_units": round(traction, 1),
                "ratio": round(surplus / max(traction, 1e-9), 2)}
        for stations in ("depot", "all"):
            for scen in ("solar", "v2g"):
                if (L, sol, n, sd, stations, scen) in done:
                    continue
                inst = make(L, sol, fleet, stations)
                t0 = time.time()
                res = column_generation(inst, scenario=scen, start="warm",
                                        do_milp=False, enrich=25,
                                        max_iter=max(2000, 5 * n))
                if res["lp_obj"] == float("inf"):
                    continue
                mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                                 battery_allowed=SCENARIOS[scen]["battery"],
                                 solver=MILP_SOLVER)
                rows.append({**base, "stations": stations, "scenario": scen,
                             "total": round(mip.obj, 1),
                             "g_units": round(float(mip.g.sum()), 2),
                             "trucks": int(sum(round(x) for x in mip.x)),
                             "batteries": int(round(mip.nb)),
                             "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                             "time_s": round(time.time() - t0, 1)})
                json.dump(rows, open(path, "w"))
        if idx % 10 == 0:
            print(f"  [{idx + 1}/{len(cells)} bases, {len(rows)} rows]", flush=True)


def sb_warmcold():
    path = os.path.join(OUT, f"stations_sb_s{SH_I}of{SH_K}.json")
    rows = json.load(open(path)) if os.path.exists(path) else []
    done = {(r["L"], r["n_tasks"], r["seed"], r["start"]) for r in rows}
    cells = [(L, n, sd, st) for L in LOCS_B for n in NTASKS_B
             for sd in range(N_SEEDS) for st in ("warm", "cold")]
    print(f"SB warm-vs-cold on the multi-station model: {len(cells)} runs, "
          f"shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (L, n, sd, st) in enumerate(cells):
        if idx % SH_K != SH_I or (L, n, sd, st) in done:
            continue
        fleet = sample_trips(L, n, 100 + sd)          # distinct seed space from SA
        inst = make(L, "2x", fleet, "all")
        t0 = time.time()
        res = column_generation(inst, scenario="v2g", start=st, do_milp=False,
                                enrich=0, max_iter=max(3000, 6 * n))
        rows.append({"L": L, "n_tasks": n, "seed": sd, "start": st,
                     "iters": res["iters"], "time_s": round(time.time() - t0, 2),
                     "pricing_s": round(res["pricing_time"], 2),
                     "lp_obj": round(res["lp_obj"], 2)})
        json.dump(rows, open(path, "w"))
        print(f"  L={L} n={n} seed={sd} {st}: {rows[-1]['time_s']}s "
              f"({res['iters']} iters)", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time()
        {"SA": sa_frontier, "SB": sb_warmcold}[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
