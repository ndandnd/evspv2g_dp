"""
Planning grid: WHEN does electrification pay, and WHEN does V2G add value on top?

A base case with every knob at a defensible mid value, plus named one/two-knob
slices around it (not a full hypercube). Every cell runs VSP / EVSP-Solar /
EVSP-V2G and reports the total-cost decomposition AND the planning ratio

    R  =  daily solar surplus energy  /  fleet traction energy,

which is the physical gate for storage value: the knob_grid results show V2G
coincides with charge-only whenever the midday surplus is fully absorbed by
traction (R small), at ANY fuel price -- price only scales the value that
surplus slack creates. Expanding the trip set (more tasks, higher intensity)
raises the denominator; more PV raises the numerator.

Base point (each defensible, none tuned):
    c_g = $0.40/kWh (island diesel), c_b = $36/day per 700 kWh ($300/kWh LFP, 15y),
    rho = 350 kW (modern DC charging), pv = 2 (29.4 MWh/day), 3 locations = 60
    trips (breaks schedule), eps = 2.0 (200 kWh/task).

Slices (edit SLICES below):
    solar_x_demand    : pv x locations   (trip set 20 / 60 / 120 -- the user's knob)
    solar_x_intensity : pv x eps         (150 / 200 / 250 kWh per task)
    prices            : c_g x c_b
    charge_rate       : rho

Run:  python3 planning_grid.py       (Gurobi MILP if available, else CBC)
Outputs: results/arxiv/planning_grid.{json,csv} + printed cells and a
"beneficial when" summary sorted by the ratio R.
"""
from __future__ import annotations
import os, sys, csv, json, time, itertools

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI, UNIT_KWH
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
BASE = dict(cg=40.0, cb=36.0, rho=1.75, pv=2.0, points=3, eps=2.0)

SLICES = {
    "solar_x_demand":    {"pv": [1.0, 2.0, 3.0], "points": [2, 3, 4]},   # 20/60/120 trips
    "solar_x_intensity": {"pv": [1.0, 2.0, 3.0], "eps": [0.5, 1.0, 1.5, 2.0, 2.5]},  # full duty-cycle range: light shuttle .. heavy off-road/patrol
    "prices":            {"cg": [20.0, 40.0, 100.0], "cb": [26.0, 36.0, 51.0]},
    "charge_rate":       {"rho": [0.5, 1.75]},                            # 100 / 350 kW
}

SCEN_LIST = ["vsp", "solar", "v2g"]
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def make_cells():
    """Cartesian product within each slice, overriding BASE; dedup shared cells."""
    seen, cells = {}, []
    for name, axes in SLICES.items():
        keys = list(axes)
        for combo in itertools.product(*[axes[k] for k in keys]):
            p = dict(BASE); p.update(dict(zip(keys, combo)))
            key = tuple(sorted(p.items()))
            if key in seen:
                seen[key]["slices"].append(name)
            else:
                c = {"params": p, "slices": [name]}
                seen[key] = c; cells.append(c)
    return cells


def run_scenario(p: dict, scen: str) -> dict:
    inst = build_instance(p["points"], p["eps"], BREAKS, pv_scale=p["pv"])
    inst.c_g, inst.c_b, inst.rho = p["cg"], p["cb"], p["rho"]
    batt = SCENARIOS[scen]["battery"]
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    out = {"scenario": scen, "trips": inst.n_trips, "lp_obj": round(res["lp_obj"], 2)}
    if res["lp_obj"] == float("inf"):
        out["feasible"] = False
        return out
    out["feasible"] = True
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=batt, solver=MILP_SOLVER)
    trucks = int(sum(round(x) for x in mip.x)); nb = int(round(mip.nb))
    gen = inst.c_g * float(mip.g.sum())
    if scen == "vsp":
        gen += inst.c_g * sum(tr.energy for tr in inst.trips)      # ICE traction is fuel
    fuel_units = float(mip.g.sum()) + (sum(tr.energy for tr in inst.trips) if scen == "vsp" else 0.0)
    out.update({"mip_obj": round(mip.obj, 1),
                "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                "trucks": trucks, "batteries": nb,
                "fuel_kwh": round(fuel_units * UNIT_KWH, 1),
                "gen_cost": round(gen, 1), "truck_cost": round(inst.c_v * trucks, 1),
                "batt_cost": round(inst.c_b * nb, 1),
                "total_cost": round(gen + inst.c_v * trucks + inst.c_b * nb
                                    + (mip.obj - inst.c_g * float(mip.g.sum())
                                       - inst.c_v * trucks - inst.c_b * nb), 1)})
    return out


def planning_ratio(p: dict) -> tuple[float, float, float]:
    """R = daily surplus energy / fleet traction energy (both MWh)."""
    inst = build_instance(p["points"], p["eps"], BREAKS, pv_scale=p["pv"])
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())            # units/day
    traction = float(sum(tr.energy for tr in inst.trips))          # units/day (tasks only)
    return surplus / max(traction, 1e-9), surplus / 10.0, traction / 10.0   # ratio, MWh, MWh


def main():
    os.makedirs(OUT, exist_ok=True)
    cells = make_cells()
    print(f"planning grid: {len(cells)} unique cells x {len(SCEN_LIST)} scenarios = "
          f"{len(cells) * len(SCEN_LIST)} runs   (MILP: {MILP_SOLVER})")
    print(f"base: cg=${BASE['cg']/100:.2f}/kWh cb=${BASE['cb']:.0f} rho={int(BASE['rho']*200)}kW "
          f"pv={BASE['pv']:.0f} points={BASE['points']} eps={BASE['eps']}\n")
    rows, t0 = [], time.time()
    for cell in cells:
        p = cell["params"]
        R, sur_mwh, trac_mwh = planning_ratio(p)
        res = {s: run_scenario(p, s) for s in SCEN_LIST}
        rec = {"slices": "+".join(cell["slices"]), **{k: p[k] for k in ("cg", "cb", "rho", "pv", "points", "eps")},
               "ratio": round(R, 3), "surplus_mwh": round(sur_mwh, 1), "traction_mwh": round(trac_mwh, 1)}
        for s in SCEN_LIST:
            for k, v in res[s].items():
                rec[f"{s}_{k}"] = v
        v, s_, b = res.get("v2g", {}), res.get("solar", {}), res.get("vsp", {})
        if all(r.get("feasible") for r in (v, s_, b)):
            rec["v2g_vs_solar_pct"] = round(100 * (s_["total_cost"] - v["total_cost"]) / s_["total_cost"], 2)
            rec["solar_vs_vsp_pct"] = round(100 * (b["total_cost"] - s_["total_cost"]) / b["total_cost"], 2)
            rec["v2g_vs_vsp_pct"] = round(100 * (b["total_cost"] - v["total_cost"]) / b["total_cost"], 2)
        rows.append(rec)
        json.dump(rows, open(os.path.join(OUT, "planning_grid.json"), "w"), indent=2)
        print(f"[{rec['slices'][:24]:24s}] pv={p['pv']:.0f} pts={p['points']} eps={p['eps']:.1f} "
              f"cg=${p['cg']/100:.2f} cb=${p['cb']:.0f} rho={int(p['rho']*200)}kW | "
              f"R={R:5.2f} ({sur_mwh:4.1f}/{trac_mwh:4.1f} MWh) | "
              f"vsp ${b.get('total_cost', 0):7.0f} | solar ${s_.get('total_cost', 0):7.0f} | "
              f"v2g ${v.get('total_cost', 0):7.0f} b={v.get('batteries', 0):2d} | "
              f"V2G/Solar -{rec.get('v2g_vs_solar_pct', float('nan')):5.1f}%  "
              f"V2G/VSP -{rec.get('v2g_vs_vsp_pct', float('nan')):5.1f}%", flush=True)

    keys = list(rows[0].keys()) if rows else []
    with open(os.path.join(OUT, "planning_grid.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted(set().union(*[set(r) for r in rows]), key=str))
        w.writeheader(); w.writerows(rows)

    # ---- "beneficial when" summary: sort by the physical ratio R ----
    ok = [r for r in rows if "v2g_vs_solar_pct" in r]
    ok.sort(key=lambda r: r["ratio"])
    print("\n=== sorted by R = surplus / traction (the physical gate) ===")
    print(f"{'R':>6} {'surplus':>8} {'traction':>9} {'trips':>6} {'V2G/Solar%':>11} {'V2G/VSP%':>9} {'batt':>5}")
    for r in ok:
        print(f"{r['ratio']:6.2f} {r['surplus_mwh']:8.1f} {r['traction_mwh']:9.1f} "
              f"{r['v2g_trips']:6d} {r['v2g_vs_solar_pct']:11.1f} {r['v2g_vs_vsp_pct']:9.1f} "
              f"{r['v2g_batteries']:5d}")
    gain = [r for r in ok if r["v2g_vs_solar_pct"] >= 5.0]
    flat = [r for r in ok if r["v2g_vs_solar_pct"] < 1.0]
    if gain and flat:
        print(f"\nV2G adds <1% below R = {max(r['ratio'] for r in flat):.2f} "
              f"and >=5% above R = {min(r['ratio'] for r in gain):.2f} "
              f"(boundary bracket for the 'beneficial when' statement).")
    elec = [r for r in ok if r.get("solar_vs_vsp_pct", -1) > 0]
    if elec:
        print(f"Electrification (Solar) beats ICE in {len(elec)}/{len(ok)} cells; "
              f"smallest R where it wins: {min(r['ratio'] for r in elec):.2f}.")
    print(f"\ntotal {time.time() - t0:.1f}s; outputs: results/arxiv/planning_grid.json / .csv")


if __name__ == "__main__":
    main()
