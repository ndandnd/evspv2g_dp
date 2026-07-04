"""
Head-to-head vs the ORIGINAL repo's code (github.com/ndandnd/evspv2g), on the
exact instance its saved run script is already configured for:
    mode 3 (EVSP_V2G), eps=2.5, 2 locations (= 20 trips, breaks schedule),
    solar_mult=7 -- i.e. just `python src/run_experiments.py` in the old repo.

Why objectives, not fuel: both codes minimize TOTAL COST; fuel is a degenerate
side metric near the optimum. And the LP value is the non-heuristic quantity --
the original's column generation converges to its master's LP optimum regardless
of its pool-heuristic pricing, so LP-to-LP is the clean pricing-equivalence test
(the same test that matched our three DP implementations to the digit).

Alignment applied on our side (everything else already matches):
  * soc_mode = "free"      : the original's free full initial charge, free end.
  * master.COVERING = True : the original's trip coverage is >= 1, not == 1.
  * constant offset        : our master carries the base-load fossil cost
                             c_g * sum_t max(Delta_t, 0) (= 845 here) that the
                             original's master leaves out of the model entirely;
                             it is subtracted before comparing.

Known residual deviations (small, with signs):
  * their 1.01 charge premium vs our eps_pen  -> theirs slightly HIGHER (~<=0.5%);
  * our half-hour charging grid vs their integer-hour charge starts (their
    cst >= arrival rounds up to the next hour) -> ours slightly LOWER;
  * their MILP stops at MIPGap 1% -> compare LPs first, MIPs as a sanity band.

Usage:
  1) On the Gurobi machine, in the OLD repo:  python src/run_experiments.py
     and note the line  "Final LP, MIP obj: <LP> <MIP>".
  2) Fill ORIG_LP / ORIG_MIP below and rerun this file -- it prints the verdict.
     (With them None it still runs our side and prints the adjusted numbers.)
"""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import master
import recreate_arxiv as R
from colgen import column_generation
from master import solve_milp

# ==================== paste the original code's output here ====================
ORIG_LP  = None   # e.g. 612.35  from "Final LP, MIP obj: <LP> <MIP>"
ORIG_MIP = None
POINTS   = 2      # 2 -> 20 trips: the old script's saved default. (3 -> 60 needs
                  # editing points_list in the old run_experiments.py too.)
# ==============================================================================


def run_ours(points, c_b=None):
    master.COVERING = True                    # original: coverage >= 1
    inst = R.build_instance(points, 2.5, R.BREAKS)
    if c_b is not None:
        inst.c_b = c_b
    baseline = float(np.maximum(inst.Delta, 0.0).sum()) * inst.c_g   # 845 at solar_mult=7
    res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips),
                            soc_mode="free")
    mip = solve_milp(inst, res["cols"], time_limit=R.MILP_TIME_LIMIT,
                     battery_allowed=True, solver=R.MILP_SOLVER, soc_mode="free")
    master.COVERING = False                   # restore the default
    trucks = int(sum(round(x) for x in mip.x))
    return {"lp": res["lp_obj"], "mip": mip.obj, "baseline": baseline,
            "lp_adj": res["lp_obj"] - baseline, "mip_adj": mip.obj - baseline,
            "trucks": trucks, "batteries": int(round(mip.nb)), "trips": inst.n_trips}


if __name__ == "__main__":
    print(f"MILP solver: {R.MILP_SOLVER} (Gurobi available: {R.HAVE_GUROBI})\n")
    # Run 1: the intended model (batt_cost = 36).
    # Run 2: replicate the original build_master's battery-cost slip -- its final
    # LP/MIP prices battery routes with bus_cost (45); the batt_cost argument is
    # never used. The original's PRINTED objective corresponds to c_b = 45.
    ours36 = run_ours(POINTS, c_b=36.0)
    ours45 = run_ours(POINTS, c_b=45.0)
    print(f"our side ({ours36['trips']} trips, free mode, covering >= 1), adjusted "
          f"(base-load constant {ours36['baseline']:.0f} subtracted):")
    print(f"  c_b=36 (intended model)          : LP = {ours36['lp_adj']:8.2f}  "
          f"MIP = {ours36['mip_adj']:8.2f}  trucks={ours36['trucks']} batt={ours36['batteries']}")
    print(f"  c_b=45 (original's final-master  : LP = {ours45['lp_adj']:8.2f}  "
          f"MIP = {ours45['mip_adj']:8.2f}  trucks={ours45['trucks']} batt={ours45['batteries']}")
    print(f"          battery-cost slip)")
    if ORIG_LP is None:
        print("\nNext: on the Gurobi machine, in the OLD repo (ndandnd/evspv2g):")
        print("    python src/run_experiments.py")
        print('  (its saved defaults are exactly this cell: mode 3, eps=2.5, 2 locations,')
        print('   solar_mult=7). Note the line "Final LP, MIP obj: <LP> <MIP>",')
        print("  fill ORIG_LP / ORIG_MIP at the top of this file, and rerun it.")
    else:
        dlp = 100 * (ours45["lp_adj"] - ORIG_LP) / abs(ORIG_LP)
        print(f"\noriginal code:  LP = {ORIG_LP:9.2f}"
              + (f"    MIP = {ORIG_MIP:9.2f}" if ORIG_MIP is not None else ""))
        print(f"vs our c_b=45 run:  LP diff = {ours45['lp_adj'] - ORIG_LP:+8.2f}  ({dlp:+.2f}%)")
        print("\nverdict: within ~1% -> the DP prices the original's own model to the same")
        print("optimum; the original's printed objective embeds its build_master slip")
        print("(batteries at bus_cost=45), which the c_b=45 run replicates. To verify")
        print("independently: in the OLD repo's src/master.py, build_master, change the two")
        print("route_costs_batt lines from bus_cost to batt_cost and rerun -- the original")
        print(f"should then print ~{ours36['lp_adj']:.0f} (our intended-model number).")
