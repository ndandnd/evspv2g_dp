"""
Recreate the computational study of the original arXiv paper (2508.06752v1)
under the REVISED model, with the labeling-DP pricing oracle in place of the
original Gurobi-MILP pricing.

Exact ports from the original repo (same instance, to the digit):
  * delta profile : data/delta.csv, hourly rows, Delta = round((Power/5 - PV) * solar_mult),
                    default solar_mult = 7 -- identical to run_experiments.py.
  * trip set      : DETERMINISTIC enumeration (no seeds): for every start hour in the
                    window(s), one trip per ordered location pair. Breaks schedule
                    (4-9 & 18-23) gives 20/60/120 trips at 2/3/4 locations; the
                    scalability tables' single window (4-9) gives 10..450 trips at 2..10.
  * geometry      : depot O=(0,0), locations at (+-.25,+-.25)... Manhattan distances;
                    0.5-block deadheads are represented EXACTLY on a half-block grid
                    (T = 48 half-hours), SoC lattice = 0.5 units.
  * parameters    : G=7 (700 kWh), eps in {1.5,2.0,2.5} (150/200/250 kWh),
                    charge rate 1 unit/hour, c_g=5, c_v=5*G+10=45, c_b=45-9=36.
                    1 unit = 100 kWh.

Deliberate differences (the revision's model -- results shift accordingly):
  * CYCLIC SoC (s_0 = s_T) instead of the original free full start: initial energy
    is no longer free, so fuel is positive -- the original's negative "net export"
    fuel numbers were an artifact of free initial charge and will NOT reproduce.
  * anti-cycling: tiny activity penalty eps_pen (~ the original 1.01 charge premium).
  * charging sessions per route are not limited to L=4 (the DP allows any number).
  * free vs paid charging is endogenous via the power balance (Prop 1), not split
    constraints -- economically equivalent.

Experiments (mirroring the original section):
  exp1  regime comparison  : VSP / EVSP-Solar / EVSP-V2G x eps x {20,60,120} trips
  exp2  trip scheduling    : breaks vs uniform windows (Table 2)
  exp3  solar scaling      : sweep solar_mult (Figure 5)
  exp4  solution timeline  : Gantt of a V2G solution (Figure 6)
  exp5  scalability        : eps=2.0 at 2..10 locations (10..450 trips) and
                             eps=1.5 at 2..8 locations (Tables 3 & 4), with
                             pricing-time share -- now DP, so seconds not hours.

Run:  python3 recreate_arxiv.py          (auto-uses Gurobi for the MILP if installed,
                                          else CBC; the LP master is always HiGHS)
Outputs: results/arxiv/exp*.{json,csv,png} + printed tables.
"""
from __future__ import annotations
import os, sys, csv, json, time, string

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from instance import Instance, Trip
from colgen import column_generation, summarize, SCENARIOS
from master import solve_milp

try:
    import gurobipy  # noqa: F401
    HAVE_GUROBI = True
except Exception:
    HAVE_GUROBI = False

# ============================== CONFIG -- EDIT ME ==============================
RUN_EXPS        = ["1", "2", "3", "4", "5"]   # which experiments to run
MILP_SOLVER     = "gurobi" if HAVE_GUROBI else "cbc"
MILP_TIME_LIMIT = 300.0        # per integer solve (original used a 4h limit; DP makes this ample)
SOLAR_MULT      = 7            # the original default
EPS_LIST        = [1.5, 2.0, 2.5]       # light / medium / heavy (150/200/250 kWh)
POINTS_LIST     = [2, 3, 4]             # -> 20 / 60 / 120 trips under the breaks schedule
SOLAR_SWEEP     = [1, 3, 5, 7, 9, 11, 13]   # exp3: solar_mult values (literal original transform)
PV_SWEEP        = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]  # exp3b: PV-only scale ('available solar')
SCAL_POINTS_E20 = list(range(2, 11))    # exp5, eps=2.0: 2..10 locations = 10..450 trips
SCAL_POINTS_E15 = list(range(2, 9))     # exp5, eps=1.5: 2..8  locations = 10..280 trips
ENRICH          = 25
SOC_MODE        = "cyclic"     # "cyclic" = revised model; "free" = ORIGINAL arXiv setting
                               # (free full initial charge for trucks and batteries)
UNIT_KWH        = 100.0        # 1 model unit = 100 kWh
GAL_PER_UNIT    = 100.0 / 33.0 # the original code's kWh->gallon equivalence (33 kWh/gal)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================

# trip windows (start hours are enumerated in [a, b) for each window)
BREAKS  = [(4, 9), (18, 23)]   # the original run file: morning + evening, 10 start hours
UNIFORM = [(9, 19)]            # midday window with the SAME trip counts (10 start hours)
SCAL    = [(4, 9)]             # single window: n(n-1)*5 trips -> 10..450 at 2..10 locations

# original geometry: depot at the origin, locations on a (+-.25 + .5k) grid so every
# Manhattan distance is a multiple of 0.5 (locations A-D exactly as in the original;
# E.. extend the same pattern for the scalability instances).
_COORDS = [(.25, .25), (-.25, .25), (.25, -.25), (-.25, -.25),
           (.75, .25), (-.75, .25), (.75, -.25), (-.75, -.25),
           (.25, .75), (-.25, .75), (.25, -.75), (-.25, -.75)]


def load_delta_units(solar_mult: float, pv_scale: float = 1.0) -> np.ndarray:
    """Hourly Delta (24 ints, model units) exactly as the original run file computes it.
    pv_scale multiplies ONLY the PV term (for the solar-scaling experiment's
    'available daily solar' axis); pv_scale=1 is the literal original transform."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "delta.csv")
    with open(path) as f:
        lines = f.read().splitlines()
    rdr = csv.DictReader(lines[1:])                       # header=1: skip the "delta" line
    P, PV = [], []
    for row in rdr:
        t = row["Time"]
        if t.endswith(":00") and "01:00" <= t <= "24:00":  # on-the-hour, 24 rows
            P.append(float(row["Power (MW)"])); PV.append(float(row["PV(MW)"]))
    assert len(P) == 24, f"expected 24 hourly rows, got {len(P)}"
    delta_mod = (np.array(P) / 5.0 - np.array(PV) * pv_scale) * solar_mult
    return np.round(delta_mod).astype(int)                # round-half-even, like pandas


def gen_trips(n_locs: int, windows) -> list[tuple[int, int, int]]:
    """(sloc, eloc, start_hour) -- the original's deterministic enumeration."""
    out = []
    for a, b in windows:
        for t in range(a, b):
            for i in range(n_locs):
                for j in range(i + 1, n_locs):
                    out.append((i + 1, j + 1, t))          # +1: index 0 is the depot
                    out.append((j + 1, i + 1, t))
    return out


def build_instance(points: int, eps: float, windows, solar_mult: float = SOLAR_MULT,
                   pv_scale: float = 1.0, delta_hourly=None) -> Instance:
    """The original instance on a half-block grid (exact 0.5-block deadheads).
    delta_hourly: optional 24-vector of hourly Delta (units) overriding the
    delta.csv transform -- used by the profile-robustness study."""
    assert points <= len(_COORDS), f"at most {len(_COORDS)} locations supported"
    T = 48                                                 # 24 h x 2 half-blocks
    coords = [(0.0, 0.0)] + list(_COORDS[:points])         # 0 = depot O
    n = len(coords)
    dist = np.zeros((n, n))
    for a in range(n):
        for b in range(n):
            man = abs(coords[a][0] - coords[b][0]) + abs(coords[a][1] - coords[b][1])
            dist[a, b] = 2.0 * man                         # half-blocks (0.5 h -> 1 block); energy = dist * epd
    trips = [Trip(idx=k, start=2 * st, end=2 * (st + 2), sloc=sl, eloc=el, energy=eps)
             for k, (sl, el, st) in enumerate(gen_trips(points, windows))]
    trips.sort(key=lambda tr: (tr.start, tr.idx))
    for k, tr in enumerate(trips):
        tr.idx = k
    delta_h = (np.asarray(delta_hourly, dtype=float) if delta_hourly is not None
               else load_delta_units(solar_mult, pv_scale))   # units per hour
    delta = np.repeat(delta_h / 2.0, 2)                    # units per half-block
    return Instance(
        T=T, D=np.maximum(delta, 0.0), P=np.maximum(-delta, 0.0), trips=trips, dist=dist,
        G=7.0, rho=0.5,                                    # 1 unit/hour = 0.5 per half-block
        eta=0.0, energy_per_dist=0.5,                      # deadhead energy = Manhattan (units)
        c_g=5.0, c_v=45.0, c_b=36.0,                       # fuel 5; bus 5*7+10; batt 45-9
        eps_pen=0.025,                                     # ~ the original 1.01 charge premium
        depot=0, gen_cap=float("inf"), charge_cap=float("inf"),
        soc_step=0.5,                                      # exact lattice for eps/G/deadheads
    )


def run_case(inst: Instance, scenario: str) -> dict:
    batt = SCENARIOS[scenario]["battery"]
    t0 = time.time()
    res = column_generation(inst, scenario=scenario, start="warm", do_milp=False,
                            enrich=ENRICH, max_iter=max(2000, 5 * inst.n_trips),
                            soc_mode=SOC_MODE)
    cg_s = time.time() - t0
    row = {"trips": inst.n_trips, "scenario": scenario, "cg_iters": res["iters"],
           "cols": res["n_cols"], "cg_s": round(cg_s, 2),
           "pricing_s": round(res["pricing_time"], 2),
           "pricing_pct": round(100 * res["pricing_time"] / cg_s, 1) if cg_s > 0 else 0.0,
           "lp_obj": round(res["lp_obj"], 2)}
    if res["lp_obj"] == float("inf"):
        row["feasible"] = False
        return row
    row["feasible"] = True
    t1 = time.time()
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=batt, solver=MILP_SOLVER, soc_mode=SOC_MODE)
    row["milp_s"] = round(time.time() - t1, 2)
    res["mip"] = mip
    s = summarize(inst, res)
    row.update({"mip_obj": round(mip.obj, 2),
                "gap_pct": round((mip.obj - res["lp_obj"]) / abs(mip.obj) * 100, 3),
                "trucks": s["trucks"], "batteries": s["batteries"],
                "fuel_units": s["fuel_kwh"],               # summarize() is unit-agnostic
                "fuel_kwh": round(s["fuel_kwh"] * UNIT_KWH, 1),
                "fuel_gal": round(s["fuel_kwh"] * GAL_PER_UNIT, 2)})
    row["_res"] = res                                      # for exp4's plot (stripped before save)
    return row


def _save(name: str, rows: list[dict]):
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    json.dump(clean, open(os.path.join(OUT, f"{name}.json"), "w"), indent=2)
    keys = sorted({k for r in clean for k in r}, key=lambda k: (k != "trips", k))
    with open(os.path.join(OUT, f"{name}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader(); w.writerows(clean)


def _plt():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


NAME = {"vsp": "VSP (ICE)", "solar": "EVSP-Solar", "v2g": "EVSP-V2G"}
COL = {"vsp": "#888888", "solar": "#e08020", "v2g": "#2E75B6"}


def exp1_regimes():
    print("\n=== exp1: regime comparison (breaks schedule, solar_mult=%s) ===" % SOLAR_MULT)
    print(f"{'eps':>4} {'trips':>6} {'scenario':>11} {'fuel_kwh':>9} {'trucks':>7} "
          f"{'batt':>5} {'gap%':>7} {'cg_s':>6} {'milp_s':>7}")
    rows = []
    for eps in EPS_LIST:
        for pts in POINTS_LIST:
            inst = build_instance(pts, eps, BREAKS)
            for scen in ("vsp", "solar", "v2g"):
                r = run_case(inst, scen); r.update({"eps": eps, "points": pts})
                rows.append(r); _save("exp1_regimes", rows)
                print(f"{eps:4.1f} {r['trips']:6d} {scen:>11} {r.get('fuel_kwh', float('nan')):9.0f} "
                      f"{r.get('trucks', 0):7d} {r.get('batteries', 0):5d} "
                      f"{r.get('gap_pct', float('nan')):7.3f} {r['cg_s']:6.1f} "
                      f"{r.get('milp_s', 0):7.1f}", flush=True)
    plt = _plt()
    if plt:
        fig, axes = plt.subplots(2, len(EPS_LIST), figsize=(4.2 * len(EPS_LIST), 7),
                                 sharex=True, constrained_layout=True, squeeze=False)
        for c, eps in enumerate(EPS_LIST):
            for scen in ("vsp", "solar", "v2g"):
                sub = [r for r in rows if r["eps"] == eps and r["scenario"] == scen and r["feasible"]]
                xs = [r["trips"] for r in sub]
                axes[0, c].plot(xs, [r["fuel_kwh"] / 1000 for r in sub], "-o", color=COL[scen], label=NAME[scen])
                axes[1, c].plot(xs, [r["trucks"] for r in sub], "-o", color=COL[scen], label=NAME[scen])
            axes[0, c].set_title(f"eps = {eps} ({int(eps*100)} kWh/trip)")
            axes[1, c].set_xlabel("number of trips")
        axes[0, 0].set_ylabel("daily fuel (MWh-equiv)"); axes[1, 0].set_ylabel("trucks deployed")
        axes[0, 0].legend()
        fig.suptitle("Regime comparison under the revised model (DP pricing)")
        fig.savefig(os.path.join(OUT, "exp1_regimes.png"), dpi=130)
    return rows


def exp2_scheduling():
    print("\n=== exp2: trip scheduling -- breaks vs uniform (eps=2.5, V2G; Table-2 analogue) ===")
    print(f"{'trips':>6} {'schedule':>9} {'fuel_kwh':>9} {'fuel_gal':>9} {'trucks':>7} {'batt':>5} {'gap%':>7}")
    rows = []
    for pts in POINTS_LIST:
        for sched, windows in (("breaks", BREAKS), ("uniform", UNIFORM)):
            inst = build_instance(pts, 2.5, windows)
            r = run_case(inst, "v2g"); r.update({"schedule": sched, "points": pts})
            rows.append(r); _save("exp2_scheduling", rows)
            print(f"{r['trips']:6d} {sched:>9} {r.get('fuel_kwh', float('nan')):9.0f} "
                  f"{r.get('fuel_gal', float('nan')):9.1f} {r.get('trucks', 0):7d} "
                  f"{r.get('batteries', 0):5d} {r.get('gap_pct', float('nan')):7.3f}", flush=True)
    return rows


def exp3_solar():
    # NOTE: the original code's solar_mult scales the WHOLE profile (demand - PV),
    # so this literal sweep grows demand too; exp3b below scales only the PV term
    # (the paper's 'available daily solar' reading). Both are reported.
    print("\n=== exp3: solar scaling, literal original transform (V2G, 60 trips) ===")
    print(f"{'eps':>4} {'solar_mult':>10} {'fuel_kwh':>9} {'trucks':>7} {'batt':>5} {'gap%':>7}")
    rows = []
    for eps in (2.0, 2.5):
        for sm in SOLAR_SWEEP:
            inst = build_instance(3, eps, BREAKS, solar_mult=sm)
            r = run_case(inst, "v2g"); r.update({"eps": eps, "solar_mult": sm})
            rows.append(r); _save("exp3_solar", rows)
            print(f"{eps:4.1f} {sm:10d} {r.get('fuel_kwh', float('nan')):9.0f} "
                  f"{r.get('trucks', 0):7d} {r.get('batteries', 0):5d} "
                  f"{r.get('gap_pct', float('nan')):7.3f}", flush=True)
    plt = _plt()
    if plt:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
        for eps, c in ((2.0, "#2E75B6"), (2.5, "#c0392b")):
            sub = [r for r in rows if r["eps"] == eps and r["feasible"]]
            xs = [r["solar_mult"] for r in sub]
            axes[0].plot(xs, [r["fuel_kwh"] / 1000 for r in sub], "-o", color=c, label=f"eps={eps}")
            axes[1].plot(xs, [r["trucks"] + r["batteries"] for r in sub], "-o", color=c, label=f"eps={eps}")
        axes[0].set_xlabel("solar multiplier"); axes[0].set_ylabel("daily fuel (MWh-equiv)"); axes[0].legend()
        axes[1].set_xlabel("solar multiplier"); axes[1].set_ylabel("vehicles + batteries"); axes[1].legend()
        fig.suptitle("Fuel and fleet vs available solar (EVSP-V2G, revised model)")
        fig.savefig(os.path.join(OUT, "exp3_solar.png"), dpi=130)
    return rows


def exp3b_solar_pv():
    print("\n=== exp3b: PV-only solar scaling (V2G, 60 trips; 'available daily solar') ===")
    print(f"{'eps':>4} {'pv_scale':>8} {'solar_mwh':>9} {'fuel_kwh':>9} {'trucks':>7} {'batt':>5} {'gap%':>7}")
    rows = []
    base_pv = load_delta_units(SOLAR_MULT, 1.0) - load_delta_units(SOLAR_MULT, 0.0)  # -solar units/hour
    daily_solar_units = float(-base_pv.sum())
    for eps in (2.0, 2.5):
        for k in PV_SWEEP:
            inst = build_instance(3, eps, BREAKS, pv_scale=k)
            r = run_case(inst, "v2g")
            r.update({"eps": eps, "pv_scale": k,
                      "solar_mwh": round(k * daily_solar_units * UNIT_KWH / 1000, 1)})
            rows.append(r); _save("exp3b_solar_pv", rows)
            print(f"{eps:4.1f} {k:8.2f} {r['solar_mwh']:9.1f} {r.get('fuel_kwh', float('nan')):9.0f} "
                  f"{r.get('trucks', 0):7d} {r.get('batteries', 0):5d} "
                  f"{r.get('gap_pct', float('nan')):7.3f}", flush=True)
    plt = _plt()
    if plt:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
        for eps, c in ((2.0, "#2E75B6"), (2.5, "#c0392b")):
            sub = [r for r in rows if r["eps"] == eps and r["feasible"]]
            xs = [r["solar_mwh"] for r in sub]
            axes[0].plot(xs, [r["fuel_kwh"] / 1000 for r in sub], "-o", color=c, label=f"eps={eps}")
            axes[1].plot(xs, [r["trucks"] + r["batteries"] for r in sub], "-o", color=c, label=f"eps={eps}")
        axes[0].set_xlabel("available daily solar (MWh)"); axes[0].set_ylabel("daily fuel (MWh-equiv)")
        axes[1].set_xlabel("available daily solar (MWh)"); axes[1].set_ylabel("vehicles + batteries")
        axes[0].legend(); axes[1].legend()
        fig.suptitle("Fuel and fleet vs available solar, PV-only scaling (EVSP-V2G)")
        fig.savefig(os.path.join(OUT, "exp3b_solar_pv.png"), dpi=130)
    return rows


def exp4_timeline():
    print("\n=== exp4: solution timeline (eps=2.5, 3 locations, V2G; Figure-6 analogue) ===")
    inst = build_instance(3, 2.5, BREAKS)
    r = run_case(inst, "v2g")
    print(f"  trips={r['trips']}  trucks={r.get('trucks')}  batteries={r.get('batteries')}  "
          f"fuel={r.get('fuel_kwh'):.0f} kWh  gap={r.get('gap_pct')}%")
    _save("exp4_timeline", [r])
    plt = _plt()
    if plt and r["feasible"]:
        res, mip, cols, T = r["_res"], r["_res"]["mip"], r["_res"]["cols"], inst.T
        lanes = [(f"Truck {k+1}", cols[i].e * round(mip.x[i]))
                 for k, i in enumerate(np.flatnonzero(mip.x > 0.5))]
        if mip.charge is not None:
            lanes.append((f"Battery (x{int(round(mip.nb))})", mip.charge - mip.discharge))
        hours = np.arange(T) / 2.0
        fig, (axd, ax) = plt.subplots(2, 1, figsize=(11, 0.9 + 0.42 * len(lanes)),
                                      gridspec_kw={"height_ratios": [1, 3]},
                                      constrained_layout=True, sharex=True)
        axd.bar(hours, inst.Delta * UNIT_KWH * 2, width=0.5, align="edge",
                color=["#f0c000" if d < 0 else "#cfcfcf" for d in inst.Delta])
        axd.axhline(0, color="k", lw=0.5); axd.set_ylabel("net demand (kW)")
        axd.set_title("EVSP-V2G solution timeline (original instance, revised model)")
        for i, (lab, e) in enumerate(lanes):
            for t in range(T):
                if e[t] > 1e-6:
                    c = "#2e9e3f" if inst.Delta[t] < 0 else "#333333"
                    ax.add_patch(plt.Rectangle((hours[t], i - 0.42), 0.5, 0.84, color=c))
                elif e[t] < -1e-6:
                    ax.add_patch(plt.Rectangle((hours[t], i - 0.42), 0.5, 0.84, color="#c0392b"))
        ax.set_yticks(range(len(lanes))); ax.set_yticklabels([l for l, _ in lanes], fontsize=8)
        ax.set_xlim(0, 24); ax.set_ylim(-0.7, len(lanes) - 0.3)
        ax.set_xlabel("hour of day"); ax.set_xticks(range(0, 25, 2))
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(color="#2e9e3f", label="free (solar) charge"),
                           Patch(color="#333333", label="paid charge"),
                           Patch(color="#c0392b", label="discharge")],
                  ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.12), fontsize=8)
        fig.savefig(os.path.join(OUT, "exp4_timeline.png"), dpi=130)
    return [r]


def exp5_scalability():
    print("\n=== exp5: scalability with DP pricing (Tables 3 & 4 analogue; V2G) ===")
    all_rows = []
    for eps, points_list, tag in ((2.0, SCAL_POINTS_E20, "eps2.0"), (1.5, SCAL_POINTS_E15, "eps1.5")):
        print(f"\n-- eps = {eps} --")
        print(f"{'locs':>5} {'trips':>6} {'cg_it':>6} {'cols':>6} {'cg_s':>7} {'pricing%':>9} "
              f"{'milp_s':>7} {'trucks':>7} {'batt':>5} {'gap%':>7}")
        rows = []
        for pts in points_list:
            inst = build_instance(pts, eps, SCAL)
            r = run_case(inst, "v2g"); r.update({"eps": eps, "points": pts})
            rows.append(r); all_rows.append(r); _save(f"exp5_scalability_{tag}", rows)
            print(f"{pts:5d} {r['trips']:6d} {r['cg_iters']:6d} {r['cols']:6d} {r['cg_s']:7.1f} "
                  f"{r['pricing_pct']:9.1f} {r.get('milp_s', 0):7.1f} {r.get('trucks', 0):7d} "
                  f"{r.get('batteries', 0):5d} {r.get('gap_pct', float('nan')):7.3f}", flush=True)
    return all_rows


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    print(f"MILP solver: {MILP_SOLVER} (Gurobi available: {HAVE_GUROBI}); LP master: HiGHS; "
          f"pricing: labeling DP\nMILP budget {MILP_TIME_LIMIT}s per instance; "
          f"unit = {UNIT_KWH:.0f} kWh; solar_mult = {SOLAR_MULT}")
    t0 = time.time()
    if "1" in RUN_EXPS: exp1_regimes()
    if "2" in RUN_EXPS: exp2_scheduling()
    if "3" in RUN_EXPS: exp3_solar(); exp3b_solar_pv()
    if "4" in RUN_EXPS: exp4_timeline()
    if "5" in RUN_EXPS: exp5_scalability()
    print(f"\ntotal {time.time() - t0:.1f}s; outputs in {OUT}")
    print("NOTE: the revised model is cyclic (no free initial charge), so fuel is "
          "positive -- the original's negative net-export values were a free-start "
          "artifact and are not expected to reproduce; trends and ~1% gaps are.")
