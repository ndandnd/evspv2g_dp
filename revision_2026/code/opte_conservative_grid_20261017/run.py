"""Conservative SoC-grid rerun of the six LATTICE planning bases (reviewer comment 5).

Inputs: the six bases of overnight4.lattice_ladder (paper-rewrite 2/code/overnight4.py
lines 262-288), exactly as in output/opte-corollary1-check-20261015/sweep.py:
3 task locations, rand_trips(3, n, seed, salt=50_000), n in {60,120,200}, seed in {0,1},
BREAKS, pv_scale 2.5, eta 0, c_g/c_b/rho/c_v = 40/36/1.75/45, scenario v2g, full
recharge, warm start, enrich 0, max_iter max(2000, 5n), pricing tolerance 1e-6,
restricted-master LPs by SciPy HiGHS (frozen colgen/master).

Arms (per base):
  frozen25   frozen vendor DP, 25 kWh (exact reference value; no traces)
  exact25    grid_dp nearest rule, 25 kWh (must equal frozen25; traces; route MIP)
  cons25     grid_dp conservative, 25 kWh (must equal frozen25: nothing is off-grid)
  cons20     grid_dp conservative, 20 kWh (the case in question; route MIP)
  cons50     grid_dp conservative, 50 kWh
  cons10     grid_dp conservative, 10 kWh
  near20     grid_dp nearest, 20 kWh (negative control: the 15 Oct letter case)
  rate160_10 grid_dp conservative, 10 kWh with the block limit set to 160 kWh
             (diagnostic: isolates the 175->160 kWh rate floor from traction rounding)

Restricted route MIP (exact25, cons20): Gurobi, cold, truck columns only, Threads 1,
Seed 0, MIPGap 1e-6, MIPGapAbs 1e-10, tolerances 1e-8, time limit 600 s.

Usage: python3 -B run.py [workers]   (writes only under output/opte-conservative-grid-20261017)
Refuses to overwrite: an existing raw/<case>/<arm>/result.json is skipped.
"""
from __future__ import annotations
import json, os, sys, time, traceback
from pathlib import Path
import multiprocessing as mp

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENDOR = HERE / "vendor"
OUT = REPO / "output/opte-conservative-grid-20261017"
RAW = OUT / "raw"
MIP_TIME = 600.0

ARMS = {  # name: (rule, step in model units, rho override or None, do_mip)
    "frozen25":   ("frozen", 0.25, None, False),
    "exact25":    ("nearest", 0.25, None, True),
    "cons25":     ("conservative", 0.25, None, False),
    "cons20":     ("conservative", 0.20, None, True),
    "cons50":     ("conservative", 0.50, None, False),
    "cons10":     ("conservative", 0.10, None, False),
    "near20":     ("nearest", 0.20, None, False),
    "rate160_10": ("conservative", 0.10, 1.60, False),
}
BASES = [(n, sd) for sd in (0, 1) for n in (60, 120, 200)]


def _setup():
    sys.dont_write_bytecode = True
    for p in (str(VENDOR), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)


def rand_trips(L, n, seed, windows=(6, 20), salt=20_000):
    # verbatim copy of ~/Downloads/paper-rewrite 2/code/overnight3.py lines 111-119
    import numpy as np
    rng = np.random.default_rng(salt + 1_000 * seed + 10 * L + n)
    out = []
    for _ in range(n):
        i = int(rng.integers(1, L + 1)); j = int(rng.integers(1, L + 1))
        while j == i:
            j = int(rng.integers(1, L + 1))
        out.append((i, j, int(rng.integers(windows[0], windows[1]))))
    return out


def build(n, sd, step, rho=1.75):
    _setup()
    import recreate_arxiv as RA
    inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, n, sd, salt=50_000), pv_scale=2.5)
    inst.c_g, inst.c_b, inst.rho, inst.c_v = 40.0, 36.0, rho, 45.0
    inst.soc_step = step
    return inst


def _jsonable(o):
    import numpy as np
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    return str(o)


def sparse(v, tol=1e-12):
    return {int(t): float(v[t]) for t in range(len(v)) if abs(v[t]) > tol}


def objective(inst, cols, x, g, chg, dis, nb, profiles):
    """Master objective recomputed from primal values and a chosen set of profiles."""
    import numpy as np
    eps = inst.eps_pen
    route = sum(x[r] * (cols[r].fixed_cost + eps * float(np.abs(profiles[r]).sum())) for r in range(len(cols)))
    return float(route + inst.c_g * g.sum() + eps * (chg.sum() + dis.sum()) + inst.c_b * nb
                 + getattr(inst, "deg_cost", 0.0) * dis.sum())


def master_check(inst, cols, x, g, chg, dis, nb, profiles):
    """Check every master row that a truck profile enters, plus coverage and the
    stationary-battery rows, for given primal values and profiles."""
    import numpy as np
    T = inst.T
    E = np.array([profiles[r] for r in range(len(cols))])            # R x T
    supply = g - x @ E - chg + dis - inst.Delta                        # must be >= 0
    A = np.array([c.a for c in cols])
    cover = x @ A - 1.0
    cum = np.concatenate([[0.0], np.cumsum((1 - inst.eta) * chg - dis)])
    bess_ok = (abs(cum[-1]) <= 1e-6 and cum.max() - cum.min() <= inst.G * nb + 1e-6
               and chg.max(initial=0) <= inst.rho * nb + 1e-6 and dis.max(initial=0) <= inst.rho * nb + 1e-6)
    return {"min_supply_slack": float(supply.min()), "max_abs_coverage_residual": float(np.abs(cover).max()),
            "bess_rows_ok": bool(bess_ok), "x_nonneg": bool((x >= -1e-9).all()),
            "ok": bool(supply.min() >= -1e-6 and np.abs(cover).max() <= 1e-6 and bess_ok and (x >= -1e-9).all())}


def solve_route_mip(inst, cols, time_limit):
    """Cold restricted MIP over real truck columns (paper settings, solve_pool_mip)."""
    import numpy as np
    from scipy import sparse as sp
    import gurobipy as gp
    from gurobipy import GRB
    import master
    assert all(c.kind == "truck" for c in cols)
    c, au, bu, ae, be, bounds, off, n, T, R, cc = master._build_lp(inst, cols, True, soc_mode="cyclic")
    oX, oG, oC, oD, oS, oNb = off
    lb = np.array([0. if lo is None else lo for lo, hi in bounds]); ub = np.array([np.inf if hi is None else hi for lo, hi in bounds])
    types = np.full(len(c), GRB.CONTINUOUS); types[np.r_[np.arange(R), oNb]] = GRB.INTEGER
    t0 = time.perf_counter()
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 0); env.start()
        with gp.Model("route_mip", env=env) as m:
            p = m.Params
            p.Threads = 1; p.Seed = 0; p.MIPGap = 1e-6; p.MIPGapAbs = 1e-10
            p.FeasibilityTol = 1e-8; p.OptimalityTol = 1e-8; p.IntFeasTol = 1e-8; p.TimeLimit = time_limit
            v = m.addMVar(len(c), lb=lb, ub=ub, obj=np.asarray(c), vtype=types)
            m.addMConstr(sp.csr_matrix(ae), v, "=", np.asarray(be)); m.addMConstr(sp.csr_matrix(au), v, "<", np.asarray(bu))
            m.optimize()
            st = {GRB.OPTIMAL: "optimal", GRB.TIME_LIMIT: "time_limit"}.get(m.Status, str(m.Status))
            out = {"status": st, "solver": "gurobi " + ".".join(map(str, gp.gurobi.version())),
                   "seconds": time.perf_counter() - t0, "solcount": int(m.SolCount)}
            if m.SolCount:
                z = np.asarray(v.X)
                out.update(obj=float(m.ObjVal), bound=float(m.ObjBound), x=z[oX:oX + R], g=z[oG:oG + T],
                           chg=z[oC:oC + T], dis=z[oD:oD + T], nb=float(z[oNb]))
    return out


def run_one(task):
    case, arm = task
    _setup()
    import numpy as np
    import colgen, master, pricing_truck
    import grid_dp, replay as RP
    n, sd = case
    rule, step, rho_ovr, do_mip = ARMS[arm]
    d = RAW / f"n{n}_s{sd}" / arm
    if (d / "result.json").exists():
        return {"case": case, "arm": arm, "skipped": "exists"}
    d.mkdir(parents=True, exist_ok=True)
    inst = build(n, sd, step, rho=(rho_ovr if rho_ovr is not None else 1.75))
    row = {"n": n, "seed": sd, "arm": arm, "rule": rule, "step_kwh": step * 100,
           "block_limit_kwh": inst.rho * 100}
    try:
        if rule == "frozen":
            colgen.price_truck_dp = pricing_truck.price_truck_dp
        else:
            colgen.price_truck_dp = grid_dp.make_pricer(rule)
            row["grid_mapping"] = grid_dp.grid_spec(inst, step, rule)["record"]
        t0 = time.time()
        res = colgen.column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                                       enrich=0, max_iter=max(2000, 5 * n))
        row["cg_seconds"] = round(time.time() - t0, 2)
        cols, lp = res["cols"], res["lp"]
        x = np.asarray(lp.x)
        row.update(lp_obj=float(res["lp_obj"]), converged=res["converged"], term_reason=res["term_reason"],
                   iters=res["iters"], n_cols=res["n_cols"],
                   lp_artificial_mass=float(sum(xv for c, xv in zip(cols, x) if c.kind == "artificial")),
                   lp_trucks=float(sum(xv for c, xv in zip(cols, x) if c.kind == "truck")),
                   lp_nb=float(lp.nb), lp_fossil_kwh=float(lp.g.sum() * 100))
        truck_idx = [r for r, c in enumerate(cols) if c.kind == "truck"]
        serial_cols = []
        if rule != "frozen":
            reps = {}
            for r in truck_idx:
                reps[r] = RP.replay(inst, cols[r])
            dp_idx = [r for r in truck_idx if getattr(cols[r], "trace", None) is not None]
            seed_idx = [r for r in truck_idx if getattr(cols[r], "trace", None) is None]
            supp = [r for r in truck_idx if x[r] > 1e-9]
            unclip = {r: RP.replay_unclipped(inst, cols[r]) for r in dp_idx}
            row["replay"] = {
                "truck_cols": len(truck_idx), "dp_cols": len(dp_idx), "seed_cols": len(seed_idx),
                "infeasible": sum(not reps[r]["ok"] for r in truck_idx),
                "infeasible_dp": sum(not reps[r]["ok"] for r in dp_idx),
                "infeasible_seed": sum(not reps[r]["ok"] for r in seed_idx),
                "reasons": sorted({z for r in truck_idx for z in reps[r]["reasons"]}),
                "needing_stop_when_full": sum(reps[r]["clipped_kwh"] > 1e-6 for r in truck_idx),
                "lp_support": len(supp),
                "lp_support_infeasible": sum(not reps[r]["ok"] for r in supp),
                "lp_support_infeasible_weight": float(sum(x[r] for r in supp if not reps[r]["ok"])),
                "lp_support_needing_stop_when_full": sum(reps[r]["clipped_kwh"] > 1e-6 for r in supp),
                "max_clipped_kwh_per_route": max([reps[r]["clipped_kwh"] for r in truck_idx] or [0.0]),
                "min_true_soc_kwh": min([reps[r]["min_soc_kwh"] for r in truck_idx if "min_soc_kwh" in reps[r]] or [None]),
                "max_true_final_shortfall_kwh": max([700.0 - reps[r]["final_kwh"] for r in truck_idx if "final_kwh" in reps[r]] or [0.0]),
                "unclipped_max_soc_kwh": max([unclip[r]["max_soc_kwh"] for r in dp_idx] or [None]),
                "unclipped_routes_above_capacity": sum(unclip[r]["max_soc_kwh"] > 700 + 1e-6 for r in dp_idx),
                "real_below_grid_events": sum(reps[r].get("real_below_grid_events", 0) for r in dp_idx),
            }
            ok_all = all(reps[r]["ok"] for r in truck_idx)
            # executed profiles (stop when full); for infeasible routes keep booked for bookkeeping
            exe = {r: (reps[r]["executed"] if reps[r]["ok"] else cols[r].e) for r in truck_idx}
            prof_booked = [c.e for c in cols]
            prof_exec = [exe.get(r, cols[r].e) for r in range(len(cols))]
            g, chg, dis, nb = lp.g, lp.charge, lp.discharge, float(lp.nb)
            row["lp_master_check_booked"] = master_check(inst, cols, x, g, chg, dis, nb, prof_booked)
            row["lp_master_check_executed"] = master_check(inst, cols, x, g, chg, dis, nb, prof_exec)
            row["lp_obj_recomputed_booked"] = objective(inst, cols, x, g, chg, dis, nb, prof_booked)
            row["lp_cost_executed_same_decisions"] = objective(inst, cols, x, g, chg, dis, nb, prof_exec)
            if ok_all:
                cols_exec = [master.Column(c.kind, c.a, prof_exec[r], c.fixed_cost, c.label + "|exec")
                             for r, c in enumerate(cols)]
                lp2 = master.solve_lp(inst, cols_exec, battery_allowed=True)
                row["lp_resolved_with_executed_profiles"] = float(lp2.obj)
            for r in truck_idx:
                c = cols[r]
                serial_cols.append({"r": r, "label": c.label, "a": np.flatnonzero(c.a > 0.5).tolist(),
                                    "e": sparse(c.e), "fixed_cost": c.fixed_cost,
                                    "trace": getattr(c, "trace", None), "x_lp": float(x[r]),
                                    "replay": {k: v for k, v in reps[r].items() if k != "executed"},
                                    "executed": sparse(reps[r]["executed"])})
        if do_mip:
            tcols = [cols[r] for r in truck_idx]
            mip = solve_route_mip(inst, tcols, MIP_TIME)
            mrow = {k: v for k, v in mip.items() if k not in ("x", "g", "chg", "dis")}
            if mip.get("solcount"):
                xm = np.round(mip["x"]).astype(float)
                sel = [i for i in range(len(tcols)) if xm[i] > 0.5]
                mreps = [RP.replay(inst, tcols[i]) for i in sel]
                mrow.update(trucks=int(xm.sum()), selected_cols=[truck_idx[i] for i in sel],
                            selected_infeasible=sum(not z["ok"] for z in mreps),
                            selected_needing_stop_when_full=sum(z["clipped_kwh"] > 1e-6 for z in mreps),
                            clipped_kwh_total=float(sum(z["clipped_kwh"] for z in mreps)),
                            fossil_kwh=float(mip["g"].sum() * 100))
                pe = [RP.replay(inst, c)["executed"] for c in tcols] if all(z["ok"] for z in mreps) else [c.e for c in tcols]
                pe = [pe[i] if xm[i] > 0.5 else tcols[i].e for i in range(len(tcols))]
                mrow["master_check_booked"] = master_check(inst, tcols, xm, mip["g"], mip["chg"], mip["dis"], mip["nb"], [c.e for c in tcols])
                mrow["master_check_executed"] = master_check(inst, tcols, xm, mip["g"], mip["chg"], mip["dis"], mip["nb"], pe)
                mrow["obj_recomputed_booked"] = objective(inst, tcols, xm, mip["g"], mip["chg"], mip["dis"], mip["nb"], [c.e for c in tcols])
                mrow["cost_executed_same_decisions"] = objective(inst, tcols, xm, mip["g"], mip["chg"], mip["dis"], mip["nb"], pe)
                mrow["x"] = sparse(xm); mrow["g"] = mip["g"]; mrow["chg"] = mip["chg"]; mrow["dis"] = mip["dis"]
            row["route_mip"] = mrow
            if rule != "frozen" and all(reps[r]["ok"] for r in truck_idx):
                # same pool, each route booked at what it actually stores (stop when full)
                ecols = [master.Column(c.kind, c.a, reps[r]["executed"], c.fixed_cost, c.label + "|exec")
                         for r, c in zip(truck_idx, tcols)]
                m2 = solve_route_mip(inst, ecols, MIP_TIME)
                row["route_mip_executed_profiles"] = {k: v for k, v in m2.items() if k not in ("x", "g", "chg", "dis")}
        row["lp_primal"] = {"x": sparse(x, 1e-12), "g": lp.g, "chg": lp.charge, "dis": lp.discharge, "nb": float(lp.nb)}
    except Exception:
        row["error"] = traceback.format_exc()
    tmp = d / "result.json.tmp"
    tmp.write_text(json.dumps({"summary": row, "columns": serial_cols if "error" not in row else []},
                              default=_jsonable, separators=(",", ":")))
    os.replace(tmp, d / "result.json")
    return {k: row.get(k) for k in ("n", "seed", "arm", "lp_obj", "cg_seconds", "error")} | \
           {"infeasible": row.get("replay", {}).get("infeasible"), "mip": row.get("route_mip", {}).get("obj")}


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else list(ARMS)
    RAW.mkdir(parents=True, exist_ok=True)
    tasks = [((n, sd), arm) for (n, sd) in BASES for arm in only]
    todo = [t for t in tasks if not (RAW / f"n{t[0][0]}_s{t[0][1]}" / t[1] / "result.json").exists()]
    todo.sort(key=lambda t: -(t[0][0] / ARMS[t[1]][1]) - (1e4 if ARMS[t[1]][3] else 0))
    print(f"{len(todo)} runs to do of {len(tasks)}", flush=True)
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pool:
        for out in pool.imap_unordered(run_one, todo):
            print(json.dumps(out, default=str), flush=True)


if __name__ == "__main__":
    main()
