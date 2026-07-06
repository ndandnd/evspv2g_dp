"""
Infrastructure caps in action: the revised model's Section-8 'Setup' claim,
shown rather than asserted.

Solves the realistic capped instance (make_instance defaults: gen cap
1500 kWh/block, charging cap 1800 kWh/block ENFORCED) under EVSP-V2G and
records the hourly profiles: no-fleet baseline generation, dispatched
generation with the V2G fleet, and total charging draw -- feeding the
peak-shaving / cap-respecting figure in the gallery.

Run: python3 caps_profile.py   (seconds; CBC suffices, Gurobi if present)
Output: results/arxiv/caps_profile.json
"""
from __future__ import annotations
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from instance import make_instance
from colgen import column_generation, SCENARIOS
from master import solve_milp

HAVE_GUROBI = True
try:
    import gurobipy  # noqa: F401
except Exception:
    HAVE_GUROBI = False
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")


def main():
    os.makedirs(OUT, exist_ok=True)
    inst = make_instance(n_trips=20, n_locations=3, eps=2.0, seed=7)   # caps ON by default
    res = column_generation(inst, scenario="v2g", start="warm", do_milp=False,
                            enrich=100, max_iter=2000)
    mip = solve_milp(inst, res["cols"], time_limit=300,
                     battery_allowed=True, solver="gurobi" if HAVE_GUROBI else "cbc",
                     mip_gap=1e-4)
    fleet_charge = np.zeros(inst.T)
    fleet_discharge = np.zeros(inst.T)
    for c, x in zip(res["cols"], mip.x):
        if x > 0.5:
            e = np.array(c.e) * round(x)
            fleet_charge += np.maximum(e, 0.0)
            fleet_discharge += np.maximum(-e, 0.0)
    total_charge = fleet_charge + np.array(mip.charge)
    out = {"T": inst.T,
           "baseline_gen": [round(float(x), 1) for x in np.maximum(inst.Delta, 0.0)],
           "delta": [round(float(x), 1) for x in inst.Delta],
           "gen": [round(float(x), 1) for x in mip.g],
           "total_charge": [round(float(x), 1) for x in total_charge],
           "fleet_discharge": [round(float(x), 1) for x in fleet_discharge + np.array(mip.discharge)],
           "gen_cap": inst.gen_cap, "charge_cap": inst.charge_cap,
           "peak_gen": round(float(mip.g.max()), 1),
           "peak_charge": round(float(total_charge.max()), 1),
           "trucks": int(sum(round(x) for x in mip.x)), "batteries": int(round(mip.nb)),
           "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)}
    json.dump(out, open(os.path.join(OUT, "caps_profile.json"), "w"), indent=1)
    print(f"peak generation {out['peak_gen']} / cap {out['gen_cap']}   "
          f"peak charging {out['peak_charge']} / cap {out['charge_cap']}   "
          f"trucks {out['trucks']}  batteries {out['batteries']}  gap {out['gap_pct']}%")
    print("output: results/arxiv/caps_profile.json")


if __name__ == "__main__":
    main()
