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


def run_ours(points):
    master.COVERING = True                    # original: coverage >= 1
    inst = R.build_instance(points, 2.5, R.BREAKS)
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
    ours = run_ours(POINTS)
    print(f"our side ({ours['trips']} trips, free mode, covering >= 1):")
    print(f"  raw LP  = {ours['lp']:9.2f}   raw MIP = {ours['mip']:9.2f}")
    print(f"  base-load constant (c_g * sum max(Delta,0)) = {ours['baseline']:.2f}")
    print(f"  ADJUSTED (comparable to the original's objective):")
    print(f"  LP  = {ours['lp_adj']:9.2f}    MIP = {ours['mip_adj']:9.2f}    "
          f"trucks = {ours['trucks']}  batteries = {ours['batteries']}")
    if ORIG_LP is None:
        print("\nNext: on the Gurobi machine, in the OLD repo (ndandnd/evspv2g):")
        print("    python src/run_experiments.py")
        print('  (its saved defaults are exactly this cell: mode 3, eps=2.5, 2 locations,')
        print('   solar_mult=7). Note the line "Final LP, MIP obj: <LP> <MIP>",')
        print("  fill ORIG_LP / ORIG_MIP at the top of this file, and rerun it.")
    else:
        dlp = 100 * (ours["lp_adj"] - ORIG_LP) / abs(ORIG_LP)
        print(f"\noriginal code:  LP = {ORIG_LP:9.2f}"
              + (f"    MIP = {ORIG_MIP:9.2f}" if ORIG_MIP is not None else ""))
        print(f"LP difference: {ours['lp_adj'] - ORIG_LP:+9.2f}  ({dlp:+.2f}%)")
        if ORIG_MIP is not None:
            dmp = 100 * (ours["mip_adj"] - ORIG_MIP) / abs(ORIG_MIP)
            print(f"MIP difference: {ours['mip_adj'] - ORIG_MIP:+9.2f}  ({dmp:+.2f}%)")
        print("\nexpected band: |LP diff| <~ 1% (their +premium ~<=0.5%, our finer")
        print("half-hour charge grid slightly negative, their colgen tail). Within")
        print("that band, the DP pricing is doing the same job as the pricing MILP.")
