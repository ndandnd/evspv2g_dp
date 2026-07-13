# %% [markdown]
# # Section-8 gallery — figures, tables, captions (draft)
#
# Run this file **cell by cell in VSCode** (Shift+Enter on each `# %%` cell:
# figures appear inline, tables render, captions follow each item) — or as a
# plain script (`python3 section8_gallery.py`), which additionally writes
# `results/figures/fig_8_*.png` and `results/figures/GALLERY.md`.
#
# Reading order = the Section-8 narrative:
#   8.1 Method: DP pricing does the MILP's job, 3 orders of magnitude faster
#   8.2 Reproduction & the free-energy artifact
#   8.3 Deployment conditions: tiers, the R-rule, robustness

# %% setup: imports, reference constants, display helpers
from __future__ import annotations
import os, sys, json
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
ARX = os.path.join(ROOT, "results", "arxiv")
FREE = os.path.join(ROOT, "results", "arxiv_free")
FIG = os.path.join(ROOT, "results", "figures")
os.makedirs(FIG, exist_ok=True)

INTERACTIVE = "ipykernel" in sys.modules          # VSCode interactive / Jupyter
try:
    from IPython.display import display, Markdown
    def emit(md: str):
        display(Markdown(md)) if INTERACTIVE else print("\n" + md + "\n")
except ImportError:
    def emit(md: str):
        print("\n" + md + "\n")

import matplotlib
if not INTERACTIVE:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

# consistent print-size typography across every figure (reviewer request):
# legend/tick text near body-font size at final print scale
plt.rcParams.update({
    "font.size": 12, "axes.titlesize": 12, "axes.labelsize": 11.5,
    "legend.fontsize": 10.5, "xtick.labelsize": 10.5, "ytick.labelsize": 10.5,
})


def finish(fig, fname: str):
    """Save the figure; show inline when interactive, close when scripted."""
    fig.savefig(os.path.join(FIG, fname), dpi=140)
    root, ext = os.path.splitext(fname)
    if ext.lower() == ".png":
        # vector sibling for journal submission (Springer asks for vector art)
        fig.savefig(os.path.join(FIG, root + ".pdf"))
    if INTERACTIVE:
        plt.show()
    else:
        plt.close(fig)


# ---------- fixed reference numbers (sources noted) ----------
# Original paper, Tables 3-4 (scalability of the MILP-pricing approach):
ORIG_SCAL = {"450_e20": dict(time_s=29722, gap=0.71, cols=45906),
             "280_e15": dict(time_s=21433, gap=0.94, cols=49559),
             "pricing_share": ">95% (99.95% at 450 tasks)"}
# Original paper, Table 2 (eps=2.5, V2G; fuel gallons / trucks, as published):
ORIG_T2 = {(20, "breaks"): (-158.59, 12.33), (20, "uniform"): (-128.28, 12.00),
           (60, "breaks"): (-60.61, 30.67), (60, "uniform"): (-29.29, 25.67),
           (120, "breaks"): (-57.58, 62.00), (120, "uniform"): (-6.06, 55.00)}
# Head-to-head vs a fresh run of the original code (original_headtohead.py):
H2H = dict(orig=295.00, ours_slip=296.50, ours_intended=237.10)
# Matched-granularity LP equivalence (three implementations):
E1 = dict(cases=(70.0, 80.0, 78.0), ladder=(80, 110, 140, 152.8571, 170))
# CBC vs Gurobi to a 1% gap on shared pools (solver_compare, gap-target run):
SOLVER = {600: (27127, 29.6), 1000: (3043, 8.4)}
BASELINE_KWH = 16900.0   # base fossil at solar_mult=7 (169 units x 100 kWh)
GAL = 100.0 / 33.0       # original code's kWh->gallon equivalence, per unit

GALLERY = ["# Section 8 gallery -- figures, tables, captions (draft)\n",
           "Read top to bottom: this is the narrative order of the computational study.\n"]
CAPTIONS: list[tuple[str, str]] = []


def load(dirpath, name):
    p = os.path.join(dirpath, name)
    if not os.path.exists(p):
        print(f"  [skip] missing {os.path.relpath(p, ROOT)}")
        return None
    return json.load(open(p))


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def caption(label, text):
    CAPTIONS.append((label, text))
    md = f"**{label}.** {text}"
    emit(md)
    GALLERY.append(md + "\n")


def table(label_md):
    emit(label_md)
    GALLERY.append(label_md)


print("data dirs:", os.path.relpath(ARX, ROOT), "|", os.path.relpath(FREE, ROOT))

# %% [markdown]
# ## 8.1 Method: DP pricing replaces MILP pricing

# %% Table 8.1 -- recreating the original scalability study
GALLERY.append("\n## 8.1 Method: DP pricing replaces MILP pricing\n")
e20 = load(ARX, "exp5_scalability_eps2.0.json")
e15 = load(ARX, "exp5_scalability_eps1.5.json")
rows = [["450 tasks, eps=2.0", f"{ORIG_SCAL['450_e20']['time_s']:,} s (8.3 h), gap {ORIG_SCAL['450_e20']['gap']}%",
         "--", f"{ORIG_SCAL['450_e20']['cols']:,} columns"]]
if e20:
    r = next((r for r in e20 if r["trips"] == 450), None)
    if r:
        rows[0][2] = f"{r['cg_s'] + r.get('milp_s', 0):.0f} s, gap {r['gap_pct']}%"
        rows[0][3] += f" vs {r['cols']:,}"
rows.append(["280 tasks, eps=1.5", f"{ORIG_SCAL['280_e15']['time_s']:,} s, gap {ORIG_SCAL['280_e15']['gap']}%", "--", ""])
if e15:
    r = next((r for r in e15 if r["trips"] == 280), None)
    if r:
        rows[1][2] = f"{r['cg_s'] + r.get('milp_s', 0):.1f} s, gap {r['gap_pct']}%"
rows.append(["pricing share of runtime", ORIG_SCAL["pricing_share"], "25-50% (master is now the bottleneck)", ""])
rows.append(["full 5-experiment suite", "hours per instance", "~95 s total", ""])
table(md_table(["instance", "original (MILP pricing, Gurobi)", "this work (DP pricing, open-source)", "notes"], rows))
caption("Table 8.1",
    "Recreating the original scalability study under the revised model. The labeling-DP "
    "pricing oracle solves the same instances three orders of magnitude faster on "
    "open-source solvers, with tighter integrality gaps and ~30x fewer columns; the "
    "runtime bottleneck moves from pricing (>95% in the original) to the master LP. "
    "The original's reported slowdown for the relaxed energy level (eps=1.5) disappears: "
    "the DP's cost is fixed by the state space, not by route feasibility.")

# %% Table 8.2 -- the equivalence chain
rows = [
    ["implementation equivalence", "three independent codebases, matched-granularity masters",
     f"LP optima identical to the digit: {E1['cases']} and ladder {E1['ladder']} (note the fractional 152.8571)"],
    ["LP-solver independence", "HiGHS vs Gurobi on shared pools, 160-1000 tasks", "identical LP objectives in every instance"],
    ["per-iteration checks", "DP reduced cost vs master formula; battery DP vs exact LP; Bellman-Ford",
     "<1e-6 each iteration; 2.3e-13; exact"],
    ["head-to-head vs original code", "fresh Gurobi run of the original repo, aligned master",
     f"{H2H['orig']:.2f} vs {H2H['ours_slip']:.2f} = 0.5% (the original's final master prices batteries at bus cost; "
     f"with the intended battery cost our model gives {H2H['ours_intended']:.2f})"],
    ["CBC vs Gurobi (practical note)", "same pools, 1% gap target",
     f"600 tasks: {SOLVER[600][0]:,} s vs {SOLVER[600][1]} s; 1000 tasks: {SOLVER[1000][0]:,} s vs {SOLVER[1000][1]} s "
     "-- commercial solver optional, affects waiting time only"],
]
table(md_table(["evidence", "test", "result"], rows))
caption("Table 8.2",
    "The equivalence chain: given the same master problem (same objective, same "
    "constraints), column generation with the DP oracle reaches the same LP optimum as "
    "MILP pricing -- exactly where every detail is matched, and to 0.5% against a fresh "
    "run of the original code once its final-master battery-cost slip is accounted for. "
    "The LP value is the heuristic-free comparison; integer solutions and side metrics "
    "are degenerate near the optimum and legitimately differ between ~1%-gap runs.")

# %% Figure 8.1 -- scalability + where the time goes
if e20:
    # two panels (print readability): CG time for both families on the left,
    # pricing share on the right
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.6), constrained_layout=True)
    for data, c, lab in ((e20, "#2E75B6", "benchmark, 200 kWh/task (laptop)"),
                         (e15 or [], "#e08020", "benchmark, 150 kWh/task (laptop)")):
        if data:
            xs = [r["trips"] for r in data]
            ax[0].plot(xs, [r["cg_s"] for r in data], "-o", color=c, label=lab)
            ax[1].plot(xs, [r["pricing_pct"] for r in data], "-o", color=c, label=lab)
    wc1 = load(ARX, "overnight2_warmcold.json")
    if wc1:
        ns1 = sorted({r["n_tasks"] for r in wc1})
        tm1 = [float(np.mean([r["time_s"] for r in wc1
                              if r["n_tasks"] == n and r["start"] == "warm"])) for n in ns1]
        ax[0].plot(ns1, tm1, "-s", color="#16a085", ms=4, lw=1.7,
                   label="random fleets, multi-station (cluster)")
    ax[0].set_xlabel("tasks"); ax[0].set_ylabel("column-generation time (s)")
    ax[0].legend(); ax[0].set_title("(a) column-generation time")
    ax[1].set_xlabel("tasks"); ax[1].set_ylabel("pricing share of CG time (%)")
    ax[1].set_ylim(0, 100); ax[1].legend(); ax[1].set_title("(b) where the time goes")
    finish(fig, "fig_8_1_scalability.png")
    GALLERY.append("\n![fig 8.1](fig_8_1_scalability.png)\n")
    caption("Figure 8.1",
        "Column-generation solve time (left) and the share of it spent in pricing (right) "
        "on the original instance family, 10-450 tasks. With the labeling DP, pricing never "
        "exceeds half the (seconds-scale) runtime; in the original MILP-pricing "
        "implementation it exceeded 95% of an hours-scale runtime. The method's bottleneck "
        "becomes the restricted master LP -- exactly the component that Proposition 2's "
        "continuous-energy result keeps small. The teal series extends the picture to "
        "1000 tasks with no additional runs, reusing the warm-start ladder of Fig 8.10 "
        "(random-fleet family, V2G at 2x solar, pure CG without enrichment, cluster "
        "hardware -- hence the separate label): even at 1000 tasks the full column "
        "generation completes in under ten minutes, and a log-log fit across the ladder "
        "puts the empirical growth near n^2.")

# %% [markdown]
# ## 8.2 Reproduction and the free-energy artifact

# %% Table 8.3 -- original Table 2 | DP free | DP cyclic
GALLERY.append("\n## 8.2 Reproduction and the free-energy artifact\n")
ex2c = load(ARX, "exp2_scheduling.json")
ex2f = load(FREE, "exp2_scheduling.json")
rows = []
for (trips, sched), (og, ot) in sorted(ORIG_T2.items()):
    rf = next((r for r in (ex2f or []) if r["trips"] == trips and r.get("schedule") == sched), None)
    rc = next((r for r in (ex2c or []) if r["trips"] == trips and r.get("schedule") == sched), None)
    f_gal = f"{(rf['fuel_kwh'] - BASELINE_KWH) / 100 * GAL:8.1f} / {rf['trucks']}t+{rf['batteries']}b" if rf else "--"
    c_gal = f"{(rc['fuel_kwh'] - BASELINE_KWH) / 100 * GAL:8.1f} / {rc['trucks']}t+{rc['batteries']}b" if rc else "--"
    rows.append([trips, sched, f"{og} / {ot}t", f_gal, c_gal])
table(md_table(["tasks", "schedule", "original (published)", "DP, free start", "DP, cyclic (revised)"], rows))
rf3 = load(ARX, "regime_fuel.json")
if rf3:
    rows2 = []
    for r in rf3:
        if r["regime"] == "v2g":
            gal = (r["g_units"] - r["baseline_units"]) * GAL
            rows2.append([f"{r['surplus_mwh']} MWh/day", f"{gal:+8.1f}", r["trucks"], r["batteries"]])
    table("**...and the cyclic model exports honestly once solar grows** "
          "(V2G, 60 tasks, same gallons metric):\n\n"
          + md_table(["solar surplus", "fuel (gal)", "trucks", "batteries"], rows2))
caption("Table 8.3",
    "The original's Table 2 (fuel in gallons; negative = net energy export) next to this "
    "implementation run in the original's free-start setting and in the revised cyclic "
    "model. Free start reproduces the original's phenomena -- net export and stationary "
    "batteries -- because each vehicle's initial charge is free energy; the cyclic model "
    "prices that energy and the export vanishes. Every level difference between the "
    "columns is attributable to this single modeling choice (plus the original's "
    "documented final-master battery-cost slip). The companion table shows the "
    "honest counterpart of the original's net export: keep the cyclic constraint "
    "and grow the solar instead -- at 2x the fleet already exports (-36 gal/day) "
    "and at 3x it displaces the ENTIRE base fossil generation (-446 gal/day), "
    "every kWh of it paid for through the power balance.")

# %% Table 8.4 -- cyclic export grid in OUR settings (tasks x solar)
eg = load(ARX, "overnight2_export.json")
if eg:
    pvs = sorted({r["pv"] for r in eg})
    sur = {pv: next(r["surplus_mwh"] for r in eg if r["pv"] == pv) for pv in pvs}
    hdr = ["tasks \\ surplus"] + [f"{sur[pv]:.1f} MWh/d" for pv in pvs]
    rows4 = []
    for n in sorted({r["n_tasks"] for r in eg}):
        row = [n]
        for pv in pvs:
            rr = next((x for x in eg if x["n_tasks"] == n and x["pv"] == pv), None)
            if rr is None:
                row.append("--")
            else:
                star = "*" if (rr.get("baseline_mwh") and
                               rr["incr_mwh"] <= -0.98 * rr["baseline_mwh"]) else ""
                row.append(f"{rr['gal']:+.0f}{star}")
        rows4.append(row)
    table("**Fleet-attributable fossil fuel (gallons/day; negative = net export). "
          "Revised cyclic model, planning prices, V2G:**\n\n" + md_table(hdr, rows4))
    caption("Table 8.4",
        "The revised paper's own export table -- no free energy, no anchoring to the "
        "original's instances: fleet-attributable fossil (total generation minus the "
        "no-fleet baseline, in the gallons metric) for task counts 20-200 against solar "
        "surplus levels, all under the cyclic model at planning prices. The sign "
        "boundary traces the R-rule diagonally through the grid: a small fleet exports "
        "at modest solar while a large fleet needs abundant solar, because export "
        "begins where the surplus outruns the fleet's own charging appetite. Starred "
        "entries: fossil generation driven literally to zero (full displacement -- the "
        "zero-touching curves of Fig. 8.6).")
# %% Figure 8.2 -- fossil energy by regime as solar grows (cyclic, honest accounting)
rf = load(ARX, "regime_fuel.json")
if rf:
    ICE_EFF_SHOW = 3.3          # drivetrain convention for the VSP bars (1.0 = equal-energy)
    pvs = sorted({r["pv"] for r in rf})
    def _incr(r):
        if r["regime"] == "vsp":
            return ICE_EFF_SHOW * r["traction_units"] / 10.0
        if r["regime"] == "ev":
            return r["fleet_paid_units"] / 10.0
        return (r["g_units"] - r["baseline_units"]) / 10.0
    fig, ax = plt.subplots(figsize=(8.5, 4.6), constrained_layout=True)
    W = 0.2
    NAMES = {"vsp": "VSP (ICE)", "ev": "EVSP (flat tariff)", "solar": "EVSP-Solar", "v2g": "EVSP-V2G"}
    COLS = {"vsp": "#888888", "ev": "#7d3c98", "solar": "#e08020", "v2g": "#2E75B6"}
    tbl_rows = []
    for i2, reg in enumerate(("vsp", "ev", "solar", "v2g")):
        xs, ys = [], []
        for k2, pv in enumerate(pvs):
            r = next((x for x in rf if x["pv"] == pv and x["regime"] == reg), None)
            if r:
                xs.append(k2 + (i2 - 1.5) * W); ys.append(_incr(r))
        ax.bar(xs, ys, W * 0.95, label=NAMES[reg], color=COLS[reg])
        for k2, pv in enumerate(pvs):
            r = next((x for x in rf if x["pv"] == pv and x["regime"] == reg), None)
            if r:
                tbl_rows.append([f"{r['surplus_mwh']} MWh surplus", NAMES[reg], f"{_incr(r):+.1f}",
                                 r["trucks"], r["batteries"]])
    ax.axhline(0, color="k", lw=0.9)
    for k2, pv in enumerate(pvs):                     # full-displacement floor: -(no-fleet fossil)
        r0 = next(x for x in rf if x["pv"] == pv)
        floor = -r0["baseline_units"] / 10.0
        ax.hlines(floor, k2 - 0.45, k2 + 0.45, colors="#c0392b", ls="--", lw=1.2,
                  label=("full displacement of base fossil (floor)" if k2 == 0 else None))
    labels = []
    for pv in pvs:
        r0 = next(x for x in rf if x["pv"] == pv)
        labels.append(f"{r0['surplus_mwh']} MWh/day\nsurplus")
    ax.set_xticks(range(len(pvs))); ax.set_xticklabels(labels)
    ax.set_ylabel("fleet-attributable fossil energy (MWh/day)\n(negative = fleet REDUCES base fossil)")
    ax.set_title("fossil energy by regime as solar grows (cyclic model, ICE at 3.3x thermal)")
    ax.legend(loc="upper right")
    finish(fig, "fig_8_2_regime_fuel.png")
    GALLERY.append("\n![fig 8.2](fig_8_2_regime_fuel.png)\n")
    table(md_table(["solar surplus", "regime", "incremental fossil (MWh)", "trucks", "batteries"], tbl_rows))
    caption("Figure 8.2 (and table)",
        "Fossil energy attributable to the fleet -- total generation minus the no-fleet "
        "baseline -- by regime and solar level, under the honest cyclic model with the "
        "measured 3.3x ICE drivetrain convention. At scarce solar the four regimes are "
        "ordered by efficiency alone; as the surplus grows, the solar step first "
        "erases the EV fleet's own fossil draw, and V2G then turns the fleet NEGATIVE: "
        "the vehicles displace base-load fossil they never consumed, an honest, "
        "fully-paid-for analogue of the original paper's net export. The flat-tariff "
        "EVSP column isolates how much of the electric fleet's advantage is drivetrain "
        "efficiency versus microgrid coupling.")

# %% [markdown]
# ## 8.3 Deployment conditions

# %% Figure 8.3 -- the technology ladder and its marginal values
GALLERY.append("\n## 8.3 Deployment conditions\n")
tt = load(ARX, "tech_tiers.json")
if tt:
    sweep = sorted([r for r in tt if r.get("ev_premium") == 1.5 and r.get("ice_eff") == 3.3
                    and r.get("v2g_total") is not None and r.get("trips") == 60],
                   key=lambda r: r["ratio"])
    if sweep:
        xs = [r["ratio"] for r in sweep]
        fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.4), constrained_layout=True)
        for tier, c, lab in (("vsp", "#888888", "VSP (ICE)"), ("ev", "#7d3c98", "EVSP (flat tariff)"),
                             ("solar", "#e08020", "EVSP-Solar"), ("v2g", "#2E75B6", "EVSP-V2G")):
            ax[0].plot(xs, [r[f"{tier}_total"] for r in sweep], "-o", color=c, label=lab)
        ax[0].set_xlabel("R = daily solar surplus / fleet traction"); ax[0].set_ylabel("total daily cost ($)")
        ax[0].legend(); ax[0].set_title("total cost by technology tier")
        for key, c, lab in (("electrify_value", "#6d6d6d", "electrify (VSP -> EVSP)"),
                            ("solar_value", "#0e9594", "+ solar (EVSP -> EVSP-Solar)"),
                            ("v2g_value", "#b5179e", "+ V2G (EVSP-Solar -> EVSP-V2G)")):
            ax[1].plot(xs, [r[key] for r in sweep], "--s", color=c, label=lab, ms=5)
        ax[1].axhline(0, color="k", lw=0.7)
        ax[1].set_xlabel("R = daily solar surplus / fleet traction"); ax[1].set_ylabel("marginal value ($/day)")
        ax[1].legend(); ax[1].set_title("marginal value of each step")
        finish(fig, "fig_8_3_tiers.png")
        GALLERY.append("\n![fig 8.3](fig_8_3_tiers.png)\n")
        caption("Figure 8.3",
            "The technology ladder VSP -> EVSP (flat tariff) -> EVSP-Solar -> "
            "EVSP-V2G (60 tasks, EV truck "
            "premium 1.5x, drivetrain efficiency 3.3x, fuel $0.40/kWh). Left: total daily cost "
            "by tier as the solar surplus grows. Right: the three marginal values are nearly "
            "separable -- electrification's value is flat in R (it scales with fuel burned), "
            "the solar step (coordinating charging into the midday surplus) is worth money from "
            "the first surplus kWh and saturates once "
            "the fleet's traction is covered (R ~ 1), and V2G switches on near R ~ 1 and keeps "
            "growing where the solar step saturates: bidirectionality is what monetizes "
            "surplus beyond the fleet's own needs.")

# %% Figure 8.4 -- when does electrification pay? (mechanism + fleet distribution)
import glob as _glob
fleets84 = []
for _p in _glob.glob(os.path.join(ARX, "overnight2_fig84_s*.json")):
    fleets84 += json.load(open(_p))
if tt:
    sens = [r for r in tt if r.get("pv") == 2.0 and r.get("points") == 3 and "electrify_value" in r]
    prems = sorted({r["ev_premium"] for r in sens})
    effs = sorted({r["ice_eff"] for r in sens})
    if len(prems) >= 2 and len(effs) >= 2:
        fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.6), constrained_layout=True)
        for a_ in ax:
            for xg in (2.5, 3.5):
                a_.axvline(xg, ls=":", lw=0.9, color="#5f8f5f")
        ax[0].text(3.0, 0.965, "measured heavy-duty EVs", ha="center", va="top",
                   transform=ax[0].get_xaxis_transform(), fontsize=10.5, color="#4d774d")
        eff_grid = np.linspace(1.0, 3.6, 50)
        CPRE = {1.0: "#2E75B6", 1.5: "#e08020", 2.0: "#c0392b"}
        for prem in prems:
            c = CPRE.get(prem, "#555555")
            prpts = sorted([(r["ice_eff"], r["electrify_value"]) for r in sens if r["ev_premium"] == prem])
            (x1, y1), (x2, y2) = prpts[0], prpts[-1]
            slope = (y2 - y1) / (x2 - x1); a0 = y1 - slope * x1
            ax[0].plot(eff_grid, a0 + slope * eff_grid, color=c, lw=1.8,
                       label=f"EV truck {prem:.1f}x ICE cost (${prem*45:.0f}/day)")
            ax[0].scatter([p[0] for p in prpts], [p[1] for p in prpts], color=c, zorder=3, s=28)
            ax[0].scatter([-a0 / slope], [0], marker="D", color=c, zorder=4, s=42)
        ax[0].axhline(0, color="k", lw=0.9)
        ax[0].set_xlabel("kWh of diesel an ICE burns per kWh an EV uses\n(1x = equal-energy bookkeeping)")
        ax[0].set_ylabel("$ saved per day by electrifying")
        ax[0].set_title("(a) one fleet: an exact line; diamonds = break-even")
        ax[0].legend(loc="upper left", fontsize=10)
        if fleets84:
            CUSD = {0.0: "#2E75B6", 22.5: "#e08020", 45.0: "#c0392b"}
            for pu, c in CUSD.items():
                v = [r[f"breakeven_prem{pu}"] for r in fleets84 if f"breakeven_prem{pu}" in r]
                if v:
                    ax[1].hist(v, bins=24, color=c, alpha=0.45,
                               label=f"{1 + pu / 45:.1f}x ICE: mean {np.mean(v):.2f}, "
                                     f"p95 {np.percentile(v, 95):.2f}")
            ax[1].text(3.0, 0.965, "measured heavy-duty EVs", ha="center", va="top",
                       transform=ax[1].get_xaxis_transform(), fontsize=10.5, color="#4d774d")
            ax[1].set_xlim(1.0, 3.6)
            ax[1].set_xlabel(f"break-even efficiency across {len(fleets84)} randomized fleets")
            ax[1].set_ylabel("number of fleets")
            ax[1].set_title("(b) all fleets break even left of reality")
            ax[1].legend(fontsize=10, loc="upper right")
        finish(fig, "fig_8_4_electrify.png")
        GALLERY.append("\n![fig 8.4](fig_8_4_electrify.png)\n")
        caption("Figure 8.4",
            "The electrification decision. Left (mechanism, one fleet): fuel enters the "
            "objective linearly, so the value of replacing ICE trucks with plain EVs is an "
            "exact straight line in the drivetrain-efficiency ratio -- how many kWh of "
            "diesel an ICE burns to do the work an EV does on one kWh (an engine-physics "
            "number; nothing to do with solar). Diamonds mark break-even. Right "
            "(robustness): the break-even distribution across 240 randomized fleets -- "
            "30-120 tasks, heterogeneous 50-250 kWh duties, breaks or full-day schedules "
            "-- at EV daily costs of 1.0x / 1.5x / 2.0x the ICE truck's (the ICCT reports "
            "battery-electric truck prices at 1.3-2.4x diesel, so the sampled range is "
            "realistic). Means 1.33/1.47/1.60, "
            "95th percentiles 1.48/1.67/1.88, single worst fleet 1.97: the ENTIRE "
            "distribution lies below the measured 2.5-3.5x band (green), so electrification "
            "pays for every sampled fleet under honest energy accounting -- and never pays "
            "under the equal-energy convention (1x). The solar profile contributes zero "
            "width by construction (both regimes are solar-blind; verified to the cent).")
# %% Figure 8.5 -- THE money figure: one curve, no special treatment (option b)
pg = load(ARX, "planning_grid.json") or []
sl = load(ARX, "scale_ladder.json") or []
pr = load(ARX, "profile_robustness.json") or []
cs = load(ARX, "collapse_sweep.json") or []
se = load(ARX, "solar_ensemble.json") or []
ov = load(ARX, "overnight_sweep.json") or []
def _basep(r):
    return (r.get("cg"), r.get("cb"), r.get("rho")) == (40.0, 36.0, 1.75)
design = [(r["ratio"], r["v2g_vs_solar_pct"]) for r in pg if _basep(r) and "v2g_vs_solar_pct" in r]
design += [(r["ratio"], r["v2g_vs_solar_pct"]) for r in sl if "v2g_vs_solar_pct" in r]
design += [(r["ratio"], r["v2g_vs_solar_pct"]) for r in pr if "v2g_vs_solar_pct" in r]
design += [(r["ratio"], r["v2g_vs_solar_pct"]) for r in cs if "v2g_vs_solar_pct" in r]
# overnight sweep: base charge rate only (100/200 kW strata belong to the rate-family analysis)
design += [(r["ratio"], r["v2g_vs_solar_pct"]) for r in ov
           if r.get("rho") == 1.75 and "v2g_vs_solar_pct" in r]
import glob as _glob5
for _p in _glob5.glob(os.path.join(ARX, "overnight2_highR_s*.json")):
    design += [(r["ratio"], r["v2g_vs_solar_pct"]) for r in json.load(open(_p))
               if "v2g_vs_solar_pct" in r]
weather = [(r["ratio"], r["v2g_vs_solar_pct"]) for r in se if "v2g_vs_solar_pct" in r]
if len(design) >= 10:
    fig, ax = plt.subplots(figsize=(8.4, 5.0), constrained_layout=True)
    ax.axhspan(-3, 2, color="#fdf2e3", zorder=0)
    # annotation INSIDE the shaded band, left side, print-size font (the gamma=1
    # marker lives at the top of its own line, so the two can no longer collide)
    ax.text(0.015, -2.55, "shaded: below the enablement break-even\n(gamma* ~ 0.31-0.35; see text)",
            ha="left", va="bottom", fontsize=11, color="#a07020",
            transform=ax.get_yaxis_transform())
    xs_a = np.array([p[0] for p in sorted(design)]); ys_a = np.array([p[1] for p in sorted(design)])
    ax.set_xscale("log")                       # the action spans R ~ 0.05 to ~70
    ax.scatter(xs_a, ys_a, color="#9aa7b5", s=16, alpha=0.8,
               label=f"{len(design)} hypothetical bases\n(20-560 tasks; varied duties, PV, profiles)")
    if weather:
        ax.scatter([p[0] for p in weather], [p[1] for p in weather], marker="^", s=34,
                   color="#2E75B6", label=f"one base, {len(weather)} real 2023 weather days")
    edges = np.geomspace(max(xs_a.min(), 0.02), xs_a.max(), 19)   # bins in log space
    ctr, med, lo_b, hi_b = [], [], [], []
    for a2, b2 in zip(edges, edges[1:]):
        m2 = (xs_a >= a2) & (xs_a <= b2)
        if m2.sum() >= 4:
            ctr.append(np.sqrt(a2 * b2)); med.append(np.median(ys_a[m2]))
            lo_b.append(np.percentile(ys_a[m2], 10)); hi_b.append(np.percentile(ys_a[m2], 90))
    ax.fill_between(ctr, lo_b, hi_b, color="#444444", alpha=0.12,
                    label="80% band (10th-90th percentile per bin)")
    ax.plot(ctr, med, "-", color="#444444", lw=2, alpha=0.85, label="binned median")

    ax.axvline(1.0, ls=":", color="#888")
    ax.text(1.06, 0.975, "gamma = 1: surplus equals fleet appetite",
            transform=ax.get_xaxis_transform(), fontsize=11, color="#666",
            rotation=90, ha="left", va="top")
    ax.set_xlabel("gamma = daily leftover solar / daily fleet driving energy")
    ax.set_ylabel("% of total daily cost saved by enabling V2G (gross)")
    ax.set_title("what is V2G worth, holding operations fixed? compute gamma, read the curve",
                 fontsize=13)
    ax.legend(loc="upper left", fontsize=11)
    finish(fig, "fig_8_5_collapse.png")
    GALLERY.append("\n![fig 8.5](fig_8_5_collapse.png)\n")
    _twin_txt = "(e.g. a 20-task and a 6x-larger 120-task base at similar gamma save 6.5% and 9.2%)"
    caption("Figure 8.5",
        "Each dot is one hypothetical base -- a specific fleet size (20-560 daily tasks), "
        "task energy (50-250 kWh), PV size, network, and schedule -- solved to optimality "
        "TWICE, with V2G allowed and charge-only; its height is the total-daily-cost "
        "saving V2G delivered. The x-coordinate is R = daily leftover solar divided by "
        "the fleet's daily driving energy: 'solar per unit of fleet appetite'. The same "
        "16.8 MWh surplus is a feast for a fleet that drives on 4 MWh and irrelevant to "
        "one that needs 24, so raw MWh predicts nothing while R predicts everything: "
        f"bases of wildly different size and duty land on one curve {_twin_txt}. Triangles "
        "are a single base re-solved under real 2023 weather days -- weather moves a "
        "site along the curve, not off it. The line is a rolling median through the "
        "dots; the shaded band holds the central 80% of studies -- a PREDICTION band "
        "(where a new site should fall), which unlike a confidence interval on the "
        "mean does not shrink to zero as more simulations are run. Reading for a "
        "planner: compute R from two "
        "energy audits and read off the gross saving. Pricing realistic enablement "
        "costs INTO the model (bidirectional-charger premium $0-8 per truck-day and "
        "cycling degradation $0-0.13/kWh -- ranges anchored to published hardware "
        "premiums and V2G-degradation studies; see the provenance table) yields a "
        "computed break-even of "
        "R* ~ 0.31-0.45 (shaded band): the charger premium dominates, while "
        "degradation is nearly free -- the optimizer cycles less rather than pay it. "
        "Charge rate is a second-order correction confined to the transition region "
        "(at 100 kW the mid-range value drops by a third to a half; 200 and 350 kW are "
        "indistinguishable; both tails are rate-independent -- 500-base overnight sweep).")
else:
    print("  [skip] not enough data for the collapse figure")

# %% Figure 8.6 -- diminishing returns across the full duty-cycle range
import glob as _glob
eb = []
for _p in _glob.glob(os.path.join(ARX, "overnight2_epsband_s*.json")):
    eb += json.load(open(_p))
eb2 = []
for _p in _glob.glob(os.path.join(ARX, "overnight2_epsband150_s*.json")):
    eb2 += json.load(open(_p))
if eb:
    from matplotlib import cm as _cm

    def _panel(ax, data, title):
        eps_all = sorted({r["eps"] for r in data})
        for eps_v in eps_all:
            col = _cm.viridis(0.05 + 0.85 * (eps_v - eps_all[0]) / max(eps_all[-1] - eps_all[0], 1e-9))
            xs, med, lo, hi = [], [], [], []
            for pv in sorted({r["pv"] for r in data}):
                v = [r["fuel_kwh"] / 1000 for r in data if r["eps"] == eps_v and r["pv"] == pv]
                if v:
                    xs.append(pv * 14.7); med.append(np.median(v)); lo.append(min(v)); hi.append(max(v))
            ax.fill_between(xs, lo, hi, color=col, alpha=0.15)
            ax.plot(xs, med, "-", color=col, lw=1.8, label=f"{int(eps_v * 100)} kWh")
        ax.axhline(0, color="k", lw=0.6)
        ax2 = ax.twinx()
        for eps_v in eps_all:
            col = _cm.viridis(0.05 + 0.85 * (eps_v - eps_all[0]) / max(eps_all[-1] - eps_all[0], 1e-9))
            xs_b, ys_b = [], []
            for pv in sorted({r["pv"] for r in data}):
                v = [r["batteries"] for r in data if r["eps"] == eps_v and r["pv"] == pv]
                if v:
                    xs_b.append(pv * 14.7); ys_b.append(np.median(v))
            ax2.plot(xs_b, ys_b, ":", color=col, lw=1.0, alpha=0.8)
        ax2.set_ylabel("batteries deployed (dotted, per duty level)", fontsize=10, color="#666666")
        ax2.tick_params(labelsize=7, colors="#666666")
        ax.set_xlabel("available daily solar (MWh)")
        ax.set_title(title, fontsize=10)

    ncols = 2 if eb2 else 1
    fig, axs = plt.subplots(1, ncols, figsize=(6.4 * ncols + 1.2, 4.6),
                            sharex=True, constrained_layout=True, squeeze=False)
    _panel(axs[0, 0], eb, "(a) 60 tasks: enough solar zeroes out ALL generation")
    axs[0, 0].set_ylabel("TOTAL daily fossil generation, base load + fleet (MWh)")
    axs[0, 0].legend(title="energy per task", fontsize=10, title_fontsize=10)
    if eb2:
        _panel(axs[0, 1], eb2, "(b) 150 tasks: heavy duties never reach zero")
    finish(fig, "fig_8_6_diminishing.png")
    GALLERY.append("\n![fig 8.6](fig_8_6_diminishing.png)\n")
    caption("Figure 8.6",
        "Total daily fossil generation (base load + fleet) versus available solar, for "
        "six task-energy levels (eps = energy one 2-hour task consumes: 50 kWh ~ a "
        "light shuttle run, up to 300 kWh ~ heavy off-road/patrol duty). Lines are "
        "medians over random trip sets and cloud-shape perturbations; shading is the "
        "spread. Every duty level shows the same concavity -- each additional MWh of "
        "solar displaces less fuel than the last (the empirical signature of "
        "Theorem 1's fixed-profile submodularity). Whether a curve REACHES zero "
        "(the whole microgrid running on time-shifted solar) depends on the "
        "surplus-vs-fleet-appetite balance: at 60 tasks (a) every duty level "
        "eventually zeroes out, while at 150 tasks (b) the heavier duties consume "
        "the surplus themselves and generation plateaus above zero -- the same "
        "boundary that the starred cells trace through Table 8.4. The dotted line "
        "(right axis) shows deployed storage growing as fuel falls: more solar is "
        "captured by more batteries, but each captures less -- the two halves of "
        "the diminishing-returns mechanism (dotted lines are color-matched to their duty level).")
# %% Figure 8.7 -- realistic solution timeline: 1-hour tasks, full-day schedule
tlp = os.path.join(ARX, "overnight2_timeline.json")
GANTT_SEED = 4             # seed 4: cleanest lanes (3.5 tasks/truck, one single-task lane)
if os.path.exists(tlp):
    tl = json.load(open(tlp))
    seeds_avail = sorted({v.get("seed", 5) for v in tl})
    pick = GANTT_SEED if GANTT_SEED in seeds_avail else seeds_avail[0]
    if len(seeds_avail) > 1:
        print(f"gantt candidates available (edit GANTT_SEED to flip): {seeds_avail}; showing {pick}")
    tl = [v for v in tl if v.get("seed", 5) == pick]
    nlanes = [len(v["lanes"]) + (1 if v.get("battery_net") else 0) for v in tl]
    fig, axes = plt.subplots(len(tl), 1, figsize=(10.5, 2.0 + 0.34 * sum(nlanes)),
                             gridspec_kw={"height_ratios": [n + 2 for n in nlanes]},
                             constrained_layout=True, sharex=True)
    axes = np.atleast_1d(axes)
    for a_, v in zip(axes, tl):
        delta = v["delta"]
        tcounts = v.get("lane_tasks", [None] * len(v["lanes"]))
        ltrips = v.get("lane_trips", [[] for _ in v["lanes"]])
        order = sorted(range(len(v["lanes"])),
                       key=lambda i: -(tcounts[i] if tcounts[i] is not None else 0))
        truck_lanes = [v["lanes"][i] for i in order]
        ltrips = [ltrips[i] for i in order]
        tcounts = [tcounts[i] for i in order]
        lanes = truck_lanes + ([v["battery_net"]] if v.get("battery_net") else [])
        for i in range(len(truck_lanes)):                 # driving bars first (slate)
            for iv in (ltrips[i] if i < len(ltrips) else []):
                a_.add_patch(plt.Rectangle((iv[0], i - 0.42), iv[1] - iv[0], 0.84,
                                           color="#9fb3c8"))
        for i, e in enumerate(lanes):
            for t, val in enumerate(e):
                if val > 1e-6:
                    c = "#2e9e3f" if delta[t] < 0 else "#333333"
                elif val < -1e-6:
                    c = "#c0392b"
                else:
                    continue
                a_.add_patch(plt.Rectangle((t / 2.0, i - 0.42), 0.5, 0.84, color=c))
        labels = [f"Truck {i + 1}" + (f" ({tcounts[i]} tasks)" if tcounts[i] is not None else "")
                  for i in range(len(truck_lanes))]
        if v.get("battery_net"):
            labels.append(f"Battery (x{v['batteries']})")
        a_.set_yticks(range(len(labels))); a_.set_yticklabels(labels, fontsize=9.5)
        a_.set_xlim(0, 24); a_.set_ylim(-0.7, len(labels) - 0.3)
        bat_txt = (f"battery \\${v['cb']:.0f}/day" if v.get("cb") else "no stationary storage")
        a_.set_title(f"truck \\${v['cv']:.0f}/day, " + bat_txt + ": "
                     f"{v['trucks']} trucks ({v['tasks_per_truck']} tasks/truck), "
                     f"{v['batteries']} batteries", fontsize=11.5)
    axes[-1].set_xlabel("hour of day")
    # proper color legend (was compressed into the x-axis label)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color="#9fb3c8", label="serving a task"),
                        Patch(color="#2e9e3f", label="free solar charge"),
                        Patch(color="#333333", label="paid charge"),
                        Patch(color="#c0392b", label="V2G discharge")],
               ncol=4, loc="outside lower center", fontsize=10.5, frameon=False)
    finish(fig, "fig_8_7_timeline.png")
    GALLERY.append("\n![fig 8.7](fig_8_7_timeline.png)\n")
    caption("Figure 8.7",
        "A realistic solution timeline: 60 one-hour tasks on a full-day schedule "
        "(6h-20h), so vehicles chain tasks the way real fleets do, instead of the "
        "breaks-schedule ceiling of ~4-5 two-hour tasks. Top: a depot WITH stationary "
        "storage -- the batteries carry the arbitrage and trucks mostly just recharge "
        "their own traction. Bottom: the same depot with NO stationary storage "
        "installed (a common real situation): the V2G-capable fleet takes over the "
        "arbitrage itself, and the truck lanes fill with discharge. Low-task lanes that "
        "charge across many blocks and discharge into both peaks are genuine "
        "fleet-as-storage vehicles, not artifacts: a representative optimal schedule "
        "(gap < 0.01%). Green cells "
        "are charging on free midday surplus, black is paid charging, red is V2G "
        "discharge into the morning/evening deficits.")
else:
    tlpng = os.path.join(ARX, "exp4_timeline.png")
    if os.path.exists(tlpng):
        if INTERACTIVE:
            from IPython.display import Image
            display(Image(filename=tlpng))
        GALLERY.append("\n![fig 8.7](../arxiv/exp4_timeline.png)\n")
        caption("Figure 8.7",
            "Representative EVSP-V2G solution (2-hour-task fallback; run overnight2 S7 "
            "for the realistic 1-hour/full-day version).")
# %% Figure 8.8 -- PV sizing under a real year of weather (overnight S2)
wx = load(ARX, "overnight_weather.json")
if wx:
    pvs = sorted({r["pv"] for r in wx if "v2g_vs_solar_pct" in r})
    mean_, p10_, p90_, p25_, p75_ = [], [], [], [], []
    for pv in pvs:
        v = np.array([r["v2g_vs_solar_pct"] for r in wx if r["pv"] == pv and "v2g_vs_solar_pct" in r])
        mean_.append(v.mean()); p10_.append(np.percentile(v, 10)); p90_.append(np.percentile(v, 90))
        p25_.append(np.percentile(v, 25)); p75_.append(np.percentile(v, 75))
    fig, ax = plt.subplots(figsize=(7.5, 4.4), constrained_layout=True)
    ax.fill_between(pvs, p10_, p90_, color="#2E75B6", alpha=0.14, label="p10-p90 (80% of days)")
    ax.fill_between(pvs, p25_, p75_, color="#2E75B6", alpha=0.28, label="p25-p75 (half of days)")
    ax.plot(pvs, mean_, "-o", color="#2E75B6", label="annual mean")
    ax.axhline(0, color="k", lw=0.7)
    ax.set_xlabel("PV sizing (multiple of the original installation; 1.0 = 14.7 MWh/day annual mean)")
    ax.set_ylabel("V2G savings vs charge-only (% of daily cost)")
    ax.set_title("how much PV makes V2G worth it -- a real year of weather (2023)")
    ax.legend()
    finish(fig, "fig_8_8_pv_sizing.png")
    GALLERY.append("\n![fig 8.8](fig_8_8_pv_sizing.png)\n")
    caption("Figure 8.8",
        "Annual V2G value as a function of PV build-out, evaluated on all 365 real days "
        "of 2023 irradiance at the site's coordinates (each day solved to optimality with "
        "and without V2G). At the original installation's sizing (1.0x) V2G is worthless "
        "every day of the year -- the site sits in the R < 0.4 dead zone even in June -- "
        "so V2G is only sensible as a JOINT decision with PV expansion. The payoff rises "
        "steeply over 1.5-2.5x, but note the risk profile: at 2.0x the mean is 31% while "
        "the 10th percentile is just 2% (cloudy-season days earn nothing); the value only "
        "becomes FIRM at ~3x, where even the 10th-percentile day saves 19%. The annual "
        "mean closely matches the mean-day design value at every sizing, so expected "
        "value can be estimated from a single average day -- but the day-to-day "
        "distribution cannot.")


# %% Figure 8.9 -- fuel and fleet size vs task count, by regime
import glob as _glob
md9 = []
for _p in _glob.glob(os.path.join(ARX, "overnight2_modes_s*.json")):
    md9 += json.load(open(_p))
NM9 = {"vsp": ("VSP (ICE, 3.3x thermal)", "#888888", "-"), "ev": ("EVSP (flat tariff)", "#7d3c98", "-"),
       "solar": ("EVSP-Solar", "#e08020", "--"), "v2g": ("EVSP-V2G", "#2E75B6", "-")}
TIT9 = {"1x": "1x solar", "2x": "2x solar", "3x": "3x solar", "4x": "4x solar",
        "summer": "summer day (1x panels, longer daylight)",
        "sum2x": "summer day, 2x panels"}
ICE9 = 3.3
def _fossil9(r):
    if r["scenario"] == "vsp":
        return (r["g_units"] + ICE9 * r["traction_units"]) / 10.0
    if r["scenario"] == "ev":
        return (r["g_units"] + r["fleet_paid_units"]) / 10.0
    return r["g_units"] / 10.0
for _p in _glob.glob(os.path.join(ARX, "overnight3_modes_s*.json")):
    md9 += json.load(open(_p))
if md9:
    def _sol9(r):
        if r.get("sol") is not None:
            return str(r["sol"])
        if r.get("pv") is not None:
            pv = float(r["pv"])
            return f"{int(pv)}x" if pv.is_integer() else f"{pv:g}x"
        return None

    md9 = [r for r in md9 if _sol9(r) is not None and "scenario" in r and "n_tasks" in r]
    for r in md9:
        r["sol"] = _sol9(r)
        r["seed"] = r.get("seed", 0)
    # 3x2 layout for print (coauthor request): three story-carrying solar levels
    # (dead zone / separation / real summer profile doubled); the 3x/4x/summer
    # interpolants told the same story at unreadable size
    sols9 = [x for x in ("1x", "2x", "sum2x")
             if any(r["sol"] == x for r in md9)]
    fig, ax = plt.subplots(2, len(sols9), figsize=(3.8 * len(sols9) + 0.6, 7.4),
                           sharex=True, constrained_layout=True, squeeze=False)
    for j, sol in enumerate(sols9):
        for scen, (lab, c, ls) in NM9.items():
            rr = [r for r in md9 if r["sol"] == sol and r["scenario"] == scen]
            ns = sorted({r["n_tasks"] for r in rr})
            if rr:
                fo = [float(np.median([_fossil9(r) for r in rr if r["n_tasks"] == n])) for n in ns]
                tk = [float(np.median([r["trucks"] for r in rr if r["n_tasks"] == n])) for n in ns]
                zo = 4 if scen == "solar" else 2
                lw = 2.2 if scen == "solar" else 1.7
                ax[0, j].plot(ns, fo, ls, color=c, lw=lw, label=lab, zorder=zo,
                              dashes=(5, 2.5) if ls == "--" else (None, None))
                ax[1, j].plot(ns, tk, ls, color=c, lw=lw, label=lab, zorder=zo,
                              dashes=(5, 2.5) if ls == "--" else (None, None))
        ax[0, j].set_title(TIT9.get(sol, sol))
        ax[1, j].set_xlabel("number of tasks")
    ax[0, 0].set_ylabel("daily fossil energy (MWh, ICE at 3.3x)")
    ax[1, 0].set_ylabel("trucks deployed")
    ax[0, 0].legend(fontsize=10)
    finish(fig, "fig_8_9_modes.png")
    GALLERY.append("\n![fig 8.9](fig_8_9_modes.png)\n")
    caption("Figure 8.9",
        "Fuel and fleet size versus workload, 20-400 tasks, at the original solar "
        "level (left) and doubled solar (right), honest drivetrain accounting. At "
        "1x solar the Solar and V2G curves COINCIDE -- the site is in the R < 0.4 "
        "dead zone, so bidirectionality has nothing to arbitrage (dashed orange under "
        "solid blue); at 2x solar they separate and the V2G fuel curve pulls away. "
        "The fleet panel carries the operational story: charge-only fleets grow "
        "fastest with workload, while V2G's storage flexibility keeps the fleet "
        "closer to the ICE baseline.")
else:
    e1c9 = load(ARX, "exp1_regimes.json")
    if e1c9:
        sub9 = [r for r in e1c9 if r.get("eps") == 2.0 and r.get("feasible")]
        fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
        for scen, (lab, c, ls) in NM9.items():
            if scen == "ev":
                continue
            rr = sorted([r for r in sub9 if r["scenario"] == scen], key=lambda r: r["trips"])
            if rr:
                ax[0].plot([r["trips"] for r in rr], [r["fuel_kwh"] / 1000 for r in rr], ls, color=c, label=lab)
                ax[1].plot([r["trips"] for r in rr], [r["trucks"] for r in rr], ls, color=c, label=lab)
        ax[0].set_xlabel("number of tasks"); ax[0].set_ylabel("daily fossil fuel (MWh-equivalent)")
        ax[0].set_title("fuel by regime (Solar dashed: coincides with V2G at this solar level)")
        ax[0].legend(); ax[1].set_xlabel("number of tasks"); ax[1].set_ylabel("trucks deployed")
        ax[1].set_title("fleet size by regime"); ax[1].legend()
        finish(fig, "fig_8_9_modes.png")
        GALLERY.append("\n![fig 8.9](fig_8_9_modes.png)\n")
        caption("Figure 8.9",
            "Fuel and fleet vs task count (fallback 3-point version; run overnight2 "
            "S12 for the dense 20-400-task, two-solar-level figure).")
# %% Figure 8.10 -- column generation: greedy warm start vs cold start
wc10 = load(ARX, "overnight2_warmcold.json")
if wc10:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    ns10 = sorted({r["n_tasks"] for r in wc10})
    for start, c in (("cold", "#888888"), ("warm", "#2E75B6")):
        it_m, tm_m = [], []
        for n in ns10:
            v = [r for r in wc10 if r["n_tasks"] == n and r["start"] == start]
            it_m.append(np.mean([r["iters"] for r in v]) if v else np.nan)
            tm_m.append(np.mean([r["time_s"] for r in v]) if v else np.nan)
        lab = "greedy warm start" if start == "warm" else "cold start"
        ax[0].plot(ns10, it_m, "-o", color=c, label=lab)
        ax[1].plot(ns10, tm_m, "-o", color=c, label=lab)
    ax[0].set_xlabel("number of tasks"); ax[0].set_ylabel("CG iterations to convergence (mean of 3 fleets)")
    ax[0].set_title("warm vs cold start"); ax[0].legend()
    ax[1].set_xlabel("number of tasks"); ax[1].set_ylabel("LP/CG solve time (s)")
    ax[1].set_title("solve time"); ax[1].legend()
    finish(fig, "fig_8_10_warmstart.png")
    GALLERY.append("\n![fig 8.10](fig_8_10_warmstart.png)\n")
    caption("Figure 8.10",
        "Column generation with the greedy warm start (repeatedly pricing against "
        "uncovered-task rewards -- the constructive counterpart of the submodular "
        "layer of Section 6) versus a cold start from single-task columns, means "
        "over three random fleets per size, 60-450 tasks. Either way the LP "
        "converges in seconds-to-a-minute on open-source solvers with no monolithic "
        "time-indexed MILP; the warm start's advantage in iterations grows with "
        "instance size.")
else:
    cg10 = load(os.path.join(ROOT, "results"), "colgen.json")
    if cg10:
        fig, ax = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
        xs10 = [r["trips"] for r in cg10]
        ax[0].plot(xs10, [r["cold_iters"] for r in cg10], "-o", color="#888888", label="cold start")
        ax[0].plot(xs10, [r["warm_iters"] for r in cg10], "-o", color="#2E75B6", label="greedy warm start")
        ax[0].set_xlabel("number of tasks"); ax[0].set_ylabel("CG iterations"); ax[0].legend()
        ax[1].plot(xs10, [r["cold_time"] for r in cg10], "-o", color="#888888", label="cold start")
        ax[1].plot(xs10, [r["warm_time"] for r in cg10], "-o", color="#2E75B6", label="greedy warm start")
        ax[1].set_xlabel("number of tasks"); ax[1].set_ylabel("time (s)"); ax[1].legend()
        finish(fig, "fig_8_10_warmstart.png")
        GALLERY.append("\n![fig 8.10](fig_8_10_warmstart.png)\n")
        caption("Figure 8.10", "Warm vs cold start (small-instance fallback; run "
                "overnight2 S13 for the 60-450-task version).")
# %% Figure 8.11 -- infrastructure caps + the value of V2G on one dispatch plot
cp = load(ARX, "caps_profile.json")
if cp and "v2g" in cp:
    hrs = np.arange(len(cp["v2g"]["gen"]))
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.3), constrained_layout=True)
    ax[0].step(hrs, cp["baseline_gen"], where="mid", color="#bbbbbb", ls=":",
               label=f"no fleet at all ({cp['baseline_mwh']:.1f} MWh)")
    ax[0].step(hrs, cp["solar"]["gen"], where="mid", color="#777777", lw=1.8,
               label=f"conventional charging, no storage ({cp['solar']['fossil_mwh']:.1f} MWh)")
    ax[0].step(hrs, cp["v2g"]["gen"], where="mid", color="#2E75B6", lw=1.9,
               label=f"full V2G technology ({cp['v2g']['fossil_mwh']:.1f} MWh)")
    _gs = np.array(cp["solar"]["gen"]); _gv = np.array(cp["v2g"]["gen"])
    ax[0].fill_between(hrs, _gv, _gs, where=_gs >= _gv, step="mid", color="#2E75B6",
                       alpha=0.10,
                       label=r"$\int (g_{\mathrm{conv}} - g_{\mathrm{V2G}})\,dt$ = "
                             f"{cp['solar']['fossil_mwh'] - cp['v2g']['fossil_mwh']:.1f} MWh/day")
    if bool((_gv > _gs).any()):
        ax[0].fill_between(hrs, _gs, _gv, where=_gv > _gs, step="mid", color="#e74c3c",
                           alpha=0.15, label="hours V2G dispatches more (charging storage)")
    ax[0].axhline(cp["gen_cap"], ls="--", color="#c0392b", lw=1.2,
                  label=f"generation cap {cp['gen_cap']:.0f}")
    ax[0].set_xlabel("hour of day"); ax[0].set_ylabel("dispatched fossil generation (kWh/block)")
    ax[0].set_title(f"same fleet, same tasks: V2G cuts daily fossil "
                    f"{cp['solar']['fossil_mwh']:.1f} -> {cp['v2g']['fossil_mwh']:.1f} MWh")
    ax[0].legend(fontsize=10)
    ax[1].step(hrs, cp["solar"]["charge"], where="mid", color="#777777", lw=1.6,
               label="charging draw, conventional")
    ax[1].step(hrs, cp["v2g"]["charge"], where="mid", color="#2e9e3f", lw=1.8,
               label="charging draw, V2G (fleet + batteries)")
    ax[1].axhline(cp["charge_cap"], ls="--", color="#c0392b", lw=1.2,
                  label=f"charging cap {cp['charge_cap']:.0f}")
    ax[1].set_xlabel("hour of day"); ax[1].set_ylabel("total charging draw (kWh/block)")
    ax[1].set_title("charging concentrates in the midday surplus, under the station cap")
    ax[1].legend(fontsize=10)
    finish(fig, "fig_8_11_caps.png")
    GALLERY.append("\n![fig 8.11](fig_8_11_caps.png)\n")
    caption("Figure 8.11",
        "The infrastructure limits of Section 3, enforced and at work (realistic "
        "capped instance, 20 tasks, 24 MWh/day solar). Left: hourly fossil dispatch "
        "for the SAME fleet and tasks under conventional charging (gray) versus full "
        "V2G technology (blue): the morning and evening peaks are shaved and the "
        "daily fossil integral falls by roughly two thirds; the V2G solution's "
        "evening peak presses the generation cap exactly, so the reported benefits "
        "hold WITH the limits binding rather than absent. The dotted trace is the "
        "no-fleet base load for reference. Right: total charging draw (fleet plus "
        "batteries) -- the V2G solution pulls a large midday hump of free solar and "
        "stays under the station capacity cap, whose congestion price nu_t is "
        "exactly the term the pricing DP of Section 7 charges for charging. The "
        "shaded area between the curves is the saved energy, sum_t g_t taken over "
        "the day; charging is a continuous (linear) decision per block, so as the "
        "block length shrinks this sum converges to the integral of g(t) -- and the "
        "DP's complexity is linear in the number of blocks, making refinement "
        "computationally cheap.")
# %% Figure 8.12 -- where V2G shines: small fleets under generous sun
vs12 = []
for _p in _glob.glob(os.path.join(ARX, "v2g_shine*.json")):
    vs12 += json.load(open(_p))
if vs12:
    _ns = sorted({r["n_tasks"] for r in vs12})
    NS12 = sorted({_ns[0], _ns[len(_ns) // 2], _ns[-1]})
    SH12 = [s for s in ("std", "summer") if any(r["shape"] == s for r in vs12)]
    PV12 = sorted({r["pv"] for r in vs12})
    SC12 = [("solar", "EVSP-Solar (charge-only)", "#e08020", "--"),
            ("v2g_fleet", "V2G trucks only (no stationary)", "#16a085", "-"),
            ("v2g", "EVSP-V2G (trucks + batteries)", "#2E75B6", "-")]

    def _m12(n, sh, pv, scen, key="fossil_mwh"):
        v = [r[key] for r in vs12 if r["n_tasks"] == n and r["shape"] == sh
             and r["pv"] == pv and r["scenario"] == scen]
        return float(np.mean(v)) if v else np.nan

    fig, ax = plt.subplots(len(SH12), len(NS12),
                           figsize=(4.6 * len(NS12) + 0.6, 3.5 * len(SH12) + 0.6),
                           sharex=True, constrained_layout=True, squeeze=False)
    for i, sh in enumerate(SH12):
        for j, n in enumerate(NS12):
            a = ax[i, j]
            bl = [float(np.mean([r["baseline_mwh"] for r in vs12
                                 if r["n_tasks"] == n and r["shape"] == sh and r["pv"] == pv]))
                  for pv in PV12]
            a.plot(PV12, bl, ":", color="#999999", lw=1.4, label="no fleet (base load only)")
            for scen, lab, c, ls in SC12:
                a.plot(PV12, [_m12(n, sh, pv, scen) for pv in PV12], ls, color=c,
                       lw=1.5 if scen == "v2g_fleet" else 2.1, label=lab,
                       dashes=(5, 2.5) if ls == "--" else (None, None))
            a.axhline(0, color="#444444", lw=0.6)
            if i == 0:
                a.set_title(f"{n} tasks/day")
            if i == len(SH12) - 1:
                a.set_xlabel("PV build-out (x design size)")
        _shl = "standard day" if sh == "std" else "summer day (longer, brighter)"
        ax[i, 0].set_ylabel(f"daily fossil (MWh)\n{_shl}")
    ax[0, 0].legend(fontsize=10)
    # headline: the technology beats the panel field (first size where it holds)
    _pvmax = max(PV12)
    for _nn in NS12:
        _fv1 = _m12(_nn, "std", 1.0, "v2g")
        _fsX = _m12(_nn, "std", _pvmax, "solar")
        if np.isfinite(_fv1) and np.isfinite(_fsX) and _fv1 <= _fsX:
            _a = ax[0, list(NS12).index(_nn)]
            _a.annotate(f"V2G at 1x panels ({_fv1:.1f} MWh)\nbeats charge-only at "
                        f"{_pvmax:g}x panels ({_fsX:.1f} MWh)",
                        xy=(1.0, _fv1), xytext=(1.55, _fv1 * 0.35), fontsize=10,
                        color="#2E75B6",
                        arrowprops=dict(arrowstyle="->", color="#2E75B6", lw=1.0))
            break
    finish(fig, "fig_8_12_shine.png")
    GALLERY.append("\n![fig 8.12](fig_8_12_shine.png)\n")
    _rmin = min(r["ratio"] for r in vs12); _rmax = max(r["ratio"] for r in vs12)
    _nzero = len({(r["n_tasks"], r["shape"], r["pv"], r["seed"]) for r in vs12
                  if r["scenario"] == "v2g" and r["fossil_mwh"] == 0.0})
    caption("Figure 8.12",
        "The corner of the design space where V2G shines: small fleets (4-20 daily "
        f"tasks) under generous sun -- R runs {_rmin:.0f} to {_rmax:.0f}, far beyond "
        "the saturation knee of Figure 8.5, in both panel build-out (0.75x-4x) and "
        "day length (bottom row: a summer day carrying 1.6x the solar energy over "
        "longer daylight). Mean of 3 random trip sets; same trips across every curve "
        "in a panel. The charge-only fleet (dashed orange) barely benefits from "
        "extra panels -- with no storage, midday surplus cannot reach the morning "
        "and evening base load, so its curve flattens toward a fossil floor. "
        "Bidirectional trucks alone (teal) shave a roughly constant slice limited "
        "by their pack capacity. The full V2G stack (blue) keeps converting every "
        f"added panel into displaced fossil generation and reaches ZERO fossil in "
        f"{_nzero} of the sampled cells: the technology substitutes for panels "
        "(annotation), and past the point where charge-only saturates it is the "
        "only regime still buying anything with additional PV.")

# %% Figure 8.13 -- the multi-station frontier: what chargers-everywhere buys
sa13 = []
for _p in _glob.glob(os.path.join(ARX, "stations_sa_s*.json")):
    sa13 += json.load(open(_p))
for _p in _glob.glob(os.path.join(ARX, "stations_sa2_s*.json")):
    sa13 += json.load(open(_p))                      # U3 densify + sub2/sub5 arms
if sa13:
    def _lp13(r):
        """Exact CG LP bound recovered from the stored MILP value and gap.
        The LP is solved to optimality in every run, so LP-based comparisons
        use ALL rows; the raw MILP values carry time-limit gaps on the harder
        multi-station instances and would silently bias any gap-filtered subset
        toward easy cells."""
        return r["total"] * (1 - r["gap_pct"] / 100.0)

    _idx13 = {(r["L"], r["sol"], r["n_tasks"], r["seed"], r["stations"], r["scenario"]): r
              for r in sa13}
    LS13 = sorted({r["L"] for r in sa13})

    def _pairs13(L, sol, scen, st2="all"):
        """(depot, st2) LP-bound pairs across n x seed."""
        out = []
        for (l, s, n, sd, st, sc), r in _idx13.items():
            if (l, s, sc, st) != (L, sol, scen, "depot"):
                continue
            r2 = _idx13.get((l, s, n, sd, st2, sc))
            if r2:
                out.append((_lp13(r), _lp13(r2)))
        return out

    fig, ax = plt.subplots(2, 2, figsize=(11.2, 8.4), constrained_layout=True)
    ax = ax.ravel()
    def _mean_lp(L, sol, scen, st):
        v = [_lp13(r) for (l, s, n, sd, st_, sc), r in _idx13.items()
             if (l, s, st_, sc) == (L, sol, st, scen)]
        return float(np.mean(v)) if v else np.nan
    for scen, c, base_lab in (("solar", "#e08020", "EVSP-Solar"), ("v2g", "#2E75B6", "EVSP-V2G")):
        for st, ls in (("depot", "--"), ("all", "-")):
            ys = [_mean_lp(L, "2x", scen, st) / 1000 for L in LS13]
            ax[0].plot(LS13, ys, ls, marker="o", ms=4, color=c,
                       label=f"{base_lab}, {'depot charger only' if st == 'depot' else 'chargers everywhere'}")
    ax[0].set_xlabel("number of task locations L")
    ax[0].set_ylabel("mean total daily cost (k$, LP bound; 2x solar)")
    ax[0].set_title("(a) absolute costs: V2G below charge-only")
    ax[0].legend(fontsize=10.5)
    for st, c, lab in (("depot", "#888888", "charger at depot only"),
                       ("all", "#16a085", "charger at every location")):
        b = []
        for L in LS13:
            v = [r["batteries"] for r in sa13 if r["L"] == L and r["sol"] == "2x"
                 and r["stations"] == st and r["scenario"] == "v2g" and "batteries" in r]
            b.append(float(np.mean(v)) if v else np.nan)
        ax[1].plot(LS13, b, "-o", color=c, ms=4, label=lab)
    ax[1].set_xlabel("number of task locations L"); ax[1].set_ylabel("stationary batteries bought (mean, 2x solar)")
    ax[1].set_title("(b) chargers substitute for storage"); ax[1].legend(fontsize=10)
    for sol, mk in (("1x", "-o"), ("2x", "-s"), ("summer", "--^"), ("sum2x", "--v")):
        vs = []
        for L in LS13:
            pp = []
            for (l, s, n, sd, st, sc), r in _idx13.items():
                if (l, s, st, sc) == (L, sol, "depot", "solar"):
                    r2 = _idx13.get((l, s, n, sd, "depot", "v2g"))
                    if r2:
                        pp.append(100 * (_lp13(r) - _lp13(r2)) / _lp13(r))
            vs.append(float(np.mean(pp)) if pp else np.nan)
        ax[2].plot(LS13, vs, mk, ms=4, label=TIT9.get(sol, sol))
    ax[2].set_xlabel("number of task locations L"); ax[2].set_ylabel("V2G saving vs charge-only (%)")
    ax[2].set_title("(c) V2G value by solar regime"); ax[2].legend(fontsize=10)
    # charger build-out frontier: depot -> +2 -> +5 -> everywhere (large maps)
    NARMS = [("depot", 1), ("sub2", 3), ("sub5", 6), ("all", 12.25)]
    for scen, c in (("solar", "#e08020"), ("v2g", "#2E75B6")):
        xs_f, ys_f = [], []
        for st, nch in NARMS:
            v = [_lp13(r) for (l, s, n, sd, st_, sc), r in _idx13.items()
                 if l in (8, 10, 12, 15) and (s, st_, sc) == ("2x", st, scen)]
            if v:
                xs_f.append(nch); ys_f.append(float(np.mean(v)) / 1000)
        ax[3].plot(xs_f, ys_f, "-o", color=c, ms=5,
                   label="EVSP-Solar" if scen == "solar" else "EVSP-V2G")
    ax[3].set_xlabel("charging locations (depot + k); large maps, 2x solar")
    ax[3].set_ylabel("mean total daily cost (k$, LP bound)")
    ax[3].set_title("(d) charger build-out: concave gains")
    ax[3].legend(fontsize=10)
    for a13 in ax:                       # print-size panel text (after all assignments)
        a13.tick_params(labelsize=11)
        a13.xaxis.label.set_size(12.5); a13.yaxis.label.set_size(12.5)
        a13.title.set_size(13)
        lg13 = a13.get_legend()
        if lg13 is not None:
            for t13 in lg13.get_texts():
                t13.set_size(11.5)
    finish(fig, "fig_8_13_stations.png")
    GALLERY.append("\n![fig 8.13](fig_8_13_stations.png)\n")
    caption("Figure 8.13",
        "The multi-station model (Section 3's H0): 3,456 solves over L = 4-15 task "
        "locations on nested maps, four solar regimes, 40-160 one-hour tasks, 9 seeds, "
        "four charger-placement arms. All cost comparisons use the exact column-"
        "generation LP bound recovered from each stored run (the harder multi-station "
        "MILPs carry time-limit gaps, and filtering on gap would bias toward easy "
        "cells); battery counts are integer-solution values. Left: moving from a "
        "single depot charger to a charger at every task location saves total cost, "
        "and the saving grows with the size of the map; charge-only fleets gain as "
        "much as V2G fleets -- distributed charging is about reaching energy in time, "
        "not about bidirectionality. Second: with chargers everywhere the optimizer "
        "buys roughly half the stationary batteries at 2x solar -- opportunistic "
        "fleet charging substitutes for dedicated storage capex. Third: V2G's saving "
        "over charge-only by regime is flat in L -- the 1x dead zone and the sum2x "
        "bonanza are properties of the energy balance, not the network. Right: the "
        "charger build-out frontier on the large maps (L >= 8): the first two extra "
        "chargers capture most of the chargers-everywhere value, a concrete "
        "infrastructure-planning readout of the same diminishing-returns mechanism.")

# %% Figure 8.14 -- the V2G advantage region in the (tasks x solar) plane
# Daily solar surplus per sol level (MWh/day), computed once from build_instance
# over the standard profiles (see overnight5.py); traction ~ 0.2 MWh/task + deadheads.
SUR14 = {"1x": 3.70, "2x": 16.80, "3x": 30.90, "4x": 45.10, "summer": 6.00, "sum2x": 25.60}
md14 = list(md9)                                     # all modes rows (U2 + extensions)
bd14 = []
for _p in _glob.glob(os.path.join(ARX, "overnight5_boundary_s*.json")):
    bd14 += json.load(open(_p))
if md14:
    gap_pts = []                                     # (sol_label, surplus, n, seed, gap MWh)
    g14 = {}
    for r in md14:
        if r["scenario"] in ("solar", "v2g"):
            g14.setdefault((r["sol"], r["n_tasks"], r["seed"], r["scenario"]), []).append(r["g_units"] / 10)
    for (sol, n, sd, sc) in list(g14):
        if sc != "solar" or (sol, n, sd, "v2g") not in g14:
            continue
        gap = float(np.mean(g14[(sol, n, sd, "solar")])) - float(np.mean(g14[(sol, n, sd, "v2g")]))
        tr14 = 0.2 * n                                # MWh/day (eps=2.0 units/task)
        gap_pts.append((sol, SUR14.get(sol, np.nan), n, sd, gap, tr14))
    b14 = {}
    for r in bd14:
        b14.setdefault((r["pv"], r["n_tasks"], r["seed"], r["scenario"]), r)
    for (pv, n, sd, sc), r in list(b14.items()):
        if sc != "solar" or (pv, n, sd, "v2g") not in b14:
            continue
        v = b14[(pv, n, sd, "v2g")]
        gap_pts.append((f"{pv:g}x", r["surplus_mwh"], n, sd,
                        r["g_units"] / 10 - v["g_units"] / 10, r["traction_mwh"]))
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.6), constrained_layout=True)
    SOLS14 = ["1x", "1.5x", "2x", "2.5x", "3x", "3.5x", "4x", "sum2x"]
    from matplotlib import cm as _cm14
    for k14, sol in enumerate(SOLS14):
        pts = sorted({(n) for (s, _, n, _, _, _) in gap_pts if s == sol})
        if not pts:
            continue
        med = [float(np.median([g for (s, _, n2, _, g, _) in gap_pts
                                if s == sol and n2 == n])) for n in pts]
        col = ("#9b59b6" if sol == "sum2x"
               else _cm14.viridis(0.05 + 0.9 * k14 / max(len(SOLS14) - 2, 1)))
        ax[0].plot(pts, med, "-", lw=1.9, color=col, label=sol)
    ax[0].axhline(0, color="k", lw=0.7)
    ax[0].set_xlabel("number of daily tasks (fleet size)")
    ax[0].set_ylabel("extra fossil displaced (MWh/day)")
    ax[0].set_title("the V2G advantage: grows with sun, fades with fleet size")
    ax[0].legend(fontsize=10, title="solar level", ncol=2)
    xs14 = [sur / max(tr, 1e-9) for (_, sur, _, _, _, tr) in gap_pts if np.isfinite(sur)]
    ys14 = [g for (_, sur, _, _, g, _) in gap_pts if np.isfinite(sur)]
    order14 = np.argsort(xs14)
    xs14 = np.array(xs14)[order14]; ys14 = np.array(ys14)[order14]
    ax[1].scatter(xs14, ys14, s=14, color="#9aa7b5", alpha=0.75, label="all (solar, fleet) cells")
    e14 = np.geomspace(max(xs14.min(), 0.05), xs14.max(), 15)
    c14, m14, l14, h14 = [], [], [], []
    for a2, b2 in zip(e14, e14[1:]):
        mm = (xs14 >= a2) & (xs14 <= b2)
        if mm.sum() >= 4:
            c14.append(np.sqrt(a2 * b2)); m14.append(np.median(ys14[mm]))
            l14.append(np.percentile(ys14[mm], 10)); h14.append(np.percentile(ys14[mm], 90))
    ax[1].fill_between(c14, l14, h14, color="#444444", alpha=0.12, label="80% band per bin")
    ax[1].plot(c14, m14, "-", color="#444444", lw=2, label="binned median")
    ax[1].axvspan(0.31, 0.35, color="#fdf2e3", zorder=0)
    ax[1].axvline(1.0, ls=":", color="#888")
    ax[1].set_xscale("log")
    ax[1].axhline(0, color="k", lw=0.7)
    ax[1].set_xlabel("gamma = daily solar surplus / fleet traction (log)")
    ax[1].set_ylabel("extra fossil displaced (MWh/day)")
    ax[1].set_title("the fade-out boundary is a level set of gamma")
    ax[1].legend(fontsize=10)
    finish(fig, "fig_8_14_boundary.png")
    GALLERY.append("\n![fig 8.14](fig_8_14_boundary.png)\n")
    caption("Figure 8.14",
        "Where V2G beats charge-only, in the planner's coordinates. Left: the extra "
        "fossil energy V2G displaces beyond the charge-only fleet (median over seeds) "
        "against fleet size, one curve per solar level. Every curve has the same "
        "anatomy: the advantage rises while idle battery capacity can still reach "
        "unserved deficit, peaks, then fades as the fleet's own traction consumes the "
        "surplus -- and more sun moves the fade-out boundary to larger fleets (at 1x "
        "the advantage is never material; at 2x it fades past ~100-140 tasks; at 3x "
        "past ~300; at 4x it is still large at 200 tasks). Right: the same cells "
        "replotted against R = surplus/traction collapse onto one curve whose "
        "fade-out sits at the shaded band -- the SAME R* ~ 0.31-0.45 as the computed "
        "enablement break-even of Fig. 8.5. The (tasks x solar) boundary is a level "
        "set of R: a planner needs two energy audits, not a simulation, to know "
        "which side of it a base sits on.")

# %% Figure 8.15 -- round-trip loss: eta rescales the value, not the boundary
et15 = []
for _p in _glob.glob(os.path.join(ARX, "overnight4_eta_s*.json")):
    et15 += json.load(open(_p))
if et15:
    eidx = {(r["eta"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]): r for r in et15}
    fig, ax = plt.subplots(figsize=(7.6, 4.4), constrained_layout=True)
    PVC15 = {1.0: "#888888", 1.5: "#e08020", 2.5: "#2E75B6", 3.5: "#16a085"}
    for pv in sorted({r["pv"] for r in et15}):
        xs, ys = [], []
        for eta in sorted({r["eta"] for r in et15}):
            v = []
            for (e, p, n, sd, sc), r in eidx.items():
                if (e, p, sc) == (eta, pv, "solar") and (e, p, n, sd, "v2g") in eidx:
                    w = eidx[(e, p, n, sd, "v2g")]
                    v.append(100 * (r["total"] - w["total"]) / r["total"])
            if v:
                xs.append(eta); ys.append(float(np.mean(v)))
        ax.plot(xs, ys, "-o", ms=4, color=PVC15.get(pv, "#555"), label=f"{pv}x solar")
    ax.axvspan(0.05, 0.15, color="#eef4ea", zorder=0)
    ax.text(0.10, 0.97, "typical round-trip loss", ha="center", va="top", fontsize=10,
            color="#4d774d", transform=ax.get_xaxis_transform())
    ax.set_xlabel("round-trip loss eta"); ax.set_ylabel("V2G saving vs charge-only (% of daily cost)")
    ax.set_title("losses rescale V2G's value; they do not move the dead zone")
    ax.legend(fontsize=10)
    finish(fig, "fig_8_15_eta.png")
    GALLERY.append("\n![fig 8.15](fig_8_15_eta.png)\n")
    caption("Figure 8.15",
        "Sensitivity of the V2G value to the battery round-trip loss eta (mean over "
        "20-120-task fleets, 2 seeds; every other experiment in this study uses the "
        "lossless base case, so this isolates the knob). In the dead zone (1x solar) "
        "the value is ~0 at every eta -- losses cannot kill what the energy balance "
        "already forbids -- while at mid and high solar each point of loss shaves "
        "value roughly linearly (at 2.5x: 54% lossless, 51% at the 5% loss of a "
        "modern LFP pack, 44% at 15%). Even at a punishing eta = 0.3, more than half "
        "the high-solar value survives. The R-rule's boundary is therefore "
        "loss-robust; only the height of the curve moves.")

# %% Figure 8.16 -- infrastructure caps: the CORRECTED four-arm frontier + matched charging-cap effect
# Panel (a) now comes from the overnight13 FOURCAPS study: Phase-I-corrected
# initialization, 25 kWh lattice, four arms including charge-only + purchasable
# storage. Infeasibility is claimed only from the true Phase-I certificate.
fc16 = []
for _p in _glob.glob(os.path.join(ARX, "overnight13_fourcaps_s*.json")):
    fc16 += json.load(open(_p))
cp16 = []
for _p in _glob.glob(os.path.join(ARX, "overnight4_caps*_s*.json")):
    cp16 += json.load(open(_p))
if fc16 and cp16:
    cidx16 = {(r["gen_m"], r["chg_c"], r["n_tasks"], r["seed"], r["scenario"]): r
              for r in cp16}
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.4), constrained_layout=True)
    # (a) the corrected cliff at the 120-task scale: median cost by arm where
    # feasible; outcome markers where no cost exists
    GM16 = [1.0, 1.05, 1.1, 1.2, 1.3, None]
    xl16 = [("uncapped" if m is None else f"{m:g}") for m in GM16]
    ARM16 = (("solar", "#e08020", "charge-only, no storage"),
             ("v2g_fleet", "#7d3c98", "V2G fleet, no storage"),
             ("solar_bess", "#16a085", "charge-only + storage"),
             ("v2g", "#2E75B6", "V2G + storage"))
    N16 = 120
    Y_CERT, Y_NRI = 13.1, 12.55           # marker bands above the cost range
    XOFF16 = {"solar": -0.09, "v2g_fleet": 0.09}   # de-overlap the two storage-less arms
    for scen, c, lab in ARM16:
        xs_ok, ys_ok = [], []
        xo = XOFF16.get(scen, 0.0)
        for k, m in enumerate(GM16):
            cell = [r for r in fc16 if r["n_tasks"] == N16 and r["scenario"] == scen
                    and r["gen_m"] == m]
            fea = [r["total"] for r in cell if r.get("outcome") == "feasible"]
            ncert = sum(1 for r in cell
                        if r.get("outcome") == "lp_certified_infeasible")
            nnri = sum(1 for r in cell
                       if r.get("outcome") in ("no_real_incumbent", "no_incumbent"))
            if fea:
                xs_ok.append(k); ys_ok.append(float(np.median(fea)) / 1000)
            if ncert:
                ax[0].scatter([k + xo], [Y_CERT], marker="x", s=75, color=c, lw=2.4, zorder=5)
            if nnri and not fea:
                ax[0].scatter([k + xo], [Y_NRI], marker="o", s=48, facecolors="none",
                              edgecolors=c, lw=1.6, zorder=5)
        ax[0].plot(xs_ok, ys_ok, "-o", ms=5, color=c, label=lab)
    from matplotlib.lines import Line2D
    ax[0].legend(handles=(ax[0].get_legend_handles_labels()[0]
                          + [Line2D([], [], marker="x", ls="", ms=8, mew=2.2, color="#555",
                                    label="Phase-I certified infeasible"),
                             Line2D([], [], marker="o", ls="", ms=7, mfc="none", color="#555",
                                    label="no incumbent within limit (diagnostic)")]),
                 fontsize=9.5, loc="center left")
    ax[0].set_xticks(range(len(GM16))); ax[0].set_xticklabels(xl16)
    ax[0].set_ylim(9.9, 13.6)
    ax[0].set_xlabel("generation cap (x no-fleet peak deficit); charging cap 0.7x peak surplus")
    ax[0].set_ylabel("median total daily cost (k$), 120 tasks")
    ax[0].set_title("(a) corrected cliff at scale: storage-less arms leave the map")
    # (b) charging-cap effect at uncapped generation, matched per fleet size
    ccs = sorted({r["chg_c"] for r in cp16 if not np.isfinite(r["gen_m"])},
                 key=lambda x: (x == float("inf"), x))
    xl = [("uncapped" if not np.isfinite(c) else f"{c:g}") for c in ccs]
    NCOL = {20: "#2E75B6", 60: "#16a085", 120: "#7d3c98", 200: "#c0392b"}
    for n in sorted({r["n_tasks"] for r in cp16}):
        ys = []
        for c in ccs:
            v = []
            for sd in range(6):
                s = cidx16.get((float("inf"), c, n, sd, "solar"))
                w = cidx16.get((float("inf"), c, n, sd, "v2g"))
                if s and w and s.get("feasible", True) and w.get("feasible", True):
                    v.append(100 * (s["total"] - w["total"]) / s["total"])
            ys.append(float(np.mean(v)) if v else np.nan)
        ax[1].plot(range(len(ccs)), ys, "-o", ms=5, color=NCOL.get(n, "#555"),
                   label=f"{n} tasks")
    ax[1].set_xticks(range(len(ccs))); ax[1].set_xticklabels(xl)
    ax[1].set_xlabel("charging cap (x peak solar surplus); generation uncapped")
    ax[1].set_ylabel("V2G saving vs charge-only (%), matched instances")
    ax[1].set_title("(b) tight charging caps clip V2G's value")
    ax[1].legend(fontsize=10, title="fleet size")
    finish(fig, "fig_8_16_caps.png")
    GALLERY.append("\n![fig 8.16](fig_8_16_caps.png)\n")
    caption("Figure 8.16",
        "CORRECTED infrastructure frontier (overnight13 FOURCAPS: Phase-I "
        "initialization, 25 kWh lattice, four arms). (a) At 120 tasks the two "
        "storage-less arms (charge-only AND the V2G fleet without stationary "
        "storage) are Phase-I-certified infeasible at caps 1.0-1.1x and produce "
        "no incumbent at 1.2x, while both storage arms operate at every cap at "
        "nearly flat cost; the dividing ingredient is purchasable storage, not "
        "V2G. At 20 tasks every arm stays feasible at every cap (economic-only "
        "penalty ~6x vs the storage arms at this solar level); 60 tasks is the "
        "transition (~2x, one feasible seed at the 1.0x cap). (b) LEGACY panel "
        "(overnight4, 50 kWh): matched charging-cap value clipping; to be "
        "refreshed by the CHARGECAPS study.")

# %% Figure 8.17 -- pack size: capacity knob + substitution across workloads
pk17 = []
for _p in _glob.glob(os.path.join(ARX, "overnight4_pack_s*.json")):
    pk17 += json.load(open(_p))
pk2 = []
for _p in _glob.glob(os.path.join(ARX, "overnight11_pack2_s*.json")):
    pk2 += json.load(open(_p))
if pk17:
    pidx17 = {(r["G"], r["rho"], r["pv"], r["n_tasks"], r["seed"], r["scenario"]): r
              for r in pk17}
    fig, ax = plt.subplots(1, 2, figsize=(12.5, 4.4), constrained_layout=True)
    GS17 = [3.5, 7.0, 10.5, 14.0]
    for pv, c in ((2.0, "#2E75B6"), (4.0, "#16a085")):
        vs = []
        for G in GS17:
            v = []
            for (g_, rh, p, n, sd, sc), r in pidx17.items():
                if (g_, rh, p) != (G, 1.75, pv) or sc != "solar":
                    continue
                w = pidx17.get((g_, rh, p, n, sd, "v2g_fleet"))
                if w:
                    v.append(100 * (r["total"] - w["total"]) / r["total"])
            vs.append(float(np.mean(v)) if v else np.nan)
        ax[0].plot([g * 100 for g in GS17], vs, "-o", ms=5, color=c,
                   label=f"{pv:g}x solar")
    ax[0].axvline(700, ls=":", color="#888", lw=1)
    ax[0].set_xlabel("truck pack size (kWh)")
    ax[0].set_ylabel("fleet-only V2G saving vs charge-only\n(% of total daily cost)")
    ax[0].set_title("bigger packs raise fleet-as-storage value, with saturation")
    ax[0].legend(fontsize=10)
    if pk2:
        for n, c in ((8, "#c0392b"), (60, "#2E75B6"), (120, "#16a085")):
            bs = []
            for G in GS17:
                b = [r["batteries"] for r in pk2 if r["G"] == G and r["n_tasks"] == n
                     and r["pv"] == 2.0 and r["scenario"] == "v2g" and r.get("feasible")]
                bs.append(float(np.mean(b)) if b else np.nan)
            ax[1].plot([g * 100 for g in GS17], bs, "-o", ms=5, color=c,
                       label=f"{n} tasks")
        ax[1].axvline(700, ls=":", color="#888", lw=1)
        ax[1].set_xlabel("truck pack size (kWh)")
        ax[1].set_ylabel("stationary batteries bought (V2G, mean over draws)")
        ax[1].set_title("pack x workload: the substitution at 8-120 tasks (2x solar)")
        ax[1].legend(fontsize=10)
    finish(fig, "fig_8_17_pack.png")
    GALLERY.append("\n![fig 8.17](fig_8_17_pack.png)\n")
    caption("Figure 8.17",
        "The truck pack as the fleet-as-storage capacity knob. Left: fleet-only "
        "V2G value vs pack size (8-120 tasks pooled, two task draws per size, "
        "350 kW charging; stationary-battery cost held fixed per kWh). Right: the "
        "pack x workload interaction from the dense grid (8-200 tasks, three task "
        "draws, 2x solar): stationary-battery purchases fall as packs grow at "
        "every workload; the fleet-as-storage substitution is not a small-fleet "
        "artifact.")

# %% Figure 8.18 -- SCHED3 + THEORY: the retiming verdict, confound-free
s318 = []
for _p in _glob.glob(os.path.join(ARX, "overnight10_sched3_s*.json")):
    s318 += json.load(open(_p))
th18 = []
for _p in _glob.glob(os.path.join(ARX, "overnight10_theory_s*.json")):
    th18 += json.load(open(_p))
if s318:
    FAMS18 = ["uniform14", "uniform10", "siesta14", "siesta10", "midday6"]
    FLAB18 = {"uniform14": "uniform\n(14h)", "uniform10": "uniform\n(10h)",
              "siesta14": "siesta\n(14h)", "siesta10": "siesta\n(10h)",
              "midday6": "midday\n(6h)"}
    SC18 = [("solar", "#e08020", "charge-only"), ("v2g_fleet", "#16a085", "V2G trucks only"),
            ("v2g", "#2E75B6", "full V2G")]
    fig, ax = plt.subplots(1, 2, figsize=(12.8, 4.4), constrained_layout=True)
    W = 0.25
    for k, (scen, c, lab) in enumerate(SC18):
        ys = []
        for f in FAMS18:
            v = [r["g_units"] / 10 for r in s318 if r["fam"] == f and not np.isfinite(r["kcap"])
                 and r["scenario"] == scen and r.get("feasible")]
            ys.append(float(np.mean(v)) if v else np.nan)
        ax[0].bar([i + (k - 1) * W for i in range(len(FAMS18))], ys, W * 0.92, color=c, label=lab)
    ax[0].set_xticks(range(len(FAMS18))); ax[0].set_xticklabels([FLAB18[f] for f in FAMS18])
    ax[0].set_ylabel("daily fossil generation (MWh, mean over grid)")
    ax[0].set_title("(a) equal-width windows included: the siesta still never wins")
    ax[0].legend(fontsize=10)
    if th18:
        ys = [float(np.mean([r["g_units"] / 10 for r in th18 if r["fam"] == f and r["n_tasks"] == 80]))
              for f in FAMS18]
        ax[1].bar(range(len(FAMS18)), ys, 0.6, color="#9aa7b5")
        ax[1].set_xticks(range(len(FAMS18))); ax[1].set_xticklabels([FLAB18[f] for f in FAMS18])
        ax[1].set_ylabel("daily fossil generation (MWh, 80 tasks)")
        sp = max(ys) - min(ys)
        ax[1].set_title(f"(b) ablation: no deadheads, free trucks -- spread {sp:.3f} MWh")
        ax[1].text(0.5, 0.9, "with the fleet-size channel removed,\nall five timetables burn identical fuel",
                   ha="center", transform=ax[1].transAxes, fontsize=10.5, color="#444")
    finish(fig, "fig_8_18_sched.png")
    GALLERY.append("\n![fig 8.18](fig_8_18_sched.png)\n")
    caption("Figure 8.18",
        "The retiming verdict with the width confound removed. (a) Five timetable "
        "families, including a 14-start-hour siesta matching uniform's width, at "
        "uncapped charging: the siesta never has the lowest fuel in any regime, and "
        "for storage-poor fleets (charge-only, trucks-only) the winner is the "
        "midday-concentrated family, the opposite of the folk rule. (b) The "
        "mechanism, isolated: zeroing deadhead energy and truck cost collapses the "
        "spread across all five families to numerically zero, so with storage "
        "available the energy layer is timetable-invariant and every scheduling "
        "effect flows through fleet size and its deadhead overhead.")

# %% Figure 8.19 -- OUT3: fixed-asset contingency ladder, window-resolved fifths
o19 = []
for _p in _glob.glob(os.path.join(ARX, "overnight11_out3_s*.json")):
    o19 += json.load(open(_p))
if o19:
    DER19 = [1.0, 0.8, 0.6, 0.5, 0.4, 0.2, 0.0]
    XL19 = ["no\noutage", "-20%", "-40%", "-50%", "-60%", "-80%", "total\nloss"]
    SC19 = (("solar", "#e08020", "charge-only"),
            ("v2g_fleet", "#16a085", "V2G trucks only"),
            ("v2g", "#2E75B6", "full V2G"))
    fig, ax = plt.subplots(1, 2, figsize=(11.2, 4.2), constrained_layout=True)
    for a, wins, ttl in ((ax[0], ("eve4h", "eve8h"), "(a) evening windows (17-21h / 14-22h)"),
                         (ax[1], ("morn4h",), "(b) morning window (5-9h)")):
        for scen, c, lab in SC19:
            ys = []
            for d in DER19:
                rows = [r for r in o19 if r["win"] in wins and abs(r["derate"] - d) < .01
                        and r["scenario"] == scen]
                ys.append(100 * sum(1 for r in rows if r.get("feasible")) / max(len(rows), 1))
            a.plot(range(len(DER19)), ys, "-o", ms=5, color=c, label=lab)
        a.set_xticks(range(len(DER19))); a.set_xticklabels(XL19, fontsize=10)
        a.set_ylabel("% of instances with a feasible schedule"); a.set_ylim(-4, 104)
        a.set_title(ttl, fontsize=10); a.legend(fontsize=10)
    finish(fig, "fig_8_19_outage2.png")
    GALLERY.append("\n![fig 8.19](fig_8_19_outage2.png)\n")
    caption("Figure 8.19",
        "Fixed-asset contingency ladder at fifths resolution, window-resolved "
        "(12 instances per morning point, 24 per evening point: 2 fleet sizes x "
        "2 solar levels x 3 task draws x windows). Evening outages need "
        "bidirectionality: charge-only and trucks-only fleets die below -20% "
        "derates, V2G holds 92% at -20% and half through total loss. Morning "
        "outages before the solar day are survivable by ANY fleet down to -60% "
        "(the base morning load is low and packs are full), and V2G extends "
        "even that to -80%. (c) Survivors pay a few percent.")

# %% Figure 8.20 -- END3: the fuel floor (fixed daily budget, budgets to 1.4x)
e20d = []
for _p in (_glob.glob(os.path.join(ARX, "overnight11_end3_s*.json"))
           + _glob.glob(os.path.join(ARX, "overnight12_end4_s*.json"))):
    e20d += json.load(open(_p))
if e20d:
    import collections as _cl20
    idx20 = _cl20.defaultdict(list)
    for r in e20d:
        idx20[(r["scenario"], r["pv"], r["n_tasks"], r["seed"])].append(r)
    fig, ax = plt.subplots(figsize=(8.2, 4.4), constrained_layout=True)
    cells20 = [(1.5, 20), (1.5, 60), (2.5, 20), (2.5, 60)]
    xt = [f"{pv}x solar\n{n} tasks" for pv, n in cells20]
    CEN = 1.55                                        # censored bars drawn AT this level, hatched
    ICE20 = 3.3                                       # measured drivetrain disadvantage

    def _floor20(scen, pv, n):
        fmins = [min([r["frac"] for r in idx20[(scen, pv, n, sd)] if r.get("feasible")],
                     default=np.nan) for sd in (0, 1, 2)]
        return float(np.nanmean(fmins)) if np.isfinite(np.nanmean(fmins)) else np.nan

    for k, (pv, n) in enumerate(cells20):
        rr0 = next(r for r in idx20[("v2g", pv, n, 0)])
        _base = rr0["budget_units"] / rr0["frac"]
        vsp_floor = 1.0 + ICE20 * rr0["traction_mwh"] * 10 / _base
        ax.bar(k - 0.34, vsp_floor, 0.30, color="#888888",
               label="ICE fleet (analytic floor)" if k == 0 else None)
        ax.annotate(f"{vsp_floor:.1f}", (k - 0.34, vsp_floor + 0.02), ha="center",
                    fontsize=10.5, color="#555")
        v = _floor20("v2g", pv, n)
        ax.bar(k + 0.02, v, 0.30, color="#2E75B6", label="full V2G" if k == 0 else None)
        ax.annotate(f"{v:.2f}", (k + 0.02, v + 0.02), ha="center", fontsize=10.5, color="#2E75B6")
        s = _floor20("solar", pv, n)
        if np.isfinite(s):
            ax.bar(k + 0.34, s, 0.30, color="#e08020",
                   label="charge-only" if k == 0 else None)
            ax.annotate(f"{s:.2f}", (k + 0.34, s + 0.02), ha="center", fontsize=10.5, color="#b06010")
        else:
            ax.bar(k + 0.34, CEN, 0.30, color="#e08020")
            ax.annotate("$\\geq$ 1.4", (k + 0.34, CEN + 0.02), ha="center", fontsize=10.5, color="#b06010")
    ax.axhline(1.0, ls=":", color="#888", lw=1)
    ax.text(0.01, 1.01, "no-fleet baseline burn", fontsize=10, color="#666",
            transform=ax.get_yaxis_transform())
    ax.set_xticks(range(len(cells20))); ax.set_xticklabels(xt)
    ax.set_ylabel("minimum feasible daily fuel (fraction of no-fleet baseline)")
    ax.set_ylim(0, 4.25)
    ax.set_title("the fuel floor: V2G fleets run the base on less fuel than no fleet at all")
    ax.legend(fontsize=10.5, loc="upper right")
    finish(fig, "fig_8_20_endurance.png")
    GALLERY.append("\n![fig 8.20](fig_8_20_endurance.png)\n")
    caption("Figure 8.20",
        "Fuel endurance under a hard daily budget, budgets swept 0.05-1.4x. Bars "
        "show the smallest budget, as a fraction of the no-fleet baseline burn, at "
        "which any feasible schedule exists (mean over three task draws). "
        "Charge-only floors are now MEASURED at 20 tasks: 1.2x baseline; at 60 "
        "tasks they exceed 1.4x (censored). Electrifying without bidirectionality "
        "strictly shortens a fuel stock's endurance. Full V2G runs the entire "
        "base+fleet on 0.80x at modest solar and 0.05x at 2.5x solar with a small "
        "fleet; at 1.5x/60 the fleet traction outruns the surplus and V2G needs "
        "1.3x. ICE floors are analytic: base burn + 3.3x traction.")

# %% Figure 8.21 -- WCITIES: same array, five skies
w21 = []
for _p in _glob.glob(os.path.join(ARX, "overnight9_wcities_s*.json")):
    w21 += json.load(open(_p))
if w21:
    widx21 = {(r["city"], r["date"], r["pv"], r["scenario"]): r for r in w21 if r.get("feasible")}
    wx21 = load(ARX, "overnight_weather.json") or []
    CITIES21 = [("socal", "SoCal\n(benchmark)"), ("gulf_desert", "Gulf desert\n(UAE)"),
                ("seoul", "Seoul"), ("keflavik", "Keflavik\n(Iceland)"), ("tromso", "Tromso")]
    fig, ax = plt.subplots(figsize=(9.2, 4.5), constrained_layout=True)
    for j, (pv, c) in enumerate(((2.0, "#2E75B6"), (3.0, "#16a085"))):
        xs, mu, p10, p90 = [], [], [], []
        for i, (key, lab) in enumerate(CITIES21):
            if key == "socal":
                v = [r["v2g_vs_solar_pct"] for r in wx21
                     if r.get("pv") == pv and "v2g_vs_solar_pct" in r]
            else:
                days = {k[1] for k in widx21 if k[0] == key and k[2] == pv}
                v = [100 * (widx21[(key, d, pv, "solar")]["total"] - widx21[(key, d, pv, "v2g")]["total"])
                     / widx21[(key, d, pv, "solar")]["total"]
                     for d in days if (key, d, pv, "solar") in widx21 and (key, d, pv, "v2g") in widx21]
            if not v:
                xs.append(np.nan); mu.append(np.nan); p10.append(np.nan); p90.append(np.nan)
                continue
            xs.append(i + (j - 0.5) * 0.22); mu.append(np.mean(v))
            p10.append(np.percentile(v, 10)); p90.append(np.percentile(v, 90))
        ax.errorbar(xs, mu, yerr=[np.array(mu) - np.array(p10), np.array(p90) - np.array(mu)],
                    fmt="o", ms=7, capsize=5, color=c, label=f"{pv:g}x panels")
    ax.set_xticks(range(len(CITIES21))); ax.set_xticklabels([lab for _, lab in CITIES21], fontsize=10.5)
    ax.axhline(0, color="#888", lw=0.7)
    ax.set_ylabel("V2G saving vs charge-only (% of daily cost)")
    ax.set_title("same array, five skies: annual mean and 10th-90th percentile days (2023)")
    ax.legend(fontsize=10)
    finish(fig, "fig_8_21_wcities.png")
    GALLERY.append("\n![fig 8.21](fig_8_21_wcities.png)\n")
    caption("Figure 8.21",
        "The 365-day study replayed on four real 2023 climates with the identical "
        "array (each city's hourly ERA5 irradiance drives the same panels).  "
        "Mean daily V2G value with 10th-90th percentile day bars: a Gulf desert "
        "base earns firm value (45% mean, 15% on the 10th-percentile day at 2x; "
        "75%/53% at 3x), Seoul earns substantial but seasonal value, London "
        "roughly halves it, and a Tromso-latitude base earns little and nothing "
        "for much of the year. Climate enters exactly as the endowment gamma "
        "predicts, day by day.")

# %% Figure 8.22 -- SATFIX2: Theorem 1's concavity under fixed assets
sf22 = []
for _p in _glob.glob(os.path.join(ARX, "overnight9_satfix2_s*.json")):
    sf22 += json.load(open(_p))
if sf22:
    fig, ax = plt.subplots(figsize=(7.6, 4.4), constrained_layout=True)
    for n, c in ((20, "#2E75B6"), (60, "#16a085")):
        pvs = sorted({r["pv"] for r in sf22})
        med = [float(np.median([r["g_units"] / 10 for r in sf22 if r["pv"] == pv
                                and r["n_tasks"] == n and r["scenario"] == "v2g"
                                and r.get("feasible")]) or np.nan) for pv in pvs]
        ax.plot(pvs, med, "-o", ms=5, color=c, label=f"{n} tasks (assets fixed at 2.0x sizing)")
    ax.set_xlabel("PV build-out (x design size)")
    ax.set_ylabel("daily fossil generation (MWh, V2G)")
    ax.set_title("fixed fleet and storage: absorption saturates, fuel bends")
    ax.legend(fontsize=10)
    finish(fig, "fig_8_22_satfix2.png")
    GALLERY.append("\n![fig 8.22](fig_8_22_satfix2.png)\n")
    caption("Figure 8.22",
        "The diminishing-returns signature of Theorem 1, made visible by fixing "
        "the residual network: fleets and batteries are sized once at 2.0x solar "
        "and then held fixed while PV grows. Fuel falls at slope ~1 while the "
        "fixed storage can still reach unserved deficit, then bends and "
        "plateaus as the network's deliverability caps bind, exactly the "
        "concave fixed-profile mechanism (with endogenous assets the optimizer "
        "keeps buying batteries and the curve stays linear to the floor).")

# %% Figure 8.23 -- STOCH: committing a schedule under a year of weather
st23 = []
for _p in _glob.glob(os.path.join(ARX, "overnight10_stoch_s*.json")):
    st23 += json.load(open(_p))
if st23:
    fig, ax = plt.subplots(1, 2, figsize=(12.8, 4.4), constrained_layout=True)
    for j, pv in enumerate((2.0, 3.0)):
        ws = {r["date"]: r["total"] for r in st23 if r["kind"] == "ws" and r["pv"] == pv and r.get("feasible")}
        wsm = float(np.mean(list(ws.values())))
        cands = sorted({r["cand"] for r in st23 if r["kind"] == "eval"})
        labs, vals = [], []
        for cand in ["annual"] + [c for c in cands if c != "annual"]:
            ev = {r["date"]: r["total"] for r in st23 if r["kind"] == "eval" and r["cand"] == cand
                  and r["pv"] == pv and r.get("feasible")}
            days = [d for d in ev if d in ws]
            labs.append(cand); vals.append(float(np.mean([ev[d] for d in days])))
        cols = ["#7d3c98" if l == "annual" else "#2E75B6" for l in labs]
        ax[j].bar(range(len(labs)), vals, color=cols)
        ax[j].axhline(wsm, ls=":", color="#888888", lw=1.2,
                      label=f"perfect foresight, annual mean (${wsm:,.0f})")
        ws_m = []
        for l in labs:
            if l == "annual":
                ws_m.append(np.nan); continue
            mdays = [d for d in ws if d[5:7] == l.replace("m", "")]
            ws_m.append(float(np.mean([ws[d] for d in mdays])) if mdays else np.nan)
        ax[j].plot(range(len(labs)), ws_m, "--", color="#c0392b", lw=1.5, marker="v", ms=4,
                   label="perfect foresight within that month (seasonal floor)")
        ax[j].set_xticks(range(len(labs)))
        ax[j].set_xticklabels([l.replace("m", "") if l != "annual" else "ann." for l in labs],
                              fontsize=10)
        ax[j].set_xlabel("design day used for the committed schedule (month)")
        ax[j].set_ylabel("expected daily cost over 365 real days ($)")
        ax[j].set_title(f"({'ab'[j]}) {pv:g}x panels: best commit +"
                        f"{100 * (min(vals) - wsm) / wsm:.1f}% vs clairvoyance")
        ax[j].legend(fontsize=10)
    ym = max(a.get_ylim()[1] for a in ax)
    for a in ax:
        a.set_ylim(0, ym)
    finish(fig, "fig_8_23_stoch.png")
    GALLERY.append("\n![fig 8.23](fig_8_23_stoch.png)\n")
    caption("Figure 8.23",
        "Committing schedules under uncertain weather: the truck routes, their "
        "charging plans, and the battery count are fixed on a candidate design "
        "day; on each of the 365 real days only the stationary battery dispatch "
        "and fossil generation re-optimize. Bars are expected daily cost per "
        "design-day candidate (teal = best; purple = the annual-mean day); the "
        "dashed line is the wait-and-see bound (full foresight, re-optimized "
        "daily). The best committed schedule lands within 5.6% (2x) and 9.7% "
        "(3x) of clairvoyance, so the deterministic backbone plus trivial "
        "recourse is nearly optimal; but the CHOICE of design day carries real "
        "risk: the annual-mean day gives +19%/+12%, and a winter design day up "
        "to +48%/+98%. Summer-designed schedules commit generous storage and "
        "charging plans that winter days simply scale back.")

# %% Parameter provenance -- a source for every empirical anchor
PROV = [
    ("fossil generation cost", "$0.20-1.00/kWh",
     "remote island / military-base diesel generation; the setting is a San Nicolas-style isolated base"),
    ("EV truck daily cost", "1.0-2.0x ICE",
     "ICCT (2023), TCO of alternative-powertrain long-haul trucks: BE truck MSRPs 1.3-2.4x diesel, "
     "TCO parity approaching 2030 (theicct.org)"),
    ("EV drivetrain efficiency", "2.5-3.5x diesel",
     "fleet telemetry: Class-8 BEVs ~1.7-2.1 kWh/mi vs ~6-7 mpg diesel at 37.7 kWh/gal "
     "(NACFE Run on Less - Electric)"),
    ("stationary battery cost", "$26-51/day per 700 kWh",
     "LFP installed capex $200-400/kWh amortized over 15 years"),
    ("bidirectional charger premium", "$0-8/truck-day",
     "V2G hardware $3-8k over unidirectional (industry guides, 2025-26); fleet DC units ~$15k "
     "(e.g. Fermata FE-20); DOE FEMP bidirectional-charging program; amortized 5-10 y"),
    ("cycling degradation", "$0-0.13/kWh discharged",
     "Peterson, Apt & Whitacre (2010), J. Power Sources 195(8): classic V2G cell-degradation "
     "measurements; Sagaria, van der Kam & Bostrom (2025), Applied Energy 377: V2G adds 9-14% "
     "degradation over 10 years, fair compensation EUR 70-132/MWh (~$0.07-0.13/kWh) -- our sweep "
     "extends to $0.13; Uddin et al. (2017), Energy: smart control can reduce net degradation, "
     "consistent with our finding that the optimizer cycles less rather than pay"),
    ("solar irradiance", "365 real days (2023)",
     "Open-Meteo ERA5 archive, 33.25N 119.5W (CC-BY 4.0), hourly GHI"),
    ("charge rate", "100-350 kW",
     "commercial DC fast charging; 350 kW is today's deployed high end for trucks"),
    ("task energy (eps)", "50-300 kWh per task",
     "duty-cycle span: light shuttle to heavy off-road/patrol with auxiliary loads; "
     "the original paper's own two conversion factors (10 vs 33 kWh/gal) embed the 3.3x ratio"),
]
table("**Parameter provenance** -- every empirical anchor used in this study:\n\n"
      + md_table(["parameter", "range used", "source / anchor"], PROV))
GALLERY.append("")


# %% write GALLERY.md + caption index
out = os.path.join(FIG, "GALLERY.md")
open(out, "w").write("\n".join(GALLERY) + "\n")
print(f"gallery -> {os.path.relpath(out, ROOT)}   ({len(CAPTIONS)} captioned items)")
print("\n--- caption index (the Section-8 outline) ---")
for label, text in CAPTIONS:
    print(f"  {label}: {text.split('. ')[0]}.")
