"""Divisibility audit for Corollary 1 (cor:lattice).

Checks, for every instance family on which the manuscript reports results,
whether G, rho, every task energy, every deadhead energy (dist*epd over all
ordered location pairs a != b; the DP creates a travel arc for every pair),
and the fixed boundary SoC (G under full recharge) are integer multiples of
delta (tolerance 1e-9 in model units, 1 unit = 100 kWh).

Also records what the frozen DP does with off-grid quantities:
  rate:      up = dn = floor(rho/step)              (restriction, conservative)
  traction:  int(round(x/step)) (nearest, banker's)  (can UNDER-count traction)
  capacity:  nL = round(G/step)+1                    (nearest)

Read-only: imports the frozen vendor and builders; writes only into this folder.
Run with:  python3 -B audit.py
"""
from __future__ import annotations
import glob, json, math, os, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNTIME = REPO / "experiments/opte_equal_mip_20261015/runtime"
VENDOR = RUNTIME / "frozen/vendor"
sys.dont_write_bytecode = True
sys.path.insert(0, str(VENDOR))
import numpy as np
import recreate_arxiv as RA

TOL = 1e-9
KWH = 100.0


def rand_trips(L, n, seed, windows=(6, 20), salt=20_000):   # verbatim overnight3.rand_trips
    rng = np.random.default_rng(salt + 1_000 * seed + 10 * L + n)
    out = []
    for _ in range(n):
        i = int(rng.integers(1, L + 1)); j = int(rng.integers(1, L + 1))
        while j == i:
            j = int(rng.integers(1, L + 1))
        out.append((i, j, int(rng.integers(windows[0], windows[1]))))
    return out


POOL = list(RA._COORDS) + [(0.75, 0.75), (-0.75, 0.75), (0.75, -0.75)]   # overnight3.POOL


def on(x, step):
    q = x / step
    return abs(q - round(q)) <= TOL


def check(G, rho, step, eta, epd, dist, task_E):
    dist = np.asarray(dist, dtype=float)
    L = dist.shape[0]
    dd = sorted({round(float(dist[a, b] * epd), 12) for a in range(L) for b in range(L) if a != b})
    tE = sorted({round(float(e), 12) for e in task_E})
    off_dd = [x for x in dd if not on(x, step)]
    off_t = [x for x in tE if not on(x, step)]
    r = {
        "step_kwh": step * KWH, "eta": eta,
        "G_kwh": G * KWH, "G_on": on(G, step),
        "rho_kwh": rho * KWH, "rho_on": on(rho, step),
        "dp_rate_kwh": math.floor((1 - eta) * rho / step + 0.0) * step * KWH,
        "task_kwh": [x * KWH for x in tE], "tasks_on": not off_t,
        "deadhead_kwh": [x * KWH for x in dd], "deadheads_on": not off_dd,
        "boundary_full_on": on(G, step),
        "off_task_dp_kwh": {f"{x*KWH:g}": int(round(x / step)) * step * KWH for x in off_t},
        "off_deadhead_dp_kwh": {f"{x*KWH:g}": int(round(x / step)) * step * KWH for x in off_dd},
    }
    r["all_on"] = r["G_on"] and r["rho_on"] and r["tasks_on"] and r["deadheads_on"]
    r["traction_on"] = r["tasks_on"] and r["deadheads_on"]
    r["corollary_applies"] = r["all_on"] and abs(eta) <= 1e-12
    under = [k for k, v in {**r["off_task_dp_kwh"], **r["off_deadhead_dp_kwh"]}.items() if v < float(k) - 1e-9]
    r["nearest_rounding_undercounts_kwh"] = under
    return r


def check_inst(inst, step=None):
    return check(inst.G, inst.rho, step or inst.soc_step, inst.eta, inst.energy_per_dist,
                 inst.dist, [t.energy for t in inst.trips])


def check_record(d):
    p = d.get("physical", d)
    return check(p["G"], p["rho"], p["soc_step"], p["eta"], p["energy_per_dist"], p["dist"],
                 [t["energy"] for t in p["trips"]])


def summarize(name, rows, claim, source):
    agg = {"family": name, "n_instances_checked": len(rows), "paper_claim": claim, "source": source}
    for k in ("G_on", "rho_on", "tasks_on", "deadheads_on", "boundary_full_on", "all_on", "corollary_applies"):
        vals = {r[k] for r in rows}
        agg[k] = (vals.pop() if len(vals) == 1 else "mixed")
    agg["steps_kwh"] = sorted({r["step_kwh"] for r in rows})
    agg["eta"] = sorted({r["eta"] for r in rows})
    agg["rho_kwh"] = sorted({r["rho_kwh"] for r in rows})
    agg["dp_rate_kwh"] = sorted({r["dp_rate_kwh"] for r in rows})
    agg["G_kwh"] = sorted({r["G_kwh"] for r in rows})
    agg["task_kwh"] = sorted({x for r in rows for x in r["task_kwh"]})
    agg["deadhead_kwh"] = sorted({x for r in rows for x in r["deadhead_kwh"]})
    agg["undercounts"] = sorted({x for r in rows for x in r["nearest_rounding_undercounts_kwh"]})
    return agg


def main():
    fams = []
    D = "~/Downloads/paper-rewrite 2/code"
    # 1. reference planning, delta=25 (overnight13/14 spine, fourarm, export, periodic, weather ...)
    rows = []
    for n in (4, 8, 20, 40, 60, 80, 100, 120, 200):
        for sd in range(10):
            for br in (RA.BREAKS, RA.BREAKS2):
                inst = RA.build_instance(3, 2.0, br, trip_list=rand_trips(3, n, sd, salt=50_000), pv_scale=2.0)
                inst.rho = 1.75; inst.soc_step = 0.25
                rows.append(check_inst(inst))
    fams.append(summarize("Reference planning (L=3, 200 kWh tasks), delta=25, eta=0", rows,
                          "line 846: step divides tasks, deadheads and 175 kWh -> corollary applies when eta=0",
                          f"{D}/overnight13.py, overnight14.py (build_instance(3,2.0,BREAKS*), soc_step=0.25)"))
    # 1b. one-factor arms at delta=25: G and rho
    rows = []
    for G in (3.5, 7.0, 10.5, 14.0):
        inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, 60, 0, salt=50_000)); inst.rho = 1.75
        inst.soc_step = 0.25; inst.G = G; rows.append(check_inst(inst))
    for rho in (0.5, 1.0, 1.75, 2.5):
        inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, 60, 0, salt=50_000)); inst.rho = rho
        inst.soc_step = 0.25; rows.append(check_inst(inst))
    fams.append(summarize("Planning one-factor arms at delta=25: G in {350,700,1050,1400}, rate 100-500 kW (spine25, pack4; NOT the Fig. 12 source)", rows,
                          "line 773: all steps divide G", f"{D}/overnight13.py spine25 (lines 395-433), pack4 (864-880)"))
    # 1c. planning eta>0 arms (corollary not claimed)
    rows = []
    for eta in (0.03, 0.05, 0.1, 0.15, 0.2, 0.3):
        inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, 60, 0, salt=50_000)); inst.rho = 1.75
        inst.soc_step = 0.25; inst.eta = eta; rows.append(check_inst(inst))
    fams.append(summarize("Planning loss arms eta>0, delta=25", rows, "line 854: result does not apply when eta>0",
                          f"{D}/overnight13.py spine25 eta arm"))
    # 2. ALIGN (56) and LATTICE (18)
    for step in (0.5, 0.25, 0.125):
        rows = []
        for sd in (0, 1):
            for n in (20, 60, 120, 200):
                for pv in (1.5, 2.5):
                    inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, n, sd, salt=50_000), pv_scale=pv)
                    inst.rho = 1.75; inst.soc_step = step; rows.append(check_inst(inst))
        fams.append(summarize(f"ALIGN/LATTICE discretization check, delta={step*KWH:g}, eta=0", rows,
                              "line 857 (16 matched delta=25/12.5 agree) and line 1850 (50->25 lowers LP 0.65-0.8%, <=2.2%)",
                              f"{D}/overnight13.py align (666-697); overnight4.py lattice_ladder (262-288)"))
    # 3. structured timing benchmarks Table 3 / Fig 2 / Table 5 structured rows
    rows = []
    for eps in (1.5, 2.0):
        for pts in range(2, 11):
            rows.append(check_inst(RA.build_instance(pts, eps, RA.SCAL)))
    fams.append(summarize("Structured timing benchmarks (Table 3, Fig. 2, Table 5 rows 1-12), delta=50, rho=50", rows,
                          "line 850: 50 kWh limit and matching 50 kWh step, corollary applies",
                          "frozen/vendor/recreate_arxiv.build_instance(pts, eps, SCAL) defaults"))
    # 4. random multi-location Table 4 / Table 5 random rows / Table 6 / Table 7 / Tables 20-22 originals
    rows = []
    for L in (4, 15):
        for n in (100, 200, 400, 600, 800, 1000):
            for sd in (0, 1):
                inst = RA.build_instance(L, 1.0, [(6, 20)], trip_list=rand_trips(L, n, 200 + sd), duration=1.0,
                                         coords_override=POOL[:L], stations="all", pv_scale=2.0)
                inst.rho = 1.75; rows.append(check_inst(inst))
    fams.append(summarize("Random multi-location (Table 4; Table 5 random rows; Tables 6-7), delta=50", rows,
                          "lines 847-848: rho=175 not divisible by 50; corollary does not apply",
                          f"{D}/overnight13.py diag2 (696-716); frozen/lp_scaling_instances.py; frozen/extension_instances.py"))
    # 5. charging-location study (Fig. 10 / App. B.5): stations_study.make and overnight3.u3_stations2
    rows = []
    for L in (4, 6, 8, 10, 12, 15):
        for n in (40, 80, 120, 160):
            inst = RA.build_instance(L, 1.0, [(6, 20)], trip_list=rand_trips(L, n, 3), duration=1.0,
                                     coords_override=POOL[:L], stations="all", pv_scale=2.0)
            inst.rho = 1.75; rows.append(check_inst(inst))
    fams.append(summarize("Charging-location study (Fig. 10, App. B.5; 3,456 solves), delta=50 (builder default)", rows,
                          "not identified as a 50 kWh study (lines 988-990, Table 10 caption)",
                          f"{D}/stations_study.py make (85-91); {D}/overnight3.py u3_stations2 (206-246) via solve(); neither sets soc_step"))
    # 6. timetable families: verbatim overnight10._tasks3 (FAM3), sched3 and theory cells
    FAM3 = {"uniform14": [(6, 20)], "uniform10": [(8, 18)],
            "siesta14": [(2, 9), (16, 23)], "siesta10": [(4, 9), (18, 23)],
            "midday6": [(9, 15)]}

    def tasks3(n, seed, fam):   # verbatim overnight10._tasks3 (lines 52-64)
        rng_loc = np.random.default_rng(120_000 + 1_000 * seed + n)
        rng_t = np.random.default_rng(140_000 + 1_000 * seed + n + 10_007 * list(FAM3).index(fam))
        wins = FAM3[fam]; out = []
        for _ in range(n):
            i = int(rng_loc.integers(1, 4)); j = int(rng_loc.integers(1, 4))
            while j == i:
                j = int(rng_loc.integers(1, 4))
            a, b = wins[int(rng_t.integers(0, len(wins)))]
            out.append((i, j, int(rng_t.integers(a, b))))
        return out
    rows = []
    for sd in (0, 1, 2):
        for n in (40, 80):
            for fam in FAM3:
                for pv in (1.5, 2.5):
                    inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=tasks3(n, sd, fam), pv_scale=pv)
                    inst.rho = 1.75; rows.append(check_inst(inst))
                inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=tasks3(n, sd, fam), pv_scale=2.5)
                inst.rho = 1.75; inst.energy_per_dist = 0.0; rows.append(check_inst(inst))   # theory(): epd=0
    fams.append(summarize("Timetable families (App. B.3, five families, 40/80 tasks; sched3 + theory), delta=50 (builder default)", rows,
                          "not identified as a 50 kWh study",
                          f"{D}/overnight10.py sched3 (82-101), theory (104-128), FAM3 (47-49) via overnight3.solve (RHO=1.75); no soc_step set"))
    # 6b. planning solar profile: 2023 selection + perfect-foresight benchmark (overnight10.stoch) and 2022 holdout
    for step, label, src in ((0.5, "Planning solar profile, 2023 selection and benchmark (Fig. 8), delta=50 (builder default)",
                              f"{D}/overnight10.py stoch (133-196) via overnight3.solve; no soc_step set"),
                             (0.25, "Planning solar profile, 2022 holdout (Table 16), delta=25",
                              f"{D}/overnight13.py holdout22 (ws/cand rows record soc_step 0.25)")):
        inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, 60, 0, salt=50_000))
        inst.rho = 1.75; inst.soc_step = step
        fams.append(summarize(label, [check_inst(inst)],
                              "2023 part not identified as a 50 kWh study" if step == 0.5 else "principal step",
                              src))
    # 6c. fuel budget (overnight11.end3 + overnight12.end4)
    rows = []
    for sd in (0, 1, 2):
        for n in (20, 60):
            for pv in (1.5, 2.5):
                inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, n, sd, salt=50_000), pv_scale=pv)
                inst.rho = 1.75; rows.append(check_inst(inst))
    fams.append(summarize("Fuel budget (Fig. 11), delta=50 (builder default)", rows, "not identified as a 50 kWh study",
                          f"{D}/overnight11.py end3 (133-157) via overnight3.solve; overnight12.py end4 (154-180) via _solve12; no soc_step set"))
    # 6d. pack size: Fig. 12 = overnight4.pack_sweep (G arms at rho=1.75, rho arms at G=7); overnight11.pack2 dense grid
    rows = []
    for sd in (0, 1):
        for n in (8, 20, 60, 120):
            for pv in (2.0, 4.0):
                for G, rh in [(G, 1.75) for G in (3.5, 7.0, 10.5, 14.0)] + [(7.0, r) for r in (0.5, 1.0, 2.5)]:
                    inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, n, sd, salt=90_000), pv_scale=pv)
                    inst.rho = rh; inst.G = G; rows.append(check_inst(inst))
    fams.append(summarize("Pack size (Fig. 12) and its rate arms, delta=50 (builder default)", rows,
                          "not identified as a 50 kWh study; line 773 (step divides G) holds",
                          f"{D}/overnight4.py pack_sweep (168-197) via _solve_custom (149-166); results/arxiv/overnight4_pack_s0of1.json; no soc_step set"))
    rows = []
    for sd in (0, 1, 2):
        for n in (8, 20, 60, 120, 200):
            for G in (3.5, 7.0, 10.5, 14.0):
                inst = RA.build_instance(3, 2.0, RA.BREAKS, trip_list=rand_trips(3, n, sd, salt=90_000), pv_scale=2.0)
                inst.rho = 1.75; inst.G = G; rows.append(check_inst(inst))
    fams.append(summarize("Pack x workload dense grid (Table 10 range 8-200 tasks), delta=50 (builder default)", rows,
                          "not identified as a 50 kWh study",
                          f"{D}/overnight11.py pack2 (69-89) via _solve_pack (49-66); no soc_step set"))
    # 6e. profile shift (App. B.3 line 1964): profile_robustness.run_cell, default task generator
    inst = RA.build_instance(3, 2.0, RA.BREAKS); inst.rho = 1.75
    fams.append(summarize("Profile shift by two hours (App. B.3), delta=50 (builder default)", [check_inst(inst)],
                          "not identified as a 50 kWh study",
                          f"{D}/profile_robustness.py run_cell (72-95), POINTS=3, EPS=2.0; no soc_step set"))
    # 7. saved instance records (Tables 8-9 planning population/direct, 17-22, plugs, etc.)
    groups = defaultdict(list)
    files = sorted(glob.glob(str(REPO / "experiments/**/instance.json"), recursive=True))
    files += sorted(glob.glob(str(RUNTIME / "inputs/*.json")))
    for f in files:
        if "/frozen/" in f:
            continue
        try:
            d = json.load(open(f))
            r = check_record(d)
        except Exception as e:  # not an instance record
            continue
        rel = os.path.relpath(f, REPO)
        parts = rel.split("/")
        depth = 4 if parts[1] == "opte_second_round" else 3
        key = "/".join(parts[:depth]) + f" [delta={r['step_kwh']:g}]"
        groups[key].append(r)
    saved = [summarize("saved: " + k, v, "", "instance.json records") for k, v in sorted(groups.items())]
    out = {"families": fams, "saved_record_groups": saved,
           "dp_rules": {"rate": "floor((1-eta)*rho/step) (pricing_truck.py:86-87)",
                        "task": "int(round(energy/step)) (pricing_truck.py:106)",
                        "deadhead": "int(round(dist*epd/step)) (pricing_truck.py:101)",
                        "levels": "round(G/step)+1 (pricing_truck.py:81)"}}
    (HERE / "audit_results.json").write_text(json.dumps(out, indent=1))
    hdr = "| family | delta kWh | G | rho (DP rate) | tasks | deadheads | full boundary | eta | corollary applies | n |"
    lines = [hdr, "|" + "---|" * 10]
    yn = lambda v: {True: "yes", False: "NO", "mixed": "mixed"}[v]
    for a in fams + saved:
        lines.append(f"| {a['family']} | {','.join(f'{x:g}' for x in a['steps_kwh'])} | {yn(a['G_on'])} | "
                     f"{yn(a['rho_on'])} ({','.join(f'{x:g}' for x in a['rho_kwh'])} -> {','.join(f'{x:g}' for x in a['dp_rate_kwh'])}) | "
                     f"{yn(a['tasks_on'])} | {yn(a['deadheads_on'])} | {yn(a['boundary_full_on'])} | "
                     f"{','.join(f'{x:g}' for x in a['eta'])} | {yn(a['corollary_applies'])} | {a['n_instances_checked']} |")
    (HERE / "audit_table.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
