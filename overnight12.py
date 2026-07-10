"""
Overnight-12: solver-diagnostics ladder + the unified one-factor SPINE.

  DIAG  : full solver diagnostics (LP bound, integer objective, gap, columns,
          CG iterations, pricing/CG/MILP time split) on the SAME multi-station
          maps as the U6 LP ladder: L in {4,15} x n in {100,200,400,600,800,
          1000} x 2 task draws, v2g. Completes the paper's Table "diagbig"
          with integer columns; MILP capped at 1800 s (gap recorded anyway).
  SPINE : every one-factor sweep re-anchored to the single reference cell of
          the paper's design table (60 two-hour 200-kWh tasks over three
          locations, depot charging, 2x solar, G=7, rho=1.75, eta=0,
          delta=0.5, planning prices), 3 task draws x {solar, v2g}:
          pv / workload / eta / pack G / rate rho / lattice delta /
          generation-cap / charging-cap arms. Every arm passes through the
          reference point itself, so the arms cross-validate at their shared
          anchor.

Run: OVERNIGHT12_STUDIES="DIAG,SPINE" OVERNIGHT12_SHARD="i/K" python3 overnight12.py
"""
from __future__ import annotations
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from colgen import column_generation, SCENARIOS
from master import solve_milp
from overnight3 import ckpt, save, rand_trips, POOL, CG_COST, CB_COST, RHO, CV, MILP_SOLVER

STUDIES = os.environ.get("OVERNIGHT12_STUDIES", "DIAG,SPINE").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT12_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")


def _stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3)}


def diag():
    """Integer diagnostics on the U6 maps (same instances as the LP ladder)."""
    rows, path = ckpt(f"overnight12_diag_s{SH_I}of{SH_K}.json")
    done = {(r["L"], r["n_tasks"], r["seed"]) for r in rows}
    cells = [(L, n, sd) for L in (4, 15) for n in (100, 200, 400, 600, 800, 1000)
             for sd in (0, 1)]
    print(f"DIAG: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (L, n, sd) in enumerate(cells):
        if idx % SH_K != SH_I or (L, n, sd) in done:
            continue
        fleet = rand_trips(L, n, 200 + sd)
        inst = build_instance(L, 1.0, [(6, 20)], trip_list=fleet, duration=1.0,
                              coords_override=POOL[:L], stations="all", pv_scale=2.0)
        inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
        t0 = time.time()
        res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                enrich=50, max_iter=max(3000, 6 * n))
        cg_s = time.time() - t0
        row = {"L": L, "n_tasks": n, "seed": sd, "cols": res["n_cols"],
               "cg_iters": res["iters"], "cg_s": round(cg_s, 2),
               "pricing_s": round(res["pricing_time"], 2),
               "lp_obj": round(res["lp_obj"], 2)}
        t1 = time.time()
        mip = solve_milp(inst, res["cols"], time_limit=1800.0,
                         battery_allowed=True, solver=MILP_SOLVER)
        row["milp_s"] = round(time.time() - t1, 2)
        if getattr(mip, "status", "optimal") == "optimal" and np.isfinite(mip.obj):
            row.update({"mip_obj": round(mip.obj, 2),
                        "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                        "trucks": int(sum(round(x) for x in mip.x)),
                        "batteries": int(round(mip.nb))})
        else:
            row["mip_obj"] = None
        rows.append(row)
        save(rows, path)
        print(f"  L={L} n={n} sd={sd}: lp {row['lp_obj']} cols {row['cols']} "
              f"cg {row['cg_s']}s milp {row['milp_s']}s gap {row.get('gap_pct')}", flush=True)


def _solve12(inst, scen, tl=180.0, c_b=None, rho=None):
    """overnight3.solve, but pack cost and rate overrides survive."""
    inst.c_g, inst.c_v = CG_COST, CV
    inst.c_b = CB_COST if c_b is None else c_b
    inst.rho = RHO if rho is None else rho
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    if getattr(mip, "status", "optimal") != "optimal" or not np.isfinite(mip.obj):
        return None
    return {"total": mip.obj, "g_units": float(mip.g.sum()),
            "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def spine():
    """All one-factor arms from the single reference cell (60 tasks, 2x solar)."""
    rows, path = ckpt(f"overnight12_spine_s{SH_I}of{SH_K}.json")
    done = {(r["factor"], str(r["value"]), r["seed"], r["scenario"]) for r in rows}
    arms = ([("pv", v) for v in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0)]
            + [("n", v) for v in (20, 40, 60, 80, 100, 120)]
            + [("eta", v) for v in (0.0, 0.03, 0.05, 0.1, 0.15, 0.2, 0.3)]
            + [("G", v) for v in (3.5, 7.0, 10.5, 14.0)]
            + [("rho", v) for v in (0.5, 1.0, 1.75, 2.5)]
            + [("delta", v) for v in (0.5, 0.25)]
            + [("genm", v) for v in (1.0, 1.1, 1.3, float("inf"))]
            + [("chgc", v) for v in (0.35, 0.7, 1.4, float("inf"))])
    cells = [(sd, f, v, scen) for sd in (0, 1, 2) for (f, v) in arms
             for scen in ("solar", "v2g")]
    print(f"SPINE: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, f, v, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (f, str(v), sd, scen) in done:
            continue
        n = int(v) if f == "n" else 60
        pv = float(v) if f == "pv" else 2.0
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"factor": f, "value": (None if not np.isfinite(v) else v),
                "n_tasks": n, "pv": pv, "seed": sd, **_stats(inst)}
        c_b = rho = None
        if f == "eta":
            inst.eta = v
        elif f == "G":
            inst.G = v
            c_b = CB_COST * v / 7.0            # stationary $/kWh held fixed
        elif f == "rho":
            rho = v
        elif f == "delta":
            inst.soc_step = v
        elif f == "genm":
            peak_def = float(np.maximum(inst.Delta, 0.0).max())
            inst.gen_cap = v * peak_def if np.isfinite(v) else float("inf")
        elif f == "chgc":
            peak_sur = float(np.maximum(-inst.Delta, 0.0).max())
            inst.charge_cap = v * peak_sur if np.isfinite(v) else float("inf")
        r = _solve12(inst, scen, c_b=c_b, rho=rho)
        if r is None:                          # infeasible under a cap IS data
            rows.append({**base, "scenario": scen, "feasible": False})
        else:
            rows.append({**base, "scenario": scen, "feasible": True,
                         "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                         "trucks": r["trucks"], "batteries": r["batteries"],
                         "gap_pct": round(r["gap"], 3)})
        save(rows, path)
        if idx % 20 == 0:
            print(f"  [{idx}/{len(cells)}] {f}={v} sd={sd} {scen}", flush=True)


def end4():
    """Measure the still-censored 60-task charge-only floors: budgets 1.5-2.5x."""
    rows, path = ckpt(f"overnight12_end4_s{SH_I}of{SH_K}.json")
    done = {(r["frac"], r["pv"], r["n_tasks"], r["seed"]) for r in rows}
    FRACS = [1.5, 1.6, 1.8, 2.0, 2.5]
    cells = [(sd, 60, pv, f) for sd in (0, 1, 2) for pv in (1.5, 2.5) for f in FRACS]
    print(f"END4: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, f) in enumerate(cells):
        if idx % SH_K != SH_I or (f, pv, n, sd) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        baseline = float(np.maximum(inst.Delta, 0.0).sum())
        base = {"frac": f, "pv": pv, "n_tasks": n, "seed": sd,
                "budget_units": round(f * baseline, 1), **_stats(inst)}
        inst.fuel_budget = f * baseline
        r = _solve12(inst, "solar", tl=300.0)
        if r is None:
            rows.append({**base, "scenario": "solar", "feasible": False})
        else:
            rows.append({**base, "scenario": "solar", "feasible": True,
                         "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                         "trucks": r["trucks"], "batteries": r["batteries"],
                         "gap_pct": round(r["gap"], 3)})
        save(rows, path)
        print(f"  frac={f} pv={pv} sd={sd}: feasible={rows[-1]['feasible']}", flush=True)


def pack3():
    """Tight-gap rerun of the dead-zone pack cells: n in {120,200}, 6 draws, 1800 s."""
    from overnight11 import _solve_pack
    rows, path = ckpt(f"overnight12_pack3_s{SH_I}of{SH_K}.json")
    done = {(r["G"], r["n_tasks"], r["seed"]) for r in rows}
    cells = [(sd, n, G) for sd in range(6) for n in (120, 200)
             for G in (3.5, 7.0, 10.5, 14.0)]
    print(f"PACK3: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, G) in enumerate(cells):
        if idx % SH_K != SH_I or (G, n, sd) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=90_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=2.0)
        base = {"G": G, "pv": 2.0, "n_tasks": n, "seed": sd,
                "c_b": round(CB_COST * G / 7.0, 1), **_stats(inst)}
        r = _solve_pack(inst, "v2g", G, tl=1800.0)
        if r is None:
            rows.append({**base, "scenario": "v2g", "feasible": False})
        else:
            rows.append({**base, "scenario": "v2g", "feasible": True,
                         "total": round(r["total"], 1), "g_units": round(r["g_units"], 2),
                         "trucks": r["trucks"], "batteries": r["batteries"],
                         "gap_pct": round(r["gap"], 3)})
        save(rows, path)
        print(f"  G={G} n={n} sd={sd}: gap={rows[-1].get('gap_pct')}", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    FN = {"DIAG": diag, "SPINE": spine, "END4": end4, "PACK3": pack3}
    for s in STUDIES:
        s = s.strip()
        if s in FN:
            print(f"=== {s} ===", flush=True)
            FN[s]()
    print(f"overnight12 done in {(time.time() - t0) / 3600:.2f} h", flush=True)
