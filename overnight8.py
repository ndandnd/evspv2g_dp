"""
Overnight-8 SCHED: the retiming experiment (successor to the first
submission's breaks-vs-uniform table, redesigned as a controlled study).

Design: for each (n, seed), ONE set of tasks is drawn (locations and energies
fixed); only the TIMETABLE changes across four families:
  uniform : starts uniform over the working day (06-20)
  siesta  : starts in (04-09) and (18-23), leaving the midday surplus free
  night   : starts in (00-05) and (19-22)
  midday  : starts in (09-15), i.e. tasks OCCUPY the surplus window (worst case)
Because locations, energies, demand, and solar are identical across families,
gamma is IDENTICAL across families for each cell -- so any fuel/cost spread
across the rows is pure scheduling, a controlled counterexample to reading
gamma as the whole story, and the value of retiming can be plotted against
gamma (hypothesis: it peaks in the transition region, like V2G value itself).

Run:   OVERNIGHT8_STUDIES="SCHED" OVERNIGHT8_SHARD="i/K" python3 overnight8.py
"""
from __future__ import annotations
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from overnight3 import ckpt, save, solve

STUDIES = os.environ.get("OVERNIGHT8_STUDIES", "SCHED").split(",")
SH_I, SH_K = (int(x) for x in os.environ.get("OVERNIGHT8_SHARD", "0/1").split("/"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "arxiv")

FAMILIES = {"uniform": [(6, 20)], "siesta": [(4, 9), (18, 23)],
            "night": [(0, 5), (19, 22)], "midday": [(9, 15)]}


def _tasks(n, seed, sched):
    """Locations fixed by (n, seed); start times drawn per schedule family
    from an independent stream so families share the same task geography."""
    rng_loc = np.random.default_rng(120_000 + 1_000 * seed + n)
    rng_t = np.random.default_rng(130_000 + 1_000 * seed + n
                                  + 10_007 * list(FAMILIES).index(sched))
    wins = FAMILIES[sched]
    out = []
    for _ in range(n):
        i = int(rng_loc.integers(1, 4)); j = int(rng_loc.integers(1, 4))
        while j == i:
            j = int(rng_loc.integers(1, 4))
        a, b = wins[int(rng_t.integers(0, len(wins)))]
        out.append((i, j, int(rng_t.integers(a, b))))
    return out


def sched():
    rows, path = ckpt(f"overnight8_sched_s{SH_I}of{SH_K}.json")
    done = {(r["sched"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]) for r in rows}
    cells = [(sd, n, pv, sc) for sd in (0, 1, 2) for n in (20, 60, 120)
             for pv in (1.0, 1.5, 2.0, 2.5, 3.0) for sc in FAMILIES]
    print(f"SCHED: {len(cells)} cells x 2, shard {SH_I}/{SH_K} ({len(rows)} done)", flush=True)
    for idx, (sd, n, pv, sc) in enumerate(cells):
        if idx % SH_K != SH_I:
            continue
        fleet = _tasks(n, sd, sc)
        inst0 = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
        surplus = float(np.maximum(-inst0.Delta, 0.0).sum())
        traction = float(sum(tr.energy for tr in inst0.trips))
        base = {"sched": sc, "pv": pv, "n_tasks": n, "seed": sd,
                "surplus_mwh": round(surplus / 10, 2),
                "traction_mwh": round(traction / 10, 2),
                "ratio": round(surplus / max(traction, 1e-9), 3)}
        for scen in ("solar", "v2g"):
            if (sc, pv, n, sd, scen) in done:
                continue
            inst = build_instance(3, 2.0, BREAKS, trip_list=fleet, pv_scale=pv)
            r = solve(inst, scen, tl=120.0)
            if r is None:
                rows.append({**base, "scenario": scen, "feasible": False})
            else:
                rows.append({**base, "scenario": scen, "feasible": True,
                             "total": round(r["total"], 1),
                             "g_units": round(r["g_units"], 2),
                             "trucks": r["trucks"], "batteries": r["batteries"],
                             "gap_pct": round(r["gap"], 3)})
            save(rows, path)
        if idx % 15 == 0:
            print(f"  [{idx + 1}/{len(cells)}, {len(rows)} rows]", flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    for st in [s.strip().upper() for s in STUDIES]:
        if st == "SCHED":
            sched()
    print(f"all done in {(time.time() - t0) / 3600:.2f} h")
