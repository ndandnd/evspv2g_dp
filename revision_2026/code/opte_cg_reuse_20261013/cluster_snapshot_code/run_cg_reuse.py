"""Fresh-process cold-CG / persistent-CG / direct-barrier diagnostic blocks.

CLI: --case-name diag2_L15_n100_s0 --repeat 0 --output FRESH_DIRECTORY
     [--budget 1800] [--variant all|cold|reuse|barrier] [--watchdog-grace 600].
--plan prints the 18 frozen block definitions without any optimization.
This module never submits jobs. All previous sources/results remain unchanged.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"vendor"))
import numpy as np

import lp_scaling_models as models
from lp_scaling_instances import build_case, case_specs, instance_record, source_manifest
from persistent_rmp import PersistentRMP
from run_lp_scaling import (DEPENDENCIES as BASE_DEPENDENCIES, environment_record,
                            run_child_bounded, sha)
from run_pilot import write_json, verify_vendor

VARIANTS = ("cold", "reuse", "barrier")
DEPENDENCIES = tuple(dict.fromkeys(BASE_DEPENDENCIES+(
    "persistent_rmp.py", "run_cg_reuse.py", "CG_REUSE_PROTOCOL.md")))


def selected_cases():
    return [s for s in case_specs() if s["points"] == 15]


def variant_order(case_index, repeat):
    shift = (case_index+repeat) % len(VARIANTS)
    return list(VARIANTS[shift:]+VARIANTS[:shift])


def experiment_plan():
    return [{"block_index": 3*i+r, "case_name": s["case"], "repeat": r,
             "variants": variant_order(i, r)}
            for i, s in enumerate(selected_cases()) for r in range(3)]


def solve_reuse_cg(inst, budget, output_dir, max_iter=20000):
    """Use the exact frozen CG driver, replacing only its RMP callback."""
    adapter = PersistentRMP(); original = models.solve_rmp
    try:
        models.solve_rmp = adapter.solve
        result = models.solve_cg_lp(inst, budget, output_dir, max_iter=max_iter)
        result.update(cg_variant="reuse", rmp_implementation=
            "Persistent original master; appended route columns; explicitly restored simplex basis; Method=-1, LPWarmStart=1",
            basis_restorations=adapter.basis_restorations,
            persistent_model_initializations=int(adapter.instance is not None),
            memory_scope="Maximum allocation in the one persistent Gurobi environment; process RSS is separately reported")
        return result
    finally:
        models.solve_rmp = original
        adapter.close()


def manifest(spec, args, raw):
    return {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "case": spec, "repeat": args.repeat, "variant": args.variant,
        "method": "barrier" if args.variant == "barrier" else "cg",
        "budget_seconds": args.budget, "max_cg_iterations": args.max_cg_iterations,
        "instance_sha256": raw["sha256"], "environment": environment_record(),
        "vendor_manifest": verify_vendor(), "source_manifest": source_manifest(),
        "code_sha256": {p: sha(ROOT/p) for p in DEPENDENCIES},
        "worker_watchdog_grace_seconds": args.watchdog_grace,
        "protocol": {"name": "CG persistent RMP diagnostic, fixed three-arm design",
            "threads": 1, "seed": 0, "feasibility_tolerance": 1e-8,
            "optimality_tolerance": 1e-8, "barrier_convergence_tolerance": 1e-8,
            "pricing_tolerance": 1e-6, "stabilization_beta": 0.5,
            "enrichment": 0, "final_mip": False,
            "cg_gurobi_method": -1, "reuse_lp_warm_start": 1,
            "direct_gurobi_method": 2, "direct_crossover": -1,
            "timing_scope": "Imports/input generation/initial serialization excluded; initial columns/graph, master construction or updates, optimization, intermediate CG replay/logging included; final certification and serialization excluded and separately reported.",
            "same_allocation_within_block": True,
            "order": "Three Latin rotations for each case; every variant occupies every position once",
            "reuse_scope": "Combined persistent-model/basis-reuse implementation effect, including potential changes in presolve, dual trajectory and generated columns; not pure model-building or simplex-iteration savings",
            "watchdog": "Whole child process group killed after arm budget plus diagnostics grace. External timeouts do not supply valid algorithm-time lower bounds.",
            "previous_studies": "Preserved; no cross-study timing pooling"}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case-name"); p.add_argument("--repeat", type=int, choices=range(3), default=0)
    p.add_argument("--output", type=Path); p.add_argument("--budget", type=float, default=1800)
    p.add_argument("--variant", choices=("all",)+VARIANTS, default="all")
    p.add_argument("--max-cg-iterations", type=int, default=20000)
    p.add_argument("--watchdog-grace", type=float, default=600)
    p.add_argument("--expected-instance-sha256"); p.add_argument("--plan", action="store_true")
    a = p.parse_args()
    if a.plan: print(json.dumps(experiment_plan(), indent=2)); return 0
    if not a.case_name or a.output is None: p.error("--case-name and --output required")
    if not np.isfinite(a.budget) or a.budget <= 0 or not np.isfinite(a.watchdog_grace) or a.watchdog_grace < 0:
        p.error("Positive finite budget and nonnegative finite watchdog grace required")
    if a.max_cg_iterations < 1: p.error("Positive maximum iteration count required")
    specs = selected_cases(); spec = next((s for s in specs if s["case"] == a.case_name), None)
    if spec is None: p.error("Use one of the six prespecified L15 inputs")
    if a.output.exists(): raise ValueError("Fresh output directory required; prior evidence is immutable")
    inst = build_case(spec); raw = instance_record(inst)
    if a.expected_instance_sha256 and raw["sha256"] != a.expected_instance_sha256:
        raise ValueError("Worker input does not match its block")
    a.output.mkdir(parents=True)
    write_json(a.output/"instance.json", raw); write_json(a.output/"manifest.json", manifest(spec, a, raw))
    if a.variant == "all":
        order = variant_order(specs.index(spec), a.repeat); results = []
        environment = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            environment[name] = "1"
        for position, variant in enumerate(order):
            command = [sys.executable, str(Path(__file__).resolve()), "--case-name", a.case_name,
                "--repeat", str(a.repeat), "--output", str(a.output/variant), "--budget", str(a.budget),
                "--variant", variant, "--max-cg-iterations", str(a.max_cg_iterations),
                "--watchdog-grace", str(a.watchdog_grace), "--expected-instance-sha256", raw["sha256"]]
            write_json(a.output/"progress.json", {"variant_order": order, "active_variant": variant, "completed": results})
            print(f"START {a.case_name} repeat={a.repeat} variant={variant}", flush=True)
            execution = run_child_bounded(command, environment, a.budget+a.watchdog_grace)
            folder = a.output/variant; result_path = folder/"result.json"
            if execution["external_timeout"]:
                folder.mkdir(parents=True, exist_ok=True)
                partial = {str(f.relative_to(folder)): sha(f) for f in folder.rglob("*")
                           if f.is_file() and f.name != "result.json" and not f.name.endswith(".tmp")}
                write_json(result_path, {"status": "external_timeout", "certified": False,
                    "objective": None, "solve_end_to_end_seconds": None,
                    "method": "barrier" if variant == "barrier" else "cg", "variant": variant,
                    "instance_sha256": raw["sha256"], "external_watchdog": execution,
                    "budget_seconds": a.budget, "algorithm_time_censor_bound_valid": False,
                    "partial_evidence_sha256": partial})
            child = json.loads(result_path.read_text()) if result_path.exists() else {}
            results.append({"variant": variant, "position": position, "returncode": execution["returncode"],
                "status": child.get("status"), "certified": child.get("certified", False),
                "objective": child.get("objective"), "seconds": child.get("solve_end_to_end_seconds"),
                "external_execution": execution})
            if (folder/"manifest.json").exists():
                child_manifest = json.loads((folder/"manifest.json").read_text())
                if child_manifest["environment"]["host"] != platform.node():
                    raise ValueError("Cross-host block")
        write_json(a.output/"block_summary.json", {"variant_order": order, "results": results,
                   "instance_sha256": raw["sha256"], "completed": True})
        return int(any(r["returncode"] != 0 for r in results))
    try:
        if a.variant == "reuse":
            result = solve_reuse_cg(inst, a.budget, a.output, a.max_cg_iterations)
        elif a.variant == "cold":
            result = models.solve_cg_lp(inst, a.budget, a.output, max_iter=a.max_cg_iterations)
            result["cg_variant"] = "cold"
        else:
            result = models.solve_direct_lp(inst, "barrier", a.budget,
                a.output/"logs"/"direct.log", crossover=-1, evidence_dir=a.output)
        exit_code = 0
    except Exception as exc:
        result = {"status": "error", "certified": False, "error": repr(exc),
                  "traceback": traceback.format_exc()}; exit_code = 1
    result.update(variant=a.variant, instance_sha256=raw["sha256"],
        process_peak_rss_after_diagnostics_bytes=models.peak_rss_bytes())
    result["evidence_sha256"] = {str(f.relative_to(a.output)): sha(f) for f in a.output.rglob("*")
                               if f.is_file() and f.name != "progress.json"}
    write_json(a.output/"result.json", result)
    print(json.dumps({"case": a.case_name, "repeat": a.repeat, "variant": a.variant,
        **{k: result.get(k) for k in ("status", "certified", "objective", "solve_end_to_end_seconds")}}), flush=True)
    return exit_code


if __name__ == "__main__": raise SystemExit(main())
