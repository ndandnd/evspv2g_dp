"""Matched, local eight-case pilot; immutable historical inputs, new Gurobi adapters.

Run from any working directory. No network, cluster submission or manuscript edits.
The shared instance is built before either timer. Timed arms include construction
and optimization. CG intermediate LP replay/progress logging consume its budget;
final solution replay and independent certification are reported separately.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback

import numpy as np
import scipy

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
import colgen
import recreate_arxiv as historical
from arc_flow import build_graph, shortest_path_reduced_cost, solve_arc_flow


def safe(value):
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return safe(value.tolist())
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(safe(value), indent=2) + "\n")
    tmp.replace(path)


def verify_vendor():
    manifest = json.loads((ROOT / "source_manifest.json").read_text())
    for name, record in manifest["files"].items():
        observed = hashlib.sha256((ROOT / "vendor" / name).read_bytes()).hexdigest()
        if observed != record["sha256"]:
            raise ValueError(f"Historical source changed: {name}")
    return manifest


def instance_record(inst, points, energy):
    return safe({"points_excluding_depot": points, "task_energy_kwh": energy,
                 "windows_hours": historical.SCAL, "T": inst.T,
                 "n_tasks": inst.n_trips, "model_energy_unit_kwh": 100,
                 "G": inst.G, "rho": inst.rho, "soc_step": inst.soc_step,
                 "eta": inst.eta, "energy_per_dist": inst.energy_per_dist,
                 "c_g": inst.c_g, "c_v": inst.c_v, "c_b": inst.c_b,
                 "eps_pen": inst.eps_pen, "deg_cost": getattr(inst, "deg_cost", 0),
                 "charge_locations": list(inst.charge_locs), "depot": inst.depot,
                 "generation_cap": "unbounded", "charging_cap": "unbounded",
                 "truck_boundary": "full/full", "stationary_boundary": "periodic",
                 "dist": inst.dist, "Delta": inst.Delta,
                 "trips": [vars(tr) for tr in inst.trips]})


class BudgetExpired(RuntimeError):
    pass


def solve_cg(inst, budget, case_dir):
    from rmp_solver import solve_rmp
    from column_witness import validate_selected_columns

    started = time.perf_counter()
    deadline = started + budget
    calls = []
    original_lp, original_price = colgen.solve_lp, colgen.price_truck_dp

    def remaining():
        available = deadline - time.perf_counter()
        if available <= 0:
            raise BudgetExpired("Common end-to-end budget exhausted")
        return available

    def lp_callback(instance, cols, battery_allowed=True, solver=None, soc_mode="cyclic"):
        if not battery_allowed or soc_mode != "cyclic":
            raise ValueError("Pilot callback only supports V2G with cyclic stationary storage")
        sol, diag = solve_rmp(instance, cols, False, remaining(),
                             case_dir / "logs" / f"cg_lp_{len(calls):04d}.log")
        calls.append(diag)
        write_json(case_dir / "cg_progress.json", {"lp_calls": len(calls),
                   "elapsed_seconds": time.perf_counter()-started, "last_call": diag})
        if sol.status != "optimal":
            raise BudgetExpired(f"RMP LP is not optimal: {diag['status']}")
        return sol

    def priced(*args, **kwargs):
        remaining()
        result = original_price(*args, **kwargs)
        remaining()
        return result

    out = {"method": "cg_then_restricted_mip", "budget_seconds": budget,
           "threads": 1, "seed": 0, "enrichment_rounds": 25,
           "max_cg_iterations": 1000, "pricing_tolerance": 1e-6,
           "stabilization_beta": 0.5}
    try:
        colgen.solve_lp, colgen.price_truck_dp = lp_callback, priced
        res = colgen.column_generation(inst, scenario="v2g", start="warm", tol=1e-6,
                rc_stop=0, beta=0.5, max_iter=1000, do_milp=False, verbose=False,
                enrich=25, lp_solver="gurobi", soc_mode="cyclic")
        cg_done = time.perf_counter()
        out.update(cg_seconds=cg_done-started, cg_iterations=res["iters"],
                   pricing_seconds=res["pricing_time"], cg_claimed_converged=res["converged"],
                   cg_termination_reason=res["term_reason"], columns=len(res["cols"]),
                   cg_lp_objective=res["lp_obj"])
        mip, mip_diag = solve_rmp(inst, res["cols"], True, remaining(),
                                  case_dir / "logs" / "restricted_mip.log")
        timed_end = time.perf_counter()
        # Intermediate LP checks are part of this implementation's CG wall time.
        # Only the final MIP's post-solve check is outside time-to-final-solve.
        out.update(status=mip_diag["status"], restricted_mip=mip_diag,
                   timed_arm_wall_seconds=timed_end-started,
                   solve_end_to_end_seconds=(timed_end-started
                     -mip_diag.get("validation_seconds", 0)))
        serialized_cols = [{"kind": c.kind, "a": c.a.tolist(), "e": c.e.tolist(),
                            "fixed_cost": c.fixed_cost, "label": c.label} for c in res["cols"]]
        with gzip.open(case_dir / "cg_columns.json.gz", "wt") as file:
            json.dump(serialized_cols, file)
        # Post-run diagnostics do not feed new columns or warm starts into either arm.
        diagnostic_start = time.perf_counter()
        lp, lp_diag = solve_rmp(inst, res["cols"], False, 120,
                                case_dir / "logs" / "final_pool_lp_check.log")
        graph = build_graph(inst)
        # Certify the actual CG stopping dual. Re-solving after enrichment can
        # choose a different, degenerate RMP dual that is not full-master feasible
        # even when its primal objective is unchanged. It must not replace the
        # already priced-out stopping dual as the algorithm's certificate.
        stopping_lp = res["lp"]
        stop_rc = shortest_path_reduced_cost(inst, graph, stopping_lp.alpha,
                                             stopping_lp.mu, stopping_lp.nu)
        certification = {"final_pool_lp": lp_diag,
                         "certificate_source": "actual_pre_enrichment_CG_stopping_duals",
                         "min_reduced_cost": stop_rc,
                         "priced_out_independently": bool(stop_rc >= -1e-6),
                         "stopping_lp_objective": stopping_lp.obj,
                         "conservative_cg_lower_bound": stopping_lp.obj-inst.n_trips*1e-6,
                         "stopping_duals": {"alpha": stopping_lp.alpha.tolist(),
                                            "mu": stopping_lp.mu.tolist(),
                                            "nu": stopping_lp.nu.tolist()}}
        if lp.status == "optimal":
            rc = shortest_path_reduced_cost(inst, graph, lp.alpha, lp.mu, lp.nu)
            certification.update(final_pool_min_reduced_cost=rc,
                                 final_pool_duals_priced_out=bool(rc >= -1e-6),
                                 final_pool_primal_objective_difference=lp.obj-stopping_lp.obj,
                                 selected_lp_paths=validate_selected_columns(inst, graph, res["cols"], lp.x))
        if np.isfinite(mip.obj):
            certification["selected_mip_paths"] = validate_selected_columns(inst, graph, res["cols"], mip.x)
        out.update(certification=certification,
                   diagnostic_seconds=time.perf_counter()-diagnostic_start)
    except BudgetExpired as exc:
        out.update(status="budget_exhausted", error=str(exc),
                   solve_end_to_end_seconds=time.perf_counter()-started)
    finally:
        colgen.solve_lp, colgen.price_truck_dp = original_lp, original_price
    out["lp_calls"] = calls
    out["total_including_checks_seconds"] = time.perf_counter()-started
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=float, default=1800)
    parser.add_argument("--points", nargs="+", type=int, default=[2, 3, 4, 5])
    parser.add_argument("--energies", nargs="+", type=int, default=[150, 200])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    import gurobipy as gp
    manifest = verify_vendor()
    args.output.mkdir(parents=True, exist_ok=True)
    meta = {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "host": platform.node(), "platform": platform.platform(),
            "machine": platform.machine(), "processor": platform.processor(),
            "python": sys.version, "executable": sys.executable,
            "numpy": np.__version__, "scipy": scipy.__version__,
            "gurobi": gp.gurobi.version(), "budget_seconds_per_arm": args.budget,
            "threads": 1, "seed": 0, "mip_relative_gap": 1e-6,
            "feasibility_tolerance": 1e-8, "optimality_tolerance": 1e-8,
            "integer_feasibility_tolerance": 1e-8,
            "vendor_manifest": manifest,
            "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(ROOT.glob("*.py"))},
            "timing_scope": "Shared input generation and imports excluded. Graph/model/seed/column generation and final MIP included. Intermediate CG LP replay and progress logging are included in CG time and budget; final-solve replay and post-run certification are separately reported and excluded from time-to-final-solve. Cold independent arms; no A solution enters CG.",
            "location": "local workstation; no cluster jobs submitted"}
    manifest_path = args.output / "run_manifest.json"
    if manifest_path.exists():
        if not args.resume:
            raise ValueError("Output already has a run manifest; use a fresh directory or compatible --resume")
        previous = json.loads(manifest_path.read_text())
        # A resumed timing study must not silently combine code, machines or protocols.
        ignored = {"started_utc"}
        differences = [key for key in meta if key not in ignored and safe(meta[key]) != previous.get(key)]
        if differences:
            raise ValueError(f"Resume manifest mismatch: {differences}; use a new output directory")
    else:
        if args.resume and any(args.output.glob("n*_e*")):
            raise ValueError("Cannot resume case outputs without their original manifest")
        write_json(manifest_path, meta)
    cases = []
    for points in args.points:
        for energy in args.energies:
            inst = historical.build_instance(points, energy/100, historical.SCAL)
            name = f"n{inst.n_trips:03d}_e{energy}"
            case_dir = args.output / name
            case_dir.mkdir(parents=True, exist_ok=True)
            record = instance_record(inst, points, energy)
            record["sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            instance_path = case_dir / "instance.json"
            if instance_path.exists():
                if not args.resume or json.loads(instance_path.read_text()) != record:
                    raise ValueError(f"Existing instance mismatch: {name}")
            else:
                write_json(instance_path, record)
            stages = [("arc_lp", lambda: solve_arc_flow(inst, True, args.budget, case_dir/"logs"/"arc_lp.log")),
                      ("arc_mip", lambda: solve_arc_flow(inst, False, args.budget, case_dir/"logs"/"arc_mip.log")),
                      ("cg", lambda: solve_cg(inst, args.budget, case_dir))]
            summary = {"case": name, "n_tasks": inst.n_trips, "energy_kwh": energy}
            for stage, solve in stages:
                path = case_dir / f"{stage}.json"
                if args.resume and path.exists():
                    result = json.loads(path.read_text())
                else:
                    print(f"START {name} {stage}", flush=True)
                    try:
                        result = solve()
                    except Exception as exc:
                        result = {"status": "error", "error": repr(exc), "traceback": traceback.format_exc()}
                    write_json(path, result)
                summary[stage] = {k: result.get(k) for k in ("status", "objective", "bound", "gap", "solve_end_to_end_seconds")}
                if stage == "cg":
                    summary[stage].update({"objective": result.get("restricted_mip", {}).get("objective"),
                                          "lp_objective": result.get("cg_lp_objective")})
                print(f"DONE {name} {stage}: {json.dumps(summary[stage])}", flush=True)
                if result["status"] == "error":
                    print(result["traceback"], flush=True)
                    return 1
            cases.append(summary)
            write_json(args.output / "summary.json", cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
