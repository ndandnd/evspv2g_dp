"""Summarize sweep_results.json into sweep_table.md (relative difference vs delta=25 frozen)."""
import json
from pathlib import Path
H = Path(__file__).resolve().parent
rows = json.loads((H / "sweep_results.json").read_text())
ref = {(r["n"], r["seed"]): r["lp_obj"] for r in rows if r["variant"] == "frozen" and r["step_kwh"] == 25}
hist = {(60,0,50):3582.286,(60,0,25):3553.788,(120,0,50):9646.02,(120,0,25):9578.541,(200,0,50):17838.187,(200,0,25):17709.761,
        (60,1,50):3736.857,(60,1,25):3712.836,(120,1,50):9602.066,(120,1,25):9532.465,(200,1,50):17803.94,(200,1,25):17663.161}
order = {"frozen": 0, "nearest": 1, "conservative": 2, "conservative_repaired": 3}
rows.sort(key=lambda r: (r["seed"], r["n"], -r["step_kwh"], order[r["variant"]]))
L = ["| n | seed | variant | delta kWh | DP rate kWh | LP value | vs delta=25 (%) | overnight4 record | converged | CG iters | columns | CG s | DP cols infeasible after clipping / DP cols | DP cols exceeding G as recorded | LP-support infeasible / support (weight) |",
     "|" + "---|" * 15]
rate = {50: 150, 25: 175, 20: 160, 12.5: 175, 10: 170}
for r in rows:
    k = (r["n"], r["seed"]); d = 100 * (r["lp_obj"] - ref[k]) / ref[k]
    h = hist.get((r["n"], r["seed"], r["step_kwh"])) if r["variant"] == "frozen" else None
    inf = "" if r["variant"] == "frozen" else f"{r['dp_cols_infeasible']} / {r['dp_cols']}"
    sup = "" if r["variant"] == "frozen" else f"{r['lp_support_infeasible']} / {r['dp_cols_in_lp_support']} ({r['lp_support_infeasible_weight']:.3g})"
    clip = "" if r["variant"] == "frozen" else f"{r['dp_cols_need_charge_clip']}"
    L.append(f"| {r['n']} | {r['seed']} | {r['variant']} | {r['step_kwh']:g} | {rate[r['step_kwh']]} | {r['lp_obj']:.4f} | {d:+.3f} | "
             f"{'' if h is None else h} | {r['converged']} | {r['iters']} | {r['n_cols']} | {r['cg_s']} | {inf} | {clip} | {sup} |")
# compact summary: range of relative differences per (variant, delta)
S = ["| variant | delta kWh | DP rate kWh | traction rounding | LP vs delta=25: min..max (%) | DP columns infeasible after clipping | DP columns exceeding G as recorded | total CG s (6 bases) |", "|" + "---|" * 8]
for var in ("frozen", "nearest", "conservative", "conservative_repaired"):
    for st in (50, 25, 20, 12.5, 10):
        sub = [r for r in rows if r["variant"] == var and r["step_kwh"] == st]
        if not sub:
            continue
        ds = [100 * (r["lp_obj"] - ref[(r["n"], r["seed"])]) / ref[(r["n"], r["seed"])] for r in sub]
        tr = "on grid" if st != 20 else ("50 kWh deadhead -> 40 kWh" if var == "nearest" else "50 kWh deadhead -> 60 kWh" + (" (profile clipped to exact)" if var.endswith("repaired") else ""))
        S.append(f"| {var} | {st:g} | {rate[st]} | {tr} | {min(ds):+.3f} .. {max(ds):+.3f} | " +
                 (f"{sum(r['dp_cols_infeasible'] for r in sub)} / {sum(r['dp_cols'] for r in sub)} | "
                  f"{sum(r['dp_cols_need_charge_clip'] for r in sub)} / {sum(r['dp_cols'] for r in sub)}" if var != "frozen" else "n/a | n/a") + f" | {sum(r['cg_s'] for r in sub):.1f} |")
# reproduction of overnight4 records and the line-1850 range under both bases
fz = {(r["n"], r["seed"], r["step_kwh"]): r["lp_obj"] for r in rows if r["variant"] == "frozen"}
dev = {k: abs(fz[k] - v) for k, v in hist.items()}
kmax = max(dev, key=dev.get)
b25 = [100 * (fz[(n, s, 50)] - fz[(n, s, 25)]) / fz[(n, s, 25)] for (n, s) in ref]
b50 = [100 * (fz[(n, s, 50)] - fz[(n, s, 25)]) / fz[(n, s, 50)] for (n, s) in ref]
X = [f"Frozen DP vs overnight4 records (12 values): max |difference| = {dev[kmax]:.4f} at n={kmax[0]}, seed={kmax[1]}, delta={kmax[2]:g} "
     f"(sweep {fz[kmax]:.4f} vs record {hist[kmax]}).",
     f"50 -> 25 kWh LP decrease relative to the 25 kWh value: {min(b25):.3f}..{max(b25):.3f}%; relative to the 50 kWh value: {min(b50):.3f}..{max(b50):.3f}%."]
(H / "sweep_table.md").write_text("## Summary\n\n" + "\n".join(S) + "\n\n" + "\n\n".join(X)
                                  + "\n\n'Infeasible after clipping': exact replay of the column's own route and grid profile, with charge above G clipped. "
                                  "It does not test other charging plans on the same route.\n\n## All runs\n\n" + "\n".join(L) + "\n")
print("\n".join(S)); print("\n".join(X)); print(); print("\n".join(L))
