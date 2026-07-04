"""
Reversibility check: run the DP code IN THE ORIGINAL ARXIV SETTINGS and show it
reproduces the original results -- so every difference in the revised paper is
attributable to the DELIBERATE model change (cyclic SoC), not the reimplementation.

The equivalence chain this completes (the coauthor story):
  1. Implementation equivalence: three independent codebases (this repo, the
     from-scratch v2g_dp, and a third implementation) match LP optima exactly on
     matched-granularity instances -- including fractional optima.
  2. Solver independence: HiGHS and Gurobi agree on every LP (solver_compare.py).
  3. THIS FILE -- setting reversibility: switching soc_mode back to "free" (the
     original's free full initial charge, trucks ending at any SoC, batteries
     starting full for free) reproduces the original paper's phenomena on the
     original instance: NEGATIVE net fuel (energy export), stationary batteries
     deployed, and Table-2-scale fleets.
  4. recreate_arxiv.py: the same experiments under the revised (cyclic) model --
     same trends and ~1% gaps; level differences are exactly the free-energy
     artifact that this file isolates.

Fuel metric (both modes): incremental fossil vs the no-fleet baseline,
    fuel = sum_t g_t - sum_t max(Delta_t, 0),
converted with the original code's 33 kWh/gal equivalence. In free mode the fleet
dumps its free initial charge into deficit hours, so this goes NEGATIVE (the
original's "net export"); in cyclic mode every kWh is paid, so it is positive.
Original Table-2 values are as published (their trucks are averages, e.g. 12.33;
ours are single deterministic integer runs, gap ~1%, like the original's MIPGap).

Run:  python3 arxiv_settings_check.py     (Gurobi MILP if available, else CBC)
Outputs: printed side-by-side + results/arxiv_free/* (full experiment suite in
free mode when RUN_FULL_SUITE = True).
"""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import recreate_arxiv as R

# ============================== CONFIG -- EDIT ME ==============================
RUN_TABLE2     = True    # the side-by-side vs the original's published Table 2
RUN_FULL_SUITE = True    # every recreate_arxiv experiment in FREE mode -> results/arxiv_free/
GAL_PER_UNIT   = 100.0 / 33.0   # the original code's kWh->gallon equivalence
# ==============================================================================

# Original paper, Table 2 (eps=2.5, V2G): (fuel gallons, trucks) as published.
ORIG_TABLE2 = {(20, "breaks"): (-158.59, 12.33), (20, "uniform"): (-128.28, 12.00),
               (60, "breaks"): (-60.61, 30.67),  (60, "uniform"): (-29.29, 25.67),
               (120, "breaks"): (-57.58, 62.00), (120, "uniform"): (-6.06, 55.00)}


def run_cell(points, windows, mode):
    R.SOC_MODE = mode
    inst = R.build_instance(points, 2.5, windows)
    baseline = float(np.maximum(inst.Delta, 0.0).sum())     # no-fleet fossil (units)
    r = R.run_case(inst, "v2g")
    if not r.get("feasible"):
        return {"gal": float("nan"), "trucks": 0, "batt": 0, "gap": float("nan")}
    return {"gal": (r["fuel_units"] - baseline) * GAL_PER_UNIT,
            "trucks": r["trucks"], "batt": r["batteries"], "gap": r["gap_pct"]}


def table2():
    print("=== Table 2 side-by-side (eps=2.5, V2G): original arXiv MILP vs this DP code ===")
    print("(fuel = incremental fossil vs no-fleet baseline, gallons at 33 kWh/gal;")
    print(" negative = net export, only possible with the free initial charge)\n")
    print(f"{'trips':>6} {'sched':>8} | {'arXiv gal':>10} {'trucks':>7} | "
          f"{'DP-free gal':>11} {'trucks':>7} {'batt':>5} | "
          f"{'DP-cyclic gal':>13} {'trucks':>7} {'batt':>5}")
    for pts in (2, 3, 4):
        for sched, windows in (("breaks", R.BREAKS), ("uniform", R.UNIFORM)):
            free = run_cell(pts, windows, "free")
            cyc = run_cell(pts, windows, "cyclic")
            trips = pts * (pts - 1) * 10
            og, ot = ORIG_TABLE2[(trips, sched)]
            print(f"{trips:6d} {sched:>8} | {og:10.2f} {ot:7.2f} | "
                  f"{free['gal']:11.2f} {free['trucks']:7d} {free['batt']:5d} | "
                  f"{cyc['gal']:13.2f} {cyc['trucks']:7d} {cyc['batt']:5d}", flush=True)
    print("\nReading: DP-free reproduces the original's signs and phenomena (negative")
    print("fuel = export, batteries deployed, breaks < uniform fuel); DP-cyclic flips")
    print("fuel positive and removes the batteries -- the free-energy artifact isolated.")


if __name__ == "__main__":
    print(f"MILP solver: {R.MILP_SOLVER} (Gurobi available: {R.HAVE_GUROBI})\n")
    if RUN_TABLE2:
        table2()
    if RUN_FULL_SUITE:
        print("\n=== full experiment suite in FREE (original arXiv) mode -> results/arxiv_free ===")
        R.SOC_MODE = "free"
        R.OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv_free")
        os.makedirs(R.OUT, exist_ok=True)
        R.exp1_regimes()
        R.exp2_scheduling()
        R.exp3_solar()
        R.exp3b_solar_pv()
        R.exp4_timeline()
        R.exp5_scalability()
        R.SOC_MODE = "cyclic"
        print(f"\nfree-mode suite saved to {R.OUT} (compare 1-1 with results/arxiv/)")
