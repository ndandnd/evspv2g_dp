"""No-solve audit and bound intersection for all 187 planning refinements.

Keeps the original1080 population and reports a separately labeled refinement.
Every new incumbent receives the same constructive repair and independent replay.
"""
from __future__ import annotations
import argparse
from collections import Counter
import copy
import csv
import datetime as dt
import gzip
import json
import math
from pathlib import Path

import numpy as np
import summarize_planning_population as audit
import planning_population_numerical_sensitivity as repair_module

ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "planning_refinement_inputs.json"
DEFAULT_PRIMARY = ROOT / "results/planning_population_analysis_final_20261012/population_summary.json"
DEFAULT_REPAIR = ROOT / "results/planning_population_numerical_sensitivity_verified_20261012/numerical_sensitivity.json"
DEFAULT_MIGRATION = ROOT / "results/planning_refinement_deployment_20261013/migration_manifest.json"
MIGRATION_SHA256 = "e1ddec584e28a1a06317735db61f76595b9c08fec6845769fc301583c9456fde"
DEPS = audit.DEPENDENCIES + ("planning_refinement.py", "planning_refinement_inputs.json",
                           "PLANNING_REFINEMENT_PROTOCOL.md")
THREAD_KEYS = {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
               "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"}
V1_SNAPSHOT = ROOT / "results/planning_refinement_deployment_20261013/code"
V1_FROZEN = {"planning_refinement.py":"6ed7882c2757198a093a9d3e3d2534d198b363beec7c05272486b4e69c00dbd7",
    "PLANNING_REFINEMENT_PROTOCOL.md":"3182e35535a298c699fbffb8dbe8ca941b90219f236a2c5f1af8698b4792eb25"}


def v1_runtime_code():
    code = {n:audit.sha(V1_SNAPSHOT/n) for n in DEPS}
    audit.require(all(code[n] == h for n,h in V1_FROZEN.items()), "Original v1 deployment snapshot changed")
    audit.require(all(code[n] == audit.sha(ROOT/n) for n in DEPS if n not in V1_FROZEN),
                  "V1/v2 physical inputs or baseline dependencies differ")
    return code


def migration_versions(path):
    audit.require(audit.sha(path) == MIGRATION_SHA256, "Frozen queue-only migration manifest changed")
    record = audit.read(path)
    migrated, retained = record["migration_indices"], record["retained_indices"]
    audit.require(record["original_array"] == 242531
                  and record["selection_basis"] == "never_started_pending_queue_state"
                  and record["scientific_outcomes_used"] is False,
                  "Migration manifest must declare queue-only selection")
    audit.require(all(type(i) is int for i in migrated+retained)
                  and len(migrated) == len(set(migrated)) and len(retained) == len(set(retained))
                  and not set(migrated)&set(retained) and set(migrated)|set(retained) == set(range(187)),
                  "Migration manifest must partition all187 indices exactly once")
    accounting = {}
    for line in record["accounting_stdout"].splitlines():
        job, state, elapsed, cpus = line.split("|")
        prefix, index = job.split("_")
        audit.require(prefix == "242531" and int(index) not in accounting,
                      "Ambiguous original-array accounting record")
        accounting[int(index)] = (state, int(elapsed), int(cpus))
    audit.require(set(accounting) == set(range(187))
                  and all(accounting[i][0].startswith("CANCELLED")
                          and accounting[i][1:] == (0,0) for i in migrated),
                  "Migrated index was not confirmed cancelled before execution")
    return {**{i:"v1_lisbeth" for i in retained}, **{i:"v2_cdses" for i in migrated}}, record


def find_launches(root):
    launches = {}
    for path in root.rglob("launch_manifest.json"):
        data = audit.read(path)
        if "selection" not in data:
            continue
        idx = data["selection"]["refinement_index"]
        audit.require(idx not in launches, "Duplicate refinement launch index")
        audit.require(0 <= idx < 187, "Unexpected refinement launch index")
        launches[idx] = path.parent
    return launches


def audit_new(entry, launch_dir, expected_code, vendor, expected_deployment=None):
    out = {"refinement_index": entry["refinement_index"], "case": entry["spec"]["case"],
        "scenario": entry["scenario"], "status": "missing", "present": False,
        "passed": False, "metadata_passed": False, "native_lower_bound_usable": False,
        "validated_upper_bound": None, "repaired_objective": None}
    if launch_dir is None:
        return out, None
    folder = launch_dir / "worker"
    out["directory"] = str(folder.resolve())
    if (launch_dir / "execution.json").exists():
        out["execution"] = audit.read(launch_dir / "execution.json")
        if out["execution"]["execution"].get("external_timeout"):
            out["status"] = "external_timeout"
    if not (folder / "result.json").exists():
        return out, None
    repaired = None
    try:
        result = audit.read(folder / "result.json")
        out.update(present=True, result_sha256=audit.sha(folder / "result.json"))
        out.update({k: result.get(k) for k in ("status", "objective", "bound", "gap",
            "solution_count", "solve_end_to_end_seconds", "solver_runtime_seconds",
            "diagnostic_seconds", "graph_arcs", "graph_nodes", "variables", "integer_variables")})
        audit.require(not out.get("execution", {}).get("execution", {}).get("external_timeout"),
                      "External watchdog output cannot supply a bound")
        launch = audit.read(launch_dir / "launch_manifest.json")
        manifest = audit.read(folder / "manifest.json")
        raw = audit.read(folder / "instance.json")
        spec, arm = entry["spec"], entry["scenario"]
        audit.require(launch["selection"] == entry == manifest["selection"], "Selection identity changed")
        audit.require(launch["inputs_sha256"] == manifest["refinement_inputs_sha256"] == audit.sha(INPUTS),
                      "Refinement manifest hash changed")
        audit.require(launch["budget_seconds"] == 300 and launch["watchdog_seconds"] == 420,
                      "Launcher budget/watchdog mismatch")
        audit.require(raw == entry["instance_record"] and manifest["case"] == spec
                      and manifest["scenario"] == arm, "Exact original input identity mismatch")
        audit.require(audit.content_hash({k:v for k,v in raw.items() if k != "sha256"}) == raw["sha256"],
                      "Instance payload hash mismatch")
        physical = audit.content_hash({k:v for k,v in raw.items() if k not in ("spec", "sha256")})
        audit.require(physical == spec["physical_sha256"] == manifest["physical_sha256"] == result["physical_sha256"],
                      "Physical input hash mismatch")
        audit.require(raw["sha256"] == manifest["instance_sha256"] == result["instance_sha256"],
                      "Instance identity differs")
        audit.require(result["refinement_index"] == entry["refinement_index"]
                      and result["case"] == spec["case"] and result["scenario"] == arm
                      and result["prior_result_sha256"] == entry["prior_result_sha256"], "Result identity mismatch")
        if manifest["code_sha256"] == expected_code:
            deployment, required_host = "v2_cdses", "cdses-compute-01"
        elif manifest["code_sha256"] == v1_runtime_code():
            deployment, required_host = "v1_lisbeth", "lisbeth"
        else:
            raise AssertionError("Neither exact v1 nor exact v2 frozen runtime hashes match")
        audit.require(manifest["vendor_manifest"] == vendor, "Frozen vendor identity mismatch")
        audit.require(expected_deployment is None or deployment == expected_deployment,
                      "Worker deployment differs from queue-selected migration index manifest")
        out.update(deployment_version=deployment, required_host=required_host)
        for name, digest in result["evidence_sha256"].items():
            path = (folder/name).resolve()
            audit.require(path.is_relative_to(folder.resolve()) and path.is_file() and audit.sha(path) == digest,
                          "Evidence mismatch: "+name)
        audit.require({"instance.json", "manifest.json"}.issubset(result["evidence_sha256"]),
                      "Missing input evidence digests")
        audit.require(result["method"] == "planning_refinement_mip" and result["budget_seconds"] == 300
                      and result["threads"] == 1 and result["seed"] == 0 and result["solver_method"] == -1
                      and result["crossover"] == -1 and result["cold_solve"]
                      and not result["solution_or_basis_sharing"], "Cold solve controls differ")
        audit.require(result["solver_version"] == [12,0,3] and result["mip_gap_tolerance"] == 1e-6
                      and result["mip_gap_absolute_tolerance"] == 1e-10
                      and all(result[k] == 1e-8 for k in ("feasibility_tolerance", "optimality_tolerance",
                                                        "integer_feasibility_tolerance")), "Solver tolerances differ")
        protocol = manifest["protocol"]
        audit.require(protocol["budget_seconds"] == 300 and protocol["watchdog_seconds"] == 420
                      and protocol["baseline_budget_override_only"] and not protocol["standalone_lp"]
                      and not protocol["external_warm_starts"], "Manifest protocol differs")
        if deployment == "v2_cdses":
            audit.require(protocol.get("required_host") == required_host
                          and protocol.get("required_cpu_model") == "AMD EPYC 9654 96-Core Processor"
                          and protocol.get("scheduling_amendment") == "2026-10-13-mixed-node-queue-only"
                          and protocol.get("migrated_index_range_inclusive") == [2,186],
                          "V2 scheduling amendment not declared")
        else:
            audit.require(protocol.get("scheduling_amendment") is None,
                          "V1 result cannot claim an amended deployment")
        env = manifest["environment"]
        audit.require(env["gurobi"] == [12,0,3] and env["allocated_cpus"] == "1"
                      and len(env["cpu_affinity"]) == 1 and set(env["thread_environment"]) == THREAD_KEYS
                      and all(v == "1" for v in env["thread_environment"].values())
                      and env["cpu_model"] == "AMD EPYC 9654 96-Core Processor"
                      and env["host"].split(".")[0] == required_host,
                      "Hardware/CPU allocation differs from its exact v1/v2 deployment")
        audit.require(all(result[k] == v for k,v in entry["prior_model_signature"].items()),
                      "Refinement model dimensions differ from the original")
        ga = result["audit"]
        audit.require(ga["passed"] and ga["all_seeds_witnessed_in_scenario_graph"]
                      and ga["off_grid_seed_count"] == 0 and ga["seed_count"] == spec["n_tasks"]
                      and ga["truck_discharge_allowed"] == (arm in ("v2g_fleet", "v2g"))
                      and ga["stationary_storage_allowed"] == (arm in ("solar_bess", "v2g")),
                      "Scenario graph/seed witness audit mismatch")
        if audit.finite(result.get("objective")) and audit.finite(result.get("bound")):
            out["absolute_native_gap"] = max(0.,result["objective"]-result["bound"])
            out["recomputed_relative_gap"] = (abs(result["objective"]-result["bound"])
                /abs(result["objective"])) if result["objective"] else None
            if audit.finite(result.get("gap")) and result["objective"]:
                audit.require(abs(result["gap"]-out["recomputed_relative_gap"]) <= 1e-6,
                              "Native gap disagrees with objective and bound")
        out["metadata_passed"] = True
        out["native_lower_bound_usable"] = result["status"] in ("optimal", "time_limit") and audit.finite(result.get("bound"))
        out["upper_bound_transfers"] = []
        reachable = {arm}
        for _ in audit.ARMS:
            reachable |= {b for a,b in audit.EDGES if a in reachable}
        out["upper_bound_transfers"] = [a for a in audit.ARMS if a in reachable and a != arm]
        if audit.finite(result.get("objective")):
            audit.require({"primal.npz", "physical_replay.json.gz"}.issubset(result["evidence_sha256"]),
                          "Missing incumbent artifacts")
            if out["native_lower_bound_usable"]:
                audit.require(result["bound"] <= result["objective"]+1e-6, "Native bound exceeds incumbent")
            inst = audit.instance_from_record(raw)
            with gzip.open(folder / "physical_replay.json.gz", "rt") as stream:
                val = json.load(stream)
            physical_check, columns = audit.replay_direct(inst, {**result,"validation":val}, True)
            out["raw_physical_replay"] = physical_check
            out["raw_vendor_master"] = audit.original_master_replay(inst, result, val, columns, arm)
            out["raw_primal_consistency"] = audit.npz_replay(folder, result, val, inst)
            # The frozen repair routine checks a lower bound against its new
            # primal. If native-bound evidence is absent, use only the universal
            # zero lower bound for that internal check; never report it as a
            # solver bound or lose an independently valid primal for this reason.
            repair_input = dict(out)
            if not out["native_lower_bound_usable"]:
                repair_input["bound"] = 0.0
            repaired = repair_module.repair(repair_input)
            out["repaired_objective"] = repaired["repaired_objective"]
            out["validated_upper_bound"] = repaired["repaired_objective"]+1e-6
            out["objective_repair_change"] = repaired["objective_change"]
            out["independent_physical_replay"] = repaired["independent_physical_replay"]
            out["original_vendor_master"] = repaired["original_vendor_master"]
        out["passed"] = True
    except Exception as exc:
        out["error"] = repr(exc)
        if not out["metadata_passed"]:
            out["native_lower_bound_usable"] = False
        out["validated_upper_bound"] = None
        out["repaired_objective"] = None
        repaired = None
    return out, repaired


def intersect_population(primary, prior_profiles, new, allowance):
    """Intersect endpoints before technology nesting; never replace by status."""
    old_repair = {(r["case"],r["scenario"]):r for r in prior_profiles}
    new_by = {(r["case"],r["scenario"]):r for r in new}
    combined = copy.deepcopy(primary["workers"])
    counts = Counter()
    for w in combined:
        key = (w["case"],w["scenario"])
        old = old_repair[key]
        audit.require(old["source_result_sha256"] == w["result_sha256"], "Prior repaired profile/result link differs")
        lows = [(w["bound"], "original60")]
        ups = [(old["repaired_objective"], "original60")]
        candidate = new_by.get(key)
        if candidate and candidate["native_lower_bound_usable"]:
            lows.append((candidate["bound"], "refinement300"))
        if candidate and candidate["repaired_objective"] is not None:
            ups.append((candidate["repaired_objective"], "refinement300"))
        low = max(x[0] for x in lows); upper = min(x[0] for x in ups)
        audit.require(low-allowance <= upper+allowance, "Inconsistent old/new bound intersection: "+str(key))
        w["bound"] = low
        w["validated_upper_bound"] = upper+allowance
        w["endpoint_sources"] = {"lower":[s for x,s in lows if x == low],
                                 "upper":[s for x,s in ups if x == upper]}
        w["endpoint_candidates"] = {"lower":lows,"repaired_upper":ups}
        w["original_status"] = w["status"]
        w["refinement_status"] = candidate["status"] if candidate else "not_selected"
        counts["strict_lower_improvements"] += int(low > lows[0][0]+1e-9)
        counts["strict_upper_improvements"] += int(upper < ups[0][0]-1e-9)
        if w["endpoint_sources"]["upper"] == ["refinement300"]:
            w["independent_physical_replay"] = candidate["independent_physical_replay"]
            w["original_vendor_master"] = candidate["original_vendor_master"]
        else:
            w["independent_physical_replay"] = old["independent_physical_replay"]
            w["original_vendor_master"] = old["original_vendor_master"]
    audit.TOL = allowance
    specs = audit.read(audit.INPUTS)["cases"]
    bases = [audit.summarize_base(spec, combined[4*i:4*i+4]) for i,spec in enumerate(specs)]
    audit.require(all(b["passed"] for b in bases), "An intersected/nested base interval failed")
    return {"allowance_dollars":allowance, "endpoint_improvements":dict(counts),
        "summary":audit.population_summary(bases, combined), "bases":bases,
        "positive_saving_population_envelope":repair_module.positive_population_envelope(bases),
        "endpoint_sources":[{"case":w["case"],"scenario":w["scenario"],
            "sources":w["endpoint_sources"],"candidates":w["endpoint_candidates"]}for w in combined]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--primary", type=Path, default=DEFAULT_PRIMARY)
    parser.add_argument("--prior-repair", type=Path, default=DEFAULT_REPAIR)
    parser.add_argument("--migration-manifest", type=Path, default=DEFAULT_MIGRATION)
    parser.add_argument("--recovery-manifest", type=Path,
                        help="Optional immutable scheduler-preemption/recovery snapshot")
    parser.add_argument("--queue-return-manifest", type=Path,
                        help="Optional second never-started queue map returning indices to frozen v1")
    args = parser.parse_args()
    audit.require(not args.output_dir.exists(), "Fresh derived output directory required")
    selection = audit.read(INPUTS); primary = audit.read(args.primary); prior = audit.read(args.prior_repair)
    audit.require(audit.sha(args.primary) == selection["prior_primary_sha256"]
                  and audit.sha(args.prior_repair) == selection["prior_repair_sha256"], "Original audit changed")
    audit.require(audit.sha(audit.INPUTS) == selection["population_inputs_sha256"], "Original inputs changed")
    audit.require(primary["summary"]["all_workers_present_and_audited"], "Complete original audit required")
    expected = {(w["case"],w["scenario"]) for w in primary["workers"] if w["status"] == "time_limit"}
    actual = {(e["spec"]["case"],e["scenario"]) for e in selection["selected"]}
    audit.require(len(expected) == len(actual) == len(selection["selected"]) == 187 and expected == actual,
                  "Selection does not include exactly all original time limits")
    profile_path = args.prior_repair.parent / "repaired_profiles.json.gz"
    audit.require(audit.sha(profile_path) == prior["repaired_profiles_sha256"], "Prior repaired profiles changed")
    with gzip.open(profile_path, "rt") as stream:
        prior_profiles = json.load(stream)
    audit.require(len(prior_profiles) == 1080, "Incomplete prior repaired population")
    for w in primary["workers"]:
        audit.require(audit.sha(Path(w["directory"])/"result.json") == w["result_sha256"], "Original result changed")
    code = {n:audit.sha(ROOT/n) for n in DEPS}
    audit.require(all(code[n] == h for n,h in selection["prior_worker_dependencies_sha256"].items()),
                  "Original frozen dependencies changed")
    original_code = v1_runtime_code()
    deployment_by_index, migration_record = migration_versions(args.migration_manifest)
    # The worker uses verify_vendor's complete saved manifest, as the primary audit did.
    original_manifest = audit.read(Path(primary["workers"][0]["directory"])/"manifest.json")
    vendor = original_manifest["vendor_manifest"]
    from planning_refinement_recovery import resolve_launches, attach_attempt_status, check_original_identity
    launches, recovery_attempts, recovery_report = resolve_launches(args.input, args.recovery_manifest)
    from planning_refinement_queue_return import apply_return
    deployment_by_index, launches, queue_returns, queue_return_report = apply_return(
        args.input,args.queue_return_manifest,deployment_by_index,launches,recovery_attempts)
    rows, profiles = [], []
    for entry in selection["selected"]:
        audit.TOL = 1e-6
        if entry["refinement_index"] in recovery_attempts:
            check_original_identity(entry, recovery_attempts[entry["refinement_index"]],
                                    code, vendor, audit.sha(INPUTS))
        row, profile = audit_new(entry, launches.get(entry["refinement_index"]), code, vendor,
                                 deployment_by_index[entry["refinement_index"]])
        if entry["refinement_index"] in recovery_attempts:
            attach_attempt_status(row, recovery_attempts[entry["refinement_index"]])
        if entry["refinement_index"] in queue_returns:
            row["pending_only_queue_return"] = queue_returns[entry["refinement_index"]]
        rows.append(row)
        if profile is not None:
            profiles.append(profile)
    all_finished = all(r.get("infrastructure_attempts_finished",False) or r["present"] or r.get("execution",{}).get("execution",{}).get("returncode") is not None
                       or r.get("execution",{}).get("execution",{}).get("external_timeout") for r in rows)
    reports = {}
    for allowance in (1e-6,1e-4,1e-3):
        result = intersect_population(primary, prior_profiles, rows, allowance)
        old = prior["sensitivities"][str(allowance)]
        changes = {}
        for name, metric in result["summary"]["metrics"].items():
            earlier = old["summary"]["metrics"][name]["median_interval"]
            later = metric["median_interval"]
            audit.require(later[0] >= earlier[0]-1e-10 and later[1] <= earlier[1]+1e-10,
                          "Intersection widened a primary median interval")
            changes[name] = {"prior_interval":earlier,"intersected_interval":later,
                "prior_width":earlier[1]-earlier[0],"intersected_width":later[1]-later[0],
                "width_reduction":earlier[1]-earlier[0]-later[1]+later[0]}
            metric["rounding_decision"]["publication_decision_provisional"] = not all_finished
        result["median_interval_comparison"] = changes
        result["summary"]["interpretation"] = "Supplementary old/new bound intersection; baseline status counts preserved, refinement outcomes recorded separately"
        result["summary"]["all_refinement_attempts_finished"] = all_finished
        for metric in result["positive_saving_population_envelope"]["metrics"].values():
            metric["rounding_decision"]["publication_decision_provisional"] = not all_finished
        reports[str(allowance)] = result
    report = {"created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"optimization_performed":False,
        "scope":"Supplementary status-selected cold300-second refinement of all187 prior time limits; original1080 study preserved",
        "scheduling_scope":"Initial queue-only v1/v2 mapping, followed by any explicitly bound never-started queue-return map; no cross-node or cross-study timing comparisons",
        "migration_manifest_sha256":audit.sha(args.migration_manifest),
        "migration_manifest":migration_record,
        "infrastructure_recovery":recovery_report,
        "pending_only_queue_return":queue_return_report,
        "final_planned_deployment_counts":dict(Counter(deployment_by_index.values())),
        "recovery_outcome_counts":dict(Counter(r["status"] for r in rows if "infrastructure_recovery" in r)),
        "accepted_runtime_hashes":{"v1_lisbeth":original_code,"v2_cdses":code},
        "deployment_outcome_counts":dict(Counter(r.get("deployment_version","missing_or_unvalidated") for r in rows)),
        "selection_sha256":audit.sha(INPUTS),"original_primary_sha256":audit.sha(args.primary),
        "original_repair_sha256":audit.sha(args.prior_repair),"checker_sha256":audit.sha(__file__),
        "checker_dependencies_sha256":{n:audit.sha(ROOT/n) for n in ("summarize_planning_population.py",
            "planning_population_numerical_sensitivity.py","planning_refinement_recovery.py",
            "planning_refinement_queue_return.py",
            "verify_extension_results.py","vendor/master.py")},
        "expected_refinements":187,"present_refinements":sum(r["present"] for r in rows),
        "all_refinement_attempts_finished":all_finished,"status_counts":dict(Counter(r["status"] for r in rows)),
        "worker_audits_passed":sum(r["passed"] for r in rows),
        "usable_new_lower_bounds":sum(r["native_lower_bound_usable"] for r in rows),
        "independently_repaired_new_incumbents":len(profiles),"workers":rows,"allowances":reports}
    args.output_dir.mkdir(parents=True)
    with gzip.open(args.output_dir/"new_repaired_profiles.json.gz","wt") as stream:
        json.dump(profiles,stream,allow_nan=False)
    report["new_repaired_profiles_sha256"] = audit.sha(args.output_dir/"new_repaired_profiles.json.gz")
    (args.output_dir/"refinement_summary.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    fields = ("refinement_index","case","scenario","status","present","passed",
              "deployment_version","required_host",
              "metadata_passed","native_lower_bound_usable","objective","bound",
              "repaired_objective","objective_repair_change","solve_end_to_end_seconds","error")
    with (args.output_dir/"worker_outcomes.csv").open("w",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
        writer.writeheader();writer.writerows(rows)
    show = lambda pair: f"{pair[0]:.2f}–{pair[1]:.2f}%"
    text = ["# Supplementary planning refinement", "",
        f"All 187 original time-limit configurations are retained. {report['present_refinements']} new results are present; "
        f"{report['worker_audits_passed']} pass every new audit. This is a status-selected supplementary 300-second pass, "
        "not a uniform 300-second study of the full population and not a continuation of a saved search tree.", "",
        "Initial queue-only scheduling retained original v1 indices 0/1 on lisbeth and moved never-started indices 2–186 to "
        "v2 on cdses-compute-01. Any subsequent pending-only return is recorded separately below. Exact deployment hashes, hosts and index mapping are audited. No cross-node or "
        "cross-study timing comparison is made.", "",
        (f"The separately bound pending-only second map returns {queue_return_report['returned_count']} never-executed "
         "indices to the original frozen v1 on lisbeth. Zero elapsed time and zero CPU allocation are verified before "
         "accepting their first scientific attempt. Final planned deployment counts: "+str(report["final_planned_deployment_counts"]))
         if queue_return_report else "No second queue-return map supplied to this checkpoint.", "",
        (f"Infrastructure recovery: {recovery_report['recovery_count']} scheduler-preempted originals receive at most "
         f"one cold retry each; interrupted original elapsed time totals {recovery_report['interrupted_elapsed_seconds']} "
         "seconds. Both attempts are retained and any second infrastructure failure remains explicit. No interrupted "
         "partial bound is used. Recovery status counts: "+str(report["recovery_outcome_counts"]))
         if recovery_report else "No infrastructure-recovery manifest supplied to this checkpoint.", "",
        f"New statuses: {report['status_counts']}. All attempts finished: {all_finished}.", "",
        "The original 1,080 results remain unchanged. Every usable new primal is constructively repaired and independently "
        "replayed; every usable new native lower bound retains its solver-evidence qualification. Missing or rejected new "
        "endpoints preserve the original valid evidence. Native optimal status never replaces a nonzero interval.", "",
        "| Statistic | Original repaired interval | Intersected interval |", "| --- | ---: | ---: |"]
    for name,metric in reports["1e-06"]["summary"]["metrics"].items():
        previous = prior["sensitivities"]["1e-06"]["summary"]["metrics"][name]
        text.append(f"| {name} | {show(previous['median_interval_percent_outward_2dp'])} | "
                    f"{show(metric['median_interval_percent_outward_2dp'])} |")
    text += ["", "The share rows above retain their conditional all-270 interpretation. The separate true-positive-saving "
        "population envelope and its possible membership count are saved for every allowance in the JSON report. "
        "All rounding decisions use full-precision endpoints and remain provisional until every planned attempt finishes. "
        "The 1e-4 and 1e-3 dollar numerical sensitivities, endpoint-source identities, failures and exact width changes "
        "are also retained there. No optimization was performed by this analyzer."]
    (args.output_dir/"refinement_summary.md").write_text("\n".join(text)+"\n")
    print(json.dumps({k:report[k] for k in ("expected_refinements","present_refinements",
        "all_refinement_attempts_finished","status_counts","worker_audits_passed",
        "usable_new_lower_bounds","independently_repaired_new_incumbents")},indent=2))


if __name__ == "__main__":
    main()
