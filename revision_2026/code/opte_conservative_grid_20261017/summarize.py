"""Summarize raw/<case>/<arm>/result.json into summary.json and tables.md (read-only on raw)."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "output/opte-conservative-grid-20261017"
OCT15 = REPO / "output/opte-corollary1-check-20261015/sweep_results.json"
BASES = [(n, sd) for sd in (0, 1) for n in (60, 120, 200)]
ARMS = ["frozen25", "exact25", "cons25", "cons50", "cons10", "cons20", "near20", "rate160_10"]


def load():
    rows = {}
    for (n, sd) in BASES:
        for arm in ARMS:
            p = OUT / "raw" / f"n{n}_s{sd}" / arm / "result.json"
            if p.exists():
                rows[(n, sd, arm)] = json.loads(p.read_text())["summary"]
    return rows


def pct(a, b):
    return 100.0 * (a - b) / b


def rng(v, f="{:+.3f}"):
    return f"{f.format(min(v))} .. {f.format(max(v))}" if v else "n/a"


def main():
    R = load()
    errors = [k for k, r in R.items() if r.get("error")]
    ex = {(n, sd): R[(n, sd, "frozen25")]["lp_obj"] for (n, sd) in BASES if (n, sd, "frozen25") in R}
    checks = {}
    # reproduction checks
    checks["missing_runs"] = [f"n{n}_s{sd}/{a}" for (n, sd) in BASES for a in ARMS if (n, sd, a) not in R]
    checks["errors"] = [f"n{k[0]}_s{k[1]}/{k[2]}" for k in errors]
    checks["all_converged_priced_out"] = all(r.get("term_reason") == "priced_out" for r in R.values())
    checks["max_artificial_mass"] = max(r.get("lp_artificial_mass", 0) for r in R.values())
    checks["exact25_minus_frozen25_max_abs"] = max(abs(R[(n, sd, "exact25")]["lp_obj"] - ex[(n, sd)]) for (n, sd) in BASES)
    checks["cons25_minus_frozen25_max_abs"] = max(abs(R[(n, sd, "cons25")]["lp_obj"] - ex[(n, sd)]) for (n, sd) in BASES)
    old = json.loads(OCT15.read_text())
    o = {(r["n"], r["seed"], r["variant"], r["step_kwh"]): r["lp_obj"] for r in old}
    rep = []
    for (n, sd) in BASES:
        for arm, key in (("frozen25", ("frozen", 25.0)), ("cons20", ("conservative", 20.0)),
                         ("cons50", ("conservative", 50.0)), ("cons10", ("conservative", 10.0)),
                         ("near20", ("nearest", 20.0))):
            rep.append(abs(R[(n, sd, arm)]["lp_obj"] - o[(n, sd) + key]))
    checks["max_abs_diff_vs_15oct_sweep"] = max(rep)
    checks["conservative_lp_at_or_above_exact"] = all(
        R[(n, sd, a)]["lp_obj"] >= ex[(n, sd)] - 1e-6 for (n, sd) in BASES for a in ("cons20", "cons50", "cons10", "cons25", "rate160_10"))
    checks["resolved_executed_at_or_above_exact"] = all(
        R[(n, sd, "cons20")]["lp_resolved_with_executed_profiles"] >= ex[(n, sd)] - 1e-6 for (n, sd) in BASES)

    lines = []
    A = lines.append
    A("## Grid mapping of every energy quantity (true kWh -> grid kWh)\n")
    A("| step | rule | capacity | charge per block | discharge per block | task | deadheads | start / end / minimum SoC |")
    A("|---|---|---|---|---|---|---|---|")
    for arm in ("exact25", "cons50", "cons20", "near20", "cons10", "rate160_10"):
        g = R[(60, 0, arm)]["grid_mapping"]
        f = lambda p: f"{p[0]:g} -> {p[1]:g}"
        A(f"| {g['step_kwh']:g} ({arm}) | {g['rule']} | {f(g['capacity_kwh'])} | {f(g['charge_gain_per_block_kwh'])} | "
          f"{f(g['discharge_per_block_kwh'])} | {', '.join(f(p) for p in g['task_kwh_true_to_grid'])} | "
          f"{', '.join(f(p) for p in g['deadhead_kwh_true_to_grid'])} | "
          f"{g['initial_soc_kwh'][1]:g} / {g['final_soc_kwh'][1]:g} / {g['min_soc_kwh'][1]:g} |")
    A("")
    A("## LP value relative to the exact value (frozen DP, 25 kWh), six bases\n")
    A("| arm | step kWh | block limit used kWh | LP vs exact, min .. max (%) | route columns replayed | physically infeasible | LP-support columns infeasible / support | columns that stop charging when full | real SoC below grid SoC (events) | CG s, 6 bases |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    summ = {}
    for arm in ARMS:
        rs = [R[(n, sd, arm)] for (n, sd) in BASES]
        d = [pct(R[(n, sd, arm)]["lp_obj"], ex[(n, sd)]) for (n, sd) in BASES]
        rp = [r.get("replay") for r in rs]
        lim = rs[0]["grid_mapping"]["charge_gain_per_block_kwh"][1] if "grid_mapping" in rs[0] else 175.0
        if rp[0]:
            tc = sum(x["truck_cols"] for x in rp); inf = sum(x["infeasible"] for x in rp)
            ls = sum(x["lp_support"] for x in rp); lsi = sum(x["lp_support_infeasible"] for x in rp)
            cl = sum(x["needing_stop_when_full"] for x in rp); iv = sum(x["real_below_grid_events"] for x in rp)
            A(f"| {arm} | {rs[0]['step_kwh']:g} | {lim:g} | {rng(d)} | {tc} | {inf} | {lsi} / {ls} | {cl} | {iv if arm.startswith('cons') or arm.startswith('rate') else 'n/a'} | {sum(r['cg_seconds'] for r in rs):.1f} |")
        else:
            A(f"| {arm} | {rs[0]['step_kwh']:g} | {lim:g} | {rng(d)} | n/a (frozen DP keeps no trace) | | | | | {sum(r['cg_seconds'] for r in rs):.1f} |")
        summ[arm] = {"pct_vs_exact": d, "lp": [r["lp_obj"] for r in rs]}
    A("")
    A("## Per base: 20 kWh conservative in detail\n")
    A("| n | seed | exact LP (25 kWh) | cons 20 LP | % | same routes, paying only for energy stored (re-solved LP) | % | trucks in LP exact / cons | fossil kWh in LP exact / cons | nearest 20 LP (% , infeasible routes in LP support) | 10 kWh grid with 160 kWh limit (%) |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for (n, sd) in BASES:
        e = ex[(n, sd)]; c = R[(n, sd, "cons20")]; x = R[(n, sd, "exact25")]; nr = R[(n, sd, "near20")]; rl = R[(n, sd, "rate160_10")]
        rs_ = c["lp_resolved_with_executed_profiles"]
        A(f"| {n} | {sd} | {e:,.3f} | {c['lp_obj']:,.3f} | {pct(c['lp_obj'], e):+.2f} | {rs_:,.3f} | {pct(rs_, e):+.2f} | "
          f"{x['lp_trucks']:.2f} / {c['lp_trucks']:.2f} | {x['lp_fossil_kwh']:,.0f} / {c['lp_fossil_kwh']:,.0f} | "
          f"{pct(nr['lp_obj'], e):+.2f}, {nr['replay']['lp_support_infeasible']}/{nr['replay']['lp_support']} | {pct(rl['lp_obj'], e):+.2f} |")
    A("")
    A("## Restricted route MIP (integer), exact 25 kWh pool vs conservative 20 kWh pool\n")
    A("Gurobi, cold, truck columns only, Threads 1, Seed 0, MIPGap 1e-6, 600 s. Both values are restricted-pool heuristics (price-and-branch), not proven integer optima of the full model.\n")
    A("| n | seed | exact LP | MIP exact 25 (status, trucks, s) | MIP cons 20 (status, trucks, s) | MIP cons20 vs MIP exact (%) | MIP cons20 vs exact LP (%) | MIP cons 20, routes booked at stored energy (%) vs MIP exact | MIP-selected cons20 routes infeasible / selected | selected routes that stop when full | stored energy not drawn, kWh |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    mipd, mipd2 = [], []
    for (n, sd) in BASES:
        e = ex[(n, sd)]; me = R[(n, sd, "exact25")]["route_mip"]; mc = R[(n, sd, "cons20")]["route_mip"]
        m2 = R[(n, sd, "cons20")].get("route_mip_executed_profiles", {})
        d1 = pct(mc["obj"], me["obj"]); mipd.append(d1)
        d2 = pct(m2["obj"], me["obj"]) if m2.get("obj") else None
        if d2 is not None:
            mipd2.append(d2)
        A(f"| {n} | {sd} | {e:,.3f} | {me['obj']:,.3f} ({me['status']}, {me['trucks']}, {me['seconds']:.1f}) | "
          f"{mc['obj']:,.3f} ({mc['status']}, {mc['trucks']}, {mc['seconds']:.1f}) | {d1:+.2f} | {pct(mc['obj'], e):+.2f} | "
          f"{'n/a' if d2 is None else f'{d2:+.2f}'} ({m2.get('status')}) | {mc['selected_infeasible']} / {mc['trucks']} | "
          f"{mc['selected_needing_stop_when_full']} | {mc['clipped_kwh_total']:.0f} |")
    A("")
    summ["mip_cons20_vs_mip_exact_pct"] = mipd
    summ["mip_cons20_executed_vs_mip_exact_pct"] = mipd2
    summ["cons20_resolved_executed_pct"] = [pct(R[(n, sd, "cons20")]["lp_resolved_with_executed_profiles"], ex[(n, sd)]) for (n, sd) in BASES]
    summ["mip_exact_master_checks_ok"] = all(R[(n, sd, a)]["route_mip"]["master_check_executed"]["ok"] and R[(n, sd, a)]["route_mip"]["master_check_booked"]["ok"]
                                             for (n, sd) in BASES for a in ("exact25", "cons20"))
    summ["lp_master_checks_ok"] = all(R[k]["lp_master_check_executed"]["ok"] and R[k]["lp_master_check_booked"]["ok"]
                                      for k in R if "lp_master_check_booked" in R[k])
    summ["lp_obj_recomputed_max_abs_diff"] = max(abs(R[k]["lp_obj_recomputed_booked"] - R[k]["lp_obj"]) for k in R if "lp_obj_recomputed_booked" in R[k])
    summ["checks"] = checks
    A("## Checks\n")
    for k, v in checks.items():
        A(f"- {k}: {v}")
    for k in ("lp_master_checks_ok", "mip_exact_master_checks_ok", "lp_obj_recomputed_max_abs_diff"):
        A(f"- {k}: {summ[k]}")
    (OUT / "tables.md").write_text("\n".join(lines) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
