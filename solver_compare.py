"""
Solver comparison for the EVSP-V2G covering-plus-arbitrage solver:
commercial Gurobi vs the open-source stack (HiGHS for the LP master, CBC for the
final integer master). The DP pricing oracle is solver-independent, so the only
thing that changes is the master: this isolates exactly where a commercial solver
helps.

For each instance it reports, on the *same* column pool (apples-to-apples):
  * LP head-to-head   : HiGHS vs Gurobi -- objective match + solve time
  * MILP head-to-head : CBC   vs Gurobi -- objective, time, and gap to the LP bound
  * (optional) end-to-end column generation with each LP backend -- total CG time
    and iteration count, which also reveals whether Gurobi avoids the dual
    ill-conditioning HiGHS hits on large degenerate set-partition LPs (~1000 tasks).

Run where Gurobi is available (your other machine / the cluster):
    python3 solver_compare.py
On a machine without gurobipy it still runs the open-source side and simply skips
the Gurobi columns, so you can sanity-check it anywhere first.

Outputs: results/solver_compare.json and .csv.
"""
from __future__ import annotations
import os, sys, time, json, csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instance import make_instance
from colgen import column_generation, summarize, SCENARIOS
from master import solve_lp, solve_milp

try:
    import gurobipy  # noqa: F401
    HAVE_GUROBI = True
except Exception:
    HAVE_GUROBI = False

# ============================== CONFIG -- EDIT ME ==============================
# (n_locations, n_tasks). Sizes chosen so CBC starts to choke (>=160 tasks) and
# the difference becomes meaningful. Add rows to push further.
LADDER = [(8, 160), (12, 360), (14, 450), (16, 600), (18, 1000)]

MILP_TIME_LIMIT   = 1800.0  # default budget (s) per integer solve for BOTH solvers -- a fair, generous
                            # 30-min head-to-head. Raise to 3600.0 for a 1-hour budget.
CBC_TIME_LIMIT    = None    # override CBC's budget only (None -> MILP_TIME_LIMIT). CBC reliably times
                            # out on large instances, so lowering this (e.g. 300) saves hours without
                            # changing the conclusion; leave None for a strictly-equal comparison.
GUROBI_TIME_LIMIT = None    # override Gurobi's budget only (None -> MILP_TIME_LIMIT).
MIP_GAP          = None    # relative gap stop, e.g. 0.01 accepts 1% and stops early.
RELAX_CAPS      = True    # relax gen/charge caps so large instances stay feasible
SCENARIO        = "v2g"   # "vsp" | "solar" | "v2g"
EPS             = 2.0     # 1.5 / 2.0 / 2.5 -> 150 / 200 / 250 kWh traction per task
SEED            = 7
ENRICH          = 25      # pool enrichment (same for both -> identical column pool)
RUN_CG_GUROBI   = True    # also run end-to-end CG with the Gurobi LP backend (set False to skip)
LP_TOL          = 1e-3    # tolerance for declaring the HiGHS/Gurobi LP objectives "matched"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
# ==============================================================================


def _env_float(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return float(value)


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_ladder(default):
    value = os.environ.get("EVSP_LADDER")
    if not value:
        return default
    ladder = []
    for item in value.split(","):
        loc, tasks = item.split(":")
        ladder.append((int(loc), int(tasks)))
    return ladder


LADDER = _env_ladder(LADDER)
MILP_TIME_LIMIT = _env_float("EVSP_MILP_TIME_LIMIT", MILP_TIME_LIMIT)
CBC_TIME_LIMIT = _env_float("EVSP_CBC_TIME_LIMIT", CBC_TIME_LIMIT)
GUROBI_TIME_LIMIT = _env_float("EVSP_GUROBI_TIME_LIMIT", GUROBI_TIME_LIMIT)
MIP_GAP = _env_float("EVSP_MIP_GAP", MIP_GAP)
RUN_CG_GUROBI = _env_bool("EVSP_RUN_CG_GUROBI", RUN_CG_GUROBI)


def _instance(n_locations, n_tasks):
    kw = dict(n_trips=n_tasks, n_locations=n_locations, eps=EPS, seed=SEED)
    if RELAX_CAPS:
        kw.update(gen_cap=float("inf"), charge_cap=float("inf"))
    return make_instance(**kw)


def _max_iter(n_tasks):
    return max(2000, 5 * n_tasks)


def _gap(mip_obj, lp_obj):
    if mip_obj is None or mip_obj == float("inf") or not mip_obj:
        return float("nan")
    return (mip_obj - lp_obj) / abs(mip_obj) * 100.0


def run_one(n_locations, n_tasks):
    inst = _instance(n_locations, n_tasks)
    batt = SCENARIOS[SCENARIO]["battery"]
    row = {"loc": n_locations, "tasks": n_tasks}

    # ---- 1. build the shared column pool via open-source CG (HiGHS LP) ----
    t0 = time.time()
    res = column_generation(inst, scenario=SCENARIO, start="warm", do_milp=False,
                            enrich=ENRICH, max_iter=_max_iter(n_tasks), lp_solver="highs")
    row["cg_highs_s"] = round(time.time() - t0, 2)
    row["cg_iters"] = res["iters"]
    row["cols"] = res["n_cols"]
    pool, lp_highs = res["cols"], res["lp_obj"]
    row["lp_obj"] = round(lp_highs, 1)
    if lp_highs == float("inf"):
        return row                                   # infeasible -- nothing else to do

    # ---- 2. LP head-to-head on the same pool ----
    t0 = time.time(); lp_h = solve_lp(inst, pool, battery_allowed=batt, solver="highs")
    row["lp_highs_solve_s"] = round(time.time() - t0, 3)
    if HAVE_GUROBI:
        t0 = time.time(); lp_g = solve_lp(inst, pool, battery_allowed=batt, solver="gurobi")
        row["lp_gurobi_solve_s"] = round(time.time() - t0, 3)
        row["lp_match"] = abs(lp_h.obj - lp_g.obj) < LP_TOL
        row["lp_gurobi_obj"] = round(lp_g.obj, 1)

    # ---- 3. MILP head-to-head on the same pool ----
    cbc_budget = CBC_TIME_LIMIT or MILP_TIME_LIMIT
    grb_budget = GUROBI_TIME_LIMIT or MILP_TIME_LIMIT
    t0 = time.time(); mip_cbc = solve_milp(inst, pool, time_limit=cbc_budget,
                                           battery_allowed=batt, solver="cbc",
                                           mip_gap=MIP_GAP)
    row["milp_cbc_s"] = round(time.time() - t0, 2)
    row["milp_cbc_obj"] = round(mip_cbc.obj, 1) if mip_cbc.obj != float("inf") else None
    row["milp_cbc_gap_pct"] = round(_gap(mip_cbc.obj, lp_highs), 3)
    row["cbc_converged"] = row["milp_cbc_s"] < 0.95 * cbc_budget      # finished before the cap => proved
    if HAVE_GUROBI:
        t0 = time.time(); mip_g = solve_milp(inst, pool, time_limit=grb_budget,
                                             battery_allowed=batt, solver="gurobi",
                                             mip_gap=MIP_GAP)
        row["milp_gurobi_s"] = round(time.time() - t0, 2)
        row["milp_gurobi_obj"] = round(mip_g.obj, 1) if mip_g.obj != float("inf") else None
        row["milp_gurobi_gap_pct"] = round(_gap(mip_g.obj, lp_highs), 3)
        row["gurobi_converged"] = row["milp_gurobi_s"] < 0.95 * grb_budget
        if row["milp_gurobi_s"] and row["milp_gurobi_s"] > 0:
            row["milp_speedup"] = round(row["milp_cbc_s"] / row["milp_gurobi_s"], 1)

    # ---- 4. (optional) end-to-end CG with the Gurobi LP backend ----
    if HAVE_GUROBI and RUN_CG_GUROBI:
        try:
            t0 = time.time()
            resg = column_generation(inst, scenario=SCENARIO, start="warm", do_milp=False,
                                     enrich=ENRICH, max_iter=_max_iter(n_tasks),
                                     lp_solver="gurobi")
            row["cg_gurobi_s"] = round(time.time() - t0, 2)
            row["cg_gurobi_iters"] = resg["iters"]
            row["cg_lp_match"] = abs(resg["lp_obj"] - lp_highs) < max(LP_TOL, 1e-3 * abs(lp_highs))
        except Exception as e:                       # don't let a CG-backend issue kill the run
            row["cg_gurobi_error"] = repr(e)[:120]
    return row


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cbc_b = CBC_TIME_LIMIT or MILP_TIME_LIMIT
    grb_b = GUROBI_TIME_LIMIT or MILP_TIME_LIMIT
    print(f"Gurobi available: {HAVE_GUROBI}   scenario={SCENARIO}  eps={EPS}  "
          f"caps={'relaxed' if RELAX_CAPS else 'enforced'}  "
          f"budgets: CBC={cbc_b}s Gurobi={grb_b}s  mip_gap={MIP_GAP}\n", flush=True)
    rows = []
    for nl, nt in LADDER:
        row = run_one(nl, nt)
        rows.append(row)
        # incremental save so a long benchmark is never lost
        json.dump({"config": {"relax_caps": RELAX_CAPS, "milp_time_limit": MILP_TIME_LIMIT,
                              "cbc_time_limit": CBC_TIME_LIMIT,
                              "gurobi_time_limit": GUROBI_TIME_LIMIT,
                              "mip_gap": MIP_GAP,
                              "ladder": LADDER,
                              "scenario": SCENARIO, "eps": EPS, "seed": SEED,
                              "have_gurobi": HAVE_GUROBI}, "rows": rows},
                  open(os.path.join(OUT_DIR, "solver_compare.json"), "w"), indent=2)
        # progress (LP-solve speed, MILP convergence, and the Gurobi-LP-backed CG)
        print(f"loc={nl:3d} tasks={nt:4d}  cols={row.get('cols')}  LP={row.get('lp_obj')}  "
              f"CG(HiGHS)={row.get('cg_highs_s')}s", flush=True)
        if row.get("lp_obj") in (None, float("inf")):
            print("    INFEASIBLE -- skipped MILP", flush=True)
        elif HAVE_GUROBI:
            print(f"    LP-solve : HiGHS={row.get('lp_highs_solve_s')}s  "
                  f"Gurobi={row.get('lp_gurobi_solve_s')}s  match={row.get('lp_match')}", flush=True)
            print(f"    MILP CBC : {row.get('milp_cbc_s')}s  gap={row.get('milp_cbc_gap_pct')}%  "
                  f"converged={row.get('cbc_converged')}", flush=True)
            print(f"    MILP GRB : {row.get('milp_gurobi_s')}s  gap={row.get('milp_gurobi_gap_pct')}%  "
                  f"converged={row.get('gurobi_converged')}  speedup={row.get('milp_speedup','-')}x", flush=True)
            if 'cg_gurobi_s' in row:
                print(f"    CG(GurobiLP): {row.get('cg_gurobi_s')}s  iters={row.get('cg_gurobi_iters')}  "
                      f"lp_match={row.get('cg_lp_match')}", flush=True)
            elif 'cg_gurobi_error' in row:
                print(f"    CG(GurobiLP): ERROR {row.get('cg_gurobi_error')}", flush=True)
        else:
            print(f"    MILP CBC : {row.get('milp_cbc_s')}s  gap={row.get('milp_cbc_gap_pct')}%  "
                  f"converged={row.get('cbc_converged')}", flush=True)

    # CSV
    keys = ["loc", "tasks", "cg_iters", "cols", "lp_obj",
            "cg_highs_s", "cg_gurobi_s", "cg_gurobi_iters", "cg_lp_match",
            "lp_highs_solve_s", "lp_gurobi_solve_s", "lp_match",
            "milp_cbc_s", "milp_cbc_gap_pct", "cbc_converged",
            "milp_gurobi_s", "milp_gurobi_gap_pct", "gurobi_converged", "milp_speedup"]
    with open(os.path.join(OUT_DIR, "solver_compare.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    print(f"\nsaved: {os.path.join(OUT_DIR, 'solver_compare.json')} and solver_compare.csv")
    if not HAVE_GUROBI:
        print("(gurobipy not found -- ran the open-source side only. Run on a Gurobi "
              "machine for the head-to-head.)")


if __name__ == "__main__":
    main()
