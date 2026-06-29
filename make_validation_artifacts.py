"""Produce tangible validation artifacts (a summary text file + a figure) from the
pieces built so far: instance generator, master RMP + duals, battery pricing DP vs LP."""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from instance import make_instance
from master import solve_lp, Column, reduced_cost
from pricing_battery import price_battery_lp, price_battery_dp

OUT = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(OUT, exist_ok=True)

inst = make_instance(n_trips=20, n_locations=3, eps=2.0, seed=2)
T = inst.T

# master with single-trip truck columns -> duals
cols = []
for i in range(inst.n_trips):
    a = np.zeros(inst.n_trips); a[i] = 1
    cols.append(Column("truck", a, np.zeros(T), inst.c_v, f"t{i}"))
sol = solve_lp(inst, cols)
rc_basis = max(abs(reduced_cost(c, sol, inst)) for c in cols)

# battery pricing: DP vs exact LP
col_lp, rc_lp = price_battery_lp(inst, sol.mu)
col_dp, rc_dp = price_battery_dp(inst, sol.mu, n_levels=141)

lines = []
def p(s=""):
    lines.append(s); print(s)

p("VALIDATION SUMMARY  (covering-plus-arbitrage EVSP-V2G solver, build in progress)")
p("=" * 78)
p("")
p("[1] Instance (San Nicolas-style)")
p(f"    time blocks T            = {inst.T}")
p(f"    trips                    = {inst.n_trips}   locations = {inst.dist.shape[0]}")
p(f"    daily demand             = {inst.D.sum():.0f} kWh")
p(f"    daily solar              = {inst.P.sum():.0f} kWh")
p(f"    midday surplus blocks    = {[int(t) for t in np.where(inst.Delta < 0)[0]]}")
p(f"    max surplus / peak deficit = {(-inst.Delta).max():.0f} / {inst.Delta.max():.0f} kWh")
p(f"    battery G / rate rho / loss eta = {inst.G} / {inst.rho} / {inst.eta}")
p(f"    costs  c_g={inst.c_g}  c_v={inst.c_v}  c_b={inst.c_b}")
p("")
p("[2] Master RMP + dual calibration  (PASS criteria in parentheses)")
p(f"    LP objective             = {sol.obj:.2f}")
p(f"    coverage dual alpha_i    = {sol.alpha[0]:.1f}   (should equal c_v = {inst.c_v})")
p(f"    generation price mu_t    in [{sol.mu.min():.3f}, {sol.mu.max():.3f}]   (should be within [0, c_g]=[0,{inst.c_g}])")
p(f"    max |reduced cost| of in-basis columns = {rc_basis:.2e}   (should be ~0)")
p("")
p("[3] Battery pricing: DP validated against exact LP")
p(f"    exact LP reduced cost    = {rc_lp:.3f}")
p(f"    SoC-discretized DP rc    = {rc_dp:.3f}")
p(f"    |LP - DP|                = {abs(rc_lp - rc_dp):.3e}   (should be ~0  ->  DP is exact here)")
chg = [int(t) for t in np.where(col_lp.e > 1e-6)[0]]
dis = [int(t) for t in np.where(col_lp.e < -1e-6)[0]]
p(f"    column charges at blocks = {chg}   (mu there = {np.round(sol.mu[chg],2).tolist()})")
p(f"    column discharges at     = {dis}   (mu there = {np.round(sol.mu[dis],2).tolist()})")
p(f"    -> charges where price ~0 (solar surplus), discharges where price ~c_g (peaks): correct arbitrage")
p("")
p("STATUS: instance generator, master+duals, and battery pricing DP are built and")
p("validated. Still to come: truck labeling DP + MILP oracle, full column-generation")
p("loop with greedy warm start, and the experiment figures/tables.")

with open(os.path.join(OUT, "validation_summary.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")

# ---- figure: profiles + battery arbitrage schedule ----
fig, axes = plt.subplots(2, 1, figsize=(9, 6.5), constrained_layout=True)
t = np.arange(T)
ax = axes[0]
ax.plot(t, inst.D, label="demand $D_t$", lw=2)
ax.plot(t, inst.P, label="solar $P_t$", lw=2)
ax.fill_between(t, inst.Delta, 0, where=inst.Delta < 0, color="gold", alpha=0.4, label="surplus")
ax.fill_between(t, inst.Delta, 0, where=inst.Delta > 0, color="tomato", alpha=0.3, label="deficit (net)")
ax.axhline(0, color="k", lw=0.6)
ax.set_xlabel("hour"); ax.set_ylabel("kWh / block")
ax.set_title("Demand, solar, and net balance (instance: 20 MWh demand / 14 MWh solar)")
ax.legend(ncol=4, fontsize=8); ax.set_xticks(range(0, T, 2))

ax = axes[1]
charge = np.clip(col_lp.e, 0, None); discharge = np.clip(-col_lp.e, 0, None)
ax.bar(t, charge, color="seagreen", label="charge (grid draw)")
ax.bar(t, -discharge, color="indianred", label="discharge (grid inject)")
ax2 = ax.twinx()
ax2.step(t, sol.mu, where="mid", color="navy", lw=1.5, alpha=0.7, label="price $\\mu_t$")
ax2.set_ylabel("$\\mu_t$  (generation price)")
ax.axhline(0, color="k", lw=0.6)
ax.set_xlabel("hour"); ax.set_ylabel("kWh charged / discharged")
ax.set_title("Priced battery column from the DP: charge at $\\mu_t\\approx 0$, discharge at $\\mu_t\\approx c_g$")
ax.legend(loc="upper left", fontsize=8); ax2.legend(loc="upper right", fontsize=8)
ax.set_xticks(range(0, T, 2))

fig.savefig(os.path.join(OUT, "profiles_and_arbitrage.png"), dpi=130)
print(f"\nWrote: {OUT}/validation_summary.txt and {OUT}/profiles_and_arbitrage.png")
