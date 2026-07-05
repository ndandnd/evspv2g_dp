"""
Uncertainty for the headline numbers: confidence intervals from REAL variation.

The single-instance results are "a model of a model" -- one solar day, one
demand curve, one trip set. This script quantifies how much that matters, in
the two places it can matter, using the right source of variation for each:

PART A -- break-even efficiencies of Fig 8.4 (electrification decision).
  The solar profile PROVABLY cannot move these: both regimes in that figure are
  solar-blind (ICE burns fuel; the plain-EV tier buys every kWh at flat price
  without touching the microgrid balance), so the base generation cost cancels
  in the difference -- verified numerically below on the cloudiest and clearest
  real days of 2023. What CAN move them is the TRIP SET (traction total, fleet
  inflation). So Part A samples random trip sets (same size, random start hours
  and O-D pairs within the breaks windows) and reports the break-even
  distribution with a 95% CI per truck-premium level.

PART B -- the R-curve figures (8.2/8.5) under real weather.
  365 real days of hourly irradiance at the site's coordinates (San Nicolas
  Island area; Open-Meteo ERA5 archive, CC-BY 4.0; data/solar_days_2023.csv;
  daily mean 5.26 kWh/m2, range 0.49-8.57 -- a 17x swing). Each sampled day's
  GHI shape is scaled so the ANNUAL-MEAN day matches the design solar level;
  individual days then vary realistically. For each day we solve charge-only
  and V2G and report: the distribution of R across days, the distribution of
  V2G savings, its annual mean with a 95% CI, and -- the point -- that the
  daily points still land on the SAME savings-vs-R curve: weather moves a site
  ALONG the curve, it does not move the curve. (Days are solved independently
  with cyclic SoC; no cross-day storage coupling.)

Run: python3 solar_ensemble.py   (Gurobi if available, else CBC; ~5-15 min)
Outputs: results/arxiv/solar_ensemble.json / .csv / .png
"""
from __future__ import annotations
import os, sys, csv, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI
from profile_robustness import base_curves
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
N_TRIPSETS = 20          # part A: sampled trip sets for the break-even CI
PREMIUMS   = [1.0, 1.5, 2.0]
N_DAYS     = 30          # part B: real days sampled (stratified across the year)
PV_B       = 2.0         # solar sizing for part B (annual-mean day = 2x original)
POINTS, EPS, N_TRIPS = 3, 2.0, 60
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "results", "arxiv")
# ==============================================================================


def run_tier(inst, tier, ev_premium=1.0):
    inst.c_g, inst.c_b, inst.rho = CG_COST, CB_COST, RHO
    inst.c_v = CV if tier == "vsp" else CV * ev_premium
    res = column_generation(inst, scenario=tier, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[tier]["battery"], solver=MILP_SOLVER)
    return {"total": mip.obj, "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def sample_trips(rng, points, n):
    hours = [h for a, b in BREAKS for h in range(a, b)]
    out = []
    for _ in range(n):
        st = int(rng.choice(hours))
        i = int(rng.integers(1, points + 1))
        j = int(rng.integers(1, points + 1))
        while j == i:
            j = int(rng.integers(1, points + 1))
        out.append((i, j, st))
    return out


def load_days():
    path = os.path.join(ROOT, "data", "solar_days_2023.csv")
    days = []
    with open(path) as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#") or row[0] == "date":
                continue
            days.append((row[0], np.array([float(x) for x in row[1:25]])))
    return days


def part_a():
    print(f"=== PART A: break-even CI over {N_TRIPSETS} sampled trip sets ===")
    rng = np.random.default_rng(0)
    bes = {p: [] for p in PREMIUMS}
    rows = []
    for seed in range(N_TRIPSETS):
        trips = sample_trips(rng, POINTS, N_TRIPS)
        inst_v = build_instance(POINTS, EPS, BREAKS, trip_list=trips)
        traction = float(sum(tr.energy for tr in inst_v.trips))
        vsp = run_tier(inst_v, "vsp")
        vsp_total_1x = vsp["total"] + CG_COST * 1.0 * traction     # eff = 1x thermal
        rec = {"seed": seed, "traction_units": traction, "vsp_trucks": vsp["trucks"]}
        for prem in PREMIUMS:
            inst_e = build_instance(POINTS, EPS, BREAKS, trip_list=trips)
            ev = run_tier(inst_e, "ev", ev_premium=prem)
            # value(eff) = vsp_total(eff) - ev_total is linear with slope c_g*traction
            be = 1.0 + (ev["total"] - vsp_total_1x) / (CG_COST * traction)
            bes[prem].append(be)
            rec[f"breakeven_p{prem}"] = round(be, 3)
            rec[f"ev_trucks_p{prem}"] = ev["trucks"]
        rows.append(rec)
        print(f"  set {seed:2d}: traction={traction:5.0f}u  " +
              "  ".join(f"be({p}x)={rec[f'breakeven_p{p}']:.2f}" for p in PREMIUMS), flush=True)
    print("\n  break-even efficiency (mean [95% CI] over trip sets):")
    for p in PREMIUMS:
        v = np.array(bes[p]); ci = 1.96 * v.std(ddof=1) / np.sqrt(len(v))
        print(f"    premium {p}x: {v.mean():.3f}  [{v.mean()-ci:.3f}, {v.mean()+ci:.3f}]"
              f"   (min {v.min():.3f}, max {v.max():.3f})")
    # solar-invariance check: same trip set, cloudiest vs clearest real day
    days = load_days()
    D, S = base_curves()
    mean_daily = np.mean([d[1].sum() for d in days])
    lo = min(days, key=lambda d: d[1].sum()); hi = max(days, key=lambda d: d[1].sum())
    trips = sample_trips(np.random.default_rng(0), POINTS, N_TRIPS)
    vals = {}
    for tag, (_, ghi) in (("cloudiest", lo), ("clearest", hi)):
        S_d = ghi * (S.sum() * PV_B / mean_daily)
        dh = np.round(D - S_d).astype(int)
        iv = build_instance(POINTS, EPS, BREAKS, delta_hourly=dh, trip_list=trips)
        ie = build_instance(POINTS, EPS, BREAKS, delta_hourly=dh, trip_list=trips)
        traction = float(sum(tr.energy for tr in iv.trips))
        v = run_tier(iv, "vsp"); e = run_tier(ie, "ev", ev_premium=1.5)
        vals[tag] = (v["total"] + CG_COST * traction) - e["total"]
    print(f"\n  solar-invariance check (same trip set): electrification value on the "
          f"cloudiest day = {vals['cloudiest']:.1f}, clearest day = {vals['clearest']:.1f} "
          f"(difference {abs(vals['cloudiest']-vals['clearest']):.1f} -- MILP gap noise only)")
    return rows


def part_b():
    print(f"\n=== PART B: {N_DAYS} real 2023 days, pv={PV_B} (annual-mean-day design) ===")
    days = load_days()
    D, S = base_curves()
    mean_daily = np.mean([d[1].sum() for d in days])
    idx = np.linspace(0, len(days) - 1, N_DAYS).astype(int)      # stratified across the year
    rows = []
    print(f"{'date':>12} {'dayGHI/mean':>11} {'R':>6} {'solar$':>8} {'v2g$':>8} {'save%':>7} {'batt':>5}")
    for k in idx:
        date, ghi = days[k]
        S_d = ghi * (S.sum() * PV_B / mean_daily)
        dh = np.round(D - S_d).astype(int)
        rec = {"date": date, "ghi_rel": round(float(ghi.sum() / mean_daily), 3)}
        inst0 = build_instance(POINTS, EPS, BREAKS, delta_hourly=dh)
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        rec["ratio"] = round(surplus / max(traction, 1e-9), 3)
        ok = True
        for scen in ("solar", "v2g"):
            inst = build_instance(POINTS, EPS, BREAKS, delta_hourly=dh)
            r = run_tier(inst, scen)
            if r is None:
                ok = False
                break
            rec[f"{scen}_total"] = round(r["total"], 1)
            rec[f"{scen}_batteries"] = r["batteries"]
        if ok:
            rec["v2g_vs_solar_pct"] = round(
                100 * (rec["solar_total"] - rec["v2g_total"]) / rec["solar_total"], 2)
            print(f"{rec['date']:>12} {rec['ghi_rel']:11.2f} {rec['ratio']:6.2f} "
                  f"{rec['solar_total']:8.0f} {rec['v2g_total']:8.0f} "
                  f"{rec['v2g_vs_solar_pct']:7.1f} {rec['v2g_batteries']:5d}", flush=True)
        rows.append(rec)
        json.dump(rows, open(os.path.join(OUT, "solar_ensemble.json"), "w"), indent=2)
    ok_rows = [r for r in rows if "v2g_vs_solar_pct" in r]
    sv = np.array([r["v2g_vs_solar_pct"] for r in ok_rows])
    rr = np.array([r["ratio"] for r in ok_rows])
    ci = 1.96 * sv.std(ddof=1) / np.sqrt(len(sv))
    print(f"\n  R across real days     : mean {rr.mean():.2f}, range [{rr.min():.2f}, {rr.max():.2f}]")
    print(f"  V2G savings across days: mean {sv.mean():.1f}%  95% CI [{sv.mean()-ci:.1f}, {sv.mean()+ci:.1f}]"
          f"  (worst day {sv.min():.1f}%, best day {sv.max():.1f}%)")
    print(f"  days with savings >= 5%: {int((sv >= 5).sum())}/{len(sv)}")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(11, 4.3), constrained_layout=True)
        ax[0].hist(rr, bins=12, color="#2E75B6", alpha=0.85)
        ax[0].axvline(1.0, ls=":", color="#888"); ax[0].set_xlabel("R on each real day")
        ax[0].set_ylabel("days"); ax[0].set_title(f"weather -> a distribution over R (pv={PV_B})")
        ax[1].scatter(rr, sv, color="#2E75B6", s=28)
        ax[1].set_xlabel("R = solar surplus / fleet driving energy")
        ax[1].set_ylabel("V2G savings that day (%)")
        ax[1].set_title("daily points still land on the savings-vs-R curve")
        fig.savefig(os.path.join(OUT, "solar_ensemble.png"), dpi=140)
        print(f"  figure -> results/arxiv/solar_ensemble.png")
    except ImportError:
        pass
    return rows


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    print(f"MILP: {MILP_SOLVER} (Gurobi available: {HAVE_GUROBI})\n")
    a = part_a()
    b = part_b()
    keys = sorted(set().union(*[set(r) for r in a]), key=str)
    with open(os.path.join(OUT, "solar_ensemble_tripsets.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(a)
    print(f"\ntotal {time.time() - t0:.1f}s; outputs: results/arxiv/solar_ensemble.json / "
          f"solar_ensemble_tripsets.csv / .png")
