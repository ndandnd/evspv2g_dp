"""
Technology-tier decomposition: WHEN is each step worth it?

    VSP (ICE)  ->  EVSP (plain EV)  ->  EVSP-Solar  ->  EVSP-V2G

Each cell runs all four regimes and reports the three MARGINAL values:
    electrify   = cost(VSP)   - cost(EV)      (drivetrain efficiency vs EV premium
                                                and fleet inflation)
    solar-aware = cost(EV)    - cost(Solar)   (value of coupling charging to the
                                                microgrid: Prop 1's free/paid split)
    V2G         = cost(Solar) - cost(V2G)     (value of bidirectionality + storage)

as a function of the planning ratio R = daily solar surplus / fleet traction.
The three thresholds where these cross zero are the deployment conditions.

Three honesty knobs the earlier experiments lacked (each anchored):
  * EV_PREMIUM : EV truck daily cost / ICE truck daily cost. Class-8 electric
    tractors carry ~1.5-2x capex today (falling). Base 1.5.
  * ICE_EFF    : thermal energy an ICE burns per unit of EV traction energy.
    The ORIGINAL paper is internally inconsistent here -- Table 1 equates at
    10 kWh/gal while its code converts at 33 kWh/gal; the 3.3x ratio between
    them IS the EV drivetrain-efficiency advantage. Base 3.3 (diesel ~ 13 kWh
    useful-equivalent per mile vs EV ~ 2). Set 1.0 to reproduce the old
    equal-energy assumption.
  * plain-EVSP tier ("ev" scenario in colgen): solar-blind charging at flat
    c_g -- the original's mode 1, previously missing from this repo.

Base prices as planning_grid: c_g=$0.40/kWh, c_b=$36/day, rho=350 kW, eps=2.0,
ICE truck $45/day. Run: python3 tech_tiers.py  (Gurobi if available, else CBC).
Outputs: results/arxiv/tech_tiers.{json,csv,png} + printed tables.
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI, UNIT_KWH
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
R_SWEEP     = [(1.0, 3), (1.5, 3), (2.0, 3), (2.5, 3), (3.0, 3),   # (pv_scale, points)
               (2.0, 2), (2.0, 4)]                                  # R ~ 4.2 and ~ 0.7
EV_PREMIUM  = 1.5      # EV truck daily cost multiple of ICE (sensitivity below)
ICE_EFF     = 3.3      # thermal units an ICE burns per EV traction unit (1.0 = old assumption)
SENS_PREMIUM = [1.0, 1.5, 2.0]      # sensitivity block at the base cell (pv=2, points=3)
SENS_EFF     = [1.0, 2.0, 3.3]
CV_ICE      = 45.0
CG_COST, CB_COST, RHO, EPS = 40.0, 36.0, 1.75, 2.0
TIERS       = ["vsp", "ev", "solar", "v2g"]
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def run_tier(pv, points, tier, ev_premium, ice_eff):
    inst = build_instance(points, EPS, BREAKS, pv_scale=pv)
    inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
    inst.c_v = CV_ICE if tier == "vsp" else CV_ICE * ev_premium
    traction = float(sum(tr.energy for tr in inst.trips))
    res = column_generation(inst, scenario=tier, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[tier]["battery"], solver=MILP_SOLVER)
    trucks = int(sum(round(x) for x in mip.x))
    total = mip.obj
    if tier == "vsp":                              # ICE traction is thermal fuel, burned
        total += inst.c_g * ice_eff * traction     # at ICE_EFF x the EV traction energy
    # fuel (kWh-equivalent of fossil burned): base fossil + tier-specific fleet part
    fossil = float(mip.g.sum())
    if tier == "vsp":
        fossil += ice_eff * traction
    elif tier == "ev":                             # flat-price energy folded into route
        fossil += sum((cols.fixed_cost - inst.c_v) / inst.c_g * round(x)
                      for cols, x in zip(res["cols"], mip.x) if x > 0.5)
    return {"tier": tier, "total_cost": round(total, 1), "trucks": trucks,
            "batteries": int(round(mip.nb)), "fuel_kwh": round(fossil * UNIT_KWH, 1),
            "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)}


def run_cell(pv, points, ev_premium=EV_PREMIUM, ice_eff=ICE_EFF):
    inst = build_instance(points, EPS, BREAKS, pv_scale=pv)
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    rec = {"pv": pv, "points": points, "trips": inst.n_trips,
           "ev_premium": ev_premium, "ice_eff": ice_eff,
           "ratio": round(surplus / max(traction, 1e-9), 3)}
    for tier in TIERS:
        r = run_tier(pv, points, tier, ev_premium, ice_eff)
        if r is None:
            rec[f"{tier}_total"] = None
            continue
        for k, v in r.items():
            if k != "tier":
                rec[f"{tier}_{k.replace('total_cost', 'total')}"] = v
    if all(rec.get(f"{t}_total") is not None for t in TIERS):
        rec["electrify_value"] = round(rec["vsp_total"] - rec["ev_total"], 1)
        rec["solar_value"] = round(rec["ev_total"] - rec["solar_total"], 1)
        rec["v2g_value"] = round(rec["solar_total"] - rec["v2g_total"], 1)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"tech tiers: base EV_PREMIUM={EV_PREMIUM} ICE_EFF={ICE_EFF}  MILP={MILP_SOLVER}\n")
    hdr = (f"{'R':>6} {'trips':>6} | {'VSP':>8} {'EV':>8} {'Solar':>8} {'V2G':>8} | "
           f"{'electrify':>9} {'+solar':>8} {'+V2G':>8}")
    rows = []

    print("=== (A) tier costs and marginal values vs R ===")
    print(hdr)
    for pv, pts in R_SWEEP:
        rec = run_cell(pv, pts)
        rows.append(rec)
        json.dump(rows, open(os.path.join(OUT, "tech_tiers.json"), "w"), indent=2)
        print(f"{rec['ratio']:6.2f} {rec['trips']:6d} | "
              f"{rec.get('vsp_total', float('nan')):8.0f} {rec.get('ev_total', float('nan')):8.0f} "
              f"{rec.get('solar_total', float('nan')):8.0f} {rec.get('v2g_total', float('nan')):8.0f} | "
              f"{rec.get('electrify_value', float('nan')):9.0f} {rec.get('solar_value', float('nan')):8.0f} "
              f"{rec.get('v2g_value', float('nan')):8.0f}", flush=True)

    print("\n=== (B) sensitivity at the base cell (pv=2, points=3, R~1.4) ===")
    print(f"{'premium':>8} {'ice_eff':>8} | {'VSP':>8} {'EV':>8} {'Solar':>8} {'V2G':>8} | "
          f"{'electrify':>9} {'+solar':>8} {'+V2G':>8}")
    for prem in SENS_PREMIUM:
        for eff in SENS_EFF:
            rec = run_cell(2.0, 3, ev_premium=prem, ice_eff=eff)
            rows.append(rec)
            json.dump(rows, open(os.path.join(OUT, "tech_tiers.json"), "w"), indent=2)
            print(f"{prem:8.1f} {eff:8.1f} | "
                  f"{rec.get('vsp_total', float('nan')):8.0f} {rec.get('ev_total', float('nan')):8.0f} "
                  f"{rec.get('solar_total', float('nan')):8.0f} {rec.get('v2g_total', float('nan')):8.0f} | "
                  f"{rec.get('electrify_value', float('nan')):9.0f} {rec.get('solar_value', float('nan')):8.0f} "
                  f"{rec.get('v2g_value', float('nan')):8.0f}", flush=True)

    keys = sorted(set().union(*[set(r) for r in rows]), key=str)
    with open(os.path.join(OUT, "tech_tiers.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        sweep = [r for r in rows if r["ev_premium"] == EV_PREMIUM and r["ice_eff"] == ICE_EFF
                 and r.get("v2g_total") is not None]
        sweep.sort(key=lambda r: r["ratio"])
        xs = [r["ratio"] for r in sweep]
        fig, ax = plt.subplots(figsize=(7.5, 4.6), constrained_layout=True)
        for tier, c in (("vsp", "#888888"), ("ev", "#7d3c98"), ("solar", "#e08020"), ("v2g", "#2E75B6")):
            ax.plot(xs, [r[f"{tier}_total"] for r in sweep], "-o", color=c,
                    label={"vsp": "VSP (ICE)", "ev": "EVSP (plain EV)",
                           "solar": "EVSP-Solar", "v2g": "EVSP-V2G"}[tier])
        ax.set_xlabel("R = daily solar surplus / fleet traction")
        ax.set_ylabel("total daily cost ($)")
        ax.set_title(f"Technology tiers vs R  (EV premium {EV_PREMIUM}x, drivetrain eff. {ICE_EFF}x)")
        ax.legend()
        fig.savefig(os.path.join(OUT, "tech_tiers.png"), dpi=130)
        print(f"\nfigure -> {os.path.join(OUT, 'tech_tiers.png')}")
    except ImportError:
        pass
    print(f"outputs: results/arxiv/tech_tiers.json / .csv")


if __name__ == "__main__":
    main()
