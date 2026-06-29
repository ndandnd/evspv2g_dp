"""
Experiment driver: produces the deterministic figures/tables for the rewrite.
  (A) regime comparison (VSP / EVSP-Solar / EVSP-V2G): fuel and fleet vs #trips
  (B) submodular saturation: fossil fuel and batteries vs available solar (V2G)
  (C) column generation: warm vs cold iterations, and solve time vs instance size
Outputs go to results/.  Run: python3 experiments.py
"""
import os, time, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from instance import make_instance
from colgen import column_generation, summarize

OUT = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(OUT, exist_ok=True)
SEED = 7
COL = {"vsp": "#888888", "solar": "#e08020", "v2g": "#2E75B6"}
NAME = {"vsp": "VSP (ICE)", "solar": "EVSP-Solar", "v2g": "EVSP-V2G"}


def exp_modes(trip_sizes=(10, 20, 40)):
    rows = []
    for nt in trip_sizes:
        inst = make_instance(n_trips=nt, n_locations=3, eps=2.0, seed=SEED)
        for scen in ("vsp", "solar", "v2g"):
            res = column_generation(inst, scenario=scen, start="warm", do_milp=True)
            s = summarize(inst, res)
            rows.append({"trips": nt, "scenario": scen, **s,
                         "gap_pct": round((res["mip_obj"]-res["lp_obj"])/abs(res["mip_obj"])*100, 3)})
    json.dump(rows, open(os.path.join(OUT, "modes.json"), "w"), indent=2)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for scen in ("vsp", "solar", "v2g"):
        xs = [r["trips"] for r in rows if r["scenario"] == scen]
        fuel = [r["fuel_kwh"]/1000 for r in rows if r["scenario"] == scen]
        fleet = [r["trucks"] for r in rows if r["scenario"] == scen]
        ax[0].plot(xs, fuel, "-o", color=COL[scen], label=NAME[scen])
        ax[1].plot(xs, fleet, "-o", color=COL[scen], label=NAME[scen])
    ax[0].set_xlabel("number of trips"); ax[0].set_ylabel("daily fuel (MWh-equiv)")
    ax[0].set_title("Fuel use by regime"); ax[0].legend()
    ax[1].set_xlabel("number of trips"); ax[1].set_ylabel("trucks deployed")
    ax[1].set_title("Fleet size by regime"); ax[1].legend()
    fig.savefig(os.path.join(OUT, "exp_modes.png"), dpi=130)
    return rows


def exp_saturation(solar_mwh=(8, 11, 14, 17, 20, 23, 26), nt=20):
    rows = []
    for sm in solar_mwh:
        inst = make_instance(n_trips=nt, n_locations=3, eps=2.0, seed=SEED,
                             daily_solar_kwh=sm * 1000.0)
        res = column_generation(inst, scenario="v2g", start="warm", do_milp=True)
        s = summarize(inst, res)
        rows.append({"solar_mwh": sm, **s})
    json.dump(rows, open(os.path.join(OUT, "saturation.json"), "w"), indent=2)
    fig, ax1 = plt.subplots(figsize=(7, 4.3), constrained_layout=True)
    xs = [r["solar_mwh"] for r in rows]
    ax1.plot(xs, [r["fuel_kwh"]/1000 for r in rows], "-o", color="#c0392b", label="fossil fuel")
    ax1.set_xlabel("available daily solar (MWh)"); ax1.set_ylabel("fossil fuel (MWh-equiv)", color="#c0392b")
    ax1.axvline(14, ls=":", color="gray", lw=1)
    ax2 = ax1.twinx()
    ax2.plot(xs, [r["batteries"] for r in rows], "-s", color="#2E75B6", label="batteries")
    ax2.set_ylabel("batteries deployed", color="#2E75B6")
    ax1.set_title("Diminishing returns: fuel & storage vs available solar (EVSP-V2G)")
    fig.savefig(os.path.join(OUT, "exp_saturation.png"), dpi=130)
    return rows


def exp_colgen(trip_sizes=(10, 20, 40, 60)):
    rows = []
    for nt in trip_sizes:
        inst = make_instance(n_trips=nt, n_locations=3, eps=2.0, seed=SEED)
        rw = column_generation(inst, scenario="v2g", start="warm", do_milp=False)
        rc = column_generation(inst, scenario="v2g", start="cold", do_milp=False)
        rows.append({"trips": nt, "warm_iters": rw["iters"], "cold_iters": rc["iters"],
                     "warm_time": round(rw["time"], 2), "cold_time": round(rc["time"], 2),
                     "cols": rw["n_cols"]})
    json.dump(rows, open(os.path.join(OUT, "colgen.json"), "w"), indent=2)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    xs = [r["trips"] for r in rows]
    ax[0].plot(xs, [r["cold_iters"] for r in rows], "-o", color="#888", label="cold start")
    ax[0].plot(xs, [r["warm_iters"] for r in rows], "-o", color="#2E75B6", label="greedy warm start")
    ax[0].set_xlabel("number of trips"); ax[0].set_ylabel("CG iterations to converge")
    ax[0].set_title("Warm vs cold start"); ax[0].legend()
    ax[1].plot(xs, [r["warm_time"] for r in rows], "-o", color="#2E75B6")
    ax[1].set_xlabel("number of trips"); ax[1].set_ylabel("LP/CG solve time (s)")
    ax[1].set_title("Column-generation solve time")
    fig.savefig(os.path.join(OUT, "exp_colgen.png"), dpi=130)
    return rows


def exp_gantt(nt=18):
    from matplotlib.patches import Patch
    inst = make_instance(n_trips=nt, n_locations=3, eps=2.0, seed=SEED)
    res = column_generation(inst, scenario="v2g", start="warm", do_milp=True)
    mip, cols, x, T = res["mip"], res["cols"], res["mip"].x, inst.T
    rows = []
    k = 0
    for r in range(len(cols)):
        if x[r] > 0.5:
            k += 1
            rows.append((f"Truck {k}", cols[r].e * round(x[r])))
    batt = (mip.charge - mip.discharge) if mip.charge is not None else np.zeros(T)
    rows.append((f"Battery (x{int(round(mip.nb))})", batt))
    fig, (axd, ax) = plt.subplots(2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [1, 4]},
                                  constrained_layout=True, sharex=True)
    axd.bar(range(T), inst.Delta, color=["#f0c000" if d < 0 else "#cfcfcf" for d in inst.Delta])
    axd.axhline(0, color="k", lw=0.5); axd.set_ylabel("net demand\n(kWh)")
    axd.set_title("EVSP-V2G solution timeline (18 trips): charge/discharge per route")
    for i, (lab, e) in enumerate(rows):
        for t in range(T):
            if e[t] > 1e-6:
                c = "#2e9e3f" if inst.Delta[t] < 0 else "#333333"   # free (solar) vs paid charge
                ax.add_patch(plt.Rectangle((t - 0.5, i - 0.42), 1, 0.84, color=c))
            elif e[t] < -1e-6:
                ax.add_patch(plt.Rectangle((t - 0.5, i - 0.42), 1, 0.84, color="#c0392b"))  # discharge
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([l for l, _ in rows], fontsize=8)
    ax.set_xlim(-0.5, T - 0.5); ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlabel("hour of day"); ax.set_xticks(range(0, T, 2))
    ax.legend(handles=[Patch(color="#2e9e3f", label="free (solar) charge"),
                       Patch(color="#333333", label="paid charge"),
                       Patch(color="#c0392b", label="discharge")],
              ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.10), fontsize=8)
    fig.savefig(os.path.join(OUT, "exp_gantt.png"), dpi=130)
    return summarize(inst, res)


if __name__ == "__main__":
    t = time.time()
    print("modes:", exp_modes())
    print("saturation:", exp_saturation())
    print("colgen:", exp_colgen())
    print("gantt:", exp_gantt())
    print(f"total {time.time()-t:.1f}s; figures in results/")
