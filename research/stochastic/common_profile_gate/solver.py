#!/usr/bin/env python3
"""Portable extensive-form *LP* for the best common fixed-skeleton truck profile.

The supported comparison domain is exactly the audited wave-16 domain: lossless
trucks and BESS, zero degradation charge, and no shared charging cap.  ``eta`` is
the historical *charge loss fraction*; it must be zero here.  Both truck and
BESS states therefore evolve by charge - discharge - withdrawal.  Extending
this domain requires a paired audit of the inherited and adaptive comparators.

Truck actions/states are common across every scenario. BESS, generation and
unpriced emergency energy are scenario-specific, with full-scenario foresight.
The first LP minimizes expected emergency; a second LP fixes that optimum and
minimizes expected economic cost. There are no integer variables or route,
fleet, capacity, initial-state, or skeleton decisions.

Requires Python 3.10+, numpy, scipy, and (by default) gurobipy.  --backend scipy
is an explicitly labelled HiGHS fallback for small semantic checks. It never
masquerades as a native Gurobi run. No optimality certificate is reported for an
incomplete phase, and no objective is invented for an infeasible model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from dataclasses import dataclass

import numpy as np
import scipy
from scipy import sparse
from scipy.optimize import linprog

SCHEMA_VERSION = 1
FEASIBILITY_TOL = 1e-7
REPORT_TOL = 1e-6


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(tmp, path)


def _number(value, name, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if positive and value <= 0:
        raise ValueError(f"{name} must be > 0")
    return float(value)


def load_input(source):
    """Read and validate the portable schema; return a detached JSON object."""
    data = json.loads(Path(source).read_text()) if isinstance(source, (str, Path)) else json.loads(
        json.dumps(source, allow_nan=False))
    for key in ("physics", "fleet", "bess", "dates", "deltas", "probabilities", "fixed_asset_cost"):
        if key not in data:
            raise ValueError(f"Missing input field {key}")
    p = data["physics"]
    for key in ("G", "rho", "eta", "c_g", "eps_pen", "deg_cost", "gen_cap", "charge_cap"):
        if key not in p:
            raise ValueError(f"Missing physics.{key}")
    for key in ("G", "rho"):
        _number(p[key], f"physics.{key}", positive=True)
    for key in ("eta", "c_g", "eps_pen", "deg_cost"):
        _number(p[key], f"physics.{key}", minimum=0)
    if "c_b" in p:
        _number(p["c_b"], "physics.c_b", minimum=0)
    if p["eta"] != 0 or p["deg_cost"] != 0 or p["charge_cap"] is not None:
        raise ValueError("Audited wave-16 domain requires eta=0 (charge loss), deg_cost=0, "
                         "and charge_cap=null (infinite shared cap)")
    # Silently accepting unfamiliar efficiency fields would make a lossless
    # model appear to implement losses. Reject them unless explicitly unity.
    for key in ("charge_efficiency", "discharge_efficiency", "truck_charge_efficiency",
                "truck_discharge_efficiency", "bess_charge_efficiency", "bess_discharge_efficiency"):
        if key in p and p[key] != 1:
            raise ValueError(f"{key} must equal 1 in the audited lossless domain")
    if p["gen_cap"] is not None:
        _number(p["gen_cap"], "physics.gen_cap", minimum=0)
    if "allow_discharge" in p and not isinstance(p["allow_discharge"], bool):
        raise ValueError("physics.allow_discharge must be boolean")
    delta = np.asarray(data["deltas"], dtype=float)
    if delta.ndim != 2 or min(delta.shape) < 1 or not np.isfinite(delta).all():
        raise ValueError("deltas must be a finite nonempty W by T array")
    W, T = delta.shape
    prob = np.asarray(data["probabilities"], dtype=float)
    if prob.shape != (W,) or not np.isfinite(prob).all() or (prob <= 0).any():
        raise ValueError("probabilities must contain one strictly positive finite weight per scenario")
    if abs(float(prob.sum()) - 1) > 1e-9:
        raise ValueError("probabilities must sum to one; they are never silently normalized")
    if len(data["dates"]) != W or not all(isinstance(d, str) for d in data["dates"]):
        raise ValueError("dates must contain one string per scenario")
    if not isinstance(data["fleet"], list) or not data["fleet"]:
        raise ValueError("fleet must be a nonempty list of fixed skeletons")
    for j, truck in enumerate(data["fleet"]):
        _number(truck["multiplicity"], f"fleet[{j}].multiplicity", positive=True)
        for key in ("connected", "withdraw", "profile"):
            arr = np.asarray(truck[key], dtype=float)
            if arr.shape != (T,) or not np.isfinite(arr).all():
                raise ValueError(f"fleet[{j}].{key} must be a finite T-vector")
            if key == "connected" and not np.isin(arr, [0, 1]).all():
                raise ValueError(f"fleet[{j}].connected must be binary")
            if key == "withdraw" and (arr < 0).any():
                raise ValueError(f"fleet[{j}].withdraw must be nonnegative")
    nb = _number(data["bess"]["units"], "bess.units", minimum=0)
    s0 = _number(data["bess"]["initial"], "bess.initial", minimum=0)
    if s0 > nb * p["G"]:
        raise ValueError("bess.initial exceeds fixed BESS capacity")
    _number(data["fixed_asset_cost"], "fixed_asset_cost", minimum=0)
    return data


@dataclass
class LP:
    data: dict
    Aeq: sparse.csr_matrix
    beq: np.ndarray
    Aub: sparse.csr_matrix
    bub: np.ndarray
    lb: np.ndarray
    ub: np.ndarray
    c_shortage: np.ndarray
    c_cost: np.ndarray
    index: dict
    pin: bool


def build_model(data, pin=False):
    """Build sparse continuous LP matrices. Fleet variables include multiplicity.

    Pinned actions are equalities added to the unchanged physical bounds. Thus
    an invalid inherited profile produces an infeasible pinned model instead
    of silently overriding connectivity or rate constraints.
    """
    data = load_input(data)
    delta = np.asarray(data["deltas"], float)
    prob = np.asarray(data["probabilities"], float)
    W, T = delta.shape
    J = len(data["fleet"])
    nt = 3 * T + 1
    ns = 5 * T + 1
    common_n = J * nt
    n = common_n + W * ns
    p = data["physics"]
    lb = np.zeros(n)
    ub = np.full(n, np.inf)
    c1 = np.zeros(n)
    c2 = np.zeros(n)
    er, ec, ev, be = [], [], [], []
    ur, uc, uv, bu = [], [], [], []

    def eq(indices, values, rhs):
        row = len(be)
        er.extend([row] * len(indices)); ec.extend(indices); ev.extend(values); be.append(rhs)

    def le(indices, values, rhs):
        row = len(bu)
        ur.extend([row] * len(indices)); uc.extend(indices); uv.extend(values); bu.append(rhs)

    indices = {"truck_charge": [], "truck_discharge": [], "truck_soc": [],
               "bess_charge": [], "bess_discharge": [], "bess_soc": [],
               "generation": [], "emergency": []}
    for j, truck in enumerate(data["fleet"]):
        mult = truck["multiplicity"]
        con = np.asarray(truck["connected"], bool)
        wd = np.asarray(truck["withdraw"], float) * mult
        oc, od, os_ = j * nt, j * nt + T, j * nt + 2 * T
        indices["truck_charge"].append(np.arange(oc, oc + T))
        indices["truck_discharge"].append(np.arange(od, od + T))
        indices["truck_soc"].append(np.arange(os_, os_ + T + 1))
        ub[oc:oc + T] = mult * p["rho"] * con
        ub[od:od + T] = mult * p["rho"] * con * p.get("allow_discharge", True)
        ub[os_:os_ + T + 1] = mult * p["G"]
        lb[os_] = lb[os_ + T] = mult * p["G"]
        c2[oc:oc + T] = p["eps_pen"]
        c2[od:od + T] = p["eps_pen"]
        for t in range(T):
            eq([os_ + t + 1, os_ + t, oc + t, od + t], [1., -1., -1., 1.], -wd[t])
        if pin:
            profile = np.asarray(truck["profile"], float) * mult
            for t in range(T):
                eq([oc + t], [1.], max(profile[t], 0.))
                eq([od + t], [1.], max(-profile[t], 0.))
    nb, s0 = data["bess"]["units"], data["bess"]["initial"]
    for w in range(W):
        base = common_n + w * ns
        oc, od, os_, og, ou = base, base + T, base + 2 * T, base + 3 * T + 1, base + 4 * T + 1
        for name, offset, length in (("bess_charge", oc, T), ("bess_discharge", od, T),
                                     ("bess_soc", os_, T + 1), ("generation", og, T), ("emergency", ou, T)):
            indices[name].append(np.arange(offset, offset + length))
        ub[oc:oc + T] = ub[od:od + T] = nb * p["rho"]
        ub[os_:os_ + T + 1] = nb * p["G"]
        lb[os_] = ub[os_] = lb[os_ + T] = ub[os_ + T] = s0
        ub[og:og + T] = np.inf if p["gen_cap"] is None else p["gen_cap"]
        c1[ou:ou + T] = prob[w]
        c2[oc:oc + T] = c2[od:od + T] = prob[w] * p["eps_pen"]
        c2[og:og + T] = prob[w] * p["c_g"]
        for t in range(T):
            eq([os_ + t + 1, os_ + t, oc + t, od + t], [1., -1., -1., 1.], 0.)
            # g + u - cB + dB - sum(cTruck) + sum(dTruck) >= delta.
            le([og + t, ou + t, oc + t, od + t]
               + [j * nt + t for j in range(J)] + [j * nt + T + t for j in range(J)],
               [-1., -1., 1., -1.] + [1.] * J + [-1.] * J, -delta[w, t])
    return LP(data, sparse.coo_matrix((ev, (er, ec)), shape=(len(be), n)).tocsr(), np.asarray(be),
              sparse.coo_matrix((uv, (ur, uc)), shape=(len(bu), n)).tocsr(), np.asarray(bu),
              lb, ub, c1, c2, {k: np.asarray(v, dtype=int) for k, v in indices.items()}, bool(pin))


def primal_diagnostics(lp, x, Aeq=None, beq=None):
    Aeq = lp.Aeq if Aeq is None else Aeq
    beq = lp.beq if beq is None else beq
    eq = np.asarray(Aeq @ x - beq)
    inequality = np.asarray(lp.Aub @ x - lp.bub)
    residual = {"equality_inf": float(np.max(np.abs(eq), initial=0)),
                "inequality_violation": float(np.max(inequality, initial=0)),
                "lower_bound_violation": float(np.max(lp.lb - x, initial=0)),
                "upper_bound_violation": float(np.max(x - lp.ub, initial=0))}
    residual["maximum_violation"] = max(residual.values())
    residual["passes_report_tolerance"] = residual["maximum_violation"] <= REPORT_TOL
    return residual


def dual_diagnostics(lp, c, x, Aeq, beq, y_eq, y_ub, reduced_cost):
    """Numerical LP KKT diagnostics, explicitly not an exact rational proof.

    <= row duals are nonpositive. Reduced costs supply lower/upper-bound
    multipliers. We do not round a negative reduced cost on an unbounded-above
    variable to manufacture a finite dual lower bound.
    """
    r = np.asarray(reduced_cost)
    stationarity = c - Aeq.T @ y_eq - lp.Aub.T @ y_ub - r
    lower_multiplier, upper_multiplier = np.maximum(r, 0), np.minimum(r, 0)
    finite_upper = np.isfinite(lp.ub)
    unbounded_negative = np.minimum(r[~finite_upper], 0)
    sign_violation = max(float(np.max(y_ub, initial=0)),
                         float(np.max(-unbounded_negative, initial=0)))
    bound_part = float(lower_multiplier @ lp.lb + upper_multiplier[finite_upper] @ lp.ub[finite_upper])
    dual_obj = None if (unbounded_negative < 0).any() else float(beq @ y_eq + lp.bub @ y_ub + bound_part)
    primal_obj = float(c @ x)
    lower_comp = lower_multiplier * (x - lp.lb)
    upper_comp = upper_multiplier[finite_upper] * (lp.ub[finite_upper] - x[finite_upper])
    row_comp = y_ub * (lp.bub - lp.Aub @ x)
    report = {"dual_objective": dual_obj,
            "primal_minus_dual": None if dual_obj is None else primal_obj - dual_obj,
            "dual_sign_violation": sign_violation,
            "stationarity_inf": float(np.max(np.abs(stationarity), initial=0)),
            "complementarity_inf": max(float(np.max(np.abs(lower_comp), initial=0)),
                                       float(np.max(np.abs(upper_comp), initial=0)),
                                       float(np.max(np.abs(row_comp), initial=0))),
            "interpretation": "Floating-point LP KKT diagnostics; not an exact rational certificate"}
    objective_tolerance = REPORT_TOL * max(1., abs(primal_obj))
    report["objective_scaled_tolerance"] = objective_tolerance
    report["passes_report_tolerance"] = bool(
        report["dual_sign_violation"] <= REPORT_TOL
        and report["stationarity_inf"] <= REPORT_TOL
        and report["complementarity_inf"] <= objective_tolerance
        and (dual_obj is None or abs(primal_obj - dual_obj) <= objective_tolerance))
    return report


def _save_primal(lp, x, path):
    arrays = {name: x[ix] for name, ix in lp.index.items()}
    np.savez_compressed(path, x=x, **arrays)
    return {"path": Path(path).name, "sha256": digest_file(path)}


def _save_dual(path, y_eq, y_ub, reduced_cost):
    np.savez_compressed(path, equality_dual=y_eq, inequality_dual=y_ub, reduced_cost=reduced_cost)
    return {"path": Path(path).name, "sha256": digest_file(path)}


def _solution(lp, x, artifact, shortage_optimum):
    a = {name: x[ix] for name, ix in lp.index.items()}
    p = lp.data["physics"]
    prob = np.asarray(lp.data["probabilities"])
    mult = np.asarray([tr["multiplicity"] for tr in lp.data["fleet"]])
    truck_cost = p["eps_pen"] * float((a["truck_charge"] + a["truck_discharge"]).sum())
    op = truck_cost + p["eps_pen"] * (a["bess_charge"] + a["bess_discharge"]).sum(axis=1) + p["c_g"] * a["generation"].sum(axis=1)
    emergency = a["emergency"].sum(axis=1)
    physical = primal_diagnostics(lp, x)
    feasible = physical["passes_report_tolerance"]
    zero = bool(feasible and (emergency <= REPORT_TOL).all())
    profile = a["truck_charge"] - a["truck_discharge"]
    return {"expected_emergency": float(prob @ emergency), "shortage_optimum": shortage_optimum,
            "scenario_emergency": emergency.tolist(), "zero_shortage_all": zero,
            "expected_operating_cost": float(prob @ op),
            "expected_total_cost": float(prob @ op + lp.data["fixed_asset_cost"]) if zero else None,
            "economic_value_at_lexicographic_shortage": float(prob @ op + lp.data["fixed_asset_cost"]),
            "cost_interpretation": "expected_total_cost is null unless every scenario has zero emergency; "
                                   "economic_value_at_lexicographic_shortage is diagnostic when shortage is positive",
            "scenario_operating_cost": op.tolist(),
            "scenario_total_cost": [float(v + lp.data["fixed_asset_cost"]) if feasible and e <= REPORT_TOL else None
                                    for v, e in zip(op, emergency)],
            "profile": profile.tolist(), "profile_per_unit": (profile / mult[:, None]).tolist(),
            "simultaneous_truck_charge_discharge_max": float(np.minimum(a["truck_charge"], a["truck_discharge"]).max(initial=0)),
            "primal_artifact": artifact, "physical_primal_residuals": physical}


def _save_matrices(lp, out, label):
    files = []
    for kind, mat in (("equality", lp.Aeq), ("inequality", lp.Aub)):
        path = out / f"{label}_{kind}_matrix.npz"
        sparse.save_npz(path, mat)
        files.append({"path": path.name, "sha256": digest_file(path)})
    path = out / f"{label}_vectors.npz"
    np.savez_compressed(path, beq=lp.beq, bub=lp.bub, lower_bound=lp.lb, upper_bound=lp.ub,
                        c_shortage=lp.c_shortage, c_cost=lp.c_cost, **{f"index_{k}": v for k, v in lp.index.items()})
    files.append({"path": path.name, "sha256": digest_file(path)})
    return files


def _version_info(backend):
    info = {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
            "platform": platform.platform(), "hostname": platform.node(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "backend": backend}
    if backend == "gurobi":
        import gurobipy as gp
        info["gurobi"] = ".".join(map(str, gp.gurobi.version()))
        info["gurobipy"] = getattr(gp, "__version__", info["gurobi"])
    else:
        info["highs"] = "Bundled with the recorded SciPy version; scipy.optimize.linprog API"
    return info


def _solve_lp(lp, out, label, backend, time_limit, method):
    records, xs = {}, {}
    Aeq, beq = lp.Aeq, lp.beq
    model = env = vx = eq_cons = ub_cons = lex_cons = None
    result = {"phases": records, "solution": None, "complete": False,
              "matrix_artifacts": _save_matrices(lp, out, label),
              "model_sizes": {"variables": len(lp.lb), "continuous_variables": len(lp.lb),
                              "integer_variables": 0, "binary_variables": 0,
                              "equalities_phase1": lp.Aeq.shape[0], "inequalities": lp.Aub.shape[0],
                              "nonzeros_phase1": lp.Aeq.nnz + lp.Aub.nnz,
                              "equalities_phase2": lp.Aeq.shape[0] + 1,
                              "nonzeros_phase2": lp.Aeq.nnz + lp.Aub.nnz + int(np.count_nonzero(lp.c_shortage))}}
    try:
        if backend == "gurobi":
            import gurobipy as gp
            env = gp.Env(empty=True)
            env.setParam("LogToConsole", 0)
            env.start()
            model = gp.Model(f"common_profile_{label}", env=env)
            model.Params.Threads = 1
            model.Params.TimeLimit = time_limit
            model.Params.Method = method
            model.Params.FeasibilityTol = FEASIBILITY_TOL
            model.Params.OptimalityTol = 1e-8
            model.Params.BarConvTol = 1e-9
            model.Params.InfUnbdInfo = 1
            model.Params.Seed = 0
            vx = model.addMVar(len(lp.lb), lb=lp.lb, ub=lp.ub, vtype=gp.GRB.CONTINUOUS, name="x")
            eq_cons = model.addMConstr(lp.Aeq, vx, "=", lp.beq, name="physical_eq")
            ub_cons = model.addMConstr(lp.Aub, vx, "<", lp.bub, name="balance_le")
        optimum = None
        for phase, c in (("shortage", lp.c_shortage), ("cost", lp.c_cost)):
            logpath = out / f"{label}_{phase}.log"
            if phase == "cost":
                # Only a completed minimum-emergency solve authorizes phase 2.
                if not records["shortage"]["optimality_certified"]:
                    break
                optimum = max(0., float(lp.c_shortage @ xs["shortage"]))
                Aeq = sparse.vstack([lp.Aeq, sparse.csr_matrix(lp.c_shortage[None, :])], format="csr")
                beq = np.r_[lp.beq, optimum]
                if backend == "gurobi":
                    lex_cons = model.addMConstr(sparse.csr_matrix(lp.c_shortage[None, :]), vx, "=", [optimum], name="lexicographic_emergency")
            start = time.monotonic()
            phase_record = {"objective": None, "native_objective_bound": None,
                            "optimality_certified": False, "has_primal": False,
                            "log": logpath.name, "lexicographic_shortage_target": optimum,
                            "time_limit_seconds": time_limit, "threads": 1}
            y_eq = y_ub = rc = x = None
            if backend == "gurobi":
                model.Params.LogFile = str(logpath)
                model.setObjective(c @ vx, gp.GRB.MINIMIZE)
                model.optimize()
                status = int(model.Status)
                names = {getattr(gp.GRB, name): name for name in ("LOADED", "OPTIMAL", "INFEASIBLE", "INF_OR_UNBD", "UNBOUNDED", "CUTOFF", "ITERATION_LIMIT", "NODE_LIMIT", "TIME_LIMIT", "SOLUTION_LIMIT", "INTERRUPTED", "NUMERIC", "SUBOPTIMAL", "INPROGRESS", "USER_OBJ_LIMIT", "WORK_LIMIT", "MEM_LIMIT") if hasattr(gp.GRB, name)}
                phase_record.update(status=names.get(status, str(status)), native_status=status,
                                    native_runtime_seconds=float(model.Runtime),
                                    iterations=float(model.IterCount), barrier_iterations=int(model.BarIterCount),
                                    solution_count=int(model.SolCount), solver_method=method,
                                    model_fingerprint=int(model.Fingerprint), is_mip=bool(model.IsMIP))
                if model.SolCount > 0:
                    x = np.asarray(vx.X)
                    phase_record["native_objective"] = float(model.ObjVal)
                try:
                    bound = float(model.ObjBound)
                    phase_record["native_objective_bound"] = bound if math.isfinite(bound) else None
                except (gp.GurobiError, AttributeError):
                    pass  # Gurobi does not expose ObjBound for every continuous-LP state.
                if status == gp.GRB.OPTIMAL:
                    y_eq = np.asarray(eq_cons.Pi)
                    if phase == "cost":
                        y_eq = np.r_[y_eq, np.asarray(lex_cons.Pi)]
                    y_ub, rc = np.asarray(ub_cons.Pi), np.asarray(vx.RC)
                solver_optimal = status == gp.GRB.OPTIMAL
            else:
                # HiGHS options outside SciPy's surface are passed through; this
                # requested single thread is recorded and forwarded explicitly.
                import warnings
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="Unrecognized options detected")
                    solved = linprog(c, A_ub=lp.Aub, b_ub=lp.bub, A_eq=Aeq, b_eq=beq,
                                     bounds=np.column_stack([lp.lb, lp.ub]), method="highs",
                                     options={"time_limit": time_limit, "threads": 1,
                                              "primal_feasibility_tolerance": FEASIBILITY_TOL,
                                              "dual_feasibility_tolerance": 1e-8})
                names = {0: "OPTIMAL", 1: "LIMIT_REACHED", 2: "INFEASIBLE", 3: "UNBOUNDED", 4: "SOLVER_ERROR"}
                phase_record.update(status=names.get(solved.status, "UNKNOWN"), native_status=int(solved.status),
                                    native_message=solved.message, iterations=int(solved.nit),
                                    is_mip=False, solver_method="scipy-highs")
                solver_optimal = bool(solved.success)
                if solved.x is not None and np.isfinite(solved.x).all():
                    x = np.asarray(solved.x)
                if solver_optimal:
                    y_eq, y_ub = solved.eqlin.marginals, solved.ineqlin.marginals
                    rc = solved.lower.marginals + solved.upper.marginals
                logpath.write_text("SciPy/HiGHS diagnostic record; this is NOT a native Gurobi solver log.\n" + str(solved.message) + "\n")
            phase_record["elapsed_seconds"] = time.monotonic() - start
            if x is not None:
                xs[phase] = x
                phase_record.update(has_primal=True, objective=float(c @ x),
                                    primal_residuals=primal_diagnostics(lp, x, Aeq, beq),
                                    primal_artifact=_save_primal(lp, x, out / f"{label}_{phase}_primal.npz"))
                phase_record["optimality_certified"] = bool(solver_optimal and phase_record["primal_residuals"]["passes_report_tolerance"])
                if y_eq is not None:
                    phase_record["duality"] = dual_diagnostics(lp, c, x, Aeq, beq, y_eq, y_ub, rc)
                    phase_record["dual_artifact"] = _save_dual(out / f"{label}_{phase}_dual.npz", y_eq, y_ub, rc)
                    phase_record["optimality_certified"] = bool(
                        phase_record["optimality_certified"] and phase_record["duality"]["passes_report_tolerance"])
                    # ObjBound may be unavailable for LPs: optimal native status
                    # gives a numerical optimum; preserve the independent KKT
                    # dual objective and all residuals alongside that claim.
                    if phase_record["optimality_certified"]:
                        phase_record["optimal_objective_value"] = float(c @ x)
                else:
                    phase_record["optimality_certified"] = False
                if phase_record["native_objective_bound"] is not None:
                    phase_record["native_primal_bound_gap"] = float(c @ x) - phase_record["native_objective_bound"]
            records[phase] = phase_record
            write_json(out / f"{label}_{phase}.json", phase_record)
            if not phase_record["optimality_certified"]:
                break
        if "cost" in xs:
            result["solution"] = _solution(lp, xs["cost"], records["cost"]["primal_artifact"], optimum)
        result["complete"] = all(records.get(p, {}).get("optimality_certified", False) for p in ("shortage", "cost"))
        result["state"] = "complete" if result["complete"] else "incomplete"
        if records.get("shortage", {}).get("status") == "INFEASIBLE":
            result["state"] = "infeasible"
    except Exception as exc:
        result.update(state="error", error=repr(exc))
        # A backend/license failure must retain a reviewable failure artifact.
        write_json(out / f"{label}_error.json", result)
    finally:
        if model is not None:
            model.dispose()
        if env is not None:
            env.dispose()
    for rec in records.values():
        logfile = out / rec["log"]
        if logfile.exists():
            rec["log_sha256"] = digest_file(logfile)
    for phase, rec in records.items():
        write_json(out / f"{label}_{phase}.json", rec)
    return result


def solve_case(data, output_dir, backend="gurobi", time_limit=3600., mode="both", method=2):
    """Solve inherited witness and/or common-profile LP; save portable artifacts.

    ``mode='pinned'`` enables replay of a profile frozen on a different support.
    Output directories are immutable once result.json exists: use a new run
    directory for a retry. Backend failures are recorded, never silently retried
    with a different solver.
    """
    source_sha = digest_file(data) if isinstance(data, (str, Path)) else None
    data = load_input(data)
    _number(time_limit, "time_limit", positive=True)
    if backend not in ("gurobi", "scipy") or mode not in ("both", "common", "pinned"):
        raise ValueError("Unsupported backend or mode")
    if method not in (-1, 0, 1, 2):
        raise ValueError("method must be -1, 0, 1, or 2")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "result.json").exists() or (out / "input.json").exists():
        raise FileExistsError(f"Run directory already contains an input/result: {out}")
    write_json(out / "input.json", data)
    W, T = np.asarray(data["deltas"]).shape
    result = {"schema_version": SCHEMA_VERSION, "state": "running", "model_kind": "LP",
              "input_sha256": digest_file(out / "input.json"), "source_input_sha256": source_sha,
              "input_semantic_sha256": json_digest(data), "solver_sha256": digest_file(__file__),
              "metadata": data.get("metadata", {}), "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "mode": mode, "backend": backend,
              "model_sizes": {"scenarios": W, "time_slots": T, "fleet_elements": len(data["fleet"])},
              "domain": {"eta_means": "charge loss fraction", "eta": 0, "deg_cost": 0,
                         "shared_charge_cap": None, "truck_boundary": "full-to-full",
                         "bess_boundary": "fixed initial-to-same-initial", "all_variables_continuous": True,
                         "common_truck_actions_and_states": True, "recourse": "full-scenario BESS/generation/emergency",
                         "emergency": "unpriced, expected minimum fixed exactly before economic optimization",
                         "fixed_asset_cost_included_once": data["fixed_asset_cost"],
                         "energy_convention": "slot energies; no extra duration factor"},
              "parameters": {"threads": 1, "time_limit_per_phase_seconds": time_limit,
                             "gurobi_method": method if backend == "gurobi" else None,
                             "feasibility_tolerance": FEASIBILITY_TOL, "report_tolerance": REPORT_TOL},
              "certificate_scope": "Numerical optimal LP status plus explicit primal/KKT residuals; never a MIP/global-route certificate"}
    try:
        result["versions"] = _version_info(backend)
        write_json(out / "status.json", result)
        for label in (["inherited", "common"] if mode == "both" else ["inherited"] if mode == "pinned" else ["common"]):
            result[label] = _solve_lp(build_model(data, pin=(label == "inherited")), out, label, backend, time_limit, method)
            write_json(out / "status.json", result)
        labels = [label for label in ("inherited", "common") if label in result]
        result["state"] = "complete" if all(result[label]["complete"] for label in labels) else "incomplete"
        if mode == "both":
            old, common = result["inherited"], result["common"]
            os_, cs = old["solution"], common["solution"]
            compare = {"same_support": True, "reliability_hierarchy_pass": None,
                       "economic_hierarchy_pass": None, "inherited_profile_regret": None,
                       "available": bool(old["complete"] and common["complete"] and os_ and cs)}
            if compare["available"]:
                compare["reliability_hierarchy_pass"] = cs["expected_emergency"] <= os_["expected_emergency"] + REPORT_TOL
                if os_["zero_shortage_all"] and cs["zero_shortage_all"]:
                    regret = os_["expected_total_cost"] - cs["expected_total_cost"]
                    compare["inherited_profile_regret"] = regret
                    compare["economic_hierarchy_pass"] = regret >= -1e-5
                if compare["reliability_hierarchy_pass"] is False or compare["economic_hierarchy_pass"] is False:
                    result["state"] = "validation_failed"
            result["comparison"] = compare
    except Exception as exc:
        result.update(state="error", error=repr(exc))
    write_json(out / "result.json", result)
    write_json(out / "status.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=("gurobi", "scipy"), default="gurobi")
    parser.add_argument("--mode", choices=("both", "common", "pinned"), default="both")
    parser.add_argument("--time-limit", type=float, default=3600., help="Finite seconds per LP phase")
    parser.add_argument("--method", type=int, choices=(-1, 0, 1, 2), default=2, help="Gurobi method; 2 = barrier with native crossover")
    args = parser.parse_args()
    result = solve_case(args.input, args.output, args.backend, args.time_limit, args.mode, args.method)
    print(json.dumps({"state": result["state"], "output": str(args.output.resolve()),
                      "comparison": result.get("comparison")}, allow_nan=False))
    return 0 if result["state"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
