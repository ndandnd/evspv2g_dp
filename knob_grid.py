"""
Knob grid: VSP vs EVSP-Solar vs EVSP-V2G across a small factorial of REALISTIC
parameter choices, with the total-cost decomposition (generation $ + truck fixed $
+ battery fixed $) for every cell.

Purpose: the original toy priced fuel at $0.05/kWh -- roughly 10x too cheap
relative to a correctly-priced battery -- which zeroes the value of storage and
makes V2G coincide with charge-only Solar. This grid sweeps each knob over a few
citable values and shows WHERE the V2G-vs-Solar gap opens (it needs BOTH leftover
solar surplus beyond fleet traction AND a fuel price above the storage cycle cost).

Knob anchors (each value is defensible, not tuned):
  c_g   $/kWh of fossil generation. Remote-island / military-base diesel is
        commonly $0.30-1.00+/kWh (DoD "fully burdened" costs run higher).
        Grid: 0.20 (low), 0.40 (typical island), 1.00 (= the Section-8 instance).
        The original toy's 0.05 is included only as the artifact anchor if you
        add 5.0 to CG_LIST.
  pv    solar scale. 1.0 = the original profile (14.7 MWh/day vs ~31 MWh demand);
        2.0 / 3.0 = 29.4 / 44.1 MWh -- islands are actively over-building PV.
  rho   charge/discharge rate. 0.5 units/half-block = 100 kW (the original);
        1.75 = 350 kW (modern DC fast charging, = the Section-8 instance).
  c_b   $/day per 700-kWh stationary battery, amortized: LFP installed capex
        $200 / $300 / $400 per kWh over 15 years -> ~26 / 36 / 51 $/day.
        (36 is the original toy value -- it was about right; the fuel price wasn't.)

Instance: the exact original-paper toy (recreate_arxiv.build_instance) -- breaks
schedule, 3 locations = 60 trips, eps=2.0 (200 kWh/task), G=700 kWh, c_v=$45/day.

Run:  python3 knob_grid.py     (Gurobi for the MILP if available, else CBC)
Outputs: results/arxiv/knob_grid.{json,csv} + printed per-combo lines and summary.
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI, UNIT_KWH
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
CG_LIST  = [20.0, 40.0, 100.0]  # $/kWh x100: 0.20 / 0.40 / 1.00 (add 5.0 = the original toy artifact)
PV_LIST  = [1.0, 2.0, 3.0]      # solar scale: 14.7 / 29.4 / 44.1 MWh per day
RHO_LIST = [0.5, 1.75]          # units per half-block: 100 kW (original) / 350 kW (modern)
CB_LIST  = [26.0, 36.0, 51.0]   # $/day per 700-kWh battery ($200/$300/$400 per kWh capex, 15y)
POINTS   = 3                    # 3 locations -> 60 trips (breaks schedule)
EPS      = 2.0                  # 200 kWh per task (medium)
SCEN_LIST = ["vsp", "solar", "v2g"]
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def run_cell(cg, pv, rho, cb, scen) -> dict:
    inst = build_instance(POINTS, EPS, BREAKS, pv_scale=pv)
    inst.c_g, inst.c_b, inst.rho = cg, cb, rho
    batt = SCENARIOS[scen]["battery"]
    t0 = time.time()
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    cg_s = time.time() - t0
    row = {"c_g": cg, "pv": pv, "rho": rho, "c_b": cb, "scenario": scen,
           "trips": inst.n_trips, "lp_obj": round(res["lp_obj"], 2), "cg_s": round(cg_s, 2)}
    if res["lp_obj"] == float("inf"):
        row["feasible"] = False
        return row
    row["feasible"] = True
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=batt, solver=MILP_SOLVER)
    trucks = int(sum(round(x) for x in mip.x))
    nb = int(round(mip.nb))
    gen_cost = inst.c_g * float(mip.g.sum())               # fossil generation $
    if scen == "vsp":                                      # ICE traction is fuel too
        gen_cost += inst.c_g * sum(tr.energy for tr in inst.trips)
    truck_cost = inst.c_v * trucks                         # fixed deployment $
    batt_cost = inst.c_b * nb
    other = mip.obj - (inst.c_g * float(mip.g.sum())) - truck_cost - batt_cost  # eps_pen etc.
    fuel_units = float(mip.g.sum()) + (sum(tr.energy for tr in inst.trips) if scen == "vsp" else 0.0)
    row.update({"mip_obj": round(mip.obj, 1),
                "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                "trucks": trucks, "batteries": nb,
                "fuel_kwh": round(fuel_units * UNIT_KWH, 1),
                "gen_cost": round(gen_cost, 1),
                "truck_cost": round(truck_cost, 1),
                "batt_cost": round(batt_cost, 1),
                "other_cost": round(other, 1),
                "total_cost": round(gen_cost + truck_cost + batt_cost + other, 1)})
    return row


def main():
    os.makedirs(OUT, exist_ok=True)
    n_combo = len(CG_LIST) * len(PV_LIST) * len(RHO_LIST) * len(CB_LIST)
    print(f"knob grid: {n_combo} combos x {len(SCEN_LIST)} scenarios = "
          f"{n_combo * len(SCEN_LIST)} runs  ({POINTS} locations = 60 trips, eps={EPS})\n"
          f"MILP solver: {MILP_SOLVER} (Gurobi available: {HAVE_GUROBI})\n")
    rows, t0 = [], time.time()
    for cg in CG_LIST:
        for pv in PV_LIST:
            for rho in RHO_LIST:
                for cb in CB_LIST:
                    cell = {}
                    for scen in SCEN_LIST:
                        r = run_cell(cg, pv, rho, cb, scen)
                        rows.append(r); cell[scen] = r
                    # incremental save
                    json.dump(rows, open(os.path.join(OUT, "knob_grid.json"), "w"), indent=2)
                    v, s = cell.get("v2g", {}), cell.get("solar", {})
                    line = (f"cg=${cg/100:4.2f}/kWh pv={pv:.0f} rho={int(rho*200)}kW cb=${cb:2.0f} | ")
                    for scen in SCEN_LIST:
                        r = cell[scen]
                        if not r.get("feasible"):
                            line += f"{scen}: INFEAS | "
                            continue
                        line += (f"{scen}: ${r['total_cost']:8.0f} (gen {r['gen_cost']:7.0f} "
                                 f"+ trk {r['truck_cost']:5.0f} + bat {r['batt_cost']:5.0f}) "
                                 f"t={r['trucks']:2d} b={r['batteries']:2d} | ")
                    if v.get("feasible") and s.get("feasible"):
                        dfuel = 100 * (s["fuel_kwh"] - v["fuel_kwh"]) / max(s["fuel_kwh"], 1e-9)
                        dcost = s["total_cost"] - v["total_cost"]
                        line += f"V2G-vs-Solar: fuel -{dfuel:4.1f}%  cost -${dcost:7.0f}"
                    print(line, flush=True)
    # CSV
    keys = ["c_g", "pv", "rho", "c_b", "scenario", "trips", "feasible", "trucks", "batteries",
            "fuel_kwh", "gen_cost", "truck_cost", "batt_cost", "other_cost", "total_cost",
            "lp_obj", "mip_obj", "gap_pct", "cg_s"]
    with open(os.path.join(OUT, "knob_grid.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    # summary: where does V2G strictly beat Solar?
    by_combo = {}
    for r in rows:
        by_combo.setdefault((r["c_g"], r["pv"], r["rho"], r["c_b"]), {})[r["scenario"]] = r
    wins, total = [], 0
    for key, cell in by_combo.items():
        v, s = cell.get("v2g"), cell.get("solar")
        if v and s and v.get("feasible") and s.get("feasible"):
            total += 1
            save = s["total_cost"] - v["total_cost"]
            if save > 0.01 * s["total_cost"]:
                wins.append((save / s["total_cost"] * 100, key, save))
    wins.sort(reverse=True)
    print(f"\nV2G beats Solar by >1% total cost in {len(wins)}/{total} combos.")
    for pct, (cg, pv, rho, cb), save in wins[:8]:
        print(f"  cg=${cg/100:.2f} pv={pv:.0f} rho={int(rho*200)}kW cb=${cb:.0f}: "
              f"V2G saves ${save:.0f}/day ({pct:.1f}%)")
    print(f"\ntotal {time.time() - t0:.1f}s; outputs: results/arxiv/knob_grid.json / .csv")


if __name__ == "__main__":
    main()
