"""
Overnight-4: targeted studies for the revision figures. Same conventions as
overnight3: per-row checkpointing (kill/requeue/timeout-safe), idx%K sharding,
every row carries its full configuration. Cell order puts SEED OUTERMOST, so a
timeout costs replication, not grid coverage.

  ETA      : round-trip-loss sweep, eta x pv x n. Every planning run so far used
             eta=0 (build_instance default) with eps_pen as the only anti-churn;
             the paper's Remark motivates eta>0. Does the R-curve move?
  CAPS     : infrastructure-limits frontier -- generation cap m x (no-fleet peak
             deficit) crossed with charging cap c x (peak surplus), at pv=2.5.
             Upgrades Fig 8.11 from one anecdotal instance to value-vs-tightness
             curves; records cap utilizations and infeasibility explicitly.
  PACK     : truck pack size G at fixed 350 kW rate, and rate rho at fixed G=7.
             Stationary-battery economics held fixed at $/kWh via c_b ~ G (the
             master's battery unit shares inst.G). Tests Fig 8.12's "bidirectional
             trucks shave a slice limited by pack capacity" and the bigger-packs-
             substitute-for-batteries trend.
  MODESX   : Fig 8.9 extension -- sols {3x, sum2x} to 400 tasks so every panel
             spans the same range. Writes overnight3_modes_sX{i}of{K}.json, which
             the existing Fig 8.9 glob (overnight3_modes_s*.json) picks up as is.
  SCALESEED: U6 warm/cold ladder at 2 extra seeds (2,3), n in {600,1000},
             L in {4,15}. Writes overnight3_scale_sX{i}of{K}.json (U6 glob-compatible).
  LATTICE  : SoC-lattice step {0.5,0.25,0.125} x n, LP-only. Quantifies the
             discretization drift; note at step 0.5 the truck charge rate
             quantizes to floor(rho/step)=3 levels/half-block (300 of the nominal
             350 kW), while step<=0.25 represents 1.75 exactly.

Run:   OVERNIGHT4_STUDIES="ETA,CAPS,PACK,MODESX,SCALESEED,LATTICE" \
       OVERNIGHT4_SHARD="i/K" python3 overnight4.py
Output: results/arxiv/overnight4_{eta,caps,pack}_s*.json,
        overnight3_modes_sX*.json, overnight3_scale_sX*.json,
        overnight4_lattice_s*.json
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from colgen import column_generation, SCENARIOS
from master import solve_milp
from overnight3 import (ckpt, solve, rand_trips, sol_kwargs,
                        CG_COST, CB_COST, RHO, CV, MILP_SOLVER)

# ============================== CONFIG -- EDIT ME ==============================
STUDIES = os.environ.get("OVERNIGHT4_STUDIES",
                         "ETA,CAPS,PACK,MODESX,SCALESEED,LATTICE").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT4_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def _base_stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 2)}


def eta_sweep():
    """ETA: eta x pv x n on the U2/modes family (L=3, 2-h tasks, salt 50k)."""
    rows, path = ckpt(f"overnight4_eta_s{SH_I}of{SH_K}.json")
    done = {(r["eta"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    ETAS = [0.0, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3]
    PVS = [1.0, 1.5, 2.5, 3.5]
    cells = [(sd, n, pv, eta) for sd in (0, 1) for n in (20, 60, 120)
             for pv in PVS for eta in ETAS]
    print(f"ETA sweep: {len(cells)} cells x 2, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv, eta) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"eta": eta, "pv": pv, "n_tasks": n, "seed": sd, **_base_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (eta, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.eta = eta
            r = solve(inst, scen, tl=120.0)
            if r is None:
                continue
            rows.append({**base, "scenario": scen, "total": round(r["total"], 1),
                         "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                         "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
            json.dump(rows, open(path, "w"))
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows]", flush=True)


def caps_sweep():
    """CAPS: gen cap m x peak deficit vs charging cap c x peak surplus, pv=2.5."""
    rows, path = ckpt(f"overnight4_caps_s{SH_I}of{SH_K}.json")
    done = {(r["gen_m"], r["chg_c"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    GEN_M = [1.0, 1.1, 1.3, float("inf")]
    CHG_C = [0.35, 0.7, 1.4, float("inf")]
    PV = 2.5
    cells = [(sd, n, m, c) for sd in (0, 1, 2) for n in (20, 60, 120)
             for m in GEN_M for c in CHG_C]
    print(f"CAPS sweep: {len(cells)} cells x 2, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, m, c) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=PV)
        peak_def = float(np.maximum(inst0.Delta, 0.0).max())     # units per half-block
        peak_sur = float(np.maximum(-inst0.Delta, 0.0).max())
        base = {"gen_m": m, "chg_c": c, "pv": PV, "n_tasks": n, "seed": sd,
                "gen_cap": (round(m * peak_def, 2) if np.isfinite(m) else None),
                "charge_cap": (round(c * peak_sur, 2) if np.isfinite(c) else None),
                **_base_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (m, c, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=PV)
            inst.gen_cap = m * peak_def if np.isfinite(m) else float("inf")
            inst.charge_cap = c * peak_sur if np.isfinite(c) else float("inf")
            r = solve(inst, scen, tl=120.0)
            if r is None:                     # infeasible under these caps IS data
                rows.append({**base, "scenario": scen, "feasible": False})
                json.dump(rows, open(path, "w"))
                continue
            mip = r["mip"]
            chg = np.zeros(inst.T)
            for col, x in zip(r["cols"], mip.x):
                if x > 0.5:
                    chg += np.maximum(col.e, 0.0) * round(x)
            if getattr(mip, "charge", None) is not None:
                chg += mip.charge
            row = {**base, "scenario": scen, "feasible": True,
                   "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                   "trucks": r["trucks"], "batteries": r["batteries"],
                   "gap_pct": round(r["gap"], 3),
                   "gen_peak": round(float(mip.g.max()), 2),
                   "chg_peak": round(float(chg.max()), 2)}
            if np.isfinite(m):
                row["gen_util"] = round(float(mip.g.max()) / (m * peak_def), 3)
            if np.isfinite(c):
                row["chg_util"] = round(float(chg.max()) / (c * peak_sur), 3)
            rows.append(row)
            json.dump(rows, open(path, "w"))
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows]", flush=True)


def _solve_custom(inst, scen, G=None, rho=None, c_b=None, tl=120.0):
    """overnight3.solve with overridable G / rho / c_b (pack study)."""
    inst.c_g, inst.c_v = CG_COST, CV
    inst.rho = RHO if rho is None else rho
    if G is not None:
        inst.G = G
    inst.c_b = CB_COST if c_b is None else c_b
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    return {"total": mip.obj, "g_units": float(mip.g.sum()),
            "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def pack_sweep():
    """PACK: G at rho=1.75, and rho at G=7; battery $/kWh fixed via c_b ~ G."""
    rows, path = ckpt(f"overnight4_pack_s{SH_I}of{SH_K}.json")
    done = {(r["G"], r["rho"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    GS = [3.5, 7.0, 10.5, 14.0]                  # 350-1400 kWh packs, rho = 1.75
    RHOS = [0.5, 1.0, 2.5]                       # 100/200/500 kW at G = 7 (1.75 = base, in GS arm)
    arms = ([(G, RHO) for G in GS] + [(7.0, rh) for rh in RHOS])
    cells = [(sd, n, pv, G, rh) for sd in (0, 1) for n in (8, 20, 60, 120)
             for pv in (2.0, 4.0) for (G, rh) in arms]
    print(f"PACK sweep: {len(cells)} cells x 3, shard {SH_I}/{SH_K} "
          f"({len(rows)} rows done)", flush=True)
    for idx, (sd, n, pv, G, rh) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=90_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"G": G, "rho": rh, "pv": pv, "n_tasks": n, "seed": sd,
                "c_b": round(CB_COST * G / 7.0, 1), **_base_stats(inst0)}
        for scen in ("solar", "v2g_fleet", "v2g"):
            if (G, rh, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            r = _solve_custom(inst, scen, G=G, rho=rh, c_b=CB_COST * G / 7.0)
            if r is None:
                continue
            rows.append({**base, "scenario": scen, "total": round(r["total"], 1),
                         "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
                         "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
            json.dump(rows, open(path, "w"))
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)} cells, {len(rows)} rows]", flush=True)


def modes_extension():
    """MODESX: U2 row schema at sols {3x, sum2x}, 240-400 tasks (same salts)."""
    rows, path = ckpt(f"overnight3_modes_sX{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["sol"], r["seed"], r["scenario"]) for r in rows}
    cells = [(sd, n, sol, scen) for sd in (0, 1) for n in (240, 280, 320, 360, 400)
             for sol in ("3x", "sum2x") for scen in ("vsp", "ev", "solar", "v2g")]
    print(f"MODESX: {len(cells)} cells, shard {SH_I}/{SH_K} "
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
        json.dump(rows, open(path, "w"))
        print(f"  n={n} {sol} seed={sd} {scen}: {time.time() - t0:.0f}s "
              f"({len(rows)} rows)", flush=True)


def scale_seeds():
    """SCALESEED: U6 ladder, seeds 2-3, n in {600,1000}, L in {4,15}, warm/cold."""
    rows, path = ckpt(f"overnight3_scale_sX{SH_I}of{SH_K}.json")
    done = {(r["L"], r["n_tasks"], r["seed"], r["start"]) for r in rows}
    from overnight3 import POOL
    cells = [(sd, L, n, st) for sd in (2, 3) for L in (4, 15)
             for n in (600, 1000) for st in ("warm", "cold")]
    print(f"SCALESEED: {len(cells)} runs, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, L, n, st) in enumerate(cells):
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
        json.dump(rows, open(path, "w"))
        print(f"  L={L} n={n} seed={sd} {st}: {rows[-1]['time_s']}s", flush=True)


def lattice_ladder():
    """LATTICE: SoC step {0.5,0.25,0.125} x n, LP-only (exact CG bound + time)."""
    rows, path = ckpt(f"overnight4_lattice_s{SH_I}of{SH_K}.json")
    done = {(r["step"], r["n_tasks"], r["seed"]) for r in rows}
    cells = [(sd, n, step) for sd in (0, 1) for n in (60, 120, 200)
             for step in (0.5, 0.25, 0.125)]
    print(f"LATTICE: {len(cells)} runs, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, step) in enumerate(cells):
        if idx % SH_K != SH_I or (step, n, sd) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.5)
        inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
        inst.soc_step = step
        t0 = time.time()
        res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                enrich=0, max_iter=max(2000, 5 * n))
        rows.append({"step": step, "n_tasks": n, "seed": sd,
                     "up_levels": int(np.floor((1 - inst.eta) * inst.rho / step)),
                     "dn_levels": int(np.floor(inst.rho / step)),
                     "lp_obj": round(res["lp_obj"], 3), "iters": res["iters"],
                     "time_s": round(time.time() - t0, 2),
                     "pricing_s": round(res["pricing_time"], 2)})
        json.dump(rows, open(path, "w"))
        print(f"  step={step} n={n} seed={sd}: lp={rows[-1]['lp_obj']} "
              f"{rows[-1]['time_s']}s", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    FN = {"ETA": eta_sweep, "CAPS": caps_sweep, "PACK": pack_sweep,
          "MODESX": modes_extension, "SCALESEED": scale_seeds,
          "LATTICE": lattice_ladder}
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time()
        FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
