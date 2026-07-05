"""
Regime fuel study: fossil energy by regime (VSP / plain EVSP / EVSP-Solar /
EVSP-V2G) as available solar grows -- cyclic model, honest energy accounting.

Feeds the redesigned Figure 8.2 and the negative-incremental Table in the
Section-8 gallery. For each pv level and regime it records the COMPONENTS of
fossil use so the gallery can display any accounting convention:

    baseline_units    fossil the microgrid burns with NO fleet (base load only)
    g_units           fossil actually generated with the fleet operating
    traction_units    fleet traction energy (electric-equivalent)
    fleet_paid_units  plain-EV energy bought at flat price (folded into routes)

Incremental fossil (the figure's y-axis) by regime:
    vsp   : ICE_EFF x traction          (trucks burn thermal fuel; base untouched)
    ev    : fleet_paid_units            (solar-blind charging, all bought)
    solar : g_units - baseline_units    (>= 0: charging beyond free surplus)
    v2g   : g_units - baseline_units    (can be NEGATIVE: the fleet displaces
                                         base fossil by shifting surplus)

Breaks schedule already leaves the midday free (trips at 4-9h and 18-23h), so
vehicles are at the depot exactly when the surplus occurs.

Run: python3 regime_fuel.py    (Gurobi if available, else CBC; ~2-5 min)
Output: results/arxiv/regime_fuel.json / .csv
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
PV_LIST  = [1.0, 2.0, 3.0]      # 14.7 / 29.4 / 44.1 MWh of solar per day
POINTS, EPS = 3, 2.0            # 60 trips, 200 kWh per task
REGIMES  = ["vsp", "ev", "solar", "v2g"]
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    print(f"regime fuel: {len(PV_LIST)} solar levels x {len(REGIMES)} regimes "
          f"(cyclic, 60 trips; MILP: {MILP_SOLVER})\n")
    print(f"{'pv':>4} {'solarMWh':>9} {'regime':>7} {'g_units':>8} {'baseline':>9} "
          f"{'incr_fossil_MWh':>16} {'trucks':>7} {'batt':>5} {'gap%':>7}")
    for pv in PV_LIST:
        for reg in REGIMES:
            inst = build_instance(POINTS, EPS, BREAKS, pv_scale=pv)
            inst.c_g, inst.c_b, inst.rho, inst.c_v = CG_COST, CB_COST, RHO, CV
            baseline = float(np.maximum(inst.Delta, 0.0).sum())
            solar_mwh = float(np.maximum(-inst.Delta, 0.0).sum() + 0) / 10.0  # surplus MWh
            traction = float(sum(tr.energy for tr in inst.trips))
            res = column_generation(inst, scenario=reg, start="warm", do_milp=False,
                                    enrich=25, max_iter=max(2000, 5 * inst.n_trips))
            if res["lp_obj"] == float("inf"):
                continue
            mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                             battery_allowed=SCENARIOS[reg]["battery"], solver=MILP_SOLVER)
            g_units = float(mip.g.sum())
            fleet_paid = 0.0
            if reg == "ev":                        # energy folded into route fixed costs
                fleet_paid = sum((c.fixed_cost - inst.c_v) / inst.c_g * round(x)
                                 for c, x in zip(res["cols"], mip.x) if x > 0.5)
            row = {"pv": pv, "regime": reg, "trips": inst.n_trips,
                   "surplus_mwh": round(solar_mwh, 1),
                   "baseline_units": round(baseline, 2), "g_units": round(g_units, 2),
                   "traction_units": round(traction, 2),
                   "fleet_paid_units": round(fleet_paid, 2),
                   "trucks": int(sum(round(x) for x in mip.x)),
                   "batteries": int(round(mip.nb)),
                   "total_cost": round(mip.obj, 1),
                   "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)}
            rows.append(row)
            json.dump(rows, open(os.path.join(OUT, "regime_fuel.json"), "w"), indent=2)
            incr = {"vsp": traction, "ev": fleet_paid,
                    "solar": g_units - baseline, "v2g": g_units - baseline}[reg]
            print(f"{pv:4.1f} {solar_mwh:9.1f} {reg:>7} {g_units:8.1f} {baseline:9.1f} "
                  f"{incr / 10:16.2f} {row['trucks']:7d} {row['batteries']:5d} "
                  f"{row['gap_pct']:7.3f}", flush=True)
    keys = list(rows[0].keys()) if rows else []
    with open(os.path.join(OUT, "regime_fuel.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)
    print("\n(NOTE: printed vsp incremental is electric-equivalent traction; the gallery"
          "\n multiplies by the drivetrain-efficiency convention it displays.)")
    print("output: results/arxiv/regime_fuel.json / .csv")


if __name__ == "__main__":
    main()
