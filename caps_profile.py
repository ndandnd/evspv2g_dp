"""
Infrastructure caps in action + the value of V2G tech on one dispatch plot.

Same realistic capped instance (gen cap 1500, charging cap 1800 kWh/block,
ENFORCED), same fleet and tasks, solved twice:
    'solar' : conventional charging -- no stationary storage, no V2G
    'v2g'   : full V2G technology (bidirectional fleet + stationary batteries)
Records both hourly dispatch profiles so the gallery can show the fossil
integral shrinking and the caps being respected. Solar is raised to 24 MWh/day
(a 1.7x build-out) so the technologies separate visibly while the evening
generation peak still presses the cap.

Run: python3 caps_profile.py    (seconds)
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
SOLAR_KWH = 24000.0
N_TASKS = 20


def run(scen):
    inst = make_instance(n_trips=N_TASKS, n_locations=3, eps=2.0, seed=7,
                         daily_solar_kwh=SOLAR_KWH)          # caps ON by default
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=100, max_iter=2000)
    mip = solve_milp(inst, res["cols"], time_limit=300,
                     battery_allowed=SCENARIOS[scen]["battery"],
                     solver="gurobi" if HAVE_GUROBI else "cbc", mip_gap=1e-4)
    charge = np.array(mip.charge)
    for c, x in zip(res["cols"], mip.x):
        if x > 0.5:
            charge += np.maximum(np.array(c.e) * round(x), 0.0)
    return inst, {"gen": [round(float(x), 1) for x in mip.g],
                  "charge": [round(float(x), 1) for x in charge],
                  "fossil_mwh": round(float(mip.g.sum()) / 1000, 2),
                  "peak_gen": round(float(mip.g.max()), 1),
                  "trucks": int(sum(round(x) for x in mip.x)),
                  "batteries": int(round(mip.nb)),
                  "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)}


def main():
    os.makedirs(OUT, exist_ok=True)
    out = {"solar_kwh": SOLAR_KWH, "n_tasks": N_TASKS}
    for scen in ("solar", "v2g"):
        inst, r = run(scen)
        out[scen] = r
        print(f"{scen:6s}: fossil {r['fossil_mwh']} MWh  peak {r['peak_gen']}  "
              f"trucks {r['trucks']}  batteries {r['batteries']}  gap {r['gap_pct']}%")
    out["baseline_gen"] = [round(float(x), 1) for x in np.maximum(inst.Delta, 0.0)]
    out["baseline_mwh"] = round(float(np.maximum(inst.Delta, 0.0).sum()) / 1000, 2)
    out["gen_cap"] = inst.gen_cap
    out["charge_cap"] = inst.charge_cap
    json.dump(out, open(os.path.join(OUT, "caps_profile.json"), "w"), indent=1)
    print(f"baseline (no fleet) {out['baseline_mwh']} MWh; caps {out['gen_cap']}/{out['charge_cap']}")
    print("output: results/arxiv/caps_profile.json")


if __name__ == "__main__":
    main()
