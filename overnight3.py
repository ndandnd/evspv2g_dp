"""
Overnight-3 mega campaign: ~15-20 h x 6 shards of labeled instance data.

Everything is per-row checkpointed (kill/requeue/timeout-safe) and every row
carries its full configuration, so any result can be regenerated exactly.
Studies run in figure-priority order; if a node times out, the tail studies
lose rows, not the head ones.

U1 shine-densify   : Fig 8.12 smoothing. The v2g_shine grid at 9 EXTRA seeds
                     (3..11), finer PV ladder, tasks to 28. Writes
                     v2g_shine_s{i}of{K}.json -- the fig 8.12 glob merges it.
U2 modes-hisolar   : Fig 8.9 upgrade. The S12 four-regime format at sols
                     {1x,2x,3x,4x,summer,sum2x}, tasks from 4 (small fleets!)
                     to 200, 3 seeds. Fig 8.9 now averages seeds and
                     auto-detects the new solar columns.
U3 stations-densify: Fig 8.13 smoothing + NEW ARM: random station subsets
                     ("sub2"/"sub5" = depot + 2/5 random chargers, station
                     list recorded per row) between depot-only and everywhere.
U4 durations       : NEW KNOB: task duration {30 min, 1 h, 2 h, mixed}, energy
                     proportional to duration (100 kWh/h). Do short flexible
                     tasks free the fleet for V2G?
U5 maps            : NEW KNOB: random maps (coords recorded per row) instead
                     of the nested pool -- is the L-axis story map-robust?
U6 scale-rich      : CG scalability ladder on the multi-station model to
                     1000 tasks at L in {4,15} (warm AND cold, pricing time
                     recorded) -- feeds Fig 8.1 and settles warm-start talk.

Run:   OVERNIGHT3_STUDIES="U1,U2,U3,U4,U5,U6" OVERNIGHT3_SHARD="i/K" python3 overnight3.py
Output: results/arxiv/v2g_shine_s*.json, overnight3_modes_s*.json,
        stations_sa2_s*.json, overnight3_durations_s*.json,
        overnight3_maps_s*.json, overnight3_scale_s*.json
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI, _COORDS
from profile_robustness import base_curves
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
STUDIES = os.environ.get("OVERNIGHT3_STUDIES", "U1,U2,U3,U4,U5,U6").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT3_SHARD", "0/1").split("/"))
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
MILP_TIME_LIMIT = 180.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
POOL = list(_COORDS) + [(0.75, 0.75), (-0.75, 0.75), (0.75, -0.75)]   # nested 15
# extended odd-quarter lattice for random maps (all pairwise deadheads exact)
BIGPOOL = [(x, y) for x in (-1.25, -0.75, -0.25, 0.25, 0.75, 1.25)
           for y in (-1.25, -0.75, -0.25, 0.25, 0.75, 1.25)
           if abs(x) + abs(y) <= 1.5]
# ==============================================================================


def ckpt(name):
    """Load a checkpoint, tolerating a file truncated by a mid-write kill: the
    corrupt file is set aside (not deleted) and the study restarts from the rows
    that survive in it -- never crashes the whole chain."""
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return [], p
    try:
        return json.load(open(p)), p
    except (json.JSONDecodeError, UnicodeDecodeError):
        bad = p + ".corrupt"
        os.replace(p, bad)
        print(f"  [ckpt] {name} unreadable (truncated write?) -- moved to "
              f"{os.path.basename(bad)}, restarting shard from scratch", flush=True)
        return [], p


def save(rows, path):
    """Atomic checkpoint write: dump to a temp file, then rename over the target,
    so a kill mid-write can never leave a truncated checkpoint."""
    tmp = path + ".tmp"
    json.dump(rows, open(tmp, "w"))
    os.replace(tmp, path)


def sol_kwargs(sol):
    if sol in ("summer", "sum2x"):
        Dh, Sh = base_curves()
        hh = np.arange(24)
        bell = np.exp(-0.5 * ((hh - 13.0) / 4.2) ** 2)
        bell[(hh < 4.5) | (hh > 21.5)] = 0.0
        f = 1.6 if sol == "summer" else 3.2
        return {"delta_hourly": np.round(Dh - bell * (Sh.sum() * f / bell.sum())).astype(int)}
    return {"pv_scale": float(sol.replace("x", ""))}


def solve(inst, scen, enrich=25, tl=None):
    inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=enrich, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=tl or MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    if getattr(mip, "status", "optimal") == "milp_failed" or not np.isfinite(mip.obj):
        return None                            # integer master infeasible/failed
    return {"total": mip.obj, "milp_status": getattr(mip, "status", "optimal"),
            "g_units": float(mip.g.sum()),
            "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)), "cols": res["cols"], "mip": mip,
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def rand_trips(L, n, seed, windows=(6, 20), salt=20_000):
    rng = np.random.default_rng(salt + 1_000 * seed + 10 * L + n)
    out = []
    for _ in range(n):
        i = int(rng.integers(1, L + 1)); j = int(rng.integers(1, L + 1))
        while j == i:
            j = int(rng.integers(1, L + 1))
        out.append((i, j, int(rng.integers(windows[0], windows[1]))))
    return out


def u1_shine():
    """v2g_shine at 9 extra seeds, finer pv, tasks to 28 (same JSON schema)."""
    from solar_ensemble import sample_trips as st_shine
    from v2g_shine import summer_delta
    rows, path = ckpt(f"v2g_shine_s{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["seed"], r["shape"], r["pv"], r["scenario"]) for r in rows}
    TASKS = [4, 6, 8, 12, 16, 20, 24, 28]
    PVS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0]
    cells = [(n, sd, sh, pv) for n in TASKS for sd in range(3, 12)
             for sh in ("std", "summer") for pv in PVS]
    print(f"U1 shine densify: {len(cells)} cells x 3, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (n, seed, shape, pv) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = st_shine(np.random.default_rng(900 + 1000 * seed + n), 3, n)
        kw = ({"delta_hourly": summer_delta(pv)} if shape == "summer"
              else {"pv_scale": pv})
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, **kw)
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        base = {"n_tasks": n, "seed": seed, "shape": shape, "pv": pv,
                "surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
                "ratio": round(surplus / max(traction, 1e-9), 2),
                "baseline_mwh": round(float(np.maximum(inst0.Delta, 0.0).sum()) / 10, 2)}
        for scen in ("solar", "v2g_fleet", "v2g"):
            if (n, seed, shape, pv, scen) in done:
                continue
            r = solve(build_instance(3, 2.0, BREAKS, trip_list=fleet, **kw), scen, tl=120.0)
            if r is None:
                continue
            rows.append({**base, "scenario": scen, "total": round(r["total"], 1),
                         "trucks": r["trucks"], "batteries": r["batteries"],
                         "fossil_mwh": round(r["g_units"] / 10, 2),
                         "gap_pct": round(r["gap"], 3)})
            save(rows, path)
        if idx % 40 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows]", flush=True)


def u2_modes_hisolar():
    """Fig 8.9 format at high solar + small fleets, 3 seeds."""
    rows, path = ckpt(f"overnight3_modes_s{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["sol"], r["seed"], r["scenario"]) for r in rows}
    NT = list(range(4, 44, 4)) + list(range(50, 201, 10))
    SOLS = ["1x", "2x", "3x", "4x", "summer", "sum2x"]
    cells = [(n, sol, sd, scen) for n in NT for sol in SOLS for sd in range(3)
             for scen in ("vsp", "ev", "solar", "v2g")]
    print(f"U2 modes hi-solar: {len(cells)} cells, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (n, sol, sd, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (n, sol, sd, scen) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, **sol_kwargs(sol))
        traction = float(sum(tr.energy for tr in inst.trips))
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
        if len(rows) % 30 == 0:
            print(f"  [{len(rows)} rows]", flush=True)


def _station_arms(L, seed):
    """depot / depot+2 random / depot+5 random / all -- lists recorded."""
    rng = np.random.default_rng(40_000 + 100 * seed + L)
    perm = list(rng.permutation(np.arange(1, L + 1)))
    return [("depot", None),
            ("sub2", [0] + sorted(int(x) for x in perm[:min(2, L)])),
            ("sub5", [0] + sorted(int(x) for x in perm[:min(5, L)])),
            ("all", list(range(L + 1)))]


def u3_stations2():
    rows, path = ckpt(f"stations_sa2_s{SH_I}of{SH_K}.json")
    done = {(r["L"], r["sol"], r["n_tasks"], r["seed"], r["stations"], r["scenario"])
            for r in rows}
    cells = [(L, sol, n, sd) for L in (4, 6, 8, 10, 12, 15) for sol in ("2x", "sum2x")
             for n in (40, 80, 120, 160) for sd in range(3, 9)]
    print(f"U3 stations densify: {len(cells)} bases x 8 arms, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (L, sol, n, sd) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = [(i, j, st) for i, j, st in rand_trips(L, n, sd)]
        inst0 = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                               coords_override=POOL[:L], **sol_kwargs(sol))
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        base = {"L": L, "sol": sol, "n_tasks": n, "seed": sd,
                "surplus_units": round(surplus, 1), "traction_units": round(traction, 1),
                "ratio": round(surplus / max(traction, 1e-9), 2)}
        for stname, stlist in _station_arms(L, sd):
            for scen in ("solar", "v2g"):
                if (L, sol, n, sd, stname, scen) in done:
                    continue
                inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                                      coords_override=POOL[:L], stations=stlist,
                                      **sol_kwargs(sol))
                t0 = time.time()
                r = solve(inst, scen)
                if r is None:
                    continue
                rows.append({**base, "stations": stname,
                             "station_locs": (stlist if stlist else [0]),
                             "scenario": scen, "total": round(r["total"], 1),
                             "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                             "batteries": r["batteries"],
                             "gap_pct": round(r["gap"], 3),
                             "time_s": round(time.time() - t0, 1)})
                save(rows, path)
        if idx % 10 == 0:
            print(f"  [{idx + 1}/{len(cells)} bases, {len(rows)} rows]", flush=True)


def u4_durations():
    """Task-duration diversity: 30 min / 1 h / 2 h / mixed; energy = 1 unit/h."""
    rows, path = ckpt(f"overnight3_durations_s{SH_I}of{SH_K}.json")
    done = {(r["L"], r["sol"], r["dur"], r["n_tasks"], r["seed"], r["stations"],
             r["scenario"]) for r in rows}
    DURS = {"30min": [0.5], "1h": [1.0], "2h": [2.0], "mixed": [0.5, 1.0, 2.0]}
    cells = [(L, sol, dname, n, sd) for L in (4, 12) for sol in ("2x", "sum2x")
             for dname in DURS for n in (40, 80, 120) for sd in range(3)]
    print(f"U4 durations: {len(cells)} bases x 4 arms, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (L, sol, dname, n, sd) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        rng = np.random.default_rng(60_000 + 1_000 * sd + 10 * L + n)
        fleet = []
        for _ in range(n):
            i = int(rng.integers(1, L + 1)); j = int(rng.integers(1, L + 1))
            while j == i:
                j = int(rng.integers(1, L + 1))
            dur = float(rng.choice(DURS[dname]))
            st = float(rng.integers(12, 40)) / 2.0        # half-hour starts, 6:00-19:30
            fleet.append((i, j, st, dur * 1.0, dur))      # energy 1 unit per hour
        for stations in ("depot", "all"):
            for scen in ("solar", "v2g"):
                if (L, sol, dname, n, sd, stations, scen) in done:
                    continue
                inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet,
                                      coords_override=POOL[:L],
                                      stations=("all" if stations == "all" else None),
                                      **sol_kwargs(sol))
                r = solve(inst, scen)
                if r is None:
                    continue
                rows.append({"L": L, "sol": sol, "dur": dname, "n_tasks": n, "seed": sd,
                             "stations": stations, "scenario": scen,
                             "total": round(r["total"], 1),
                             "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                             "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
                save(rows, path)
        if idx % 10 == 0:
            print(f"  [{idx + 1}/{len(cells)} bases, {len(rows)} rows]", flush=True)


def u5_maps():
    """Random maps from the extended lattice pool; coords recorded per row."""
    rows, path = ckpt(f"overnight3_maps_s{SH_I}of{SH_K}.json")
    done = {(r["L"], r["map_seed"], r["n_tasks"], r["seed"], r["stations"],
             r["scenario"]) for r in rows}
    cells = [(L, ms, n, sd) for L in (6, 10) for ms in range(12)
             for n in (60, 120) for sd in range(2)]
    print(f"U5 random maps: {len(cells)} bases x 4 arms, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (L, ms, n, sd) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        mrng = np.random.default_rng(70_000 + ms)
        coords = [BIGPOOL[k] for k in mrng.choice(len(BIGPOOL), size=L, replace=False)]
        fleet = rand_trips(L, n, sd, salt=80_000)
        for stations in ("depot", "all"):
            for scen in ("solar", "v2g"):
                if (L, ms, n, sd, stations, scen) in done:
                    continue
                inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                                      coords_override=coords, pv_scale=2.0,
                                      stations=("all" if stations == "all" else None))
                r = solve(inst, scen)
                if r is None:
                    continue
                rows.append({"L": L, "map_seed": ms, "coords": coords, "n_tasks": n,
                             "seed": sd, "stations": stations, "scenario": scen,
                             "total": round(r["total"], 1),
                             "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                             "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
                save(rows, path)
        if idx % 10 == 0:
            print(f"  [{idx + 1}/{len(cells)} bases, {len(rows)} rows]", flush=True)


def u6_scale_rich():
    """CG ladder to 1000 tasks on the multi-station model (feeds Fig 8.1)."""
    rows, path = ckpt(f"overnight3_scale_s{SH_I}of{SH_K}.json")
    done = {(r["L"], r["n_tasks"], r["seed"], r["start"]) for r in rows}
    cells = [(L, n, sd, st) for L in (4, 15) for n in (100, 200, 400, 600, 800, 1000)
             for sd in range(2) for st in ("warm", "cold")]
    print(f"U6 scale on rich maps: {len(cells)} runs, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (L, n, sd, st) in enumerate(cells):
        if idx % SH_K != SH_I or (L, n, sd, st) in done:
            continue
        fleet = rand_trips(L, n, 200 + sd)
        inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                              coords_override=POOL[:L], stations="all", pv_scale=2.0)
        inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
        t0 = time.time()
        res = column_generation(inst, scenario="v2g", start=st, do_milp=False,
                                enrich=0, max_iter=max(3000, 6 * n))
        rows.append({"L": L, "n_tasks": n, "seed": sd, "start": st,
                     "iters": res["iters"], "time_s": round(time.time() - t0, 2),
                     "pricing_s": round(res["pricing_time"], 2),
                     "lp_obj": round(res["lp_obj"], 2)})
        save(rows, path)
        print(f"  L={L} n={n} seed={sd} {st}: {rows[-1]['time_s']}s", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    FN = {"U1": u1_shine, "U2": u2_modes_hisolar, "U3": u3_stations2,
          "U4": u4_durations, "U5": u5_maps, "U6": u6_scale_rich}
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time()
        FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
