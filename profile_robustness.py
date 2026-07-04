"""
Profile-shape robustness: is the R-rule a San Nicolas artifact?

Every planning result so far uses ONE demand/solar shape (the San Nicolas
profile, scaled). This study reshapes the profiles while HOLDING DAILY TOTALS
FIXED (same total demand, same total solar at each pv), so R changes only via
pv -- and then asks whether V2G-vs-Solar savings still collapse onto the same
savings-vs-R curve across shapes.

Shapes (all sum-preserving transforms of the original):
    original     : the San Nicolas profile (demand bumps 8h/19h, solar ~10-17h)
    solar_early  : solar shifted 2 h earlier (peak ~11h)
    demand_late  : demand shifted 2 h later (evening peak ~21h)
    flat_demand  : demand uniform across 24 h (same total)
    wide_solar   : same solar energy spread over a wider bell (6h-19h, sd 3h)

If the curves coincide, R is the collapse variable regardless of shape; if they
fan out, the spread measures how much TEMPORAL OVERLAP (when surplus occurs vs
when the fleet is idle/deficits occur) matters beyond the energy ratio -- either
outcome sharpens the paper's planning rule.

Base: 3 locations = 60 trips (breaks), eps=2.0, c_g=$0.40/kWh, c_b=$36,
rho=350 kW, cyclic (the revised model). Run: python3 profile_robustness.py
Outputs: results/arxiv/profile_robustness.{json,csv,png}
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, load_delta_units, BREAKS, HAVE_GUROBI
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
PROFILES = ["original", "solar_early", "demand_late", "flat_demand", "wide_solar"]
PV_LIST  = [1.0, 1.5, 2.0, 2.5, 3.0]
POINTS, EPS = 3, 2.0
CG_COST, CB_COST, RHO = 40.0, 36.0, 1.75
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def base_curves():
    """Hourly demand D and solar S (units) from the original transform."""
    D = load_delta_units(7.0, 0.0).astype(float)          # pv=0: demand only
    S = D - load_delta_units(7.0, 1.0).astype(float)      # demand - Delta = solar
    return D, S


def shaped(profile: str):
    D, S = base_curves()
    if profile == "original":
        return D, S
    if profile == "solar_early":
        return D, np.roll(S, -2)
    if profile == "demand_late":
        return np.roll(D, 2), S
    if profile == "flat_demand":
        return np.full(24, D.sum() / 24.0), S
    if profile == "wide_solar":
        h = np.arange(24)
        bell = np.exp(-0.5 * ((h - 12.5) / 3.0) ** 2)
        bell[(h < 6) | (h > 19)] = 0.0
        return D, bell * (S.sum() / bell.sum())
    raise ValueError(profile)


def run_cell(profile: str, pv: float):
    D, S = shaped(profile)
    delta_h = np.round(D - pv * S).astype(int)            # same rounding as the original
    inst = build_instance(POINTS, EPS, BREAKS, delta_hourly=delta_h)
    inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    rec = {"profile": profile, "pv": pv, "ratio": round(surplus / max(traction, 1e-9), 3),
           "surplus_mwh": round(surplus / 10, 1)}
    for scen in ("solar", "v2g"):
        res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                                enrich=25, max_iter=max(2000, 5 * inst.n_trips))
        if res["lp_obj"] == float("inf"):
            rec[f"{scen}_total"] = None
            continue
        mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                         battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
        rec[f"{scen}_total"] = round(mip.obj, 1)
        rec[f"{scen}_batteries"] = int(round(mip.nb))
        rec[f"{scen}_gap_pct"] = round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3)
    if rec.get("solar_total") and rec.get("v2g_total") is not None:
        rec["v2g_vs_solar_pct"] = round(
            100 * (rec["solar_total"] - rec["v2g_total"]) / rec["solar_total"], 2)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"profile robustness: {len(PROFILES)} shapes x {len(PV_LIST)} pv levels, "
          f"solar+v2g each  (MILP: {MILP_SOLVER})\n")
    print(f"{'profile':>12} {'pv':>4} {'R':>6} {'surplusMWh':>10} {'V2G/Solar%':>11} {'batt':>5}")
    rows, t0 = [], time.time()
    for profile in PROFILES:
        for pv in PV_LIST:
            r = run_cell(profile, pv)
            rows.append(r)
            json.dump(rows, open(os.path.join(OUT, "profile_robustness.json"), "w"), indent=2)
            print(f"{profile:>12} {pv:4.1f} {r['ratio']:6.2f} {r['surplus_mwh']:10.1f} "
                  f"{r.get('v2g_vs_solar_pct', float('nan')):11.1f} "
                  f"{r.get('v2g_batteries', 0):5d}", flush=True)
    keys = sorted(set().union(*[set(r) for r in rows]), key=str)
    with open(os.path.join(OUT, "profile_robustness.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)

    # collapse check: for each pv level, spread of savings across shapes at ~equal R
    print("\n=== collapse check: savings spread across shapes ===")
    for pv in PV_LIST:
        sub = [r for r in rows if r["pv"] == pv and "v2g_vs_solar_pct" in r]
        if sub:
            v = [r["v2g_vs_solar_pct"] for r in sub]
            rr = [r["ratio"] for r in sub]
            print(f"  pv={pv:.1f}: R in [{min(rr):.2f},{max(rr):.2f}]  "
                  f"savings {min(v):5.1f}% .. {max(v):5.1f}%  (spread {max(v)-min(v):4.1f} pts)")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7.5, 4.6), constrained_layout=True)
        colors = {"original": "#2E75B6", "solar_early": "#e08020", "demand_late": "#c0392b",
                  "flat_demand": "#888888", "wide_solar": "#2e9e3f"}
        for profile in PROFILES:
            sub = sorted([r for r in rows if r["profile"] == profile and "v2g_vs_solar_pct" in r],
                         key=lambda r: r["ratio"])
            ax.plot([r["ratio"] for r in sub], [r["v2g_vs_solar_pct"] for r in sub],
                    "-o", color=colors[profile], label=profile)
        ax.set_xlabel("R = daily solar surplus / fleet traction")
        ax.set_ylabel("V2G savings vs charge-only (%)")
        ax.set_title("Does the R-rule survive reshaped demand/solar profiles?")
        ax.legend()
        fig.savefig(os.path.join(OUT, "profile_robustness.png"), dpi=130)
        print(f"\nfigure -> {os.path.join(OUT, 'profile_robustness.png')}")
    except ImportError:
        pass
    print(f"total {time.time() - t0:.1f}s; outputs: results/arxiv/profile_robustness.json / .csv")


if __name__ == "__main__":
    main()
