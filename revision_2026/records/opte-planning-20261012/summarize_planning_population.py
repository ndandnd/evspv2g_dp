"""Independent, no-solve audit of the complete uniform COMMON4 population.

Only new 60-second native MIP bounds and independently replayed new incumbents
enter the primary intervals. Every one of 1,080 outcomes and all 270 bases remain
in the denominator. No direct graph builder, optimizer, original rounded result,
or selected 1,800-second diagnostic is used by this analysis.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from master import _build_lp
from verify_extension_results import instance_from_record, replay_direct

ARMS = ("solar", "solar_bess", "v2g_fleet", "v2g")
EDGES = (("solar", "solar_bess"), ("solar", "v2g_fleet"),
         ("solar_bess", "v2g"), ("v2g_fleet", "v2g"))
TOL = 1e-6
INPUTS = ROOT / "planning_population_inputs.json"
DEPENDENCIES = ("planning_population.py", "planning_population_inputs.json",
    "PLANNING_POPULATION_PROTOCOL.md", "planning_direct.py", "planning_direct_inputs.json",
    "direct_mip_1000.py", "lp_scaling_models.py", "lp_scaling_instances.py", "run_lp_scaling.py",
    "extension_instances.py", "extension_models.py", "arc_flow.py", "column_witness.py",
    "rmp_solver.py", "run_pilot.py", "source_manifest.json")
METRICS = {"BESS_share": (96.0, 0), "V2G_alone_share": (62.0, 0),
    "V2G_alone_daily_reduction": (19.6, 1),
    "V2G_with_BESS_daily_reduction_low_gamma": (.6, 1),
    "V2G_with_BESS_daily_reduction_high_gamma": (9.3, 1)}

PROOF = """# Numerical population intervals and their propagation

For each configuration, a retained native full-family MIP bound L and an
independently physically replayed new feasible objective U give the numerical
interval [max(0,L-1e-6), U+1e-6]. These rely on floating-point solver bounds and
the documented replay tolerance; they are not exact-arithmetic certificates.
Missing bounds use only the universal nonnegative-cost lower bound. Missing or
rejected incumbents have no finite upper bound. Original rounded objectives and
the selected 1,800-second runs do not enter these intervals.

Write A=solar, B=solar_bess, C=v2g_fleet and D=v2g. The same inputs, costs and
individual boundaries give A>=B>=D and A>=C>=D: adding BESS or permitting truck
discharge only enlarges the feasible set. For each restrictive/flexible edge
X>=Y, update L_X=max(L_X,L_Y) and U_Y=min(U_Y,U_X). Repetition propagates these
valid implications; an inconsistent interval is an audit failure, not a value
to clip. The transfer of an upper bound is supported by independently replaying
the restrictive schedule in the more flexible configuration. Finite transferred
upper bounds carry their originating new worker identity.

For R=(A-B)/(A-D), assume A>D and A>=B>=D. Its partial derivatives with respect
to A,B,D have signs +,-,+. After nesting propagation, minimizing uses A=L_A,
D=L_D and B=min(U_B,L_A), giving max(0,L_A-U_B)/(L_A-L_D) when that denominator
is positive. Maximizing uses A=U_A, B=L_B and D=min(U_D,L_B), giving
(U_A-L_B)/(U_A-min(U_D,L_B)). The other intermediate configuration can be chosen
between D and A because of the propagated bounds. Unbounded or degenerate
endpoints conservatively use 0 and 1. The same argument applies with C instead
of B. Strict positivity is certified only when L_A>U_D; otherwise these bounds
are conditional on positive joint saving and no unconditional share is asserted.
For 1-B/A with A>0, monotonicity gives
[max(0,1-U_B/L_A), min(1,1-L_B/U_A)], with conservative [0,1] extensions at
unbounded or zero endpoints.

If each statistic r_i lies in [l_i,u_i], every order statistic is monotone in
each coordinate. Therefore the median lies in [median(l),median(u)]. All 270
bases are retained; with 270 observations each median is the arithmetic mean
of the 135th and 136th sorted endpoints. An unresolved base contributes its
full conservative interval, rather than being dropped. The gamma subsets are
fixed by the input manifest (30 at gamma<=0.35 and 100 at gamma>2).

A headline rounded to p decimal percentage places is supported only if the
entire numerical median interval is strictly inside the same rounding cell,
of width 10^(-p) percentage points. Boundary-touching intervals remain
unresolved. Any claim about a full-population share additionally requires every
joint denominator to be certified positive. Native optimal status alone never
collapses a nonzero recorded objective-bound interval to a point.
"""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def original_master_replay(inst, result, validation, columns, arm):
    """Construct original vendor path rows, evaluate; never optimize them."""
    c, au, bu, ae, be, bounds, offsets, _, T, R, _ = _build_lp(
        inst, columns, battery_allowed=arm in ("solar_bess", "v2g"), soc_mode="cyclic")
    ox, og, oc, od, os, on = offsets
    vector = np.zeros(len(c))
    weights = [p["weight"] for p in validation["paths"]]
    weights += [p["weight"] for p in validation.get("singleton_paths", [])]
    require(len(weights) == R, "Recovered route order mismatch")
    vector[ox:ox+R] = weights
    for offset, values in ((og, validation["generation"]), (oc, validation["battery_charge"]),
                           (od, validation["battery_discharge"]), (os, validation["battery_soc"])):
        vector[offset:offset+len(values)] = values
    vector[on] = validation["nb"]
    lower = np.asarray([0 if lo is None else lo for lo, _ in bounds])
    upper = np.asarray([math.inf if hi is None else hi for _, hi in bounds])
    residuals = {"equalities": float(np.max(abs(ae @ vector-be), initial=0)),
        "inequalities": float(np.max(au @ vector-bu, initial=0)),
        "lower_bounds": float(np.max(lower-vector, initial=0)),
        "upper_bounds": float(np.max(vector-upper, initial=0)),
        "objective": abs(float(c @ vector)-result["objective"])}
    require(max(residuals.values()) <= TOL, f"Original path-master replay failed: {residuals}")
    return {"passed": True, "residuals": residuals, "objective": float(c @ vector),
            "columns": R, "optimization_performed": False}


def scenario_replay(validation, arm):
    discharge = sum(p["weight"]*sum(max(-e, 0) for e in p["energy"])
                    for p in validation["paths"])
    discharge += sum(p["weight"]*sum(max(-e, 0) for e in p["witness"]["energy"])
                     for p in validation.get("singleton_paths", []))
    require(arm not in ("solar", "solar_bess") or discharge <= TOL,
            "Truck discharge in charge-only configuration")
    require(arm in ("solar_bess", "v2g") or abs(validation["nb"]) <= TOL,
            "Stationary storage in no-BESS configuration")
    return float(discharge)


def npz_replay(folder, result, validation, inst):
    """Check raw variable layout/integrality and shared dispatch against paths.

    Arc conservation was checked by the worker; independently recovered physical
    paths establish a feasible upper bound without trusting that decomposition.
    The original vendor master independently checks all coupling rows.
    """
    with np.load(folder / "primal.npz", allow_pickle=False) as archive:
        require(archive.files == ["x"], "Unexpected raw primal archive keys")
        x = archive["x"]
    E, K, T = result["graph_arcs"], result["seed_count"], inst.T
    f = E; g = f+1; ch = g+T; dis = ch+T; soc = dis+T; nb = soc+T+1; seed = nb+1
    require(x.shape == (seed+K,) and len(x) == result["variables"]
            and np.all(np.isfinite(x)), "Invalid raw primal dimensions or values")
    integer = np.r_[np.arange(E+1), nb, np.arange(seed, len(x))].astype(int)
    residuals = {"nonnegative": float(np.max(-x, initial=0)),
        "integer": float(np.max(abs(x[integer]-np.rint(x[integer])), initial=0)),
        "arc_fleet_upper": float(np.max(x[:E+1]-inst.n_trips, initial=0)),
        "seed_upper": float(np.max(x[seed:]-1, initial=0)),
        "dag_fleet": abs(float(x[f])-validation["dag_fleet"]),
        "singleton_fleet": abs(float(x[seed:].sum())-validation["singleton_fleet"]),
        "bess_count": abs(float(x[nb])-validation["nb"])}
    for key, start, length in (("generation", g, T), ("battery_charge", ch, T),
                              ("battery_discharge", dis, T), ("battery_soc", soc, T+1)):
        residuals[key] = float(np.max(abs(x[start:start+length]-validation[key]), initial=0))
    sw = np.zeros(K)
    for p in validation.get("singleton_paths", []):
        require(0 <= p["seed_index"] < K, "Invalid seed index")
        sw[p["seed_index"]] += p["weight"]
    residuals["seed_weights"] = float(np.max(abs(x[seed:]-sw), initial=0))
    require(max(residuals.values()) <= TOL, f"Raw-primal consistency failed: {residuals}")
    return {"passed": True, "residuals": residuals,
        "scope": "Variable integrality/bounds and shared dispatch; independent paths and vendor rows establish the upper bound"}


def audit_worker(base_folder, spec, arm, dependencies, vendor):
    folder = base_folder / arm
    out = {"case": spec["case"], "scenario": arm, "directory": str(folder),
        "status": "missing", "present": False, "passed": False,
        "native_lower_bound_usable": False, "validated_upper_bound": None}
    execution_path = folder.parent / f"{arm}_execution.json"
    if execution_path.exists():
        out["execution"] = read(execution_path)
        if out["execution"].get("execution", {}).get("external_timeout"):
            out["status"] = "external_timeout"
    if not (folder / "result.json").exists():
        return out
    try:
        result = read(folder / "result.json")
        out.update({k: result.get(k) for k in ("status", "objective", "bound", "gap", "solution_count",
            "solve_end_to_end_seconds", "solver_runtime_seconds", "diagnostic_seconds",
            "graph_arcs", "graph_nodes", "variables", "integer_variables")})
        out.update(present=True, result_sha256=sha(folder / "result.json"))
        require(not out.get("execution", {}).get("execution", {}).get("external_timeout"),
                "External watchdog output has unknown optimization completion")
        manifest = read(folder / "manifest.json"); raw = read(folder / "instance.json")
        launch = read(base_folder / "launch_manifest.json")
        require(launch["case"] == spec and launch["inputs_sha256"] == sha(INPUTS)
                and launch["budget_seconds"] == 60 and launch["watchdog_seconds"] == 120,
                "Base launch identity or protocol mismatch")
        require(manifest["case"] == raw["spec"] == spec and manifest["scenario"] == arm,
                "Input or configuration identity mismatch")
        require(result["case"] == spec["case"] and result["scenario"] == arm,
                "Result identity mismatch")
        require(manifest["code_sha256"] == dependencies, "Frozen worker dependency hashes differ")
        require(manifest["vendor_manifest"] == vendor, "Frozen vendor manifest differs")
        require(content_hash({k:v for k,v in raw.items() if k != "sha256"}) == raw["sha256"],
                "Instance content hash mismatch")
        physical = content_hash({k:v for k,v in raw.items() if k not in ("spec", "sha256")})
        require(physical == spec["physical_sha256"] == manifest["physical_sha256"] == result["physical_sha256"],
                "Physical input hash mismatch")
        require(raw["sha256"] == manifest["instance_sha256"] == result["instance_sha256"],
                "Saved instance hash mismatch")
        for name, digest in result["evidence_sha256"].items():
            path = (folder / name).resolve()
            require(path.is_relative_to(folder.resolve()) and path.is_file() and sha(path) == digest,
                    f"Evidence changed or missing: {name}")
        require({"instance.json", "manifest.json"}.issubset(result["evidence_sha256"]),
                "Incomplete input evidence hashes")
        require(result["method"] == "planning_population_mip" and result["budget_seconds"] == 60
                and result["threads"] == 1 and result["seed"] == 0
                and result["solver_method"] == -1 and result["crossover"] == -1
                and result["cold_solve"] and not result["solution_or_basis_sharing"],
                "Uniform cold-solve protocol mismatch")
        require(result["solver_version"] == [12, 0, 3] and result["mip_gap_tolerance"] == 1e-6
                and result["mip_gap_absolute_tolerance"] == 1e-10
                and all(result[k] == 1e-8 for k in ("feasibility_tolerance", "optimality_tolerance",
                                                  "integer_feasibility_tolerance")), "Solver tolerance/version mismatch")
        require(manifest["protocol"]["budget_seconds"] == 60
                and manifest["protocol"]["watchdog_seconds"] == 120
                and not manifest["protocol"]["standalone_lp"]
                and not manifest["protocol"]["external_warm_starts"], "Manifest protocol mismatch")
        environment = manifest["environment"]
        require(environment["gurobi"] == [12, 0, 3] and environment["allocated_cpus"] == "1"
                and len(environment["cpu_affinity"]) == 1
                and set(environment["thread_environment"]) == {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"}
                and all(v == "1" for v in environment["thread_environment"].values()),
                "Allocated CPU or thread environment differs from the protocol")
        inst = instance_from_record(raw)
        require(inst.n_trips == spec["n_tasks"] and inst.soc_step == .25 and inst.rho == 1.75
                and inst.G == 7 and inst.c_g == 40 and inst.c_v == 45 and inst.c_b == 36
                and inst.eps_pen == .025 and inst.deg_cost == 0 and inst.charge_locs == [0],
                "Physical/economic planning settings mismatch")
        require(np.max(abs(np.asarray(raw["D"])-raw["P"]-np.asarray(raw["Delta"]))) <= TOL,
                "Demand/PV/net-demand mismatch")
        gamma = sum(max(-v, 0) for v in inst.Delta)/sum(t.energy for t in inst.trips)
        require(abs(gamma-spec["gamma"]) <= 1e-12, "Fixed gamma subset mismatch")
        audit = result["audit"]
        require(audit["passed"] and audit["all_seeds_witnessed_in_scenario_graph"]
                and audit["off_grid_seed_count"] == 0 and audit["seed_count"] == inst.n_trips
                and audit["truck_discharge_allowed"] == (arm in ("v2g_fleet", "v2g"))
                and audit["stationary_storage_allowed"] == (arm in ("solar_bess", "v2g")),
                "Scenario graph/seed audit mismatch")
        objective, bound = result.get("objective"), result.get("bound")
        if finite(objective) and finite(bound):
            require(bound <= objective+TOL, "Native lower bound exceeds supplied incumbent")
            out["absolute_native_gap"] = max(0., objective-bound)
            out["recomputed_relative_gap"] = abs(objective-bound)/abs(objective) if objective else None
            if finite(result.get("gap")) and objective:
                require(abs(result["gap"]-out["recomputed_relative_gap"]) <= TOL,
                        "Reported native gap disagrees with objective and bound")
        bound_status = result["status"] in ("optimal", "time_limit", "interrupted")
        out["native_lower_bound_usable"] = bool(bound_status and finite(bound))
        out["metadata_passed"] = True
        out["environment"] = manifest["environment"]
        out["physical_sha256"] = physical
        if finite(objective):
            require({"primal.npz", "physical_replay.json.gz"}.issubset(result["evidence_sha256"]),
                    "Missing hashed incumbent evidence")
            with gzip.open(folder / "physical_replay.json.gz", "rt") as handle:
                validation = json.load(handle)
            independent, columns = replay_direct(inst, {**result, "validation": validation}, True)
            out["truck_discharge_model_units"] = scenario_replay(validation, arm)
            out["independent_physical_replay"] = independent
            out["original_vendor_master"] = original_master_replay(inst, result, validation, columns, arm)
            out["raw_primal_consistency"] = npz_replay(folder, result, validation, inst)
            out["validated_upper_bound"] = max(objective, independent["replayed_objective"],
                                                  out["original_vendor_master"]["objective"])+TOL
            out["upper_bound_transfers"] = []
            reachable = {arm}
            for _ in ARMS:
                reachable |= {b for a,b in EDGES if a in reachable}
            for target in ARMS:
                if target not in reachable or target == arm:
                    continue
                scenario_replay(validation, target)
                original_master_replay(inst, result, validation, columns, target)
                out["upper_bound_transfers"].append(target)
        out["passed"] = True
    except Exception as exc:
        out["error"] = repr(exc)
        # A failed physical replay rejects its upper bound. A failure before the
        # full metadata guard also rejects the solver-bound/model association.
        if not out.get("metadata_passed"):
            out["native_lower_bound_usable"] = False
        out["validated_upper_bound"] = None
    return out


def propagate(intervals):
    z = {arm: list(intervals[arm]) for arm in ARMS}
    for _ in ARMS:
        for restrictive, flexible in EDGES:
            z[restrictive][0] = max(z[restrictive][0], z[flexible][0])
            z[flexible][1] = min(z[flexible][1], z[restrictive][1])
    require(all(lo <= hi for lo,hi in z.values()), "Inconsistent nested cost intervals")
    return z


def share_interval(z, arm):
    al, au = z["solar"]; bl, bu = z[arm]; dl, du = z["v2g"]
    lo = max(0., al-bu)/(al-dl) if finite(al) and al > dl else 0.
    end = min(du, bl)
    hi = (au-bl)/(au-end) if finite(au) and au > end else 1.
    require(-1e-12 <= lo <= hi <= 1+1e-12, "Invalid nested share endpoints")
    return [max(0., lo), min(1., hi)]


def fractional_reduction(z, restrictive, flexible):
    al, au = z[restrictive]; bl, bu = z[flexible]
    lo = max(0., 1-bu/al) if al > 0 and finite(bu) else 0.
    hi = min(1., 1-bl/au) if au > 0 and finite(au) else 1.
    require(-1e-12 <= lo <= hi <= 1+1e-12, "Invalid daily-reduction endpoints")
    return [max(0., lo), min(1., hi)]


def summarize_base(spec, workers):
    by = {w["scenario"]: w for w in workers}
    raw = {a: [max(0., by[a]["bound"]-TOL) if by[a]["native_lower_bound_usable"] else 0.,
                by[a]["validated_upper_bound"] if by[a]["validated_upper_bound"] is not None else math.inf]
           for a in ARMS}
    out = {"case": spec["case"], "n_tasks": spec["n_tasks"], "pv_scale": spec["pv_scale"],
        "draw_seed": spec["draw_seed"], "gamma": spec["gamma"], "raw_cost_intervals": raw,
        "all_workers_audited": all(w["passed"] for w in workers),
        "all_workers_have_validated_incumbents": all(w["validated_upper_bound"] is not None for w in workers)}
    try:
        for a,b in EDGES:
            if finite(raw[a][1]):
                require(b in by[a].get("upper_bound_transfers", []), "Unverified schedule transfer")
        z = propagate(raw)
        out["cost_intervals"] = z
        out["upper_bound_sources"] = {
            arm: [w["case"]+"/"+w["scenario"] for w in workers
                  if w["validated_upper_bound"] is not None
                  and (w["scenario"] == arm or arm in w.get("upper_bound_transfers", []))
                  and w["validated_upper_bound"] == z[arm][1]] for arm in ARMS}
        out["strictly_positive_joint_saving_certified"] = z["solar"][0] > z["v2g"][1]
        out["joint_saving_interval"] = [max(0., z["solar"][0]-z["v2g"][1]),
                                        z["solar"][1]-z["v2g"][0]]
        out["conditional_V2G_saving_interval"] = [max(0., z["solar_bess"][0]-z["v2g"][1]),
                                                  z["solar_bess"][1]-z["v2g"][0]]
        out["strict_additional_V2G_with_BESS_certified"] = z["solar_bess"][0] > z["v2g"][1]
        out["positive_cost_denominators_certified"] = z["solar"][0] > 0 and z["solar_bess"][0] > 0
        metrics = {"BESS_share": share_interval(z, "solar_bess"),
            "V2G_alone_share": share_interval(z, "v2g_fleet"),
            "V2G_alone_daily_reduction": fractional_reduction(z, "solar", "v2g_fleet")}
        if spec["gamma"] <= .35:
            metrics["V2G_with_BESS_daily_reduction_low_gamma"] = fractional_reduction(z, "solar_bess", "v2g")
        if spec["gamma"] > 2:
            metrics["V2G_with_BESS_daily_reduction_high_gamma"] = fractional_reduction(z, "solar_bess", "v2g")
        out.update(metrics=metrics, passed=True)
    except Exception as exc:
        # Keep this base; an audit failure cannot silently create a 269-base median.
        out.update(passed=False, error=repr(exc), strictly_positive_joint_saving_certified=False,
                   positive_cost_denominators_certified=False)
        names = ["BESS_share", "V2G_alone_share", "V2G_alone_daily_reduction"]
        if spec["gamma"] <= .35: names.append("V2G_with_BESS_daily_reduction_low_gamma")
        if spec["gamma"] > 2: names.append("V2G_with_BESS_daily_reduction_high_gamma")
        out["metrics"] = {key: [0., 1.] for key in names}
    return out


def rounded_claim(interval, original_percent, places, denominators_certified):
    lo, hi = [100*x for x in interval]; width = 10.**(-places)
    candidate = math.floor(((lo+hi)/2)/width+.5)*width
    resolved = lo > candidate-width/2 and hi < candidate+width/2
    original_excluded = hi < original_percent-width/2 or lo > original_percent+width/2
    return {"original_percent": original_percent, "display_decimal_places": places,
        "median_interval_percent": [lo, hi], "denominators_certified": denominators_certified,
        "resolved_to_displayed_precision": bool(resolved and denominators_certified),
        "new_rounded_percent": round(candidate, places) if resolved and denominators_certified else None,
        "original_supported_to_displayed_precision": bool(resolved and denominators_certified
            and abs(candidate-original_percent) < width/10),
        "original_rounding_cell_excluded": bool(original_excluded and denominators_certified),
        "boundary_rule": "Both endpoints strictly inside the same rounding cell"}


def population_summary(bases, workers):
    metrics = {}
    for name, (headline, places) in METRICS.items():
        selected = [b for b in bases if name in b["metrics"]]
        lower = sorted(b["metrics"][name][0] for b in selected)
        upper = sorted(b["metrics"][name][1] for b in selected)
        n = len(selected); interval = [median(lower), median(upper)]
        denom = all(b["strictly_positive_joint_saving_certified"] if name.endswith("share")
                    else b["positive_cost_denominators_certified"] for b in selected)
        positions = [n//2, n//2+1] if n%2 == 0 else [n//2+1]
        metrics[name] = {"count": n, "median_interval": interval,
            "median_interval_percent_outward_2dp": [math.floor(interval[0]*10000)/100,
                                                     math.ceil(interval[1]*10000)/100],
            "one_based_median_order_statistics": positions,
            "lower_endpoint_order_values": [lower[i-1] for i in positions],
            "upper_endpoint_order_values": [upper[i-1] for i in positions],
            "median_individual_interval_width": median(b["metrics"][name][1]-b["metrics"][name][0] for b in selected),
            "rounding_decision": rounded_claim(interval, headline, places, denom)}
    require(len(bases) == 270 and len(workers) == 1080, "Fixed population denominator changed")
    require(metrics["V2G_with_BESS_daily_reduction_low_gamma"]["count"] == 30
            and metrics["V2G_with_BESS_daily_reduction_high_gamma"]["count"] == 100, "Gamma subset changed")
    present = [w for w in workers if w["present"]]
    attempts_finished = all(w["present"] or w.get("execution", {}).get("execution", {}).get("returncode") is not None
                            or w.get("execution", {}).get("execution", {}).get("external_timeout") for w in workers)
    times = [w["solve_end_to_end_seconds"] for w in workers if finite(w.get("solve_end_to_end_seconds"))]
    replayed = [w for w in workers if w.get("validated_upper_bound") is not None]
    maximum = lambda key: max((max(w[key]["residuals"].values()) for w in replayed), default=None)
    for item in metrics.values():
        item["rounding_decision"]["publication_decision_provisional"] = not attempts_finished
    return {"expected_workers": 1080, "expected_bases": 270, "present_workers": len(present),
        "all_attempts_finished": attempts_finished,
        "analysis_state": "all_attempts_finished" if attempts_finished else "incomplete_checkpoint",
        "status_counts": dict(sorted(Counter(w["status"] for w in workers).items())),
        "worker_audits_passed": sum(w["passed"] for w in workers),
        "usable_new_native_bounds": sum(w["native_lower_bound_usable"] for w in workers),
        "independently_validated_new_incumbents": sum(w["validated_upper_bound"] is not None for w in workers),
        "base_interval_audits_passed": sum(b["passed"] for b in bases),
        "bases_with_positive_joint_saving_certified": sum(b["strictly_positive_joint_saving_certified"] for b in bases),
        "bases_with_strict_additional_V2G_with_BESS_certified": sum(b.get("strict_additional_V2G_with_BESS_certified", False) for b in bases),
        "bases_with_additional_V2G_with_BESS_sign_unresolved": 270-sum(b.get("strict_additional_V2G_with_BESS_certified", False) for b in bases),
        "all_workers_present_and_audited": len(present) == 1080 and all(w["passed"] for w in workers),
        "independent_replay": {"transitions_checked": sum(w["independent_physical_replay"]["transitions"] for w in replayed),
            "maximum_physical_residual": maximum("independent_physical_replay"),
            "maximum_vendor_master_residual": maximum("original_vendor_master"),
            "maximum_npz_consistency_residual": maximum("raw_primal_consistency")},
        "solve_timing_seconds": {"count": len(times), "minimum": min(times) if times else None,
            "median": median(times) if times else None, "maximum": max(times) if times else None,
            "sum": sum(times), "soft_limit_overshoot_count": sum(t > 60 for t in times)},
        "metrics": metrics,
        "interpretation": "Full-population numerical intervals, using only new uniform-budget evidence. Unfinished and missing cases are retained; shares with uncertified joint denominators remain conditional."}


def original_comparison(specs):
    """Separately reproduce displayed original points; never supply cost bounds."""
    source = ROOT / "results/planning_common_audit_20261012.json"
    require(sha(source) == read(INPUTS)["historical_audit_sha256"], "Original comparison source changed")
    rows = {}
    for entry in read(source)["input_records"]:
        r = entry["record"]
        rows.setdefault((r["n_tasks"], r["pv"], r["seed"]), {})[r["scenario"]] = r["total"]
    require(len(rows) == 270 and all(set(r) == set(ARMS) for r in rows.values()), "Original comparison denominator changed")
    values = {key: [] for key in METRICS}
    for spec in specs:
        z = rows[(spec["n_tasks"], spec["pv_scale"], spec["draw_seed"])]; a = z["solar"]; d = z["v2g"]
        require(a > d and a > 0 and z["solar_bess"] > 0, "Undefined original point statistic")
        values["BESS_share"].append((a-z["solar_bess"])/(a-d))
        values["V2G_alone_share"].append((a-z["v2g_fleet"])/(a-d))
        values["V2G_alone_daily_reduction"].append(1-z["v2g_fleet"]/a)
        conditional = 1-d/z["solar_bess"]
        if spec["gamma"] <= .35: values["V2G_with_BESS_daily_reduction_low_gamma"].append(conditional)
        if spec["gamma"] > 2: values["V2G_with_BESS_daily_reduction_high_gamma"].append(conditional)
    return {"scope": "Supplementary original rounded restricted-incumbent point estimates only; excluded from every primary bound",
        "source_sha256": sha(source), "source": str(source),
        "metrics": {key: {"count": len(v), "median_point_estimate": median(v),
            "median_percent": 100*median(v), "displayed_percent": METRICS[key][0]} for key,v in values.items()},
        "gamma_membership": {"definition": "Sum of negative net-demand magnitudes divided by total task traction energy; computed before rounding gamma",
            "low_threshold": .35, "high_threshold": 2,
            "low_cases": [s["case"] for s in specs if s["gamma"] <= .35],
            "high_cases": [s["case"] for s in specs if s["gamma"] > 2],
            "minimum_distance_to_low_threshold": min(abs(s["gamma"]-.35) for s in specs),
            "minimum_distance_to_high_threshold": min(abs(s["gamma"]-2) for s in specs),
            "two_decimal_rounding_changes_membership": [s["case"] for s in specs
                if (round(s["gamma"],2) <= .35) != (s["gamma"] <= .35)
                or (round(s["gamma"],2) > 2) != (s["gamma"] > 2)]}}


def safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict): return {k: safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [safe(v) for v in value]
    return value


def write_report(report, output):
    require(not output.exists(), "Use a fresh derived output directory")
    output.mkdir(parents=True)
    (output / "population_summary.json").write_text(json.dumps(safe(report), indent=2, allow_nan=False)+"\n")
    (output / "interval_proof.md").write_text(PROOF)
    with (output / "worker_outcomes.csv").open("w", newline="") as handle:
        fields = ["case", "scenario", "status", "present", "passed", "objective", "bound", "gap",
                  "native_lower_bound_usable", "validated_upper_bound", "solve_end_to_end_seconds", "error"]
        writer = csv.DictWriter(handle, fields, extrasaction="ignore"); writer.writeheader()
        writer.writerows(report["workers"])
    with (output / "base_intervals.csv").open("w", newline="") as handle:
        fields = ["case", "n_tasks", "pv_scale", "draw_seed", "gamma", "passed",
                  "strictly_positive_joint_saving_certified"]
        fields += [f"{key}_{end}" for key in METRICS for end in ("lower", "upper")]
        writer = csv.DictWriter(handle, fields, extrasaction="ignore"); writer.writeheader()
        for base in report["bases"]:
            row = {k:v for k,v in base.items() if k in fields}
            for key, (lo,hi) in base["metrics"].items():
                row[key+"_lower"] = lo; row[key+"_upper"] = hi
            writer.writerow(row)
    s = report["summary"]
    lines = ["# Uniform 60-second population verification", "",
        f"All {s['expected_workers']} configuration outcomes and {s['expected_bases']} bases are retained. "
        f"{s['present_workers']} results are present; {s['worker_audits_passed']} pass the independent audit. "
        f"{s['independently_validated_new_incumbents']} new incumbents are physically replayed and "
        f"{s['usable_new_native_bounds']} new native bounds are usable.", "",
        "Status counts: "+", ".join(f"{k}: {v}" for k,v in s["status_counts"].items())+".", "",
        f"Positive joint savings are certified for {s['bases_with_positive_joint_saving_certified']}/270 bases. "
        "Any remaining share intervals are conditional on positive joint saving. "
        "These are floating-point bounds, not exact-arithmetic certificates.", "",
        "| Statistic | Cases | Original incumbent median (%) | New median interval (%) | Rounded value resolved | Original display supported |",
        "|---|---:|---:|---:|---:|---:|"]
    for name, item in s["metrics"].items():
        d = item["rounding_decision"]; lo,hi = item["median_interval_percent_outward_2dp"]
        old = report["separate_original_comparison"]["metrics"][name]["median_percent"]
        lines.append(f"| {name} | {item['count']} | {old:.8f} | {lo:.2f}–{hi:.2f} | "
                     f"{d['new_rounded_percent'] if d['resolved_to_displayed_precision'] else 'unresolved'} | "
                     f"{'yes' if d['original_supported_to_displayed_precision'] else 'no / unresolved'} |")
    lines += ["", "The primary intervals use only this uniform run. Original rounded results and the "
              "three selected 1,800-second diagnostics are excluded. Native optimal status does not "
              "erase a nonzero objective-bound gap. A null upper cost endpoint in JSON means unbounded, "
              "not a zero cost. Displayed interval endpoints are rounded outward to two decimal "
              "percentage places; rounding decisions use the full-precision JSON endpoints. "
              "No optimization is performed by this analyzer."]
    if not s["all_attempts_finished"]:
        lines += ["", "This is an incomplete checkpoint. All publication decisions remain provisional until the fixed pass finishes."]
    (output / "population_summary.md").write_text("\n".join(lines)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    specs = read(INPUTS)["cases"]
    require(len(specs) == 270 and len({s["case"] for s in specs}) == 270, "Population input count mismatch")
    dependencies = {name: sha(ROOT / name) for name in DEPENDENCIES}
    vendor = read(ROOT / "source_manifest.json")
    for name, record in vendor["files"].items():
        require(sha(ROOT / "vendor" / name) == record["sha256"], f"Frozen vendor changed: {name}")
    workers = []; bases = []
    for index, spec in enumerate(specs):
        current = [audit_worker(args.input_root / f"base_{index}", spec, arm, dependencies, vendor) for arm in ARMS]
        workers.extend(current); bases.append(summarize_base(spec, current))
    summary = population_summary(bases, workers)
    report = {"created_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "optimization_performed": False,
        "primary_scope": "All 270 original COMMON4 bases, all four configurations, new uniform 60-second direct MIPs only",
        "integer_model_scope": "Complete finite DP-path plus original real-seed family, original continuous BESS dispatch and integer asset counts; no claim of continuous-truck-energy integer-fleet equivalence",
        "input_root": str(args.input_root.resolve()), "population_inputs_sha256": sha(INPUTS),
        "checker_sha256": sha(__file__), "checker_dependencies_sha256": {
            "verify_extension_results.py": sha(ROOT / "verify_extension_results.py"),
            "vendor/master.py": sha(ROOT / "vendor/master.py")},
        "worker_dependencies_sha256": dependencies, "absolute_numerical_allowance": TOL,
        "summary": summary, "separate_original_comparison": original_comparison(specs),
        "workers": workers, "bases": bases}
    write_report(report, args.output_dir)
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
