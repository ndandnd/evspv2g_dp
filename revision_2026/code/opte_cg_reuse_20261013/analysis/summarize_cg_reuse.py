"""Independent, read-only analysis of all 54 prespecified CG-reuse outcomes.

--input BATCH --output FRESH_DIRECTORY --verify [--supplement CERTIFICATE_JSON]
--verify replays compressed evidence with the unchanged LP checker, including
graph, original singleton and continuous periodic-BESS pricing. Supplementary
barrier certificates are accepted only with exact artifact-digest bindings and
remain a separate view. No solver is invoked and no input artifact is modified.
"""
from __future__ import annotations

import argparse
import collections
import copy
import csv
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"vendor"))
from run_cg_reuse import DEPENDENCIES, VARIANTS, experiment_plan, selected_cases
from run_pilot import safe, write_json
from summarize_lp_scaling import (TOL, audit_worker, count_values, digest,
                                  distribution, finite, write_csv)
from summarize_lp_supplement import check_record
from cg_reuse_recovery import load_recovery_map, execution_ledger, execution_counts

COMPARISONS = (("cold", "reuse"), ("barrier", "cold"), ("barrier", "reuse"))
EXPECTED_CPU = "AMD EPYC 9654 96-Core Processor"


def _positive(value):
    return finite(value) and value > 0


def _key(row):
    return row["case"], row["repeat"], row["variant"]


def load_supplement(paths):
    records = {}; reports = []
    expected = {(s["case"], r, "barrier") for s in selected_cases() for r in range(3)}
    for path in paths:
        data = json.loads(path.read_text())
        if data.get("post_hoc") is not True or data.get("primary_results_changed") is not False:
            raise ValueError("Supplement must declare post-hoc scope and unchanged primary results")
        reports.append({"path": str(path.resolve()), "sha256": digest(path),
                        "checker_sha256": data.get("checker_sha256")})
        for record in data["results"]:
            key = record.get("case"), record.get("repeat"), record.get("method")
            if key not in expected: raise ValueError(f"Unexpected supplementary identity: {key}")
            if key in records: raise ValueError(f"Duplicate supplementary identity: {key}")
            records[key] = record
    return records, reports


def audit_variant(folder, variant, block, verify, expected_cpu, expected_gurobi):
    method = "barrier" if variant == "barrier" else "cg"
    spec = next(s for s in selected_cases() if s["case"] == block["case_name"])
    # The frozen helper sees the correct native method for each individual
    # worker. Variant/position checks are imposed separately below.
    adapted = {**block, "methods": [method]}
    try:
        row, proof, manifest = audit_worker(folder, method, adapted, verify=False)
    except Exception as exc:
        row = {"case": block["case_name"], "repeat": block["repeat"], "method": method,
            "status": "malformed_evidence", "present": bool(folder), "identity_passed": False,
            "accepted_certificate": False, "saved_certificate_passed": False,
            "genuine_optimization_time_limit": False}
        proof = {"folder": str(folder), "errors": [repr(exc)], "replay": None}; manifest = None
    row.update(variant=variant, method_position=block["variants"].index(variant)+1,
        n_tasks=spec["n_tasks"], task_locations=15, draw_seed=spec["draw_seed"],
        independent_replay="not_requested", primary_accepted=False,
        supplementary_accepted=False, additional_posthoc_validation=False)
    if manifest is None: return row, proof, manifest
    errors = proof["errors"]
    if manifest.get("variant") != variant: errors.append("Wrong declared CG variant")
    if set(manifest.get("code_sha256", {})) != set(DEPENDENCIES):
        errors.append("Runtime dependency manifest is incomplete or changed")
    environment = manifest["environment"]
    if environment.get("gurobi") != expected_gurobi: errors.append("Unexpected Gurobi version")
    if environment.get("cpu_model") != expected_cpu: errors.append("Unexpected CPU model")
    if environment.get("allocated_cpus") != "1" or len(environment.get("cpu_affinity") or []) != 1:
        errors.append("Worker was not recorded in a one-CPU allocation/affinity")
    protocol = manifest["protocol"]
    for key, expected in (("cg_gurobi_method", -1), ("reuse_lp_warm_start", 1),
                          ("direct_gurobi_method", 2), ("direct_crossover", -1),
                          ("stabilization_beta", 0.5), ("same_allocation_within_block", True)):
        if protocol.get(key) != expected: errors.append(f"Protocol mismatch: {key}")
    if manifest.get("max_cg_iterations") != 20000: errors.append("Changed maximum CG iterations")
    result = json.loads((folder/"result.json").read_text())
    if result.get("variant") != variant: errors.append("Result variant disagrees with manifest")
    row["native_optimal"] = (bool(result.get("status") == "optimal" and result.get("native_status") == 2)
                             if method == "barrier" else None)
    row["native_optimal_scope"] = "Direct LP only; not applicable to top-level CG results"
    row["source_certified"] = bool(result.get("certified"))
    for key in ("cg_iterations", "rmp_call_count", "basis_restorations", "persistent_model_initializations",
                "rmp_implementation", "last_rmp_finished_elapsed_seconds", "process_peak_rss_after_diagnostics_bytes",
                "total_including_checks_seconds"):
        row[key] = result.get(key)
    if method == "cg":
        if result.get("cg_variant") != variant and result.get("status") not in ("error", "external_timeout"):
            errors.append("CG implementation variant missing or changed")
        calls = result.get("lp_calls", [])
        row["total_simplex_iterations"] = sum(c.get("iterations", 0) for c in calls)
        row["maximum_rmp_variables"] = max((c.get("variables", 0) for c in calls), default=None)
        row["maximum_rmp_constraints"] = max((c.get("constraints", 0) for c in calls), default=None)
        row["maximum_rmp_nonzeros"] = max((c.get("nonzeros", 0) for c in calls), default=None)
        if variant == "reuse" and calls:
            basis_ok = (calls[0].get("initial_model_build") is True
                and calls[0].get("explicit_basis_restored") is False
                and all(c.get("persistent_model") is True and c.get("gurobi_method") == -1
                        and c.get("lp_warm_start") == 1 for c in calls)
                and all(c.get("explicit_basis_restored") is True and c.get("initial_model_build") is False
                        for c in calls[1:])
                and result.get("basis_restorations") == len(calls)-1
                and result.get("persistent_model_initializations") == 1)
            proof["persistent_basis_protocol_passed"] = basis_ok
            if not basis_ok: errors.append("Persistent model/basis provenance differs from protocol")
        cert = result.get("certificate") or {}
        row["numerical_lower_bound"] = cert.get("pricing_tolerance_corrected_bound")
        row["graph_min_reduced_cost"] = cert.get("graph_min_reduced_cost")
        row["seed_min_reduced_cost"] = cert.get("seed_min_reduced_cost")
    else:
        native = result.get("native_dual_certificate") or {}
        row["numerical_lower_bound"] = native.get("dual_objective")
        row["native_primal_dual_gap"] = (native.get("residuals") or {}).get("primal_dual_objective_difference")
    if verify:
        from verify_lp_scaling import verify_worker
        replay = verify_worker(folder); proof["replay"] = replay
        row["independent_replay"] = "passed" if replay.get("passed") else "failed"
        row["independently_certified"] = bool(replay.get("independently_certified"))
        if not replay.get("passed"): errors.append("Independent primal/path/certificate replay failed")
        if row["source_certified"] and not row["independently_certified"]:
            errors.append("Claimed certificate did not pass independent verification")
    row["identity_passed"] = not errors
    row["primary_accepted"] = bool(row["saved_certificate_passed"] and not errors
        and (not verify or row.get("independently_certified")))
    # Keep the frozen helper's field aligned with strict acceptance for its
    # supplementary certificate validator; never overwrite the native flag.
    row["accepted_certificate"] = row["primary_accepted"]
    proof["identity_passed"] = row["identity_passed"]
    return row, proof, manifest


def pair(a, b, supplementary=False):
    out = {k: a[k] for k in ("case", "repeat", "n_tasks", "draw_seed")}
    out.update(numerator=a["variant"], denominator=b["variant"],
        ratio_definition=f"time({a['variant']})/time({b['variant']}); >1 favors {b['variant']}",
        view="supplementary_barrier_full_family" if supplementary else "strict_primary",
        numerator_status=a["status"], denominator_status=b["status"],
        classification="unavailable_or_uncertified", ratio=None, ratio_lower_bound=None,
        ratio_upper_bound=None, absolute_objective_difference=None)
    if not a["identity_passed"] or not b["identity_passed"]:
        out["classification"] = "provenance_incomplete_or_failed"; return out
    accepted = lambda r: bool(r["primary_accepted"] or
        supplementary and r["variant"] == "barrier" and r["supplementary_accepted"])
    aa, ba = accepted(a), accepted(b)
    ta, tb = a.get("solve_end_to_end_seconds"), b.get("solve_end_to_end_seconds")
    ac, bc = a["genuine_optimization_time_limit"], b["genuine_optimization_time_limit"]
    if aa and ba:
        difference = abs(a["objective"]-b["objective"])
        out["absolute_objective_difference"] = difference
        intervals = []
        for r in (a, b):
            bound = (r.get("supplementary_lower_bound") if supplementary and r["variant"] == "barrier"
                     and r["supplementary_accepted"] else r.get("numerical_lower_bound"))
            objective = r["objective"]
            intervals.append([min(bound, objective)-TOL, max(bound, objective)+TOL] if finite(bound) else None)
        out.update(numerical_objective_intervals=intervals, interval_padding=TOL,
            interval_scope="Floating-point numerical evidence envelopes, not exact arithmetic enclosures")
        if difference > TOL:
            compatible = all(i is not None for i in intervals) and max(i[0] for i in intervals) <= min(i[1] for i in intervals)
            out["classification"] = "compatible_intervals_not_equal_LP" if compatible else "incompatible_objectives"
        elif not _positive(ta) or not _positive(tb): out["classification"] = "invalid_timing"
        else:
            out.update(classification="paired_accepted_equal_LP", ratio=ta/tb,
                ratio_lower_bound=ta/tb, ratio_upper_bound=ta/tb)
    elif ac and ba:
        budget = a.get("budget_seconds")
        if not all(_positive(v) for v in (ta, tb, budget)): out["classification"] = "invalid_timing"
        else:
            cutoff = min(ta, budget)
            out.update(classification="numerator_time_censored", ratio_lower_bound=cutoff/tb,
                       censor_cutoff_seconds=cutoff, bound_is_strict=False)
    elif aa and bc:
        budget = b.get("budget_seconds")
        if not all(_positive(v) for v in (ta, tb, budget)): out["classification"] = "invalid_timing"
        else:
            cutoff = min(tb, budget)
            out.update(classification="denominator_time_censored", ratio_lower_bound=0.0,
                ratio_upper_bound=ta/cutoff, censor_cutoff_seconds=cutoff, bound_is_strict=False)
    elif ac and bc: out["classification"] = "both_time_censored_ratio_unidentified"
    elif a["status"] == "external_timeout" or b["status"] == "external_timeout":
        out["classification"] = "external_watchdog_no_algorithm_time_bound"
    return out


def summaries(rows, pairs):
    groups = []; comparisons = []; by_draw = []
    for n in (100, 400, 1000):
        for variant in VARIANTS:
            group = [r for r in rows if r["n_tasks"] == n and r["variant"] == variant]
            primary = [r for r in group if r["primary_accepted"]]
            augmented = [r for r in group if r["primary_accepted"] or r["supplementary_accepted"]]
            item = {"n_tasks": n, "task_locations": 15, "variant": variant, "planned": 6,
                "status_counts": count_values(group, "status"), "primary_accepted": len(primary),
                "native_optimal": sum(bool(r.get("native_optimal")) for r in group) if variant == "barrier" else None,
                "native_optimal_without_primary_acceptance": (sum(bool(r.get("native_optimal")) and not r["primary_accepted"] for r in group)
                                                              if variant == "barrier" else None),
                "native_optimal_scope": "Direct LP only; null for CG variants",
                "supplementary_accepted": sum(r["supplementary_accepted"] for r in group),
                "additional_posthoc_validations": sum(r["additional_posthoc_validation"] for r in group),
                "genuine_time_limits": sum(r["genuine_optimization_time_limit"] for r in group),
                "primary_completed_stop_seconds": distribution([r.get("solve_end_to_end_seconds") for r in primary]),
                "supplementary_completed_stop_seconds": distribution([r.get("solve_end_to_end_seconds") for r in augmented]),
                "all_native_optimal_stop_seconds": distribution([r.get("solve_end_to_end_seconds") for r in group if r.get("native_optimal")]),
                "all_outcomes_retained": True}
            fields = ("rmp_model_build_seconds", "rmp_solver_runtime_seconds", "pricing_callback_seconds",
                "intermediate_replay_seconds", "process_peak_rss_at_stop_bytes",
                "process_peak_rss_after_diagnostics_bytes", "solver_peak_memory_gb",
                "columns", "rmp_call_count", "total_simplex_iterations", "maximum_rmp_variables",
                "maximum_rmp_nonzeros", "graph_arcs", "graph_nodes", "variables", "constraints",
                "nonzeros", "diagnostic_seconds", "total_including_checks_seconds")
            item["all_observed_stop_metrics"] = {k: distribution([r.get(k) for r in group]) for k in fields}
            item["primary_completed_metrics"] = {k: distribution([r.get(k) for r in primary]) for k in fields}
            item["censored_stop_metrics"] = {k: distribution([r.get(k) for r in group if r["genuine_optimization_time_limit"]]) for k in fields}
            groups.append(item)
        for numerator, denominator in COMPARISONS:
            for view in ("strict_primary", "supplementary_barrier_full_family"):
                group = [p for p in pairs if p["n_tasks"] == n and p["numerator"] == numerator
                         and p["denominator"] == denominator and p["view"] == view]
                exact = [p for p in group if p["classification"] == "paired_accepted_equal_LP"]
                comparisons.append({"n_tasks": n, "numerator": numerator, "denominator": denominator,
                    "view": view, "planned_pairs": 6, "classification_counts": count_values(group, "classification"),
                    "exact_pair_ratios_completed_only": distribution([p["ratio"] for p in exact]),
                    "denominator_faster_count": sum(p["ratio"] > 1 for p in exact),
                    "numerator_faster_count": sum(p["ratio"] < 1 for p in exact),
                    "censored_bounds": [{k: p.get(k) for k in ("case", "repeat", "classification", "ratio_lower_bound", "ratio_upper_bound")}
                                        for p in group if "censored" in p["classification"]],
                    "no_scaling_claim_from_completed_only_subset": True})
                for draw in (0, 1):
                    specific = [p for p in group if p["draw_seed"] == draw]
                    by_draw.append({"n_tasks": n, "draw_seed": draw, "numerator": numerator,
                        "denominator": denominator, "view": view, "planned_timing_repeats": 3,
                        "classification_counts": count_values(specific, "classification"),
                        "completed_pair_ratios": distribution([p["ratio"] for p in specific if p["classification"] == "paired_accepted_equal_LP"])})
    return groups, comparisons, by_draw


def describe(report):
    def fmt(d):
        return "—" if not d["count"] else f"{d['median']:.3f} [{d['minimum']:.3f}, {d['maximum']:.3f}]"
    lines = ["# CG persistent-master diagnostic", "", report["interpretation"], "",
        f"Planned outcomes:54; present:{report['present_outcomes']}; complete blocks:{report['complete_blocks']}/18.",
        f"Independent replay requested:{report['independent_verification_requested']}. Global checks:{report['global_checks_passed']}.", "",
        "Times below are median [minimum, maximum] seconds for the explicitly selected completed population. Censors remain separate and are not entered as completed times.", "",
        "| Tasks | Variant | Primary accepted /6 | Direct native optimal | Additional supplementary | Time limits | Primary completed times | Supplementary completed times |",
        "|---:|:---|---:|---:|---:|---:|:---|:---|"]
    for g in report["groups"]:
        native = "n/a" if g["native_optimal"] is None else str(g["native_optimal"])
        lines.append(f"| {g['n_tasks']} | {g['variant']} | {g['primary_accepted']}/6 | {native} | {g['additional_posthoc_validations']} | {g['genuine_time_limits']} | {fmt(g['primary_completed_stop_seconds'])} | {fmt(g['supplementary_completed_stop_seconds'])} |")
    def memory_fmt(d):
        if not d["count"]: return "—"
        return f"{d['median']/2**20:.2f} [{d['minimum']/2**20:.2f}, {d['maximum']/2**20:.2f}] ({d['count']}/6)"
    lines += ["", "Peak resident process memory, MiB, median [minimum, maximum] (observed workers /6):", "",
        "| Tasks | Variant | At algorithm stop | After worker diagnostics |",
        "|---:|:---|:---|:---|"]
    for g in report["groups"]:
        metrics = g["all_observed_stop_metrics"]
        lines.append(f"| {g['n_tasks']} | {g['variant']} | {memory_fmt(metrics['process_peak_rss_at_stop_bytes'])} | {memory_fmt(metrics['process_peak_rss_after_diagnostics_bytes'])} |")
    lines += ["", "Both memory columns are cumulative per-worker process high-water marks, not Gurobi-only allocations. The stop measurement includes construction, optimization/pricing and intermediate RMP checks, but precedes final full-family validation. The second includes the worker's later diagnostics and evidence generation; separate later replay/analysis processes are excluded. CG may materialize its full graph only for post-stop validation. A budget-exhausted worker may not produce that certificate, so its second measurement does not imply completed validation. The memory table retains all observed outcomes; certificate and censor counts above identify their status. Algorithm-stop memory and timing advantages must not be described as full validation-workflow advantages.", ""]
    if report.get("recovery_map", {}).get("used"):
        lines += ["", f"Infrastructure recovery: {report['recovery_map']['registered_recovery_blocks']} whole blocks have one registered replacement after external preemption. All original partial executions remain in execution_ledger.csv; completed original arms are not mixed with replacement arms. The54 logical outcomes are distinct from the additional execution attempts.",
                  f"Execution counts: {json.dumps(report['execution_counts'], sort_keys=True)}", ""]
    lines += ["", "Every paired ratio, censor, provenance error, phase statistic and raw stop is in the JSON/CSV outputs. A ratio above one favors its denominator. Repeated timings are not additional independent task draws. Basis reuse can alter presolve and dual/column trajectories, so this measures the complete declared implementation change.", ""]
    if report["errors"]: lines += ["## Global issues", ""]+[f"- {x}" for x in report["errors"]]+[""]
    return "\n".join(lines)


def analyze(base, output, verify=False, supplements=(), expected_cpu=EXPECTED_CPU,
            expected_gurobi=(12, 0, 3), recovery_map=None):
    started = time.perf_counter(); base = base.resolve()
    if output.exists(): raise ValueError("Fresh output directory required")
    if not base.is_dir(): raise ValueError("Input batch directory does not exist")
    plan = experiment_plan(); allowed = {(p["case_name"], p["repeat"]) for p in plan}
    recoveries, recovery_provenance = load_recovery_map(recovery_map, base)
    blocks = collections.defaultdict(list); errors = []; unexpected = []
    for path in sorted(base.rglob("manifest.json")):
        data = json.loads(path.read_text())
        if data.get("variant") != "all": continue
        key = data.get("case", {}).get("case"), data.get("repeat")
        if key not in allowed: unexpected.append(str(path)); continue
        blocks[key].append(path.parent)
    if unexpected: errors.append("Unexpected block manifests present; see unexpected_blocks")
    rows = []; proofs = []; block_checks = []; complete = 0; executions = []
    for block in plan:
        key = block["case_name"], block["repeat"]
        matches = blocks.get(key, [])
        block_errors = []
        recovery = recoveries.get(key)
        if recovery:
            known = {recovery["original"], recovery["recovery"]}
            if any(p.resolve() not in known for p in matches):
                block_errors.append("Unregistered extra attempt; no additional recovery is allowed")
            folder = recovery["recovery"] if recovery["recovery"].is_dir() else None
            selected_attempt = "recovery"
            executions += execution_ledger(block, recovery["original"], "original", False, recovery["original_preemption"])
            selected_execution_rows = execution_ledger(block, recovery["recovery"], "recovery", True, recovery["recovery_preemption"])
            executions += selected_execution_rows
            if folder and not (folder/"manifest.json").is_file(): block_errors.append("Selected recovery block manifest missing")
        else:
            folder = matches[0] if len(matches) == 1 else None
            selected_attempt = "original"
            if len(matches) > 1: block_errors.append("Duplicate block identity; no favorable selection performed")
            selected_execution_rows = execution_ledger(block, folder, "original", True)
            executions += selected_execution_rows
        current = []; current_proofs = []; manifests = []
        for variant in VARIANTS:
            row, proof, manifest = audit_variant(folder/variant if folder else None, variant, block,
                                                 verify, expected_cpu, list(expected_gurobi))
            row.update(selected_attempt=selected_attempt, selected_block_folder=str(folder) if folder else None)
            execution = next(e for e in selected_execution_rows if e["variant"] == variant)
            row["execution_state"] = execution["execution_state"]
            if not row["present"] and execution["block_scheduler_state"] == "PREEMPTED":
                row["status"] = execution["execution_state"]
                row["genuine_optimization_time_limit"] = False
            rows.append(row); proofs.append(proof); current.append(row); current_proofs.append(proof)
            if manifest: manifests.append(manifest)
        if folder and (folder/"block_summary.json").is_file():
            summary = json.loads((folder/"block_summary.json").read_text())
            if summary.get("completed") is True: complete += 1
            else: block_errors.append("Block summary does not report completion")
            if summary.get("variant_order") != block["variants"]: block_errors.append("Wrong block order")
            declared = summary.get("results", [])
            if [r.get("variant") for r in declared] != block["variants"]:
                block_errors.append("Incomplete or reordered worker sequence")
            lookup = {r["variant"]: r for r in current}
            for item in declared:
                actual = lookup.get(item.get("variant"))
                if not actual or any(item.get(a) != actual.get(b) for a, b in
                    (("status", "status"), ("objective", "objective"), ("seconds", "solve_end_to_end_seconds"))):
                    block_errors.append("Block summary and worker outcome disagree")
            if any(summary.get("instance_sha256") != m.get("instance_sha256") for m in manifests):
                block_errors.append("Block/worker input hash mismatch")
        else: block_errors.append("Missing final block summary")
        if len(manifests) == 3:
            for getter, label in ((lambda m: m["instance_sha256"], "instance"),
                (lambda m: m["environment"].get("host"), "host"),
                (lambda m: m["environment"].get("cpu_model"), "CPU model"),
                (lambda m: tuple(m["environment"].get("cpu_affinity") or []), "CPU affinity"),
                (lambda m: json.dumps(m["code_sha256"], sort_keys=True), "code manifest")):
                if len({getter(m) for m in manifests}) != 1: block_errors.append(f"Within-block {label} mismatch")
        else: block_errors.append("Not all three worker manifests are present")
        if block_errors:
            for row, proof in zip(current, current_proofs):
                row["identity_passed"] = row["primary_accepted"] = row["accepted_certificate"] = False
                proof["errors"].extend(block_errors)
        block_checks.append({"case": key[0], "repeat": key[1], "folders": list(map(str, matches)),
                             "selected_attempt": selected_attempt, "selected_folder": str(folder) if folder else None,
                             "passed": not block_errors, "errors": block_errors})
    if len(rows) != 54 or len({_key(r) for r in rows}) != 54: raise AssertionError("Lost planned outcomes")
    associated_results = {str((Path(p["folder"])/"result.json").resolve()) for p in proofs
                          if p.get("folder") and (Path(p["folder"])/"result.json").is_file()}
    associated_results.update(str((Path(e["worker_folder"])/"result.json").resolve()) for e in executions
                              if e["worker_folder"] and e["saved_result"])
    unexpected_results = sorted(str(p.resolve()) for p in base.rglob("result.json")
                                if str(p.resolve()) not in associated_results)
    if unexpected_results: errors.append("Unassociated/duplicate result files present; see unexpected_results")
    records, supplement_sources = load_supplement(supplements)
    for row, proof in zip(rows, proofs):
        if row["variant"] != "barrier": continue
        record = records.get((row["case"], row["repeat"], "barrier"))
        check = check_record(row, proof, record); proof["supplementary_check"] = check
        if record:
            # Bind all raw artifacts, not just the manifest/result pair.
            binding = record.get("evidence_binding_sha256", {})
            folder = Path(proof["folder"]) if proof.get("folder") is not None else None
            if folder is None or not folder.is_dir():
                check["errors"].append("Supplementary record has no unambiguous existing worker folder")
            else:
                for name in ("result.json", "manifest.json", "instance.json", "direct_primal.npz", "direct_dual.npz"):
                    if not (folder/name).is_file() or binding.get(name) != digest(folder/name):
                        check["errors"].append(f"Missing/mismatched supplementary raw-artifact binding: {name}")
            check["accepted"] = bool(check["accepted"] and not check["errors"])
        row["supplementary_accepted"] = bool(check["accepted"])
        row["additional_posthoc_validation"] = row["supplementary_accepted"] and not row["primary_accepted"]
        row["supplementary_lower_bound"] = check.get("supplementary_lower_bound")
        row["supplementary_interval_width"] = check.get("primal_minus_supplementary_bound")
    indexed = {_key(r): r for r in rows}; pairs = []
    for block in plan:
        for a, b in COMPARISONS:
            for posthoc in (False, True):
                pairs.append(pair(indexed[(block["case_name"], block["repeat"], a)],
                                  indexed[(block["case_name"], block["repeat"], b)], posthoc))
    assert len(pairs) == 108
    groups, comparison_groups, per_draw = summaries(rows, pairs)
    if not all(b["passed"] for b in block_checks): errors.append("One or more block identity/order/completion checks failed")
    if any(r["present"] and not r["identity_passed"] for r in rows): errors.append("One or more present worker provenance/verification checks failed")
    present = sum(r["present"] for r in rows)
    report = {"protocol": "CG_REUSE_PROTOCOL.md", "planned_blocks": 18, "planned_outcomes": 54,
        "present_outcomes": present, "complete_blocks": complete,
        "collection_complete": present == 54 and complete == 18,
        "independent_verification_requested": verify,
        "acceptance_scope": "independently_replayed" if verify else "provisional_saved_certificate_only",
        "global_checks_passed": not errors and present == 54 and complete == 18,
        "interpretation": "Fixed three-arm, matched-allocation diagnostic. Strict primary acceptance and post-hoc barrier full-family validation are separate; original native flags/times remain unchanged. Censors and failures are retained. This is a combined persistent-model/basis implementation comparison, not isolated causal attribution to model construction or warm starts.",
        "expected_environment": {"cpu_model": expected_cpu, "gurobi": list(expected_gurobi)},
        "measurement_scope": {
            "algorithm_stop": "Construction through returned optimization/pricing stop, including intermediate RMP replay; before final full-family validation",
            "process_memory": "Cumulative ru_maxrss per fresh worker, separately sampled at algorithm stop and after in-worker diagnostics; excludes later independent replay/analysis processes",
            "cg_poststop_memory": "Full graph can be materialized only for final certification; budget failures may not complete this step",
            "solver_memory": "Separate Gurobi allocation measure; not total process RSS, with per-RMP versus persistent-environment scopes retained in raw results",
            "model_size": "Fixed L15 map, T48 horizon and 0.5 SoC grid; task count changes task arcs, coverage rows and original seed variables. Large task-independent graph terms remain. Inputs at different task counts are independent rather than nested draws; no inference about arbitrary horizon/map/grid scaling."},
        "errors": errors, "unexpected_blocks": unexpected, "unexpected_results": unexpected_results,
        "block_checks": block_checks, "recovery_map": recovery_provenance,
        "execution_counts": execution_counts(executions), "execution_ledger": executions,
        "raw_worker_rows": rows, "worker_evidence": proofs, "paired_rows": pairs,
        "groups": groups, "paired_groups": comparison_groups, "per_draw_repeat_groups": per_draw,
        "supplementary_sources": supplement_sources,
        "analysis_sources": {name: digest(ROOT/name) for name in
            ("summarize_cg_reuse.py", "summarize_lp_scaling.py", "summarize_lp_supplement.py",
             "verify_lp_scaling.py", "direct_common_certificate.py", "cg_reuse_recovery.py",
             "CG_REUSE_RECOVERY_POLICY.md")},
        "analysis_seconds": time.perf_counter()-started}
    output.mkdir(parents=True)
    write_json(output/"analysis.json", report)
    write_csv(output/"worker_outcomes.csv", rows); write_csv(output/"paired_outcomes.csv", pairs)
    write_csv(output/"execution_ledger.csv", executions)
    (output/"comparison.md").write_text(describe(report))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p.add_argument("--verify", action="store_true"); p.add_argument("--supplement", type=Path, action="append", default=[])
    p.add_argument("--expected-cpu", default=EXPECTED_CPU)
    p.add_argument("--expected-gurobi", default="12.0.3")
    p.add_argument("--recovery-map", type=Path)
    a = p.parse_args()
    report = analyze(a.input, a.output, a.verify, a.supplement, a.expected_cpu,
                     tuple(map(int, a.expected_gurobi.split("."))), a.recovery_map)
    print(json.dumps({k: report[k] for k in ("present_outcomes", "complete_blocks", "global_checks_passed")}))


if __name__ == "__main__": main()
