"""
Scalability study for the covering-plus-arbitrage EVSP-V2G solver.

What it shows
-------------
(A) The realism instance has a *physical* capacity ceiling: with the generation
    and charging caps enforced, only so many daily tasks can be served before the
    LP is infeasible (the infrastructure, not the routing, is the bottleneck).
(B) Method scalability: with caps relaxed (to isolate the solver), the LP
    relaxation -- column generation with the labeling-DP pricing oracle -- scales
    to hundreds of tasks in seconds on open-source solvers (HiGHS + CBC), versus
    the ~8.3 hours the MILP-pricing conference version needed for 450 tasks.

How to run (VSCode)
-------------------
Open the `evspv2g_dp` folder, pick an interpreter that has numpy/scipy/pulp
installed (matplotlib optional, only for the plot), and press Run on this file.
From a terminal:  python3 scalability.py

How to scale it up yourself
---------------------------
Everything you'd want to change lives in the CONFIG block just below. To push
larger, add rows to LADDER (more locations spread tasks over space-time and keep
the instance feasible). To study the realism ceiling instead, set RELAX_CAPS =
False. To trade accuracy for speed, lower MILP_TIME_LIMIT or set it to None
(LP/CG only -- the fastest, and the part this study is really about).
"""
from __future__ import annotations
import os, sys, time, json, csv

# Make `from instance import ...` work no matter where VSCode runs this from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from instance import make_instance
from colgen import column_generation, summarize, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
# (B) Method-scalability ladder: (n_locations, n_tasks). Add rows to go bigger;
#     scaling locations alongside tasks keeps routes feasible. Try e.g.
#     (16, 600), (18, 800), (20, 1000) -- expect the LP/CG time to keep growing
#     gently while CBC's integer step becomes the bottleneck.
LADDER = [(16, 600), (18, 800), (20, 1000)]
#[(2, 10), (3, 20), (4, 40), (5, 80), (8, 160), (10, 240), (12, 360), (14, 450), 

RELAX_CAPS      = True   # True: relax gen/charge caps to isolate solver scaling (Table-style).
                         # False: enforce the realism caps (then big sizes go INFEASIBLE -- that's (A)).
MILP_TIME_LIMIT = 120.0  # seconds of CBC per instance for the integer solve and gap.
                         # Set to None for LP/CG only (fastest; no gap/vehicle columns).
SCENARIO        = "v2g"  # "vsp" (ICE) | "solar" (charge-only EV) | "v2g" (EV + V2G + battery)
EPS             = 2.0    # 1.5 / 2.0 / 2.5  ->  150 / 200 / 250 kWh traction per task
SEED            = 7
ENRICH          = 25     # pool-enrichment rounds (shrinks the integrality gap; LP bound unchanged)
MAX_ITER        = None    # CG iteration cap. None = auto (max(2000, 5x tasks)) so it grows with
                         # instance size and never truncates convergence. Set an int for a hard cap
                         # (the library default was 1000, which truncated >=1000-task instances).

# (A) Capacity-ceiling scan under the realism caps (fixed locations, caps ON).
DO_CEILING_SCAN = True
CEILING_LOCS    = 3
CEILING_TASKS   = [60, 70, 80, 90, 100, 110, 120]

# Output
OUT_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
MAKE_PLOT = True         # save a LP/CG-time-vs-tasks plot if matplotlib is available
# ==============================================================================


def _instance(n_locations, n_tasks):
    kw = dict(n_trips=n_tasks, n_locations=n_locations, eps=EPS, seed=SEED)
    if RELAX_CAPS:
        kw.update(gen_cap=float("inf"), charge_cap=float("inf"))
    return make_instance(**kw)


def _max_iter(n_tasks):
    """CG iteration budget: explicit MAX_ITER, else an auto cap that scales with size."""
    return MAX_ITER if MAX_ITER else max(2000, 5 * n_tasks)


def run_one(n_locations, n_tasks):
    """Solve one instance. Returns a result row (dict)."""
    inst = _instance(n_locations, n_tasks)
    batt = SCENARIOS[SCENARIO]["battery"]
    t0 = time.time()
    res = column_generation(inst, scenario=SCENARIO, start="warm",
                            do_milp=False, enrich=ENRICH,
                            max_iter=_max_iter(n_tasks))     # fast LP/CG (the method)
    cg_time = time.time() - t0
    feasible = res["lp_obj"] != float("inf")

    row = {"loc": n_locations, "tasks": n_tasks, "feasible": feasible,
           "cg_iters": res["iters"], "cols": res["n_cols"],
           "cg_time_s": round(cg_time, 2), "lp_obj": round(res["lp_obj"], 1)}

    if feasible and MILP_TIME_LIMIT:                        # configurable integer solve
        t1 = time.time()
        mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT, battery_allowed=batt)
        res["mip"] = mip
        s = summarize(inst, res)
        gap = (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100 if mip.obj else float("nan")
        row.update({"mip_time_s": round(time.time() - t1, 2), "trucks": s["trucks"],
                    "batteries": s["batteries"], "mip_obj": round(mip.obj, 1),
                    "gap_pct": round(gap, 3)})
    return row


def ceiling_scan():
    print("\n=== (A) Capacity ceiling under the realism caps "
          f"({CEILING_LOCS} locations, caps ON) ===")
    rows = []
    for nt in CEILING_TASKS:
        inst = make_instance(n_trips=nt, n_locations=CEILING_LOCS, eps=EPS, seed=SEED)
        r = column_generation(inst, scenario=SCENARIO, start="warm", do_milp=False,
                              max_iter=_max_iter(nt))
        feas = r["lp_obj"] != float("inf")
        rows.append({"tasks": nt, "feasible": feas,
                     "lp_obj": (round(r["lp_obj"], 1) if feas else None)})
        print(f"  tasks={nt:4d}  "
              + (f"FEASIBLE  lp={r['lp_obj']:.0f}" if feas else "INFEASIBLE (caps bind)"))
    feas_tasks = [r["tasks"] for r in rows if r["feasible"]]
    if feas_tasks and len(feas_tasks) < len(rows):
        print(f"  -> ceiling: feasible up to {max(feas_tasks)} tasks, infeasible beyond.")
    return rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ceiling = ceiling_scan() if DO_CEILING_SCAN else None

    caps_txt = "caps RELAXED (solver scaling)" if RELAX_CAPS else "caps ENFORCED (realism)"
    print(f"\n=== (B) Method scalability ladder -- {SCENARIO}, eps={EPS}, {caps_txt} ===")
    header = ["loc", "tasks", "cg_it", "cols", "cg_s"]
    if MILP_TIME_LIMIT:
        header += ["mip_s", "trucks", "batt", "gap%"]
    print("  " + "".join(f"{h:>8}" for h in header))

    rows = []
    for nl, nt in LADDER:
        row = run_one(nl, nt)
        rows.append(row)
        if not row["feasible"]:
            print(f"  {nl:>8}{nt:>8}{'--':>8}{row['cols']:>8}{row['cg_time_s']:>8}   INFEASIBLE")
        else:
            cells = [row["loc"], row["tasks"], row["cg_iters"], row["cols"], row["cg_time_s"]]
            if MILP_TIME_LIMIT:
                cells += [row.get("mip_time_s", ""), row.get("trucks", ""),
                          row.get("batteries", ""), row.get("gap_pct", "")]
            print("  " + "".join(f"{str(c):>8}" for c in cells))
        # save after every instance so a long run is never lost
        json.dump({"config": {"relax_caps": RELAX_CAPS, "milp_time_limit": MILP_TIME_LIMIT,
                              "scenario": SCENARIO, "eps": EPS, "seed": SEED},
                   "ceiling": ceiling, "ladder": rows},
                  open(os.path.join(OUT_DIR, "scalability.json"), "w"), indent=2)

    # CSV (easy to open in a spreadsheet)
    if rows:
        keys = ["loc", "tasks", "feasible", "cg_iters", "cols", "cg_time_s", "lp_obj",
                "mip_time_s", "trucks", "batteries", "mip_obj", "gap_pct"]
        with open(os.path.join(OUT_DIR, "scalability.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    if MAKE_PLOT:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            feas = [r for r in rows if r["feasible"]]
            if feas:
                xs = [r["tasks"] for r in feas]
                fig, ax = plt.subplots(figsize=(6.5, 4), constrained_layout=True)
                ax.plot(xs, [r["cg_time_s"] for r in feas], "-o", color="#2E75B6",
                        label="LP/CG (DP pricing)")
                if MILP_TIME_LIMIT:
                    ax.plot(xs, [r.get("mip_time_s", 0) for r in feas], "-s", color="#c0392b",
                            label=f"CBC integer ({MILP_TIME_LIMIT:.0f}s cap)")
                ax.set_xlabel("number of tasks"); ax.set_ylabel("solve time (s)")
                ax.set_title("EVSP-V2G scalability (open-source solvers)"); ax.legend()
                fig.savefig(os.path.join(OUT_DIR, "scalability.png"), dpi=130)
                print(f"\nplot -> {os.path.join(OUT_DIR, 'scalability.png')}")
        except ImportError:
            print("\n(matplotlib not installed -- skipping plot; numbers are in results/)")

    print(f"\nsaved: {os.path.join(OUT_DIR, 'scalability.json')} and scalability.csv")
    print("For reference, the MILP-pricing conference version needed ~8.3 h for 450 tasks.")


if __name__ == "__main__":
    main()
