"""SoC-step sweep on the LATTICE bases (overnight4.lattice_ladder): 3 locations,
rand_trips(3, n, sd, salt=50_000), BREAKS, pv_scale=2.5, eta=0, c_g/c_b/rho/c_v =
40/36/1.75/45, scenario v2g, warm start, enrich=0, max_iter=max(2000, 5n),
pricing tolerance 1e-6 (colgen default). Full recharge (cyclic).

Configurations per base:
  frozen        @ 50, 25 kWh : frozen vendor DP (reproduction check vs overnight4 JSON)
  nearest       @ 50,25,20,12.5,10 : copied DP with the frozen index rules
  conservative  @ 50,25,20,12.5,10 : copied DP, ceil traction / floor rate / floor capacity
  conservative_repaired @ 20 : conservative DP, column grid profile clipped so exact SoC <= G

Usage: python3 -B sweep.py [n_workers]
Writes sweep_results.json (one row per run, checkpointed) in this folder.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
import multiprocessing as mp

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENDOR = REPO / "experiments/opte_equal_mip_20261015/runtime/frozen/vendor"
OUT = HERE / "sweep_results.json"


def _setup():
    sys.dont_write_bytecode = True
    for p in (str(VENDOR), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)


def build(n, sd, step):
    _setup()
    import recreate_arxiv as RA
    from audit import rand_trips
    inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, n, sd, salt=50_000), pv_scale=2.5)
    inst.c_g, inst.c_b, inst.rho, inst.c_v = 40.0, 36.0, 1.75, 45.0
    inst.soc_step = step
    return inst


def run(cfg):
    _setup()
    import numpy as np
    import colgen, pricing_truck
    import dp_variants as V
    n, sd, variant, step = cfg
    inst = build(n, sd, step)
    colgen.price_truck_dp = (pricing_truck.price_truck_dp if variant == "frozen"
                             else V.make_repaired_pricer() if variant == "conservative_repaired"
                             else V.make_pricer(variant))
    t0 = time.time()
    res = colgen.column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                   enrich=0, max_iter=max(2000, 5 * n))
    wall = time.time() - t0
    cols, lp = res["cols"], res["lp"]
    x = np.asarray(lp.x) if lp is not None else np.zeros(len(cols))
    art = float(sum(xv for c, xv in zip(cols, x) if c.kind == "artificial"))
    row = {"n": n, "seed": sd, "variant": variant, "step_kwh": step * 100,
           "lp_obj": float(res["lp_obj"]), "converged": res["converged"],
           "term_reason": res["term_reason"], "iters": res["iters"], "n_cols": res["n_cols"],
           "cg_s": round(wall, 2), "pricing_s": round(res["pricing_time"], 2),
           "lp_artificial_mass": art}
    if variant != "frozen":
        dp_cols = [(c, xv) for c, xv in zip(cols, x) if hasattr(c, "trace")]
        reps = [(V.replay(inst, c), xv) for c, xv in dp_cols]
        row.update({
            "dp_cols": len(dp_cols),
            "dp_cols_trace_incomplete": sum(r["ok"] is None for r, _ in reps),
            "dp_cols_infeasible": sum(r["ok"] is False for r, _ in reps),
            "dp_cols_need_charge_clip": sum(bool(r.get("clipped_kwh", 0) > 1e-5) for r, _ in reps),
            "dp_cols_in_lp_support": sum(xv > 1e-9 for _, xv in reps),
            "lp_support_infeasible": sum((r["ok"] is False) and xv > 1e-9 for r, xv in reps),
            "lp_support_infeasible_weight": float(sum(xv for r, xv in reps if r["ok"] is False and xv > 1e-9)),
            "max_shortfall_kwh": max([r.get("shortfall_kwh", 0.0) for r, _ in reps] or [0.0]),
            "min_soc_kwh_min": min([r.get("min_soc_kwh", 1e9) for r, _ in reps] or [None]),
            "infeasible_reasons": sorted({x for r, _ in reps if r["ok"] is False for x in r["reason"]}),
        })
    return row


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    bases = [(n, sd) for sd in (0, 1) for n in (60, 120, 200)]
    cfgs = []
    for n, sd in bases:
        cfgs += [(n, sd, "frozen", 0.5), (n, sd, "frozen", 0.25)]
        for var in ("nearest", "conservative"):
            for step in (0.5, 0.25, 0.2, 0.125, 0.1):
                cfgs.append((n, sd, var, step))
        cfgs.append((n, sd, "conservative_repaired", 0.2))
    rows = json.loads(OUT.read_text()) if OUT.exists() else []
    done = {(r["n"], r["seed"], r["variant"], r["step_kwh"]) for r in rows}
    todo = [c for c in cfgs if (c[0], c[1], c[2], c[3] * 100) not in done]
    todo.sort(key=lambda c: -c[0] / c[3])          # longest first
    print(f"{len(todo)} runs to do ({len(rows)} done)", flush=True)
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pool:
        for row in pool.imap_unordered(run, todo):
            rows.append(row)
            tmp = OUT.with_suffix(".tmp"); tmp.write_text(json.dumps(rows, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))); os.replace(tmp, OUT)
            print(f"n={row['n']} sd={row['seed']} {row['variant']:12s} d={row['step_kwh']:5g} "
                  f"lp={row['lp_obj']:.3f} conv={row['converged']} cols={row['n_cols']} "
                  f"t={row['cg_s']}s infeas={row.get('dp_cols_infeasible')}/{row.get('dp_cols')} "
                  f"supp_infeas={row.get('lp_support_infeasible')}", flush=True)


if __name__ == "__main__":
    main()
