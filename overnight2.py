"""
Overnight campaign 2: distribution versions of the reviewed figures.

  S5  fig84_bands   ~240 randomized FLEETS (task count 30-120, breaks or
                    full-day schedule, HETEROGENEOUS per-task energies drawn
                    from 50-250 kWh) x {VSP, plain-EV at +$0/+$22.5/+$45 per
                    truck-day}. Gives Fig 8.4 its honest uncertainty: a band
                    of value-vs-efficiency lines and a DISTRIBUTION of
                    break-even efficiencies. (A solar-curve distribution is
                    deliberately absent: both regimes are solar-blind, so the
                    solar profile provably adds zero width -- verified earlier
                    to the cent.)
  S6  eps_band      Fig 8.6 as a band: task energy eps in {0.5..3.0} x solar
                    scale 0..3 in steps of 0.25 x 3 sampled trip sets, V2G.
  S7  timeline      A REALISTIC Gantt: 1-hour tasks on a full-day schedule
                    (6h-20h), so trucks chain ~8-10 tasks/day instead of the
                    breaks-schedule maximum of ~4-5; run at truck cost $45 and
                    $150/day for the comparison. Full solution serialized for
                    the gallery to render.
  S8  exp5_e15      Extends the eps=1.5 scalability ladder to 10 locations /
                    450 tasks so Fig 8.1's two lines end together (the short
                    line merely mirrored the original paper's own Table 4).

Sharding (use every node): set OVERNIGHT2_SHARD="i/K" to run slice i of K
(0-indexed) of S5/S6; each shard checkpoints to its own file and the gallery
merges overnight2_*_s*.json automatically. S7/S8 are small -- run unsharded.

Run:  OVERNIGHT2_STUDIES=S5 OVERNIGHT2_SHARD=0/3 sbatch ... (etc.)
Outputs: results/arxiv/overnight2_{fig84,epsband}_s{i}of{K}.json,
         overnight2_timeline.json, exp5_scalability_eps1.5.json (refreshed)
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI
import recreate_arxiv as R
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
STUDIES = os.environ.get("OVERNIGHT2_STUDIES", "S5,S6,S7,S8").split(",")
SHARD   = os.environ.get("OVERNIGHT2_SHARD", "0/1")        # "i/K"
N_FLEETS   = int(os.environ.get("OVERNIGHT2_N_FLEETS", "240"))   # S5
EPS_GRID   = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]                      # S6 (0.5-lattice multiples)
PVGRID     = [round(0.25 * k, 2) for k in range(0, 13)]          # S6: 0 .. 3.0
N_SEEDS_S6 = 3
PREMIUMS   = [0.0, 22.5, 45.0]     # ABSOLUTE $/truck-day on top of CV (easier to interpret)
FULL_DAY   = [(6, 20)]
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
POINTS_DEF, PV_DEF = 3, 2.0
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
SH_I, SH_K = (int(x) for x in SHARD.split("/"))
# ==============================================================================


def solve(inst, scen, cv=CV):
    inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, cv
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    return {"total": mip.obj, "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)), "mip": mip, "cols": res["cols"],
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def sample_fleet(rng, points, n, windows, eps_choices=None):
    """Random trip set; 4-tuples with per-task energy when eps_choices given."""
    hours = [h for a, b in windows for h in range(a, b)]
    out = []
    for _ in range(n):
        st = int(rng.choice(hours))
        i = int(rng.integers(1, points + 1)); j = int(rng.integers(1, points + 1))
        while j == i:
            j = int(rng.integers(1, points + 1))
        if eps_choices is None:
            out.append((i, j, st))
        else:
            out.append((i, j, st, float(rng.choice(eps_choices))))
    return out


def ckpt(name):
    p = os.path.join(OUT, name)
    return (json.load(open(p)) if os.path.exists(p) else []), p


def s5_fig84_bands():
    rows, path = ckpt(f"overnight2_fig84_s{SH_I}of{SH_K}.json")
    done = {r["k"] for r in rows}
    rng = np.random.default_rng(21)
    print(f"S5 fleet bands: {N_FLEETS} fleets, shard {SH_I}/{SH_K} "
          f"({len(done)} done)", flush=True)
    for k in range(N_FLEETS):
        points = int(rng.choice([2, 3, 4]))
        n_tasks = int(rng.integers(30, 121))
        windows = BREAKS if rng.random() < 0.5 else FULL_DAY
        fleet = sample_fleet(rng, points, n_tasks, windows,
                             eps_choices=[0.5, 1.0, 1.5, 2.0, 2.5])
        if k % SH_K != SH_I or k in done:
            continue
        inst_v = build_instance(points, 2.0, windows, trip_list=fleet)
        traction = float(sum(tr.energy for tr in inst_v.trips))
        v = solve(inst_v, "vsp")
        rec = {"k": k, "points": points, "n_tasks": n_tasks,
               "window": "breaks" if windows is BREAKS else "full_day",
               "traction_units": round(traction, 1),
               "vsp_mip": round(v["total"], 1), "vsp_trucks": v["trucks"]}
        for prem in PREMIUMS:
            inst_e = build_instance(points, 2.0, windows, trip_list=fleet)
            e = solve(inst_e, "ev", cv=CV + prem)
            # value(eff) = (vsp_mip + c_g*eff*traction) - ev_total  (linear in eff)
            rec[f"ev_total_prem{prem}"] = round(e["total"], 1)
            rec[f"breakeven_prem{prem}"] = round((e["total"] - v["total"])
                                                 / (CG_COST * traction), 4)
            rec[f"ev_trucks_prem{prem}"] = e["trucks"]
        rows.append(rec)
        json.dump(rows, open(path, "w"))
        if len(rows) % 10 == 0:
            print(f"  [{len(rows)} fleets done] latest: n={n_tasks} "
                  f"be@22.5={rec['breakeven_prem22.5']:.2f}", flush=True)


def s6_eps_band():
    rows, path = ckpt(f"overnight2_epsband_s{SH_I}of{SH_K}.json")
    done = {(r["eps"], r["pv"], r["seed"]) for r in rows}
    print(f"S6 eps band: {len(EPS_GRID)}x{len(PVGRID)}x{N_SEEDS_S6}, "
          f"shard {SH_I}/{SH_K} ({len(done)} done)", flush=True)
    cells = [(eps, pv, seed) for eps in EPS_GRID for pv in PVGRID
             for seed in range(N_SEEDS_S6)]
    for idx, (eps, pv, seed) in enumerate(cells):
        if idx % SH_K != SH_I or (eps, pv, seed) in done:
            continue
        fleet = sample_fleet(np.random.default_rng(300 + seed), POINTS_DEF, 60, BREAKS)
        inst = build_instance(POINTS_DEF, eps, BREAKS, pv_scale=pv, trip_list=fleet)
        surplus = float(np.maximum(-inst.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst.trips))
        r = solve(inst, "v2g")
        if r is None:
            continue
        rows.append({"eps": eps, "pv": pv, "seed": seed,
                     "surplus_mwh": round(surplus / 10, 1),
                     "ratio": round(surplus / max(traction, 1e-9), 3),
                     "fuel_kwh": round(float(r["mip"].g.sum()) * 100, 1),
                     "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
        json.dump(rows, open(path, "w"))
        if len(rows) % 20 == 0:
            print(f"  [{len(rows)} cells done]", flush=True)


def s7_timeline():
    path = os.path.join(OUT, "overnight2_timeline.json")
    out = []
    print("S7 realistic timeline: 1-hour tasks, full-day schedule, cv in {45,150}", flush=True)
    fleet = sample_fleet(np.random.default_rng(5), POINTS_DEF, 60, FULL_DAY)
    for cv in (45.0, 150.0):
        inst = build_instance(POINTS_DEF, 1.0, FULL_DAY, pv_scale=PV_DEF,
                              trip_list=fleet, duration=1.0)
        r = solve(inst, "v2g", cv=cv)
        lanes = []
        for i in np.flatnonzero(r["mip"].x > 0.5):
            reps = int(round(r["mip"].x[i]))
            for _ in range(reps):
                lanes.append([round(float(x), 3) for x in r["cols"][i].e])
        mip = r["mip"]
        out.append({"cv": cv, "trucks": r["trucks"], "batteries": r["batteries"],
                    "gap_pct": round(r["gap"], 3), "total": round(r["total"], 1),
                    "tasks_per_truck": round(60.0 / max(r["trucks"], 1), 1),
                    "delta": [round(float(d), 3) for d in inst.Delta],
                    "lanes": lanes,
                    "battery_net": [round(float(c - d), 3) for c, d in
                                    zip(mip.charge, mip.discharge)] if mip.charge is not None else None})
        print(f"  cv=${cv:.0f}: trucks={r['trucks']} ({60.0/max(r['trucks'],1):.1f} tasks/truck) "
              f"batteries={r['batteries']} gap={r['gap']:.2f}%", flush=True)
        json.dump(out, open(path, "w"), indent=1)


def s8_exp5_e15():
    print("S8: eps=1.5 scalability ladder extended to 10 locations", flush=True)
    R.MILP_TIME_LIMIT = 300.0
    rows = []
    for pts in range(2, 11):
        inst = R.build_instance(pts, 1.5, R.SCAL)
        r = R.run_case(inst, "v2g")
        r.update({"eps": 1.5, "points": pts})
        rows.append(r)
        R._save("exp5_scalability_eps1.5", rows)
        print(f"  locs={pts} trips={r['trips']} cg_s={r['cg_s']} "
              f"gap={r.get('gap_pct')}%", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    print(f"overnight2: studies {STUDIES} shard {SHARD}  MILP={MILP_SOLVER}\n", flush=True)
    fns = {"S5": s5_fig84_bands, "S6": s6_eps_band, "S7": s7_timeline, "S8": s8_exp5_e15}
    for st in STUDIES:
        st = st.strip()
        if st in fns:
            t1 = time.time()
            fns[st]()
            print(f"-- {st} done in {(time.time()-t1)/60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time()-t0)/3600:.2f} h")
