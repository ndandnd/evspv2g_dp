"""Direct COMMON4 planning spot checks on three prespecified historical bases.

Only new files are used: frozen vendor, pilot and extension modules are unchanged.
Every configuration retains the complete aligned DP graph and all real vendor
singleton seeds. Charge-only trucks remove DISCHARGE arcs; no-BESS configurations
fix Nb=0, which forces its dispatch and SoC to zero through the original bounds.

Public API:
    planning_specs() -> list[dict]
    build_planning_case(spec) -> Instance
    prepare_planning(inst, scenario) -> (graph, seeds, proofs, audit)
    solve_planning(inst, scenario, relax, time_limit, log_path,
                   lp_method=2, threads=1) -> JSON-compatible dict

Worker: --input CASE --config SCENARIO --output FRESH_DIRECTORY --budget 1800.
Both LP and MIP run serially with fresh Gurobi environments. No MIP starts,
historical incumbents, LP basis, or solutions are shared between solves. LP uses
explicit Method=2 and Crossover=-1; integer solve uses Method=-1. Historical rows
are comparison evidence only. --plan lists inputs without building or solving;
--preflight builds and validates one input/configuration without optimization.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import traceback

import numpy as np
import scipy

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
import recreate_arxiv as historical
from colgen import SCENARIOS
from arc_flow import Graph, DISCHARGE, build_graph, validate_instance
from column_witness import find_column_path
from extension_instances import rand_trips
from extension_models import _seeds_with_witnesses, _hybrid_matrices, _hybrid_replay
from run_pilot import safe, write_json, verify_vendor

INPUT_FILE = ROOT / "planning_direct_inputs.json"
SCENARIO_ORDER = ("solar", "solar_bess", "v2g_fleet", "v2g")


def planning_specs():
    return json.loads(INPUT_FILE.read_text())["cases"]


def build_planning_case(spec):
    canonical = next((s for s in planning_specs() if s["case"] == spec.get("case")), None)
    if canonical is None or canonical != spec:
        raise ValueError("Use an unmodified planning_specs() entry")
    verify_vendor()
    if Path(historical.__file__).resolve() != (ROOT / "vendor/recreate_arxiv.py").resolve():
        raise RuntimeError("Instance builder must be the frozen vendor snapshot")
    fleet = rand_trips(3, spec["n_tasks"], spec["draw_seed"], salt=50000)
    inst = historical.build_instance(3, 2.0, historical.BREAKS,
                                     trip_list=fleet, pv_scale=spec["pv_scale"])
    inst.c_g, inst.c_b, inst.rho, inst.c_v = 40.0, 36.0, 1.75, 45.0
    inst.soc_step = 0.25
    expected = json.loads(INPUT_FILE.read_text())["builder"]
    for key in ("T", "G", "rho", "soc_step", "eta", "energy_per_dist", "c_g",
                "c_v", "c_b", "eps_pen", "deg_cost"):
        if getattr(inst, key) != expected[key]:
            raise ValueError(f"Historical planning input mismatch: {key}")
    if inst.n_trips != spec["n_tasks"] or list(inst.charge_locs) != [inst.depot]:
        raise ValueError("Unexpected task count or charging locations")
    if np.any(np.isfinite(np.asarray(inst.gen_cap))) or np.isfinite(inst.charge_cap):
        raise ValueError("COMMON4 has uncapped generation and aggregate charging")
    validate_instance(inst)
    return inst


def _charge_only_graph(graph):
    keep = graph.kind != DISCHARGE
    tail, head = graph.tail[keep], graph.head[keep]
    reachable = np.zeros(graph.n_nodes, dtype=bool); reachable[graph.source] = True
    for u, v in zip(tail, head):
        if reachable[u]:
            reachable[v] = True
    coreachable = np.zeros(graph.n_nodes, dtype=bool); coreachable[graph.sink] = True
    for u, v in zip(tail[::-1], head[::-1]):
        if coreachable[v]:
            coreachable[u] = True
    active = reachable & coreachable
    active[graph.source] = active[graph.sink] = True
    edge_keep = reachable[tail] & coreachable[head]
    mapping = np.full(graph.n_nodes, -1, dtype=np.int32)
    mapping[active] = np.arange(int(active.sum()), dtype=np.int32)
    return Graph(graph.states[active], mapping[tail[edge_keep]], mapping[head[edge_keep]],
                 graph.kind[keep][edge_keep], graph.task[keep][edge_keep],
                 graph.energy[keep][edge_keep], int(mapping[graph.source]),
                 int(mapping[graph.sink]), graph.step, graph.n_nodes, int(keep.sum()))


def prepare_planning(inst, scenario):
    if scenario not in SCENARIO_ORDER:
        raise ValueError("Only the four matched COMMON4 scenarios are supported")
    caps = SCENARIOS[scenario]
    if caps["ice"] or not caps["allow_charge"] or caps.get("flat_price", False):
        raise ValueError("Unexpected frozen scenario definition")
    # Unlike coarse DIAG2, planning must pass original-rate divisibility checks.
    original_graph = build_graph(inst)
    graph = original_graph if caps["allow_discharge"] else _charge_only_graph(original_graph)
    seeds, physical_proofs = _seeds_with_witnesses(inst)
    summaries = []
    for col, proof in zip(seeds, physical_proofs):
        if proof["off_grid_profile"] or np.any(col.e < -1e-9):
            raise ValueError("COMMON4 requires nonnegative lattice singleton profiles")
        witness = find_column_path(inst, graph, col)
        if not witness["passed"]:
            raise ValueError(f"Planning singleton is not in the scenario graph: {witness}")
        summaries.append({"task_ids": proof["task_ids"], "passed": True,
                          "physical_max_residual": proof["max_residual"],
                          "graph_max_residual": witness["max_residual"]})
    audit = {"passed": True, "scenario": scenario,
             "truck_discharge_allowed": bool(caps["allow_discharge"]),
             "stationary_storage_allowed": bool(caps["battery"]),
             "G_over_step": inst.G / inst.soc_step,
             "rho_over_step": inst.rho / inst.soc_step,
             "eta": float(inst.eta), "lattice_inputs_validated": True,
             "truck_boundary": "full/full", "stationary_boundary": "periodic",
             "original_graph_nodes": original_graph.n_nodes,
             "original_graph_arcs": original_graph.n_arcs,
             "scenario_graph_nodes": graph.n_nodes, "scenario_graph_arcs": graph.n_arcs,
             "seed_count": len(seeds), "off_grid_seed_count": 0,
             "all_seeds_witnessed_in_scenario_graph": True,
             "seed_audit": summaries,
             "family": "all scenario-admissible frozen DP paths union real initial seeds; all seeds are graph paths"}
    return graph, seeds, physical_proofs, audit


def solve_planning(inst, scenario, relax, time_limit, log_path, lp_method=2, threads=1):
    started = time.perf_counter()
    if not math.isfinite(time_limit) or time_limit <= 0 or threads != 1:
        raise ValueError("Positive finite budget and one solver thread required")
    if lp_method not in (1, 2):
        raise ValueError("Explicit LP Method=1 or2 required")
    import gurobipy as gp
    from gurobipy import GRB
    graph, seeds, proofs, audit = prepare_planning(inst, scenario)
    graph_done = time.perf_counter()
    c, lb, ub, ae, be, au, bu, off = _hybrid_matrices(inst, graph, seeds)
    if not SCENARIOS[scenario]["battery"]:
        ub[off["nb"]] = 0.0
    method = lp_method if relax else -1
    result = {"method": "planning_direct_lp" if relax else "planning_direct_mip",
              "scenario": scenario, "relax": bool(relax), "audit": audit,
              "family": audit["family"], "n_tasks": inst.n_trips,
              "graph_nodes": graph.n_nodes, "graph_arcs": graph.n_arcs,
              "seed_count": len(seeds), "off_grid_seed_count": 0,
              "original_rho": float(inst.rho), "bess_rho": float(inst.rho),
              "soc_step": float(inst.soc_step), "graph_and_audit_seconds": graph_done-started,
              "objective": None, "bound": None, "gap": None, "validation": None,
              "solution_count": 0, "time_limit_seconds": float(time_limit),
              "threads": 1, "seed": 0, "solver_version": list(gp.gurobi.version()),
              "solver_method": method, "crossover": -1, "mip_gap_tolerance": 1e-6,
              "feasibility_tolerance": 1e-8, "optimality_tolerance": 1e-8,
              "integer_feasibility_tolerance": 1e-8,
              "cold_solve": True, "solution_or_basis_sharing": False}
    if log_path is not None:
        log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
        result["log_path"] = str(log_path.resolve())
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 1 if log_path is not None else 0)
        env.setParam("LogToConsole", 0)
        if log_path is not None:
            env.setParam("LogFile", str(log_path))
        env.start()
        with gp.Model("COMMON4_complete_DP_family", env=env) as model:
            model.Params.Threads = 1; model.Params.Seed = 0
            model.Params.Method = method; model.Params.Crossover = -1
            model.Params.MIPGap = 1e-6
            model.Params.FeasibilityTol = 1e-8; model.Params.OptimalityTol = 1e-8
            model.Params.IntFeasTol = 1e-8
            vtype = np.full(len(c), GRB.CONTINUOUS)
            if not relax:
                vtype[:graph.n_arcs + 1] = GRB.INTEGER
                vtype[off["nb"]] = GRB.INTEGER
                vtype[off["seed_start"]:] = GRB.INTEGER
            variables = model.addMVar(len(c), lb=lb, ub=ub, obj=c, vtype=vtype, name="v")
            model.addMConstr(ae, variables, "=", be, name="eq")
            model.addMConstr(au, variables, "<", bu, name="ub")
            model.update(); built = time.perf_counter(); remaining = time_limit-(built-started)
            result.update(model_build_seconds=built-graph_done, variables=model.NumVars,
                          constraints=model.NumConstrs, nonzeros=model.NumNZs,
                          integer_variables=model.NumIntVars,
                          solver_budget_seconds=max(0.0, remaining))
            if remaining <= 0:
                result.update(status="budget_exhausted_before_optimize", native_status=None,
                              solve_seconds=0.0, solve_end_to_end_seconds=built-started,
                              total_seconds=built-started)
                return result
            model.Params.TimeLimit = remaining
            solve_start = time.perf_counter(); model.optimize(); finished = time.perf_counter()
            names = {GRB.OPTIMAL: "optimal", GRB.INFEASIBLE: "infeasible",
                     GRB.INF_OR_UNBD: "infeasible_or_unbounded", GRB.UNBOUNDED: "unbounded",
                     GRB.TIME_LIMIT: "time_limit", GRB.INTERRUPTED: "interrupted",
                     GRB.NUMERIC: "numeric", GRB.SUBOPTIMAL: "suboptimal"}
            result.update(status=names.get(model.Status, f"status_{model.Status}"),
                          native_status=int(model.Status), solution_count=int(model.SolCount),
                          solve_seconds=finished-solve_start,
                          solver_runtime_seconds=float(model.Runtime),
                          solve_end_to_end_seconds=finished-started,
                          node_count=float(model.NodeCount), iterations=float(model.IterCount),
                          barrier_iterations=int(model.BarIterCount))
            for attr, key in (("ObjBound", "bound"), ("MIPGap", "gap"),
                              ("MaxMemUsed", "solver_peak_memory_gb")):
                try:
                    value = float(getattr(model, attr))
                    result[key] = value if math.isfinite(value) else None
                except (AttributeError, gp.GurobiError):
                    pass
            if model.SolCount:
                result["objective"] = float(model.ObjVal)
                if relax and model.Status == GRB.OPTIMAL:
                    result["bound"] = float(model.ObjVal); result["gap"] = 0.0
                validation = _hybrid_replay(inst, graph, seeds, proofs,
                                            np.asarray(variables.X), off, model.ObjVal, not relax)
                truck_discharge = sum(p["weight"] * sum(max(-e, 0.0) for e in p["energy"])
                                      for p in validation["paths"])
                truck_discharge += sum(p["weight"] * sum(max(-e, 0.0)
                                       for e in p["witness"]["profile"])
                                       for p in validation["singleton_paths"])
                scenario_residuals = {
                    "forbidden_truck_discharge": 0.0 if SCENARIOS[scenario]["allow_discharge"]
                                                  else float(truck_discharge),
                    "forbidden_bess_count": 0.0 if SCENARIOS[scenario]["battery"]
                                             else abs(validation["nb"])}
                if max(scenario_residuals.values()) > 1e-6:
                    raise ValueError(f"Scenario replay failed: {scenario_residuals}")
                validation.update(scenario_residuals=scenario_residuals,
                                  truck_discharge_total=float(truck_discharge))
                result["validation"] = validation
            result["validation_seconds"] = time.perf_counter()-finished
            result["total_seconds"] = time.perf_counter()-started
    return safe(result)


def _instance_record(inst, spec):
    record = safe({"spec": spec, "T": inst.T, "n_tasks": inst.n_trips,
                   "D": inst.D, "P": inst.P, "Delta": inst.Delta,
                   "dist": inst.dist, "trips": [vars(tr) for tr in inst.trips],
                   "G": inst.G, "rho": inst.rho, "eta": inst.eta,
                   "soc_step": inst.soc_step, "energy_per_dist": inst.energy_per_dist,
                   "c_g": inst.c_g, "c_v": inst.c_v, "c_b": inst.c_b,
                   "eps_pen": inst.eps_pen, "deg_cost": inst.deg_cost,
                   "charge_locations": list(inst.charge_locs), "depot": inst.depot,
                   "generation_cap": "unbounded", "charging_cap": "unbounded",
                   "truck_boundary": "full/full", "stationary_boundary": "periodic"})
    record["sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return record


def _historical_comparison(spec, scenario, result):
    entry = next(x for x in spec["historical_source"]["rows"]
                 if x["row"]["scenario"] == scenario)
    old = entry["row"]; objective = result.get("objective")
    out = {"historical_record": entry, "historical_lp_printed_decimal_places": 4,
           "historical_incumbent_printed_decimal_places": 2,
           "historical_lp_rounding_radius": 0.00005,
           "historical_incumbent_rounding_radius": 0.005,
           "historical_solver_bound_scope": "restricted common route pool only; never a full-family integer lower bound",
           "historical_lp_scope": "reported priced-out family LP; saved duals absent, not independently certified from this row"}
    if objective is not None:
        out["objective_minus_historical_lp_union"] = objective-old["lp_union"]
        out["objective_minus_historical_incumbent_rounded"] = objective-old["total"]
        if result["relax"]:
            out["lp_agrees_with_printed_historical_value_at_1e_minus4"] = abs(objective-old["lp_union"]) <= 1e-4
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "--case", dest="case")
    parser.add_argument("--config", "--scenario", dest="scenario", choices=SCENARIO_ORDER)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--budget", type=float, default=1800.0)
    parser.add_argument("--lp-method", type=int, choices=(1, 2), default=2)
    parser.add_argument("--stage", choices=("both", "lp", "mip"), default="both")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps({"inputs": planning_specs(), "configs": SCENARIO_ORDER,
                          "total_configurations": 12, "optimizations_launched": 0}, indent=2))
        return 0
    spec = next((s for s in planning_specs() if s["case"] == args.case), None)
    if spec is None or args.scenario is None:
        parser.error("Choose --input from --plan and supply --config")
    inst = build_planning_case(spec)
    if args.preflight:
        graph, seeds, proofs, audit = prepare_planning(inst, args.scenario)
        print(json.dumps(safe(audit), indent=2)); return 0
    if args.output is None:
        parser.error("--output is required for solving")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use an empty or fresh output directory; prior evidence is immutable")
    import gurobipy as gp
    manifest = {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "case": spec["case"], "scenario": args.scenario, "spec": spec,
                "host": platform.node(), "platform": platform.platform(),
                "python": sys.version, "executable": sys.executable,
                "numpy": np.__version__, "scipy": scipy.__version__,
                "gurobi": list(gp.gurobi.version()), "budget_per_stage": args.budget,
                "threads": 1, "seed": 0, "lp_method": args.lp_method,
                "lp_crossover": -1, "mip_root_method": -1, "mip_gap": 1e-6,
                "cold_independent_models": True, "solution_sharing": False,
                "vendor_manifest": verify_vendor(),
                "code_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(ROOT.glob("*.py"))},
                "selected_inputs_sha256": hashlib.sha256(INPUT_FILE.read_bytes()).hexdigest(),
                "timing_scope": "Instance reconstruction/imports excluded. Graph, physical seed audit, model and solve included. Final path/master replay excluded from time-to-solve; separately recorded.",
                "scope": "Three selected informative planning bases, not a representative estimator of all270; comparison with rounded saved rows is separate from solver bounds."}
    write_json(args.output / "run_manifest.json", manifest)
    write_json(args.output / "instance.json", _instance_record(inst, spec))
    stages = ("lp", "mip") if args.stage == "both" else (args.stage,)
    for stage in stages:
        write_json(args.output / "progress.json", {"stage": stage, "status": "running"})
        try:
            result = solve_planning(inst, args.scenario, stage == "lp", args.budget,
                                    args.output / "logs" / f"{stage}.log", args.lp_method)
            result["historical_comparison"] = _historical_comparison(spec, args.scenario, result)
        except Exception as error:
            result = {"status": "error", "error": repr(error), "traceback": traceback.format_exc()}
        write_json(args.output / f"{stage}.json", result)
        print(json.dumps({"stage": stage, **{k: result.get(k) for k in
              ("status", "objective", "bound", "gap", "solve_end_to_end_seconds")}}), flush=True)
        if result["status"] == "error":
            write_json(args.output / "progress.json", {"stage": stage, "status": "error"})
            return 1
    write_json(args.output / "progress.json", {"status": "complete", "stages": stages})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
