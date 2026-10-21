"""Gurobi backends using the common matrix and independently checked incumbents.

A verified time-limited incumbent is feasible; its finite-pool bound does not
certify column-generation pricing or a full-route integer optimum.
"""
from __future__ import annotations
import numpy as np
from time import perf_counter
import master
from master import Column, RMPSolution


def native_reason(status):
    return {1:"loaded", 2:"optimal", 3:"infeasible", 4:"infeasible_or_unbounded",
            5:"unbounded", 6:"cutoff", 7:"iteration_limit", 8:"node_limit",
            9:"time_limit", 10:"solution_limit", 11:"interrupted", 12:"numerical_error",
            13:"suboptimal", 14:"in_progress", 15:"objective_limit", 16:"work_limit",
            17:"memory_limit"}.get(int(status), "unknown_status")


def build_native(form, integer=False, time_limit=None, mip_gap=None,
                 x_start=None, threads=1):
    import gurobipy as gp
    from gurobipy import GRB
    m = gp.Model("rmp")
    m.Params.OutputFlag = 0
    m.Params.Threads = threads
    if not integer:
        m.Params.Method = 1  # dual simplex; persistent updates retain the basis
    if time_limit is not None:
        m.Params.TimeLimit = float(time_limit)
    if integer and mip_gap is not None:
        m.Params.MIPGap = float(mip_gap)
    indices = set(form.integer_indices) if integer else set()
    v = [m.addVar(lb=0.0 if lb is None else float(lb),
                 ub=GRB.INFINITY if ub is None else float(ub), obj=float(form.c[j]),
                 vtype=GRB.INTEGER if j in indices else GRB.CONTINUOUS, name=f"v_{j}")
         for j, (lb, ub) in enumerate(form.bounds)]
    m.update()
    rows = []
    for matrix, rhs, equality in ((form.Aeq, form.beq, True), (form.Aub, form.bub, False)):
        part = []
        for k in range(matrix.shape[0]):
            a, b = matrix.indptr[k:k+2]
            expr = gp.LinExpr(matrix.data[a:b].tolist(), [v[int(j)] for j in matrix.indices[a:b]])
            part.append(m.addConstr(expr == float(rhs[k]) if equality else expr <= float(rhs[k]),
                                    name=f"{'eq' if equality else 'ub'}_{k}"))
        rows.append(part)
    if integer and x_start:
        start = {int(k): value for k, value in x_start.get("x", {}).items()}
        for r in range(form.R):
            v[r].Start = int(round(start.get(r, 0)))
        v[form.off[-1]].Start = int(round(x_start.get("nb", 0)))
    m.update()
    return m, v, rows[0], rows[1]


def _optional_attribute(m, key):
    try:
        value = float(getattr(m, key))
        return value if np.isfinite(value) else None
    except (AttributeError, RuntimeError):
        return None


def extract_native(m, form, ordered_vars, eq, ub, integer=False):
    reason = native_reason(m.Status)
    meta = dict(native_status=int(m.Status), termination_reason=reason,
                message=f"Gurobi {reason}; SolCount={m.SolCount}")
    if integer:
        meta["solver_bound"] = _optional_attribute(m, "ObjBound")
        meta["gap"] = _optional_attribute(m, "MIPGap") if m.SolCount else None
    if not m.SolCount or reason in ("infeasible", "infeasible_or_unbounded", "unbounded", "numerical_error"):
        return master.empty_solution(form, reason, integer, **meta)
    z = np.array([v.X for v in ordered_vars])
    sol = master.solution_from_vector(form, z, integer,
        status="optimal" if m.Status == 2 else "feasible", objective=m.ObjVal, **meta)
    if not integer and sol.status == "optimal":
        sol.alpha = np.array([r.Pi for r in eq[:form.n]])
        sol.mu = -np.array([r.Pi for r in ub[:form.T]])
        if form.cc_start is not None:
            sol.nu = -np.array([r.Pi for r in ub[form.cc_start:form.cc_start + form.T]])
        if form.fleet_row is not None:
            sol.fleet_dual = float(ub[form.fleet_row].Pi)
        sol.solver_bound, sol.gap = sol.obj, 0.0
    return sol


def _build(inst, cols, integer, battery_allowed, time_limit=None, soc_mode="cyclic",
           mip_gap=None, x_start=None):
    """Compatibility wrapper preserving the historical private return tuple."""
    form = master.canonical_model(inst, cols, battery_allowed, soc_mode)
    m, v, eq, ub = build_native(form, integer, time_limit, mip_gap, x_start)
    m.optimize()
    _, og, oc, od, os, onb = form.off
    return (m, {r:v[r] for r in range(form.R)}, {t:v[og+t] for t in range(form.T)},
            {t:v[oc+t] for t in range(form.T)}, {t:v[od+t] for t in range(form.T)},
            {t:v[os+t] for t in range(form.T+1)}, v[onb], eq[:form.n], ub[:form.T],
            None if form.cc_start is None else ub[form.cc_start:form.cc_start+form.T])


def solve_lp_gurobi(inst, cols, battery_allowed=True, soc_mode="cyclic"):
    started = perf_counter()
    form = master.canonical_model(inst, cols, battery_allowed, soc_mode)
    m, v, eq, ub = build_native(form)
    built = perf_counter()
    try:
        m.optimize()
        solved = perf_counter()
        sol = extract_native(m, form, v, eq, ub)
        sol.timings = dict(build_seconds=built-started, solve_seconds=solved-built,
            solver_runtime_seconds=float(m.Runtime), validation_seconds=perf_counter()-solved,
            rows=len(eq)+len(ub), columns=len(v))
        return sol
    finally:
        m.dispose()


def solve_milp_gurobi(inst, cols, time_limit=120.0, battery_allowed=True,
                      soc_mode="cyclic", mip_gap=None, x_start=None):
    started = perf_counter()
    form = master.canonical_model(inst, cols, battery_allowed, soc_mode)
    m, v, eq, ub = build_native(form, True, time_limit, mip_gap, x_start)
    built = perf_counter()
    try:
        m.optimize()
        solved = perf_counter()
        sol = extract_native(m, form, v, eq, ub, True)
        sol.timings = dict(build_seconds=built-started, solve_seconds=solved-built,
            solver_runtime_seconds=float(m.Runtime), validation_seconds=perf_counter()-solved,
            rows=len(eq)+len(ub), columns=len(v))
        return sol
    finally:
        m.dispose()
