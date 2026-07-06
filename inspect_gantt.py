"""Replay every Gantt lane's state of charge and flag infeasible lanes.

Loads results/arxiv/overnight2_timeline.json, rebuilds each variant's instance
from its seed, and simulates each truck lane hour by hour: start FULL, apply
grid draw (charge) / injection (discharge) and task traction. Any lane whose
SoC leaves [0, G] is physically impossible (e.g. the pre-fix warm-start seeds
that charged before departure while already full).

Run: python3 inspect_gantt.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance
import overnight2 as O

tl = json.load(open(os.path.join("results", "arxiv", "overnight2_timeline.json")))
for v in tl:
    sd = v.get("seed", 5)
    fleet = O.sample_fleet(np.random.default_rng(sd), O.POINTS_DEF, 60, O.FULL_DAY)
    inst = build_instance(O.POINTS_DEF, 1.0, O.FULL_DAY, pv_scale=O.PV_DEF,
                          trip_list=fleet, duration=1.0)
    G = inst.G
    print(f"\nseed {sd} | {v['tag']} | trucks {v['trucks']} batteries {v['batteries']}")
    print(f"{'lane':>5} {'tasks':>6} {'chg_units':>9} {'dis_units':>9} {'SoC_min':>8} {'SoC_max':>8} {'feasible':>9}")
    for li, e in enumerate(v["lanes"]):
        e = np.array(e)
        ivs = v.get("lane_trips", [[]] * len(v["lanes"]))[li]
        soc = G; lo = hi = G
        # traction debited at each task start (approximation: task energy at start block)
        debit = {int(round(iv[0] * 2)): 1.0 for iv in ivs}     # eps=1.0 in this instance
        for t in range(len(e)):
            soc += max(e[t], 0.0) * (1 - inst.eta) + min(e[t], 0.0)
            soc -= debit.get(t, 0.0)
            lo, hi = min(lo, soc), max(hi, soc)
        ok = (lo >= -0.26) and (hi <= G + 0.26)               # deadheads ignored -> tolerance
        print(f"{li:5d} {len(ivs):6d} {float(np.maximum(e,0).sum()):9.2f} "
              f"{float(-np.minimum(e,0).sum()):9.2f} {lo:8.2f} {hi:8.2f} "
              f"{'OK' if ok else '** INFEASIBLE **':>9}")
