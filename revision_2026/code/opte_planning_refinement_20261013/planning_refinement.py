"""One additive cold 300-second MIP for each of 187 prior planning time limits.

No SSH or scheduler action. Frozen baseline files remain unchanged. --launch
runs one worker in a fresh process with a 420-second process-group watchdog.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import planning_population as baseline

BUDGET = 300.0
WATCHDOG = 420.0
EXPECTED_HOST = "cdses-compute-01"
EXPECTED_CPU = "AMD EPYC 9654 96-Core Processor"
SCHEDULING_AMENDMENT = "2026-10-13-mixed-node-queue-only"
MIGRATED_INDICES = frozenset(range(2, 187))
INPUTS = ROOT / "planning_refinement_inputs.json"
DEPENDENCIES = baseline.DEPENDENCIES + (
    "planning_refinement.py", "planning_refinement_inputs.json",
    "PLANNING_REFINEMENT_PROTOCOL.md")
THREAD_KEYS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
               "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")


def entries():
    data = json.loads(INPUTS.read_text())
    if len(data["selected"]) != 187:
        raise ValueError("Expected all 187 prior time-limit configurations")
    if baseline.sha(baseline.INPUTS) != data["population_inputs_sha256"]:
        raise ValueError("Original population input manifest changed")
    if any(e["prior_status"] != "time_limit" for e in data["selected"]):
        raise ValueError("Refinement contains a non-time-limit configuration")
    return data, data["selected"]


def protocol():
    return {"budget_seconds": BUDGET, "watchdog_seconds": WATCHDOG,
        "threads": 1, "seed": 0, "solver_method": -1, "crossover": -1,
        "mip_gap_tolerance": 1e-6, "mip_gap_absolute_tolerance": 1e-10,
        "native_tolerances": 1e-8, "standalone_lp": False,
        "external_warm_starts": False, "baseline_budget_override_only": True,
        "required_host": EXPECTED_HOST, "required_cpu_model": EXPECTED_CPU,
        "scheduling_amendment": SCHEDULING_AMENDMENT,
        "migrated_index_range_inclusive": [2, 186],
        "timing": "Input reconstruction excluded; graph/seed/matrices/environment/model/solve included; final diagnostics excluded"}


def launch(entry, output):
    env = os.environ.copy()
    for name in THREAD_KEYS:
        env[name] = "1"
    command = [sys.executable, str(Path(__file__).resolve()), "--index",
               str(entry["refinement_index"]), "--output", str(output / "worker")]
    baseline.write_json(output / "launch_manifest.json", {
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "selection": entry, "inputs_sha256": baseline.sha(INPUTS),
        "budget_seconds": BUDGET, "watchdog_seconds": WATCHDOG,
        "command": command})
    execution = baseline.run_child_bounded(command, env, WATCHDOG)
    baseline.write_json(output / "execution.json", {"command": command,
        "watchdog_seconds": WATCHDOG, "execution": execution})
    if execution["external_timeout"]:
        baseline.write_json(output / "external_timeout.json", {
            "status": "external_timeout", "optimization_completion_unknown": True,
            "native_bound_from_interrupted_output_usable": False})
    return 0 if execution["returncode"] == 0 else 1


def run(entry, output, preflight=False):
    spec = entry["spec"]
    inst, record = baseline.build_case(spec)
    if record != entry["instance_record"]:
        raise ValueError("Regenerated input differs from the exact original serialized instance")
    environment = baseline.environment_record()
    baseline.write_json(output / "instance.json", record)
    baseline.write_json(output / "manifest.json", {
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "case": spec, "scenario": entry["scenario"], "selection": entry,
        "refinement_inputs_sha256": baseline.sha(INPUTS),
        "physical_sha256": spec["physical_sha256"], "instance_sha256": record["sha256"],
        "environment": environment, "vendor_manifest": baseline.verify_vendor(),
        "code_sha256": {n: baseline.sha(ROOT / n) for n in DEPENDENCIES},
        "protocol": protocol()})
    try:
        if preflight:
            graph, seeds, _, audit = baseline.pd.prepare_planning(inst, entry["scenario"])
            matrices = baseline._hybrid_matrices(inst, graph, seeds)
            result = {"status": "preflight_only", "optimization_performed": False,
                "audit": audit, "variables": len(matrices[0]), "graph_nodes": graph.n_nodes,
                "graph_arcs": graph.n_arcs}
        else:
            if environment["gurobi"] != [12, 0, 3]:
                raise ValueError("Protocol requires Gurobi 12.0.3")
            if (environment["allocated_cpus"] != "1" or len(environment["cpu_affinity"]) != 1
                or set(environment["thread_environment"]) != set(THREAD_KEYS)
                or any(v != "1" for v in environment["thread_environment"].values())
                or environment["cpu_model"] != EXPECTED_CPU
                or environment["host"].split(".")[0] != EXPECTED_HOST):
                raise ValueError("Mixed-node v2 requires cdses-compute-01, AMD EPYC 9654 and one bound CPU")
            # This changes only the constant read by the imported function; it
            # does not edit the frozen file or alter any algorithm/control.
            if baseline.BUDGET != 60.0:
                raise ValueError("Unexpected original baseline budget")
            baseline.BUDGET = BUDGET
            try:
                result = baseline.solve(inst, entry["scenario"], output)
            finally:
                baseline.BUDGET = 60.0
            result["method"] = "planning_refinement_mip"
        code = 0
    except Exception as exc:
        result = {"status": "error", "error": repr(exc), "traceback": traceback.format_exc()}
        code = 1
    result.update(case=spec["case"], scenario=entry["scenario"],
        refinement_index=entry["refinement_index"],
        prior_result_sha256=entry["prior_result_sha256"],
        physical_sha256=spec["physical_sha256"], instance_sha256=record["sha256"])
    result["evidence_sha256"] = {str(f.relative_to(output)): baseline.sha(f)
        for f in output.rglob("*") if f.is_file() and f.name != "result.json"
        and not f.name.endswith(".tmp")}
    result["process_peak_rss_after_diagnostics_bytes"] = baseline.peak_rss_bytes()
    baseline.write_json(output / "result.json", result)
    print(json.dumps({k: result.get(k) for k in ("case", "scenario", "status", "objective",
        "bound", "gap", "incumbent_validated", "solve_end_to_end_seconds")}), flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args()
    data, selected = entries()
    if args.describe:
        print(json.dumps({"count": len(selected), "protocol": protocol(),
            "dependency_sha256": {n: baseline.sha(ROOT/n) for n in DEPENDENCIES},
            "vendor_directory": str(ROOT / "vendor"),
            "prior_primary_sha256": data["prior_primary_sha256"],
            "prior_repair_sha256": data["prior_repair_sha256"]}, indent=2))
        return 0
    if args.index is None or not 0 <= args.index < len(selected) or args.output is None:
        parser.error("Provide --index 0..186 and a fresh --output directory")
    if not args.preflight and args.index not in MIGRATED_INDICES:
        parser.error("V2 can run only confirmed migrated indices 2..186; indices 0 and 1 retain v1")
    if args.launch and args.preflight:
        parser.error("--launch and --preflight are mutually exclusive")
    if args.output.exists():
        raise ValueError("Fresh output directory required")
    output = args.output.resolve()
    output.mkdir(parents=True)
    entry = selected[args.index]
    if entry["refinement_index"] != args.index:
        raise ValueError("Selection index mismatch")
    return launch(entry, output) if args.launch else run(entry, output, args.preflight)


if __name__ == "__main__":
    raise SystemExit(main())
