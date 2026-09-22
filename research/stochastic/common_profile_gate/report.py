#!/usr/bin/env python3
"""Audit saved wave-17 outputs and report descriptive calendar dependence sensitivity.

The bootstrap holds each fitted truck profile fixed. Its intervals do not include
training-fit uncertainty, policy selection, forecast-model uncertainty or variation
across sites/instances. Resample full calendar positions before conditioning costs
on common feasible dates; never replace missing/failed-day costs by zero. Wilson
intervals are explicitly IID-only reference calculations, not reliability guarantees.

This standalone postprocessor does not import the solver or rerun an optimization.
Only complete, internally consistent saved cases receive numerical summaries.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import NormalDist
import sys

import numpy as np


CASES = tuple(f"policy{policy}_nb20_fit{year}" for year in (2022, 2023) for policy in (17, 14))
DATES = tuple((date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(365))
LABELS = ("old", "common", "adaptive")
CONTRASTS = (("old_minus_common", "old", "common"),
             ("common_minus_adaptive", "common", "adaptive"),
             ("old_minus_adaptive", "old", "adaptive"))
BLOCK_LENGTHS = (7, 14, 30)
REPLICATES = 1000
SEED = 20260922
SHORTAGE_TOL = 1e-6
COST_TOL = 1e-4


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def load(path):
    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(name + " must be a finite number")
    return float(value)


def relative(path, output):
    return Path(os.path.relpath(Path(path).resolve(), Path(output).resolve())).as_posix()


def local_artifact(directory, name):
    """Artifact metadata must resolve inside its declared directory."""
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError("artifact path must be relative")
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("artifact escapes its directory")
    return path


def read_journal(path):
    rows, previous = [], "0" * 64
    with Path(path).open() as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank journal line {number}")
            row = json.loads(line)
            saved = row.pop("hash")
            if (row.get("previous") != previous or row.get("sequence") != len(rows)
                    or digest(row) != saved):
                raise ValueError(f"journal hash/sequence mismatch at line {number}")
            row["hash"] = saved
            rows.append(row)
            previous = saved
    return rows, previous


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"n": 0, "mean": None, "median": None, "p05": None, "p95": None}
    if not np.isfinite(values).all():
        raise ValueError("nonfinite distribution input")
    q = np.quantile(values, [0.05, 0.5, 0.95])
    return {"n": len(values), "mean": float(values.mean()), "median": float(q[1]),
            "p05": float(q[0]), "p95": float(q[2])}


def wilson(failures, n):
    if not 0 <= failures <= n or n <= 0:
        raise ValueError("invalid failure count")
    z = NormalDist().inv_cdf(0.975)
    p, z2 = failures / n, z * z
    center = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return {"level": 0.95, "lower": max(0.0, center - half), "upper": min(1.0, center + half),
            "scope": "IID-only binomial benchmark; temporal dependence invalidates this as a calibrated confidence interval. Zero observed failures never guarantees zero future risk."}


def interval(values):
    values = np.asarray(values, dtype=float)
    valid = values[np.isfinite(values)]
    q = np.quantile(valid, [0.025, 0.975]) if len(valid) else [None, None]
    return {"lower": None if q[0] is None else float(q[0]),
            "upper": None if q[1] is None else float(q[1]),
            "valid_replicates": len(valid), "empty_support_replicates": len(values) - len(valid)}


def calendar_bootstrap(costs, shortages, joint):
    """Paired circular blocks include failed dates before cost conditioning.

    The same seed produces the same date draws for every case of the same length.
    Cases are reported separately: no independent-population interpretation follows.
    """
    n = len(joint)
    result, rng = {}, np.random.default_rng(SEED)
    for length in BLOCK_LENGTHS:
        starts = rng.integers(0, n, size=(REPLICATES, math.ceil(n / length)))
        indices = ((starts[:, :, None] + np.arange(length)) % n).reshape(REPLICATES, -1)[:, :n]
        mask = joint[indices]
        counts = mask.sum(axis=1)
        means = {}
        for label in LABELS:
            sampled = np.where(mask, costs[label][indices], 0.0)
            means[label] = np.divide(sampled.sum(axis=1), counts,
                                     out=np.full(REPLICATES, np.nan), where=counts > 0)
        result[str(length)] = {
            "block_length_days": length, "kind": "circular moving blocks; wrap from year end to year start",
            "cost_means_on_joint_support": {label: interval(means[label]) for label in LABELS},
            "paired_cost_mean_differences": {key: interval(means[left] - means[right])
                                             for key, left, right in CONTRASTS},
            "failure_probabilities": {label: interval((shortages[label][indices] > SHORTAGE_TOL).mean(axis=1))
                                      for label in LABELS},
            "minimum_joint_support_draw_count": int(counts.min()),
            "maximum_joint_support_draw_count": int(counts.max()),
        }
    return result


def summarize_rows(rows):
    shortages = {label: np.asarray([finite(row[label]["shortage"], label + " shortage") for row in rows])
                 for label in LABELS}
    costs = {label: np.asarray([np.nan if row[label]["total_cost"] is None else
                               finite(row[label]["total_cost"], label + " total cost") for row in rows])
             for label in LABELS}
    for label in LABELS:
        if np.any(shortages[label] < -SHORTAGE_TOL):
            raise ValueError(label + " has negative shortage")
        if not np.array_equal(shortages[label] <= SHORTAGE_TOL, np.isfinite(costs[label])):
            raise ValueError(label + " cost availability disagrees with shortage feasibility")
    joint = np.logical_and.reduce([np.isfinite(costs[label]) for label in LABELS])
    all_feasible = bool(joint.all())
    arms = {}
    for label in LABELS:
        count = int((shortages[label] > SHORTAGE_TOL).sum())
        arms[label] = {"failures": count, "days": len(rows), "failure_probability": count / len(rows),
                       "failure_wilson_iid_only": wilson(count, len(rows)),
                       "mean_shortage": float(shortages[label].mean()),
                       "max_shortage": float(shortages[label].max()),
                       "cost_on_shared_feasible_dates": distribution(costs[label][joint]),
                       "mean_cost_all_days": float(costs[label].mean()) if count == 0 else None}
    contrasts = {}
    for key, left, right in CONTRASTS:
        contrasts[key] = {"on_shared_feasible_dates": distribution((costs[left] - costs[right])[joint]),
                          "all_day_mean": float((costs[left] - costs[right]).mean()) if all_feasible else None}
    return {"days": len(rows), "shared_feasible_days": int(joint.sum()),
            "shared_feasible_dates": [row["date"] for row, keep in zip(rows, joint) if keep],
            "all_three_arms_feasible_every_day": all_feasible,
            "cost_support": "all 365 calendar days" if all_feasible else
                            "conditional on dates feasible for old, common AND adaptive; no all-day saving/decomposition claim",
            "arms": arms, "paired_cost_differences": contrasts,
            "bootstrap": calendar_bootstrap(costs, shortages, joint)}


def analyze_case(directory, output):
    name = directory.name
    report = {"name": name, "state": "incomplete", "missing": [], "errors": [],
              "artifacts": {}, "phases": [], "statistics": None}
    required = {"execution": directory / "execution.json", "fit": directory / "fit/result.json",
                "validation": directory / "validation.json", "status": directory / "replay2022/status.json",
                "journal": directory / "replay2022/days.jsonl", "identity": directory / "replay2022/identity.json"}
    for key, path in required.items():
        if not path.is_file():
            report["missing"].append(relative(path, output))
        else:
            report["artifacts"][key] = {"path": relative(path, output), "sha256": sha(path)}
    if report["missing"]:
        return report, None
    try:
        execution, fit, validation, status, identity = [load(required[k]) for k in
                                                       ("execution", "fit", "validation", "status", "identity")]
        report["saved_states"] = {"execution": execution.get("state"), "fit": fit.get("state"),
                                   "validation": validation.get("state"), "replay": status.get("state")}
        report["execution"] = {key: execution.get(key) for key in
                                ("state", "execution_commit", "manifest_sha256", "started_utc", "finished_utc", "elapsed_seconds")}
        report["execution"]["job_ids"] = {key: value for key, value in execution.get("scheduler", {}).items()
                                           if key in ("SLURM_JOB_ID", "SLURM_ARRAY_JOB_ID", "SLURM_ARRAY_TASK_ID")}
        report["backend"] = fit.get("backend")
        report["solver_versions"] = fit.get("versions")
        report["fit_metadata"] = {key: fit.get("metadata", {}).get(key) for key in
                                    ("source_policy", "source_seed", "fit_year", "fit_role")}
        report["saved_replay_scope"] = status.get("scope")
        report["same_fit_and_evaluation_population"] = status.get("same_fit_and_evaluation_population")
        report["saved_decomposition"] = status.get("decomposition")
        report["saved_fit_comparison"] = fit.get("comparison")
        report["saved_validation_residuals"] = {key: {field: stage.get(field) for field in
                                                      ("state", "max_residual", "phases_complete", "errors")}
                                                 for key, stage in validation.get("stages", {}).items()}
        states = report["saved_states"]
        if any(v in ("invalid", "validation_failed", "failed", "error") for v in states.values()):
            raise ValueError("a saved stage reports failure/invalidity: " + repr(states))
        if states != {"execution": "complete", "fit": "complete", "validation": "valid", "replay": "complete"}:
            report["incomplete_reason"] = "all execution, fitting, independent validation and replay stages must complete"
            return report, None
        if validation.get("errors") or status.get("errors"):
            raise ValueError("saved validation/replay contains errors")
        if fit.get("backend") != "gurobi":
            raise ValueError("registered native Gurobi fit is missing; no substitute backend accepted")
        result_hash = sha(required["fit"])
        if validation.get("result_sha256") != result_hash or identity.get("result_sha256") != result_hash:
            raise ValueError("validation or replay identity does not bind the fit result")
        if status.get("identity_sha256") != sha(required["identity"]):
            raise ValueError("replay status does not bind its identity")
        if identity.get("stage") != "common":
            raise ValueError("replay did not freeze the fitted common profile")
        if validation.get("input_sha256") != identity.get("fit_input_sha256"):
            raise ValueError("validation and replay use different fit-input hashes")
        if fit.get("source_input_sha256") != identity.get("fit_input_sha256"):
            raise ValueError("fit source input differs from replay fit input")
        same = identity.get("fit_population_fingerprint") == identity.get("evaluation_population_fingerprint")
        if not identity.get("fit_population_fingerprint") or not identity.get("evaluation_population_fingerprint"):
            raise ValueError("missing fit/evaluation population fingerprints")
        if status.get("same_fit_and_evaluation_population") is not same or same != name.endswith("fit2022"):
            raise ValueError("population scope disagrees with case name or saved status")
        rows, final = read_journal(required["journal"])
        if tuple(row.get("date") for row in rows) != DATES:
            raise ValueError("journal must match every 2022 date once in calendar order")
        if status.get("days") != len(rows) or status.get("target_days") != len(DATES) or status.get("journal_hash") != final:
            raise ValueError("replay completion count or terminal journal hash differs")
        for stage_name in ("inherited", "common"):
            stage = fit.get(stage_name, {})
            checked = validation.get("stages", {}).get(stage_name, {})
            if not stage.get("complete") or checked.get("state") != "valid" or not checked.get("phases_complete"):
                raise ValueError(stage_name + " lacks complete independent fitting validation")
            for phase in ("shortage", "cost"):
                saved = stage.get("phases", {}).get(phase, {})
                log = local_artifact(required["fit"].parent, saved.get("log"))
                if not log.is_file():
                    report["missing"].append(relative(log, output))
                    continue
                if not saved.get("log_sha256") or sha(log) != saved["log_sha256"]:
                    raise ValueError(stage_name + "/" + phase + " native log hash mismatch")
                if (saved.get("status") != "OPTIMAL" or saved.get("native_status") != 2
                        or not saved.get("optimality_certified")
                        or not saved.get("primal_residuals", {}).get("passes_report_tolerance")
                        or not saved.get("duality", {}).get("passes_report_tolerance")):
                    raise ValueError(stage_name + "/" + phase + " lacks numerical optimality/KKT acceptance")
                native = {key: saved.get(key) for key in
                          ("status", "native_status", "native_runtime_seconds", "elapsed_seconds", "objective",
                           "native_objective", "native_objective_bound", "iterations", "barrier_iterations",
                           "optimality_certified", "primal_residuals", "duality", "time_limit_seconds", "threads")}
                native.update(stage=stage_name, phase=phase, log=relative(log, output),
                              log_sha256=saved["log_sha256"], log_hash_verified=True)
                report["phases"].append(native)
        if report["missing"]:
            report["incomplete_reason"] = "native log artifacts have not all been synchronized"
            return report, None
        statistics = summarize_rows(rows)
        # Recompute the status summary and retain its mathematical eligibility flag.
        for label in LABELS:
            saved = status.get("statistics", {}).get(label, {})
            actual = statistics["arms"][label]
            if saved.get("failures") != actual["failures"]:
                raise ValueError(label + " failure count disagrees with saved summary")
            if abs(finite(saved.get("mean_shortage"), "saved shortage") - actual["mean_shortage"]) > SHORTAGE_TOL:
                raise ValueError(label + " mean shortage disagrees with saved summary")
            a, b = saved.get("mean_cost_all"), actual["mean_cost_all_days"]
            if (a is None) != (b is None) or (a is not None and abs(finite(a, "saved mean") - b) > COST_TOL):
                raise ValueError(label + " all-day cost disagrees with saved summary")
        for row in rows:
            for label in ("old", "common"):
                if finite(row[label].get("max_residual"), "daily physical residual") > SHORTAGE_TOL:
                    raise ValueError(label + " daily replay residual exceeds tolerance")
                if row[label].get("phase_statuses") != {"shortage": 0, "cost": 0}:
                    raise ValueError(label + " daily independent LP phases were not optimal")
        if status.get("jointly_feasible_days") != statistics["shared_feasible_days"]:
            raise ValueError("shared feasible support count disagrees with saved summary")
        decomposition = status.get("decomposition")
        if statistics["all_three_arms_feasible_every_day"]:
            if not isinstance(decomposition, dict) or decomposition.get("nesting_asserted") is not same:
                raise ValueError("missing or incorrect saved decomposition/nesting scope")
            for key, _, _ in CONTRASTS:
                value = statistics["paired_cost_differences"][key]["all_day_mean"]
                if abs(finite(decomposition.get(key), "saved contrast") - value) > COST_TOL:
                    raise ValueError("saved decomposition disagrees with daywise " + key)
                if same and key != "old_minus_adaptive" and value < -COST_TOL:
                    raise ValueError("same-population nesting violated")
        elif decomposition is not None:
            raise ValueError("monetary decomposition recorded despite failed days")
        report.update(state="validated_complete", statistics=statistics,
                      integrity={"journal_records": len(rows), "journal_hash": final,
                                 "journal_chain_verified": True, "native_logs_verified": len(report["phases"]),
                                 "result_validation_identity_bindings_verified": True,
                                 "trace_scope": "Daily trace arrays are not re-solved or replayed by this report; saved independent validation and daily residuals are retained."})
        report["replay_max_residuals"] = {label: max(finite(row[label].get("max_residual"), "replay residual") for row in rows)
                                           for label in ("old", "common")}
        return report, rows
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        report.update(state="invalid", statistics=None)
        report["errors"].append(str(exc))
        return report, None


def analyze(runs, output):
    reports, records = {}, {}
    for name in CASES:
        reports[name], records[name] = analyze_case(runs / name, output)
    cross_checks = []
    for policy in (17, 14):
        a, b = (f"policy{policy}_nb20_fit{year}" for year in (2022, 2023))
        if records[a] is None or records[b] is None:
            cross_checks.append({"policy": policy, "state": "not_checked", "reason": "one or both cases unavailable"})
            continue
        errors = []
        for left, right in zip(records[a], records[b]):
            for label in ("old", "adaptive"):
                for field, tol in (("shortage", SHORTAGE_TOL), ("total_cost", COST_TOL)):
                    x, y = left[label][field], right[label][field]
                    if (x is None) != (y is None) or (x is not None and abs(x - y) > tol):
                        errors.append(f"{left['date']} {label} {field}")
        cross_checks.append({"policy": policy, "state": "verified" if not errors else "invalid",
                             "checks": "Matched calendar dates and unchanged old/adaptive references across fitting years", "errors": errors})
        if errors:
            for name in (a, b):
                reports[name].update(state="invalid", statistics=None)
                reports[name]["errors"].append("old/adaptive references changed across fit years")
    states = [r["state"] for r in reports.values()]
    state = "invalid" if "invalid" in states else ("validated_complete" if all(s == "validated_complete" for s in states) else "incomplete")
    return {"state": state, "report_script_sha256": sha(__file__), "cases": reports,
            "cross_fit_reference_checks": cross_checks,
            "method": {"replicates": REPLICATES, "seed": SEED, "block_lengths_days": list(BLOCK_LENGTHS),
                       "bootstrap_interval": "2.5/97.5 percentile endpoints; descriptive dependence sensitivity",
                       "bootstrap_excludes": "training-fit uncertainty, policy selection, weather/site/model uncertainty",
                       "calendar": "all 365 positions resampled before conditioning on old/common/adaptive shared feasibility",
                       "weights": "equal calendar-day weights; registered full-year population",
                       "failure_threshold_energy_units": SHORTAGE_TOL,
                       "wilson": "95% IID-only binomial benchmark; not calibrated for dependent days; zero observed never guarantees zero future failure probability",
                       "scope": "2022 development weather, fixed assets/skeletons, perfect-information BESS/generator recourse; no causal-controller or fresh-test claim"}}


def fmt(value, digits=4):
    return "n/a" if value is None else f"{value:,.{digits}f}"


def sci(value):
    return "n/a" if value is None else f"{value:.3e}"


def markdown(report):
    lines = ["# Common-profile gate: saved-output report", "", f"Status: **{report['state']}**."]
    focal = report["cases"].get("policy17_nb20_fit2022", {})
    stats = focal.get("statistics")
    if (focal.get("state") == "validated_complete" and stats
            and stats["all_three_arms_feasible_every_day"]
            and (focal.get("saved_decomposition") or {}).get("nesting_asserted")):
        gaps = stats["paired_cost_differences"]
        old_gap = gaps["old_minus_adaptive"]["all_day_mean"]
        retuning = gaps["old_minus_common"]["all_day_mean"]
        remaining = gaps["common_minus_adaptive"]["all_day_mean"]
        if old_gap > COST_TOL:
            lines.extend(["", f"For source policy 17 (seed 47), fitting one common truck profile on 2022 removes **{100 * retuning / old_gap:.2f}%** of the inherited {fmt(old_gap)}-per-day oracle gap. Static retuning saves {fmt(retuning)} per day; the remaining common-profile-to-adaptive gap is **{fmt(remaining)} per day**.", "",
                          "This result is conditional on the retained assets, reconstructed skeletons and 2022 development population, with full-day BESS/generator foresight. It does not measure attainable causal savings. The 2023-fit rows below are separate frozen-profile evaluations; same-population nesting is not asserted for them."])
    lines.extend(["", "| Source policy / fit year | Old cost/day | Common cost/day | Adaptive oracle/day | Common − oracle/day | Failed days: old / common / oracle |",
                  "|---|---:|---:|---:|---:|---|"])
    for name, case in report["cases"].items():
        stat = case.get("statistics")
        if case["state"] != "validated_complete" or not stat:
            lines.append(f"| {name} | — | — | — | — | {case['state']} |")
            continue
        meta = case["fit_metadata"]
        source = f"{meta['source_policy']} (seed {meta['source_seed']}) / {meta['fit_year']}"
        all_ok = stat["all_three_arms_feasible_every_day"]
        costs = [stat["arms"][label]["mean_cost_all_days"] if all_ok else None for label in LABELS]
        gap = stat["paired_cost_differences"]["common_minus_adaptive"]["all_day_mean"]
        fails = " / ".join(str(stat["arms"][label]["failures"]) for label in LABELS)
        lines.append("| " + source + " | " + " | ".join(fmt(x) for x in costs + [gap]) + f" | {fails} (365 days) |")
    lines.extend(["", "Overview costs and remaining gaps require every day to be feasible for all three arms; otherwise they are withheld. All costs include the same fixed assets.", "",
             "A separate [cost-component audit](https://github.com/ndandnd/evspv2g_dp/blob/codex/stochastic-adaptation-gates/research/stochastic/common_profile_gate/report/COST_COMPONENTS.md) of these archived runs finds equal common/oracle fuel costs day by day; their small remaining gap is the model's throughput penalty. Reproduce that accounting with cost_components.py.", "",
             "Bootstrap intervals are descriptive dependence sensitivity with fixed fitted profiles. They do not include training-fit uncertainty or policy-selection uncertainty. The 7/14/30-day circular block lengths use 1,000 replicates and seed 20260922; year-end wrapping is an approximation, not a seasonal or independent-weather model.", "",
             "All cases replay 2022 development weather. Fits on 2022 are retrospective same-population mechanism tests; 2023 fits are frozen-profile cross-year comparisons, without a nesting guarantee or chronological deployment claim. BESS/generator recourse has full-day foresight; this is not a causal controller comparison.", "",
             "Failed days remain in failure statistics. Every cost table uses dates jointly feasible for old, common and adaptive. When any day fails, those costs are conditional and do not establish all-day savings or a monetary nesting decomposition. Zero observed failures never guarantees zero future risk. Wilson intervals below are IID-only binomial benchmarks and are not calibrated for temporal dependence.", "",
             "Full statistics, support dates, hashes and diagnostic fields are in [stats.json](stats.json). Input cases remain separate; seeds/source plans share weather and are not independent populations."])
    for name, case in report["cases"].items():
        lines.extend(["", "## " + name, "", "Status: **" + case["state"] + "**."])
        if case["artifacts"]:
            lines.extend(["", "Evidence: " + "; ".join(f"[{key}]({value['path']})" for key, value in case["artifacts"].items()) + "."])
        if case["state"] != "validated_complete":
            messages = case["errors"] + ([case["incomplete_reason"]] if case.get("incomplete_reason") else [])
            lines.extend(["", "No numerical result claimed. " + ("; ".join(messages) or "Required saved outputs are missing.")])
            if case["missing"]:
                lines.extend(["", "Missing: " + ", ".join("`" + p + "`" for p in case["missing"]) + "."])
            continue
        stat = case["statistics"]
        lines.extend(["", case["saved_replay_scope"] + ". Cost support: " + stat["cost_support"] + ".",
                      "", "| Arm | Failures / days | Failure probability | Wilson 95% IID-only benchmark | Mean shortage |",
                      "|---|---:|---:|---|---:|"])
        for label, arm in stat["arms"].items():
            w = arm["failure_wilson_iid_only"]
            lines.append(f"| {label} | {arm['failures']} / {arm['days']} | {arm['failure_probability']:.3%} | [{w['lower']:.3%}, {w['upper']:.3%}] | {fmt(arm['mean_shortage'], 8)} |")
        lines.extend(["", f"Costs on the same {stat['shared_feasible_days']} jointly feasible dates (fixed asset cost included):", "",
                      "| Arm | Mean | Median | 5th percentile | 95th percentile |", "|---|---:|---:|---:|---:|"])
        for label, arm in stat["arms"].items():
            d = arm["cost_on_shared_feasible_dates"]
            lines.append("| " + label + " | " + " | ".join(fmt(d[k]) for k in ("mean", "median", "p05", "p95")) + " |")
        lines.extend(["", "| Signed paired cost difference | Mean | Median | 5th percentile | 95th percentile |",
                      "|---|---:|---:|---:|---:|"])
        for key, _, _ in CONTRASTS:
            d = stat["paired_cost_differences"][key]["on_shared_feasible_dates"]
            lines.append("| " + key.replace("_", " ") + " | " + " | ".join(fmt(d[k]) for k in ("mean", "median", "p05", "p95")) + " |")
        dec = case["saved_decomposition"]
        lines.extend(["", ("Saved nesting asserted: **" + str(dec["nesting_asserted"]).lower() + "**. " + dec["interpretation"] + ".") if dec else
                      "No monetary decomposition: the full shared zero-shortage condition is not satisfied.", "",
                      "Descriptive paired-mean interval sensitivity (full calendar sampled before cost conditioning):", "",
                      "| Circular block length | Old − common | Common − adaptive | Old − adaptive |",
                      "|---:|---|---|---|"])
        for length, block in stat["bootstrap"].items():
            entries = []
            for key, _, _ in CONTRASTS:
                x = block["paired_cost_mean_differences"][key]
                entries.append(f"[{fmt(x['lower'])}, {fmt(x['upper'])}] ({x['valid_replicates']}/1000)")
            lines.append("| " + length + " days | " + " | ".join(entries) + " |")
        lines.extend(["", "Failure-probability block intervals and arm cost-mean intervals are retained in stats.json. Parenthesized counts above are bootstrap replicates with nonempty shared cost support.", "",
                      "Native Gurobi fitting phases (floating-point optimality/KKT diagnostics, not exact rational or full-route integer certificates). Residuals use scientific notation. n/a means unavailable; native objective/bound values remain visible even when a reconstructed dual bound is undefined:", "",
                      "| Stage / phase | Native status | Runtime s | Native objective / bound | Max primal residual | KKT stationarity / complementarity / sign | Primal − dual | Log |",
                      "|---|---|---:|---:|---:|---|---:|---|"])
        for p in case["phases"]:
            kkt = p.get("duality") or {}
            components = " / ".join(sci(kkt.get(k)) for k in ("stationarity_inf", "complementarity_inf", "dual_sign_violation"))
            lines.append(f"| {p['stage']} / {p['phase']} | {p['status']} ({p['native_status']}) | {fmt(p['native_runtime_seconds'], 3)} | {fmt(p['native_objective'], 8)} / {fmt(p['native_objective_bound'], 8)} | {sci(p['primal_residuals'].get('maximum_violation'))} | {components} | {sci(kkt.get('primal_minus_dual'))} | [verified log]({p['log']}) |")
        ex = case["execution"]
        lines.extend(["", f"All {len(case['phases'])} native phase-log hashes and the {stat['days']}-day journal chain verified. Independent replay maximum residuals: old {sci(case['replay_max_residuals']['old'])}, common {sci(case['replay_max_residuals']['common'])}. Execution elapsed: {fmt(ex.get('elapsed_seconds'), 3)} s. Execution commit: `{ex.get('execution_commit')}`."])
    lines.extend(["", "## Report integrity and scope", "",
                  "The report checks completion, result/validation/replay identity bindings, every daily journal link, every native phase-log hash, saved summary recomputation and unchanged old/adaptive references across fitting years. The independent fit validation is retained; this postprocessor does not reconstruct model matrices or rerun trace physics. Missing artifacts remain incomplete, and inconsistent artifacts are invalid.", "",
                  "A same-population decomposition is an in-sample mechanism result. Cross-year differences are signed descriptive comparisons; neither cost ordering nor uncertainty calibration carries over automatically. Results do not establish optimal asset investment, original-route recovery, causal savings or population reliability.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True, help="attempt directory containing the four case directories")
    parser.add_argument("--output-dir", type=Path, required=True, help="separate directory for RESULTS.md and stats.json")
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = analyze(args.runs, args.output_dir)
    for name, content in (("stats.json", json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"),
                          ("RESULTS.md", markdown(report))):
        target = args.output_dir / name
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(content)
        temporary.replace(target)
    print(json.dumps({"state": report["state"], "complete_cases": sum(c["state"] == "validated_complete" for c in report["cases"].values()),
                      "expected_cases": len(CASES), "output_dir": str(args.output_dir)}))
    return 0 if report["state"] == "validated_complete" else 2 if report["state"] == "invalid" else 1


if __name__ == "__main__":
    sys.exit(main())
