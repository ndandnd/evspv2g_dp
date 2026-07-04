"""
Scale ladder: does the planning rule survive at 500+ trips?

planning_grid found that V2G value switches on at R = (daily solar surplus) /
(fleet traction) ~ 1, regardless of which knob moves R. This ladder tests
whether that boundary -- and the savings level at a given R -- is SCALE-FREE:
trips grow 20 -> 560 (locations 2..8, breaks schedule) while the microgrid is
co-scaled with the fleet (solar_mult grows proportionally, scaling demand and
solar together, exactly the original paper's whole-profile multiplier), so each
pv level holds R roughly constant across the ladder.

If the V2G-vs-Solar savings at fixed R stay flat as trips x10, the 'beneficial
when R >~ 1' statement is a scale-free planning rule, not a small-instance
artifact. The run doubles as the DP-pricing-at-scale demonstration on the
original instance family (CG iterations/time per cell are reported).

Set CO_SCALE = False to keep the microgrid FIXED while the fleet grows: R then
collapses ~1/trips and V2G value should die -- the boundary approached from the
other side.

Base prices: cg=$0.40/kWh, cb=$36/day, rho=350kW, eps=2.0 (all as planning_grid).

Run:  python3 scale_ladder.py     (Gurobi MILP if available, else CBC)
Outputs: results/arxiv/scale_ladder.{json,csv}. Full ladder is ~30-60 min with
Gurobi (the 420/560-trip cells dominate); trim LADDER_POINTS to go faster.
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI, UNIT_KWH
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
LADDER_POINTS = [2, 3, 4, 5, 6, 7, 8]   # -> 20/60/120/200/300/420/560 trips (breaks)
PV_LIST       = [1.0, 2.0, 3.0]         # per-pv R stays ~constant when CO_SCALE=True
CO_SCALE      = True                     # True: microgrid grows with the fleet (solar_mult
                                         # = 7 * trips/60). False: fixed microgrid, R ~ 1/trips.
CG_COST, CB_COST, RHO, EPS = 40.0, 36.0, 1.75, 2.0
# Trip windows: BREAKS = original (4-9 & 18-23, 10 start hours). FULL_DAY gives
# 14 start hours -> points 7 = 588 trips, 8 = 784. Realistic-duty suggestion:
# WINDOWS = FULL_DAY with EPS = 1.0 (100 kWh per 2-h task; heavy duty = 1.5,
# light = 0.5 -- measured EV-truck consumption, multiples of the 0.5 SoC lattice).
FULL_DAY = [(6, 20)]
WINDOWS  = BREAKS
SCEN_LIST = ["vsp", "solar", "v2g"]
MILP_TIME_LIMIT = 300.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def make_inst(points, pv):
    n_starts = sum(b - a for a, b in WINDOWS)
    n_trips = points * (points - 1) * n_starts
    # co-scale reference: 60 trips at eps=2.0 (12 MWh traction) is the base microgrid
    sm = 7.0 * (n_trips * EPS / (60.0 * 2.0)) if CO_SCALE else 7.0
    inst = build_instance(points, EPS, WINDOWS, solar_mult=sm, pv_scale=pv)
    inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
    return inst, sm


def run_cell(points, pv):
    inst, sm = make_inst(points, pv)
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    rec = {"points": points, "trips": inst.n_trips, "pv": pv, "solar_mult": round(sm, 2),
           "ratio": round(surplus / max(traction, 1e-9), 3),
           "surplus_mwh": round(surplus / 10, 1), "traction_mwh": round(traction / 10, 1)}
    for scen in SCEN_LIST:
        batt = SCENARIOS[scen]["battery"]
        t0 = time.time()
        res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                                enrich=25, max_iter=max(2000, 5 * inst.n_trips))
        cg_s = time.time() - t0
        if res["lp_obj"] == float("inf"):
            rec[f"{scen}_feasible"] = False
            continue
        t1 = time.time()
        mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                         battery_allowed=batt, solver=MILP_SOLVER)
        trucks = int(sum(round(x) for x in mip.x)); nb = int(round(mip.nb))
        fuel_units = float(mip.g.sum()) + (traction if scen == "vsp" else 0.0)
        # VSP: ICE traction is fuel too -- add it so totals are cross-scenario comparable
        total = mip.obj + (inst.c_g * traction if scen == "vsp" else 0.0)
        rec.update({f"{scen}_feasible": True,
                    f"{scen}_total_cost": round(total, 1),
                    f"{scen}_fuel_kwh": round(fuel_units * UNIT_KWH, 1),
                    f"{scen}_trucks": trucks, f"{scen}_batteries": nb,
                    f"{scen}_gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                    f"{scen}_cg_iters": res["iters"], f"{scen}_cg_s": round(cg_s, 1),
                    f"{scen}_milp_s": round(time.time() - t1, 1)})
    if rec.get("v2g_feasible") and rec.get("solar_feasible"):
        rec["v2g_vs_solar_pct"] = round(
            100 * (rec["solar_total_cost"] - rec["v2g_total_cost"]) / rec["solar_total_cost"], 2)
    if rec.get("v2g_feasible") and rec.get("vsp_feasible"):
        rec["v2g_vs_vsp_pct"] = round(
            100 * (rec["vsp_total_cost"] - rec["v2g_total_cost"]) / rec["vsp_total_cost"], 2)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True)
    mode = "co-scaled microgrid (R ~ const per pv)" if CO_SCALE else "FIXED microgrid (R ~ 1/trips)"
    print(f"scale ladder: {len(LADDER_POINTS)}x{len(PV_LIST)} cells x {len(SCEN_LIST)} scenarios, "
          f"{mode}\nMILP: {MILP_SOLVER}  base: cg=${CG_COST/100:.2f}/kWh cb=${CB_COST:.0f} "
          f"rho={int(RHO*200)}kW eps={EPS}\n")
    print(f"{'trips':>6} {'pv':>3} {'R':>6} {'V2G/Solar%':>11} {'V2G/VSP%':>9} {'batt':>5} "
          f"{'v2g_gap%':>9} {'v2g_cg_s':>9} {'v2g_iters':>9}")
    rows, t0 = [], time.time()
    for points in LADDER_POINTS:
        for pv in PV_LIST:
            r = run_cell(points, pv)
            rows.append(r)
            json.dump(rows, open(os.path.join(OUT, "scale_ladder.json"), "w"), indent=2)
            print(f"{r['trips']:6d} {r['pv']:3.0f} {r['ratio']:6.2f} "
                  f"{r.get('v2g_vs_solar_pct', float('nan')):11.1f} "
                  f"{r.get('v2g_vs_vsp_pct', float('nan')):9.1f} "
                  f"{r.get('v2g_batteries', 0):5d} {r.get('v2g_gap_pct', float('nan')):9.3f} "
                  f"{r.get('v2g_cg_s', 0):9.1f} {r.get('v2g_cg_iters', 0):9d}", flush=True)
    with open(os.path.join(OUT, "scale_ladder.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted(set().union(*[set(r) for r in rows]), key=str))
        w.writeheader(); w.writerows(rows)
    # scale-invariance check: savings spread per pv level across the ladder
    print("\n=== scale-invariance check (V2G/Solar% across trips at fixed pv) ===")
    for pv in PV_LIST:
        vals = [r["v2g_vs_solar_pct"] for r in rows if r["pv"] == pv and "v2g_vs_solar_pct" in r]
        if vals:
            print(f"  pv={pv:.0f} (R~{np.mean([r['ratio'] for r in rows if r['pv'] == pv]):.2f}): "
                  f"savings {min(vals):.1f}% .. {max(vals):.1f}%  (spread {max(vals)-min(vals):.1f} pts)")
    print(f"\ntotal {time.time() - t0:.1f}s; outputs: results/arxiv/scale_ladder.json / .csv")


if __name__ == "__main__":
    main()
