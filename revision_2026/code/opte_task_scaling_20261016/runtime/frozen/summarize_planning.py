"""Independently replay and summarize the three prespecified planning bases.

Reads immutable worker directories; writes only new derived JSON/CSV/Markdown.
Does not import the new direct graph/model builders. Complete JSON path and BESS
primal records are replayed using the separate extension checker, then evaluated
in the original vendor path-master matrices. Optional bounded HiGHS LP checks
use only those recovered selected paths, never the full direct model or a MIP.
Missing, failed and time-limited stages remain visible. Three selected bases do
not estimate the 270-base medians or replace the historical precision audit.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from master import _build_lp
from verify_extension_results import instance_from_record, replay_direct

ARMS = ("solar", "solar_bess", "v2g_fleet", "v2g")
NESTING = (("solar", "solar_bess"), ("solar", "v2g_fleet"),
           ("solar_bess", "v2g"), ("v2g_fleet", "v2g"))
DEPS = ("planning_direct.py", "arc_flow.py", "column_witness.py",
        "extension_instances.py", "extension_models.py", "rmp_solver.py", "run_pilot.py")
TOL = 1e-6


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def original_master_check(inst, stage, columns, battery_allowed, lp_seconds):
    """Evaluate the saved physical vector in independently built vendor rows."""
    v = stage["validation"]
    c, au, bu, ae, be, bounds, offsets, n, T, R, _ = _build_lp(
        inst, columns, battery_allowed=battery_allowed, soc_mode="cyclic")
    ox, og, oc, od, os, on = offsets
    x = np.zeros(len(c))
    weights = [p["weight"] for p in v["paths"]] + [p["weight"] for p in v.get("singleton_paths", [])]
    require(len(weights) == len(columns), "Recovered route order mismatch")
    x[ox:ox+R] = weights
    x[og:og+T] = v["generation"]; x[oc:oc+T] = v["battery_charge"]
    x[od:od+T] = v["battery_discharge"]; x[os:os+T+1] = v["battery_soc"]
    x[on] = v["nb"]
    res = {"equality": float(np.max(abs(ae @ x-be), initial=0)),
           "inequality": float(np.max(np.maximum(au @ x-bu, 0), initial=0)),
           "nonnegative": float(max(0, -x.min())),
           "objective": float(abs(c @ x-stage["objective"]))}
    require(max(res.values()) <= TOL, f"Original vendor matrix replay failed: {res}")
    out = {"passed": True, "residuals": res, "path_columns": R,
           "variables": len(c), "recovered_saved_objective": float(c @ x),
           "uses_new_graph_or_model_builder": False}
    if lp_seconds <= 0:
        out["selected_path_lp"] = {"status": "not_requested"}
        return out
    started = time.perf_counter()
    sol = linprog(c, A_ub=au, b_ub=bu, A_eq=ae, b_eq=be, bounds=bounds,
                  method="highs", options={"time_limit": lp_seconds,
                                           "primal_feasibility_tolerance": 1e-8,
                                           "dual_feasibility_tolerance": 1e-8})
    check = {"native_status": int(sol.status), "message": sol.message,
             "status": "optimal" if sol.success else "unfinished_or_failed",
             "seconds": time.perf_counter()-started,
             "allowance_seconds": lp_seconds,
             "objective": float(sol.fun) if sol.fun is not None else None,
             "scope": "Original vendor LP on this stage's independently recovered selected paths only"}
    require(sol.status != 2, "Vendor selected-path LP declares its supplied feasible vector infeasible")
    if sol.success:
        require(sol.fun <= stage["objective"] + TOL,
                "Selected-path LP exceeds its supplied feasible vector")
        if stage.get("relax") and stage.get("status") == "optimal":
            require(abs(sol.fun-stage["objective"]) <= TOL,
                    "Selected LP paths do not reproduce the saved full LP optimum")
    out["selected_path_lp"] = check
    return out


def audit_stage(folder, name, inst, arm, spec, lp_seconds):
    path = folder / f"{name}.json"
    if not path.exists():
        return {"status": "missing", "present": False, "passed": False}
    data = read(path)
    report = {key: data.get(key) for key in
              ("status", "objective", "bound", "gap", "solution_count",
               "solve_end_to_end_seconds", "solver_runtime_seconds", "validation_seconds",
               "variables", "constraints", "graph_arcs", "graph_nodes", "solver_method")}
    report.update(present=True, result_sha256=digest(path), passed=False)
    try:
        if data.get("status") == "error":
            raise AssertionError(data.get("error", "Worker stage error"))
        require(data["scenario"] == arm and data["relax"] == (name == "lp"), "Stage identity mismatch")
        require(data["threads"] == 1 and data["seed"] == 0 and data["cold_solve"]
                and not data["solution_or_basis_sharing"], "Cold-solve settings mismatch")
        require(data["time_limit_seconds"] == 1800 and data["mip_gap_tolerance"] == 1e-6,
                "Planning solve budget or gap mismatch")
        require(data["solver_method"] == (2 if name == "lp" else -1) and data["crossover"] == -1,
                "Prespecified LP barrier/default MIP method mismatch")
        require(all(data[k] == 1e-8 for k in ("feasibility_tolerance", "optimality_tolerance", "integer_feasibility_tolerance")),
                "Native numerical tolerances differ from the protocol")
        require(data["original_rho"] == data["bess_rho"] == 1.75 and data["soc_step"] == .25,
                "Planning rate/grid mismatch")
        audit = data["audit"]
        require(audit["passed"] and audit["all_seeds_witnessed_in_scenario_graph"]
                and audit["off_grid_seed_count"] == 0, "Invalid saved seed-family audit")
        objective, bound = data.get("objective"), data.get("bound")
        report["native_bound_used_in_intervals"] = bound is not None and data.get("status") in ("optimal", "time_limit", "interrupted")
        if objective is not None and bound is not None:
            require(bound <= objective+TOL, "Native lower bound exceeds incumbent")
        if objective is not None:
            physical, columns = replay_direct(inst, data, name == "mip")
            v = data["validation"]
            discharge = sum(p["weight"]*sum(max(-e, 0) for e in p["energy"])
                            for p in v["paths"])
            discharge += sum(p["weight"]*sum(max(-e, 0) for e in p["witness"]["energy"])
                             for p in v.get("singleton_paths", []))
            battery = arm in ("solar_bess", "v2g")
            require(arm not in ("solar", "solar_bess") or discharge <= TOL,
                    "Charge-only scenario contains truck discharge")
            require(battery or abs(v["nb"]) <= TOL, "No-BESS scenario contains batteries")
            report["independent_physical_replay"] = physical
            report["original_vendor_master"] = original_master_check(inst, data, columns, battery, lp_seconds)
            report["truck_discharge_model_units"] = discharge
            report["battery_count"] = float(v["nb"])
            report["fleet_count"] = float(v["fleet"])
            report["primal_json_complete"] = True
        else:
            report["primal_json_complete"] = False
            report["primal_note"] = "No saved incumbent; no physical feasibility is claimed"
        old = next(e["row"] for e in spec["historical_source"]["rows"] if e["row"]["scenario"] == arm)
        historical = {"rounded_lp": old["lp_union"], "rounded_incumbent": old["total"],
                      "lp_rounding_radius": .00005, "incumbent_rounding_radius": .005,
                      "restricted_solver_bound": old["solver_bound"],
                      "restricted_bound_is_full_integer_bound": False}
        if objective is not None:
            historical["objective_minus_rounded_lp"] = objective-old["lp_union"]
            historical["objective_minus_rounded_incumbent"] = objective-old["total"]
            if name == "lp" and data["status"] == "optimal":
                historical["matches_lp_at_saved_precision"] = abs(objective-old["lp_union"]) <= .00005+TOL
        if name == "mip" and objective is not None:
            lo = bound if report["native_bound_used_in_intervals"] else None
            historical["historical_incumbent_excess_interval"] = (
                [old["total"]-.005-objective-TOL, old["total"]+.005-lo+TOL] if lo is not None else None)
        report["historical_comparison"] = historical
        report["passed"] = True
    except Exception as exc:
        report["error"] = repr(exc)
    return report


def audit_worker(folder, spec, arm, lp_seconds):
    out = {"case": spec["case"], "scenario": arm, "directory": str(folder), "passed": False}
    out["stages"] = {}
    for name in ("lp", "mip"):
        path = folder / f"{name}.json"
        if path.exists():
            try:
                raw_stage = read(path)
                out["stages"][name] = {k: raw_stage.get(k) for k in ("status", "objective", "bound", "gap", "solution_count")}
                out["stages"][name].update(present=True, passed=False, result_sha256=digest(path))
            except Exception as exc:
                out["stages"][name] = {"status": "unreadable", "present": True, "passed": False, "error": repr(exc)}
        else:
            out["stages"][name] = {"status": "missing", "present": False, "passed": False}
    if not (folder / "run_manifest.json").exists():
        return {**out, "status": "missing_manifest"}
    try:
        manifest = read(folder / "run_manifest.json"); raw = read(folder / "instance.json")
        require(manifest["case"] == spec["case"] and manifest["scenario"] == arm
                and manifest["spec"] == spec and raw["spec"] == spec, "Worker input identity mismatch")
        require(manifest["selected_inputs_sha256"] == digest(ROOT / "planning_direct_inputs.json"),
                "Prespecified inputs hash mismatch")
        require(manifest["vendor_manifest"] == read(ROOT / "source_manifest.json"),
                "Worker frozen-vendor manifest differs from the local frozen snapshot")
        require(raw["sha256"] == hashlib.sha256(json.dumps({k:v for k,v in raw.items() if k != "sha256"}, sort_keys=True).encode()).hexdigest(), "Instance checksum mismatch")
        require(np.max(abs(np.asarray(raw["D"])-np.asarray(raw["P"])-np.asarray(raw["Delta"]))) <= TOL,
                "Demand/PV/net-demand mismatch")
        inst = instance_from_record(raw)
        require(inst.soc_step == .25 and inst.rho == 1.75 and inst.G == 7
                and inst.c_g == 40 and inst.c_v == 45 and inst.c_b == 36
                and inst.eps_pen == .025 and inst.eta == 0 and inst.charge_locs == [0],
                "Planning physical/economic settings mismatch")
        hashes = {name: digest(ROOT / name) for name in DEPS}
        require(all(manifest["code_sha256"].get(name) == sha for name, sha in hashes.items()),
                "A benchmark dependency differs from its worker launch hash")
        unrelated = {name: {"worker_sha256": sha, "current_sha256": digest(ROOT/name)}
                     for name, sha in manifest["code_sha256"].items()
                     if name not in DEPS and (ROOT/name).exists() and digest(ROOT/name) != sha}
        out.update(instance_sha256=raw["sha256"], worker_manifest_sha256=digest(folder/"run_manifest.json"),
                   actual_dependencies_sha256=hashes, unrelated_manifest_differences=unrelated,
                   host=manifest["host"], gurobi=manifest["gurobi"],
                   progress=read(folder/"progress.json") if (folder/"progress.json").exists() else None)
        out["stages"] = {name: audit_stage(folder, name, inst, arm, spec, lp_seconds) for name in ("lp", "mip")}
        lp, mip = out["stages"]["lp"], out["stages"]["mip"]
        if lp.get("passed") and lp.get("status") == "optimal" and mip.get("objective") is not None:
            require(lp["objective"] <= mip["objective"]+TOL, "LP exceeds integer incumbent")
            check = mip.get("original_vendor_master", {}).get("selected_path_lp", {})
            if check.get("status") == "optimal":
                require(check["objective"] >= lp["objective"]-TOL, "Selected integer-path LP below full-family LP")
        out["passed"] = all(s.get("passed") for s in out["stages"].values())
        out["status"] = "audited" if out["passed"] else "incomplete_or_failed"
    except Exception as exc:
        out["error"] = repr(exc); out["status"] = "failed"
    return out


def summarize_base(spec, workers):
    g = {w["scenario"]: w for w in workers}; out = {"case": spec["case"], "n_tasks": spec["n_tasks"],
        "pv_scale": spec["pv_scale"], "draw_seed": spec["draw_seed"], "selection_reason": spec["selection_reason"]}
    stage = lambda a, n: g[a].get("stages", {}).get(n, {})
    intervals = {}; incumbents = {}; nested = []
    for a in ARMS:
        l, m = stage(a, "lp"), stage(a, "mip")
        if m.get("passed") and m.get("objective") is not None:
            lows = [x for x in (m.get("bound") if m.get("native_bound_used_in_intervals") else None,
                               l.get("objective") if l.get("passed") and l.get("status") == "optimal" else None) if x is not None]
            if lows: intervals[a] = [max(lows)-TOL, m["objective"]+TOL]
            incumbents[a] = m["objective"]
    for a, b in NESTING:
        entry = {"restrictive": a, "flexible": b}
        la, lb = stage(a, "lp"), stage(b, "lp")
        if la.get("passed") and lb.get("passed") and la.get("status") == lb.get("status") == "optimal":
            entry["lp_reduction"] = la["objective"]-lb["objective"]
            entry["lp_nesting_passed"] = entry["lp_reduction"] >= -TOL
        if a in intervals and b in intervals:
            entry["integer_reduction_interval"] = [intervals[a][0]-intervals[b][1], intervals[a][1]-intervals[b][0]]
            entry["integer_bounds_consistent_with_nesting"] = entry["integer_reduction_interval"][1] >= -TOL
            entry["incumbent_reduction"] = incumbents[a]-incumbents[b]
        nested.append(entry)
    out.update(integer_optimum_intervals=intervals, nesting=nested,
               same_input_across_arms=len({w.get("instance_sha256") for w in workers if w.get("instance_sha256")}) <= 1)
    if all(a in incumbents for a in ARMS):
        den = incumbents["solar"]-incumbents["v2g"]
        out["new_incumbent_shares"] = ({"BESS": (incumbents["solar"]-incumbents["solar_bess"])/den,
            "V2G_without_BESS": (incumbents["solar"]-incumbents["v2g_fleet"])/den,
            "V2G_without_BESS_daily_reduction": (incumbents["solar"]-incumbents["v2g_fleet"])/incumbents["solar"]} if den > TOL else None)
        old = {e["row"]["scenario"]: e["row"]["total"] for e in spec["historical_source"]["rows"]}
        oldden = old["solar"]-old["v2g"]
        out["historical_rounded_incumbent_shares"] = {"BESS":(old["solar"]-old["solar_bess"])/oldden,
             "V2G_without_BESS":(old["solar"]-old["v2g_fleet"])/oldden,
             "V2G_without_BESS_daily_reduction":(old["solar"]-old["v2g_fleet"])/old["solar"]}
    if all(a in intervals for a in ARMS):
        dslo = max(0, intervals["solar"][0]-intervals["v2g"][1])
        dshi = intervals["solar"][1]-intervals["v2g"][0]
        out["optimal_share_intervals"] = {}
        if dshi > TOL:
            out["share_interval_condition"] = ("Unconditional: strictly positive joint saving is certified by the recorded bounds"
                if dslo > TOL else "Conditional on strictly positive joint saving; zero saving is not excluded and its shares would be undefined")
            for label, a in (("BESS", "solar_bess"), ("V2G_without_BESS", "v2g_fleet")):
                lo = max(0, intervals["solar"][0]-intervals[a][1])/dshi
                hi = min(1, (intervals["solar"][1]-intervals[a][0])/dslo) if dslo > TOL else 1
                out["optimal_share_intervals"][label] = [max(0, lo), max(0, hi)]
    out["passed"] = out["same_input_across_arms"] and all(x.get("lp_nesting_passed", True) and x.get("integer_bounds_consistent_with_nesting", True) for x in nested)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True, help="New empty directory for derived files")
    p.add_argument("--vendor-lp-seconds", type=float, default=10.0, help="Per selected-path LP; zero skips optimization")
    args = p.parse_args()
    if args.vendor_lp_seconds < 0:
        raise ValueError("Selected-path LP allowance must be nonnegative")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Use a fresh output directory; prior derived evidence is immutable")
    started = time.perf_counter(); inputs = read(ROOT / "planning_direct_inputs.json")
    vendor = read(ROOT / "source_manifest.json")
    require(all(digest(ROOT/"vendor"/name) == item["sha256"] for name,item in vendor["files"].items()), "Frozen vendor checksum mismatch")
    workers = [audit_worker(args.input_root/f"{s['case']}_{a}", s, a, args.vendor_lp_seconds)
               for s in inputs["cases"] for a in ARMS]
    bases = [summarize_base(s, [w for w in workers if w["case"] == s["case"]]) for s in inputs["cases"]]
    complete = all(w.get("passed") for w in workers)
    passed = complete and all(b["passed"] for b in bases)
    report = {"created_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "passed": passed,
              "all_expected_stages_audited": complete, "expected_workers": 12, "expected_stages": 24,
              "all_stages_native_optimal_with_incumbents": all(w.get("stages", {}).get(n, {}).get("status") == "optimal"
                    and w.get("stages", {}).get(n, {}).get("objective") is not None for w in workers for n in ("lp", "mip")),
              "input_root": str(args.input_root.resolve()), "checker_sha256": digest(__file__),
              "independent_replay_sha256": digest(ROOT/"verify_extension_results.py"),
              "selected_inputs_sha256": digest(ROOT/"planning_direct_inputs.json"),
              "vendor_sha256": {n: x["sha256"] for n,x in vendor["files"].items()},
              "absolute_numerical_tolerance": TOL, "workers": workers, "bases": bases,
              "diagnostic_seconds": time.perf_counter()-started,
              "scope": ["Three prespecified diagnostic bases, not an estimator of the 270-base medians.",
                        "No full direct model or integer model is reoptimized by this checker.",
                        "Full selected path and BESS primal vectors are preserved in JSON; NPZ is not needed for independent primal replay.",
                        "Native solver bounds are recorded, not independently reconstructed dual/KKT certificates.",
                        "Optional bounded HiGHS checks optimize original vendor LPs on recovered paths only; their times are diagnostic, not benchmark data.",
                        "A selected integer-path LP need only lie between the full-family LP and its supplied integer incumbent; equality to the integer incumbent is not required.",
                        "Historical solver_bound belongs to a restricted route pool and is never treated as a full-family integer lower bound.",
                        "Native optimal MIP status means the configured relative gap tolerance 1e-6; a nonzero objective-to-bound difference remains an interval, not an exact optimum.",
                        "Numerical tolerance allowances do not constitute exact rational certification."]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/"planning_summary.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    rows = [{"case":w["case"], "scenario":w["scenario"], "stage":name, **{k:s.get(k) for k in
             ("status", "passed", "objective", "bound", "gap", "battery_count", "fleet_count", "solve_end_to_end_seconds")}}
            for w in workers for name in ("lp", "mip") for s in [w.get("stages", {}).get(name, {"status": "unavailable_after_worker_audit_failure", "passed": False})]]
    with (args.output_dir/"planning_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    lines = ["# Targeted planning validation", "", f"All 24 expected stages audited: {complete}. Overall checks passed: {passed}.",
             "", "These are three prespecified diagnostic bases; their shares do not estimate the 270-base medians.", "",
             "| Case | Configuration | Stage | Status | Objective | Bound |", "| --- | --- | --- | --- | ---: | ---: |"]
    for row in rows:
        show = lambda x: "—" if x is None else f"{x:.6f}"
        lines.append(f"| {row['case']} | {row['scenario']} | {row['stage']} | {row['status']} | {show(row['objective'])} | {show(row['bound'])} |")
    for b in bases:
        lines += ["", f"## {b['case']}", "", b["selection_reason"], ""]
        if "share_interval_condition" in b:
            lines += [b["share_interval_condition"] + ".", ""]
        for label, values in b.get("optimal_share_intervals", {}).items():
            lines.append(f"- {label}: optimum-share interval {100*values[0]:.4f}–{100*values[1]:.4f}%.")
        lines.append("- The JSON retains historical rounded-incumbent estimates, new incumbent estimates, all native bounds and nesting comparisons.")
    lines += ["", "Physical schedules and original vendor rows are independently replayed from saved JSON. Native solver bounds are retained without an independent dual proof. All extra LP checks use only recovered selected paths and are excluded from benchmark timing."]
    (args.output_dir/"planning_summary.md").write_text("\n".join(lines)+"\n")
    print(json.dumps({"output":str(args.output_dir), "passed":passed, "stages_audited":sum(s.get("passed",False) for w in workers for s in w.get("stages",{}).values()), "seconds":report["diagnostic_seconds"]}))


if __name__ == "__main__":
    main()
