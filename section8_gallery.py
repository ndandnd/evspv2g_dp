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


def finish(fig, fname: str):
    """Save the figure; show inline when interactive, close when scripted."""
    fig.savefig(os.path.join(FIG, fname), dpi=140)
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
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
    for data, c, lab in ((e20, "#2E75B6", "eps=2.0"), (e15 or [], "#e08020", "eps=1.5")):
        if data:
            xs = [r["trips"] for r in data]
            ax[0].plot(xs, [r["cg_s"] for r in data], "-o", color=c, label=lab)
            ax[1].plot(xs, [r["pricing_pct"] for r in data], "-o", color=c, label=lab)
    ax[0].set_xlabel("tasks"); ax[0].set_ylabel("column-generation time (s)")
    ax[0].annotate("original MILP pricing:\n8.3 h at 450 tasks", xy=(450, max(r["cg_s"] for r in e20)),
                   xytext=(0.45, 0.75), textcoords="axes fraction", fontsize=9,
                   arrowprops=dict(arrowstyle="->", lw=0.8))
    ax[0].legend(); ax[0].set_title("solve time (DP pricing, open-source)")
    ax[1].axhline(95, ls=":", color="#c0392b")
    ax[1].text(0.03, 0.9, "original: pricing >95% of runtime", transform=ax[1].transAxes, fontsize=9, color="#c0392b")
    ax[1].set_xlabel("tasks"); ax[1].set_ylabel("pricing share of CG time (%)")
    ax[1].set_ylim(0, 100); ax[1].legend(); ax[1].set_title("where the time goes")
    finish(fig, "fig_8_1_scalability.png")
    GALLERY.append("\n![fig 8.1](fig_8_1_scalability.png)\n")
    caption("Figure 8.1",
        "Column-generation solve time (left) and the share of it spent in pricing (right) "
        "on the original instance family, 10-450 tasks. With the labeling DP, pricing never "
        "exceeds half the (seconds-scale) runtime; in the original MILP-pricing "
        "implementation it exceeded 95% of an hours-scale runtime. The method's bottleneck "
        "becomes the restricted master LP -- exactly the component that Proposition 2's "
        "continuous-energy result keeps small.")

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
caption("Table 8.3",
    "The original's Table 2 (fuel in gallons; negative = net energy export) next to this "
    "implementation run in the original's free-start setting and in the revised cyclic "
    "model. Free start reproduces the original's phenomena -- net export and stationary "
    "batteries -- because each vehicle's initial charge is free energy; the cyclic model "
    "prices that energy and the export vanishes. Every level difference between the "
    "columns is attributable to this single modeling choice (plus the original's "
    "documented final-master battery-cost slip).")

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
    NAMES = {"vsp": "VSP (ICE)", "ev": "EVSP (solar-blind)", "solar": "EVSP-Solar", "v2g": "EVSP-V2G"}
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
    labels = []
    for pv in pvs:
        r0 = next(x for x in rf if x["pv"] == pv)
        labels.append(f"{r0['surplus_mwh']} MWh/day\nsurplus")
    ax.set_xticks(range(len(pvs))); ax.set_xticklabels(labels)
    ax.set_ylabel("fleet-attributable fossil energy (MWh/day)\n(negative = fleet REDUCES base fossil)")
    ax.set_title("fossil energy by regime as solar grows (cyclic model, ICE at 3.3x thermal)")
    ax.legend()
    finish(fig, "fig_8_2_regime_fuel.png")
    GALLERY.append("\n![fig 8.2](fig_8_2_regime_fuel.png)\n")
    table(md_table(["solar surplus", "regime", "incremental fossil (MWh)", "trucks", "batteries"], tbl_rows))
    caption("Figure 8.2 (and table)",
        "Fossil energy attributable to the fleet -- total generation minus the no-fleet "
        "baseline -- by regime and solar level, under the honest cyclic model with the "
        "measured 3.3x ICE drivetrain convention. At scarce solar the four regimes are "
        "ordered by efficiency alone; as the surplus grows, solar-aware charging first "
        "erases the EV fleet's own fossil draw, and V2G then turns the fleet NEGATIVE: "
        "the vehicles displace base-load fossil they never consumed, an honest, "
        "fully-paid-for analogue of the original paper's net export. The solar-blind "
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
        for tier, c, lab in (("vsp", "#888888", "VSP (ICE)"), ("ev", "#7d3c98", "EVSP (plain EV)"),
                             ("solar", "#e08020", "EVSP-Solar"), ("v2g", "#2E75B6", "EVSP-V2G")):
            ax[0].plot(xs, [r[f"{tier}_total"] for r in sweep], "-o", color=c, label=lab)
        ax[0].set_xlabel("R = daily solar surplus / fleet traction"); ax[0].set_ylabel("total daily cost ($)")
        ax[0].legend(); ax[0].set_title("total cost by technology tier")
        for key, c, lab in (("electrify_value", "#7d3c98", "electrify (VSP->EV)"),
                            ("solar_value", "#e08020", "+ solar-aware charging"),
                            ("v2g_value", "#2E75B6", "+ V2G")):
            ax[1].plot(xs, [r[key] for r in sweep], "-o", color=c, label=lab)
        ax[1].axhline(0, color="k", lw=0.7)
        ax[1].set_xlabel("R = daily solar surplus / fleet traction"); ax[1].set_ylabel("marginal value ($/day)")
        ax[1].legend(); ax[1].set_title("marginal value of each step")
        finish(fig, "fig_8_3_tiers.png")
        GALLERY.append("\n![fig 8.3](fig_8_3_tiers.png)\n")
        caption("Figure 8.3",
            "The technology ladder VSP -> EVSP -> EVSP-Solar -> EVSP-V2G (60 tasks, EV truck "
            "premium 1.5x, drivetrain efficiency 3.3x, fuel $0.40/kWh). Left: total daily cost "
            "by tier as the solar surplus grows. Right: the three marginal values are nearly "
            "separable -- electrification's value is flat in R (it scales with fuel burned), "
            "solar-aware charging is worth money from the first surplus kWh and saturates once "
            "the fleet's traction is covered (R ~ 1), and V2G switches on near R ~ 1 and keeps "
            "growing where solar-awareness saturates: bidirectionality is what monetizes "
            "surplus beyond the fleet's own needs.")

# %% Figure 8.4 -- when does electrification pay?
if tt:
    sens = [r for r in tt if r.get("pv") == 2.0 and r.get("points") == 3 and "electrify_value" in r]
    prems = sorted({r["ev_premium"] for r in sens})
    effs = sorted({r["ice_eff"] for r in sens})
    if len(prems) >= 2 and len(effs) >= 2:
        fig, ax = plt.subplots(figsize=(7, 4.2), constrained_layout=True)
        W = 0.8 / len(prems)
        for j, prem in enumerate(prems):
            xs, ys = [], []
            for i, eff in enumerate(effs):
                r = next((r for r in sens if r["ev_premium"] == prem and r["ice_eff"] == eff), None)
                if r:
                    xs.append(i + (j - (len(prems) - 1) / 2) * W); ys.append(r["electrify_value"])
            ax.bar(xs, ys, W * 0.95, label=f"EV premium {prem}x")
        ax.axhline(0, color="k", lw=0.8)
        # break-even efficiency per premium (linear in eff; slope = c_g x traction)
        be_txt = []
        for prem in prems:
            pr = sorted([(r["ice_eff"], r["electrify_value"]) for r in sens if r["ev_premium"] == prem])
            if len(pr) >= 2:
                (x1, y1), (x2, y2) = pr[0], pr[-1]
                slope = (y2 - y1) / (x2 - x1)
                if slope > 0:
                    be_txt.append(f"premium {prem}x: break-even at {x1 - y1 / slope:.2f}x")
        if be_txt:
            ax.text(0.02, 0.97, "\n".join(be_txt), transform=ax.transAxes, va="top",
                    fontsize=9, bbox=dict(boxstyle="round", fc="#f7f7f7", ec="#999"))
        ax.set_xticks(range(len(effs))); ax.set_xticklabels([f"{e}x" for e in effs])
        ax.set_xlabel("drivetrain efficiency: kWh of diesel an ICE burns per kWh an EV uses\n"
                      "(1x = equal-energy bookkeeping; measured trucks ~2.5-3.5x)")
        ax.set_ylabel("$ saved per day by electrifying (VSP cost - plain-EV cost)")
        ax.set_title("when does electrification pay?  (negative = EVs cost more; solar plays no role here)")
        ax.legend()
        finish(fig, "fig_8_4_electrify.png")
        GALLERY.append("\n![fig 8.4](fig_8_4_electrify.png)\n")
        caption("Figure 8.4",
            "The electrification decision isolated. X-axis: how many kWh of diesel an ICE "
            "truck burns to do the work an EV does on one kWh (an engine-physics ratio, "
            "nothing to do with solar); 1x is the equal-energy bookkeeping convention, "
            "measured heavy trucks are ~2.5-3.5x. Y-axis: dollars per day saved by "
            "replacing the ICE fleet with a plain-EV fleet; negative bars mean the EV "
            "fleet costs MORE (bigger fleet + truck premium, no efficiency edge). "
            "Break-even is at 1.40x / 1.53x / 1.68x for truck premiums of 1.0x / 1.5x / "
            "2.0x -- comfortably below reality, so electrification pays robustly once "
            "energy is accounted honestly. Solar-awareness and V2G values are unchanged "
            "across every bar: the three deployment decisions are independent.")

# %% Figure 8.5 -- THE money figure: the R-collapse across everything
pg = load(ARX, "planning_grid.json") or []
sl = load(ARX, "scale_ladder.json") or []
pr = load(ARX, "profile_robustness.json") or []
pts = []
for r in pg:
    if (r.get("cg"), r.get("cb"), r.get("rho")) == (40.0, 36.0, 1.75) and "v2g_vs_solar_pct" in r:
        pts.append((r["ratio"], r["v2g_vs_solar_pct"], "planning grid (demand/intensity/solar knobs)"))
for r in sl:
    if "v2g_vs_solar_pct" in r:
        pts.append((r["ratio"], r["v2g_vs_solar_pct"], "scale ladder (20-560 tasks, co-scaled)"))
for r in pr:
    if "v2g_vs_solar_pct" in r:
        pts.append((r["ratio"], r["v2g_vs_solar_pct"], "reshaped profiles (5 shapes)"))
if len(pts) >= 5:
    fig, ax = plt.subplots(figsize=(8.5, 5), constrained_layout=True)
    ax.axvspan(0, 1.0, color="#f2f2f2")
    for x0, lab in ((0.45, "V2G adds ~nothing"), (1.6, "transition"), (3.0, "V2G transformative")):
        ax.text(x0, 0.94, lab, transform=ax.get_xaxis_transform(), ha="center", fontsize=9, color="#666")
    # rolling-median trend of all points
    allp = sorted(pts)
    xs_a = np.array([p[0] for p in allp]); ys_a = np.array([p[1] for p in allp])
    k = max(3, len(allp) // 8)
    xt = [np.median(xs_a[max(0, i - k):i + k]) for i in range(len(allp))]
    yt = [np.median(ys_a[max(0, i - k):i + k]) for i in range(len(allp))]
    ax.plot(xt, yt, "-", color="#c0392b", lw=2, alpha=0.7, zorder=1, label="trend (rolling median)")
    marks = {"planning grid (demand/intensity/solar knobs)": ("o", "#2E75B6"),
             "scale ladder (20-560 tasks, co-scaled)": ("s", "#888888"),
             "reshaped profiles (5 shapes)": ("^", "#2e9e3f")}
    for src, (m, c) in marks.items():
        sub = [(x, y) for x, y, s in pts if s == src]
        if sub:
            ax.scatter(*zip(*sub), marker=m, color=c, alpha=0.75, label=src)
    ax.set_xlabel("R = daily solar surplus / fleet traction")
    ax.set_ylabel("V2G savings vs charge-only (%)")
    ax.set_title("one curve: V2G value collapses onto R across every knob, scale, and profile shape")
    ax.legend(loc="lower right", fontsize=9)
    finish(fig, "fig_8_5_collapse.png")
    GALLERY.append("\n![fig 8.5](fig_8_5_collapse.png)\n")
    caption("Figure 8.5",
        "The central planning result, one dot at a time: each marker is one complete "
        "microgrid design study -- a specific number of tasks (20 to 560), task energy, "
        "PV size, and demand/solar shape -- solved to optimality TWICE, with and without "
        "V2G; its height is the cost V2G saved. Dozens of very different microgrids all "
        "land on one curve when plotted against a single number, R = (daily solar energy "
        "left over after serving the base load) / (energy the fleet's driving needs). "
        "Consequence: to estimate what V2G is worth for a candidate site, compute R from "
        "two energy audits -- no schedule details needed. V2G adds nothing below R ~ 0.3 "
        "(any surplus is eaten by charging), switches on near R ~ 1 (surplus exceeds what "
        "driving absorbs), and approaches full fossil displacement above R ~ 2.5.")
else:
    print("  [skip] not enough data for the collapse figure")

# %% Figure 8.6 -- diminishing returns (Theorem 1's signature)
e3b = load(ARX, "exp3b_solar_pv.json")
if e3b:
    fig, ax = plt.subplots(figsize=(7, 4.2), constrained_layout=True)
    for eps_v, c in ((2.0, "#2E75B6"), (2.5, "#c0392b")):
        sub = sorted([r for r in e3b if r.get("eps") == eps_v and r.get("feasible")], key=lambda r: r["solar_mwh"])
        if sub:
            ax.plot([r["solar_mwh"] for r in sub], [r["fuel_kwh"] / 1000 for r in sub], "-o", color=c, label=f"eps={eps_v}")
    ax.set_xlabel("available daily solar (MWh)"); ax.set_ylabel("fossil fuel (MWh-equivalent)")
    ax.set_title("diminishing returns to solar (EVSP-V2G)")
    ax.legend()
    finish(fig, "fig_8_6_diminishing.png")
    GALLERY.append("\n![fig 8.6](fig_8_6_diminishing.png)\n")
    caption("Figure 8.6",
        "Fossil fuel versus available daily solar under EVSP-V2G. The marginal fuel "
        "displaced by each additional MWh of solar shrinks monotonically -- the empirical "
        "signature of the fixed-profile submodularity of Theorem 1: each additional unit "
        "of solar (and the storage that shifts it) captures less of the remaining "
        "displaceable fuel.")

# %% Figure 8.7 -- representative solution timeline (pre-rendered by recreate_arxiv)
tl = os.path.join(ARX, "exp4_timeline.png")
if os.path.exists(tl):
    if INTERACTIVE:
        from IPython.display import Image
        display(Image(filename=tl))
    GALLERY.append("\n![fig 8.7](../arxiv/exp4_timeline.png)\n")
    caption("Figure 8.7",
        "A representative EVSP-V2G solution on the original instance (60 tasks). Top: "
        "net microgrid demand (gold = solar surplus). Bottom: per-vehicle activity -- "
        "trucks charge on the free midday surplus (green), pay for residual charging "
        "in deficit hours (black), and discharge into the morning and evening peaks "
        "(red); the aggregate battery performs the same temporal arbitrage at scale.")
else:
    print("  [skip] missing results/arxiv/exp4_timeline.png")

# %% write GALLERY.md + caption index
out = os.path.join(FIG, "GALLERY.md")
open(out, "w").write("\n".join(GALLERY) + "\n")
print(f"gallery -> {os.path.relpath(out, ROOT)}   ({len(CAPTIONS)} captioned items)")
print("\n--- caption index (the Section-8 outline) ---")
for label, text in CAPTIONS:
    print(f"  {label}: {text.split('. ')[0]}.")
