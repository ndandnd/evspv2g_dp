"""
Overnight study driver: four cluster-scale studies, each checkpointed to its
own JSON (safe to kill and rerun; finished rows are never lost).

  S1  mega_sweep      ~N_SWEEP randomized bases across (tasks, energy, PV,
                      network, trip set) STRATIFIED BY CHARGE RATE rho in
                      {100, 200, 350 kW}. Tests whether the savings-vs-R
                      collapse is one curve or a curve FAMILY indexed by rho
                      (the knob grid hinted rate shifts it).
  S2  weather_year    all 365 real 2023 days x PV in {1,...,3} x {solar,v2g}.
                      Deliverable: annual EXPECTED V2G savings as a function of
                      PV sizing, with day-to-day distribution bands -- the
                      PV-sizing curve under real weather.
  S3  breakeven       V2G-enablement economics, now COMPUTED not asserted:
                      sweep cycling-degradation cost x bidirectional-charger
                      premium x PV; reports net savings and the break-even R*
                      where net value crosses zero. (Degradation enters the
                      model via instance.deg_cost on discharge throughput;
                      the charger premium via the v2g fleet's truck cost.)
  S4  tripset_ci      200 sampled trip sets for the Fig 8.4 break-even CIs
                      (10x the earlier sample).

Env overrides (matching the cluster workflow):
  OVERNIGHT_STUDIES="S1,S2,S3,S4"   which studies, in order
  OVERNIGHT_N_SWEEP=500             S1 sample count
Run: python3 overnight.py           (expect ~6-12 h for all four with Gurobi)
Outputs: results/arxiv/overnight_{sweep,weather,breakeven,tripsets}.json
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS, HAVE_GUROBI
from solar_ensemble import sample_trips, load_days
from profile_robustness import base_curves
from colgen import column_generation, SCENARIOS
from master import solve_milp

# ============================== CONFIG -- EDIT ME ==============================
STUDIES   = os.environ.get("OVERNIGHT_STUDIES", "S1,S2,S3,S4").split(",")
N_SWEEP   = int(os.environ.get("OVERNIGHT_N_SWEEP", "500"))
RHO_STRATA = [0.5, 1.0, 1.75]            # 100 / 200 / 350 kW
SWEEP_TASKS, SWEEP_PV = (20, 400), (0.5, 4.0)
WEATHER_PV = [1.0, 1.5, 2.0, 2.5, 3.0]
BE_DEG     = [0.0, 2.0, 5.0]             # $/unit (100 kWh) of discharge: $0 / 0.02 / 0.05 per kWh
BE_PREM    = [0.0, 4.0, 8.0]             # $/day bidirectional-charger premium per v2g truck
BE_PV      = [1.0, 1.5, 2.0, 2.5, 3.0]
N_TRIPSETS = 200
CG_COST, CB_COST, RHO, CV = 40.0, 36.0, 1.75, 45.0
POINTS, EPS, N_TRIPS = 3, 2.0, 60        # S3/S4 base cell
MILP_TIME_LIMIT = 120.0
MILP_SOLVER = "gurobi" if HAVE_GUROBI else "cbc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")
# ==============================================================================


def solve(inst, scen, rho=RHO, deg=0.0, cv=CV):
    inst.c_g, inst.c_b, inst.rho, inst.c_v, inst.deg_cost = CG_COST, CB_COST, rho, cv, deg
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=MILP_TIME_LIMIT,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    return {"total": mip.obj, "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def ckpt(name):
    p = os.path.join(OUT, name)
    return (json.load(open(p)) if os.path.exists(p) else []), p


def s1_mega_sweep():
    rows, path = ckpt("overnight_sweep.json")
    done = len(rows)
    rng = np.random.default_rng(11)
    print(f"S1 mega sweep: {N_SWEEP} bases x rho strata (resuming at {done})", flush=True)
    plan = []
    for k in range(N_SWEEP):
        plan.append(dict(rho=float(rng.choice(RHO_STRATA)),
                         points=int(rng.choice([2, 3, 4])),
                         n_tasks=int(rng.integers(*SWEEP_TASKS)),
                         eps=float(rng.choice([0.5, 1.0, 1.5, 2.0, 2.5])),
                         pv=float(np.round(rng.uniform(*SWEEP_PV), 2)),
                         seed=k))
    for k, p in enumerate(plan):
        if k < done:
            continue
        trips = sample_trips(np.random.default_rng(1000 + p["seed"]), p["points"], p["n_tasks"])
        inst0 = build_instance(p["points"], p["eps"], BREAKS, pv_scale=p["pv"], trip_list=trips)
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        rec = {**p, "ratio": round(surplus / max(traction, 1e-9), 3)}
        ok = True
        for scen in ("solar", "v2g"):
            inst = build_instance(p["points"], p["eps"], BREAKS, pv_scale=p["pv"], trip_list=trips)
            r = solve(inst, scen, rho=p["rho"])
            if r is None:
                ok = False; break
            rec[f"{scen}_total"] = round(r["total"], 1); rec[f"{scen}_batteries"] = r["batteries"]
        if ok:
            rec["v2g_vs_solar_pct"] = round(100 * (rec["solar_total"] - rec["v2g_total"])
                                            / rec["solar_total"], 2)
        rows.append(rec)
        json.dump(rows, open(path, "w"))
        if k % 10 == 0:
            print(f"  [{k}/{N_SWEEP}] tasks={p['n_tasks']} rho={p['rho']} R={rec['ratio']:.2f} "
                  f"save={rec.get('v2g_vs_solar_pct', float('nan'))}%", flush=True)


def s2_weather_year():
    rows, path = ckpt("overnight_weather.json")
    done = {(r["date"], r["pv"]) for r in rows}
    days = load_days()
    D, S = base_curves()
    mean_daily = np.mean([d[1].sum() for d in days])
    print(f"S2 weather year: {len(days)} days x {len(WEATHER_PV)} pv levels "
          f"({len(done)} cells already done)", flush=True)
    for pv in WEATHER_PV:
        for date, ghi in days:
            if (date, pv) in done:
                continue
            S_d = ghi * (S.sum() * pv / mean_daily)
            dh = np.round(D - S_d).astype(int)
            inst0 = build_instance(POINTS, EPS, BREAKS, delta_hourly=dh)
            surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
            traction = float(sum(tr.energy for tr in inst0.trips))
            rec = {"date": date, "pv": pv, "ratio": round(surplus / max(traction, 1e-9), 3)}
            ok = True
            for scen in ("solar", "v2g"):
                inst = build_instance(POINTS, EPS, BREAKS, delta_hourly=dh)
                r = solve(inst, scen)
                if r is None:
                    ok = False; break
                rec[f"{scen}_total"] = round(r["total"], 1)
            if ok:
                rec["v2g_vs_solar_pct"] = round(100 * (rec["solar_total"] - rec["v2g_total"])
                                                / rec["solar_total"], 2)
            rows.append(rec)
            json.dump(rows, open(path, "w"))
        sub = [r["v2g_vs_solar_pct"] for r in rows if r["pv"] == pv and "v2g_vs_solar_pct" in r]
        if sub:
            print(f"  pv={pv}: annual mean {np.mean(sub):.1f}%  "
                  f"(p10 {np.percentile(sub, 10):.1f}, p90 {np.percentile(sub, 90):.1f})", flush=True)


def s3_breakeven():
    rows, path = ckpt("overnight_breakeven.json")
    done = {(r["deg"], r["prem"], r["pv"]) for r in rows}
    trips = sample_trips(np.random.default_rng(0), POINTS, N_TRIPS)
    print("S3 enablement break-even: deg x charger-premium x pv", flush=True)
    solar_cache = {}
    for pv in BE_PV:
        inst = build_instance(POINTS, EPS, BREAKS, pv_scale=pv, trip_list=trips)
        surplus = float(np.maximum(-inst.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst.trips))
        r = solve(inst, "solar")
        solar_cache[pv] = (r["total"], round(surplus / traction, 3))
    for deg in BE_DEG:
        for prem in BE_PREM:
            for pv in BE_PV:
                if (deg, prem, pv) in done:
                    continue
                inst = build_instance(POINTS, EPS, BREAKS, pv_scale=pv, trip_list=trips)
                r = solve(inst, "v2g", deg=deg, cv=CV + prem)
                st, ratio = solar_cache[pv]
                # note: the premium also applies to charge-only trucks' chargers? No --
                # prem is the bidirectional DIFFERENTIAL, so solar keeps plain CV.
                net = round(100 * (st - r["total"]) / st, 2)
                rows.append({"deg": deg, "prem": prem, "pv": pv, "ratio": ratio,
                             "net_savings_pct": net, "batteries": r["batteries"]})
                json.dump(rows, open(path, "w"))
        # report break-even R* per (deg, prem): first R where net savings cross 0
    for deg in BE_DEG:
        for prem in BE_PREM:
            pts = sorted([(r["ratio"], r["net_savings_pct"]) for r in rows
                          if r["deg"] == deg and r["prem"] == prem])
            rstar = None
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                if y1 < 0 <= y2:
                    rstar = x1 + (0 - y1) * (x2 - x1) / (y2 - y1)
            first = pts[0][1] if pts else float("nan")
            print(f"  deg=${deg}/unit prem=${prem}/truck-day: net savings at lowest R "
                  f"= {first:.1f}%" + (f", break-even R* ~ {rstar:.2f}" if rstar else
                                       " (positive everywhere tested)" if first >= 0 else ""), flush=True)


def s4_tripset_ci():
    rows, path = ckpt("overnight_tripsets.json")
    done = len(rows)
    rng = np.random.default_rng(7)
    print(f"S4 trip-set CI: {N_TRIPSETS} sets (resuming at {done})", flush=True)
    for seed in range(N_TRIPSETS):
        trips = sample_trips(rng, POINTS, N_TRIPS)      # keep rng stream aligned
        if seed < done:
            continue
        inst_v = build_instance(POINTS, EPS, BREAKS, trip_list=trips)
        traction = float(sum(tr.energy for tr in inst_v.trips))
        vsp = solve(inst_v, "vsp")
        vsp1x = vsp["total"] + CG_COST * traction
        rec = {"seed": seed}
        for prem in (1.0, 1.5, 2.0):
            inst_e = build_instance(POINTS, EPS, BREAKS, trip_list=trips)
            ev = solve(inst_e, "ev", cv=CV * prem)
            rec[f"breakeven_p{prem}"] = round(1.0 + (ev["total"] - vsp1x) / (CG_COST * traction), 4)
        rows.append(rec)
        json.dump(rows, open(path, "w"))
        if seed % 20 == 0:
            print(f"  [{seed}/{N_TRIPSETS}]", flush=True)
    for prem in (1.0, 1.5, 2.0):
        v = np.array([r[f"breakeven_p{prem}"] for r in rows])
        ci = 1.96 * v.std(ddof=1) / np.sqrt(len(v))
        print(f"  premium {prem}x: {v.mean():.3f} [{v.mean()-ci:.3f}, {v.mean()+ci:.3f}] "
              f"(min {v.min():.3f}, max {v.max():.3f}, n={len(v)})", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    print(f"overnight driver: studies {STUDIES}  MILP={MILP_SOLVER}  N_SWEEP={N_SWEEP}\n", flush=True)
    fns = {"S1": s1_mega_sweep, "S2": s2_weather_year, "S3": s3_breakeven, "S4": s4_tripset_ci}
    for st in STUDIES:
        st = st.strip()
        if st in fns:
            t1 = time.time()
            fns[st]()
            print(f"-- {st} done in {(time.time()-t1)/60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time()-t0)/3600:.2f} h")
