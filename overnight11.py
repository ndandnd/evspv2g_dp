"""
Overnight-11: densification round requested after the figure review.

  PACK2   : pack x workload x solar interaction (the missing 2nd dimension of
            the pack figure): G in {3.5,7,10.5,14} x n in {8,20,60,120,200}
            x pv in {2,3} x 3 seeds x {solar, v2g_fleet, v2g}.
  OUT3    : denser outage ladder: derates {1, 5/6, 2/3, 1/2, 1/3, 1/6, 0} and
            a morning window (05:00-09:00) besides the evening ones; fixed
            assets as in OUTAGE2.
  END3    : endurance with the censored region resolved: budget fractions
            {1.4, 1.3, 1.2, 1.1, 1.05, 1.0, 0.9, 0.8, 0.65, 0.5, 0.35, 0.2,
            0.1, 0.05} so charge-only floors (>1) and the V2G 1.5x/60 floor
            become measured instead of censored.
  SCHED3X : seeds 3-5 for the five-family retiming study (error bars).

Run: OVERNIGHT11_STUDIES="PACK2,OUT3,END3,SCHED3X" OVERNIGHT11_SHARD="i/K" python3 overnight11.py
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from colgen import column_generation, SCENARIOS
from master import solve_milp
from overnight3 import ckpt, save, solve, rand_trips, CG_COST, CB_COST, RHO, CV, MILP_SOLVER
from overnight10 import FAM3, _tasks3

STUDIES = os.environ.get("OVERNIGHT11_STUDIES", "PACK2,OUT3,END3,SCHED3X").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT11_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")


def _stats(inst):
    surplus = float(np.maximum(-inst.Delta, 0.0).sum())
    traction = float(sum(tr.energy for tr in inst.trips))
    return {"surplus_mwh": round(surplus / 10, 2), "traction_mwh": round(traction / 10, 2),
            "ratio": round(surplus / max(traction, 1e-9), 3)}


def _row(base, scen, r, **extra):
    if r is None:
        return {**base, "scenario": scen, "feasible": False, **extra}
    return {**base, "scenario": scen, "feasible": True, "total": round(r["total"], 1),
            "g_units": round(r["g_units"], 2), "trucks": r["trucks"],
            "batteries": r["batteries"], "gap_pct": round(r["gap"], 3), **extra}


def _solve_pack(inst, scen, G, tl=120.0):
    inst.c_g, inst.c_v = CG_COST, CV
    inst.rho = RHO
    inst.G = G
    inst.c_b = CB_COST * G / 7.0
    res = column_generation(inst, scenario=scen, start="warm", do_milp=False,
                            enrich=25, max_iter=max(2000, 5 * inst.n_trips))
    if res["lp_obj"] == float("inf"):
        return None
    mip = solve_milp(inst, res["cols"], time_limit=tl,
                     battery_allowed=SCENARIOS[scen]["battery"], solver=MILP_SOLVER)
    if getattr(mip, "status", "optimal") == "milp_failed" or not np.isfinite(mip.obj):
        return None
    return {"total": mip.obj, "milp_status": getattr(mip, "status", "optimal"),
            "g_units": float(mip.g.sum()),
            "trucks": int(sum(round(x) for x in mip.x)),
            "batteries": int(round(mip.nb)),
            "gap": (mip.obj - res["lp_obj"]) / abs(mip.obj) * 100}


def pack2():
    rows, path = ckpt(f"overnight11_pack2_s{SH_I}of{SH_K}.json")
    done = {(r["G"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    cells = [(sd, n, pv, G) for sd in (0, 1, 2) for n in (8, 20, 60, 120, 200)
             for pv in (2.0, 3.0) for G in (3.5, 7.0, 10.5, 14.0)]
    print(f"PACK2: {len(cells)} cells x 3, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, G) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=90_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"G": G, "pv": pv, "n_tasks": n, "seed": sd,
                "c_b": round(CB_COST * G / 7.0, 1), **_stats(inst0)}
        for scen in ("solar", "v2g_fleet", "v2g"):
            if (G, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            rows.append(_row(base, scen, _solve_pack(inst, scen, G)))
            save(rows, path)
        if idx % 15 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def out3():
    rows, path = ckpt(f"overnight11_out3_s{SH_I}of{SH_K}.json")
    done = {(r["derate"], r["win"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    DER = [1.0, 0.8, 0.6, 0.5, 0.4, 0.2, 0.0]
    WINS = {"eve4h": (34, 42), "eve8h": (28, 44), "morn4h": (10, 18)}
    cells = [(sd, n, pv, w, scen) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for w in WINS for scen in ("solar", "v2g_fleet", "v2g")]
    print(f"OUT3: {len(cells)} bases x {len(DER)} derates, shard {SH_I}/{SH_K} "
          f"({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, w, scen) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        if all((round(d, 3), w, pv, n, sd, scen) in done for d in DER):
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base_cap = 1.5 * float(np.maximum(inst0.Delta, 0.0).max())
        a, b = WINS[w]
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        inst.gen_cap = np.full(inst.T, base_cap)
        s1 = solve(inst, scen, tl=120.0)
        if s1 is None:
            continue
        for d in DER:
            if (round(d, 3), w, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            caps = np.full(inst.T, base_cap); caps[a:b] = d * base_cap
            inst.gen_cap = caps
            inst.max_trucks = s1["trucks"]; inst.nb_fixed = float(s1["batteries"])
            rows.append(_row({"derate": round(d, 3), "win": w, "pv": pv, "n_tasks": n,
                              "seed": sd, "stage1_trucks": s1["trucks"],
                              "stage1_batteries": s1["batteries"],
                              "stage1_total": round(s1["total"], 1), **_stats(inst0)},
                             scen, solve(inst, scen, tl=120.0)))
            save(rows, path)
        if idx % 8 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def end3():
    rows, path = ckpt(f"overnight11_end3_s{SH_I}of{SH_K}.json")
    done = {(r["frac"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    FRACS = [1.4, 1.3, 1.2, 1.1, 1.05, 1.0, 0.9, 0.8, 0.65, 0.5, 0.35, 0.2, 0.1, 0.05]
    cells = [(sd, n, pv, f) for sd in (0, 1, 2) for n in (20, 60)
             for pv in (1.5, 2.5) for f in FRACS]
    print(f"END3: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, f) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        baseline = float(np.maximum(inst0.Delta, 0.0).sum())
        base = {"frac": f, "pv": pv, "n_tasks": n, "seed": sd,
                "budget_units": round(f * baseline, 1), **_stats(inst0)}
        for scen in ("solar", "v2g"):
            if (f, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            inst.fuel_budget = f * baseline
            rows.append(_row(base, scen, solve(inst, scen, tl=120.0)))
            save(rows, path)
        if idx % 12 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def sched3x():
    rows, path = ckpt(f"overnight10_sched3_sX{SH_I}of{SH_K}.json")
    done = {(r["fam"], r["kcap"], r["pv"], r["n_tasks"], r["seed"], r["scenario"])
            for r in rows}
    cells = [(sd, n, pv, kc, fam, scen) for sd in (3, 4, 5) for n in (40, 80)
             for pv in (1.5, 2.5) for kc in (float("inf"), 0.5)
             for fam in FAM3 for scen in ("solar", "v2g_fleet", "v2g")]
    print(f"SCHED3X: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, kc, fam, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (fam, kc, pv, n, sd, scen) in done:
            continue
        fleet = _tasks3(n, sd, fam)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        base = {"fam": fam, "kcap": kc, "pv": pv, "n_tasks": n, "seed": sd, **_stats(inst)}
        if np.isfinite(kc):
            inst.charge_cap = kc * float(np.maximum(-inst.Delta, 0.0).max())
        rows.append(_row(base, scen, solve(inst, scen, tl=120.0)))
        save(rows, path)
        if idx % 20 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


def modesx3():
    from overnight3 import sol_kwargs
    rows, path = ckpt(f"overnight3_modes_sX3_{SH_I}of{SH_K}.json")
    done = {(r["n_tasks"], r["sol"], r["seed"], r["scenario"]) for r in rows}
    NT = list(range(4, 44, 4)) + list(range(50, 201, 10))
    cells = [(sd, n, sol, scen) for sd in (3, 4, 5) for n in NT
             for sol in ("1x", "2x", "3x", "4x", "summer", "sum2x")
             for scen in ("vsp", "ev", "solar", "v2g")]
    print(f"MODESX3: {len(cells)} cells, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, sol, scen) in enumerate(cells):
        if idx % SH_K != SH_I or (n, sol, sd, scen) in done:
            continue
        fleet = rand_trips(3, n, sd, salt=50_000)
        inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, **sol_kwargs(sol))
        traction = float(sum(tr.energy for tr in inst.trips))
        r = solve(inst, scen, tl=120.0)
        if r is None:
            continue
        fleet_paid = 0.0
        if scen == "ev":
            fleet_paid = sum((c.fixed_cost - inst.c_v) / inst.c_g * round(x)
                             for c, x in zip(r["cols"], r["mip"].x) if x > 0.5)
        rows.append({"n_tasks": n, "sol": sol, "seed": sd, "scenario": scen,
                     "g_units": round(r["g_units"], 2), "traction_units": round(traction, 2),
                     "fleet_paid_units": round(fleet_paid, 2), "trucks": r["trucks"],
                     "batteries": r["batteries"], "gap_pct": round(r["gap"], 3)})
        save(rows, path)
        if idx % 40 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    FN = {"PACK2": pack2, "OUT3": out3, "END3": end3, "SCHED3X": sched3x,
          "MODESX3": modesx3}
    _known = {s.strip().upper() for s in FN}
    _bad = [s for s in STUDIES if s.strip().upper() not in _known]
    if _bad:
        sys.exit(f"unknown OVERNIGHT11_STUDIES entries: {_bad} -- known: {sorted(FN)}")
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        t1 = time.time(); FN[st]()
        print(f"-- {st} done in {(time.time() - t1) / 60:.1f} min --\n", flush=True)
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
