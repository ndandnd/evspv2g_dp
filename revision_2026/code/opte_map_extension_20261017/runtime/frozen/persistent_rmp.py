"""Incremental LP-only RMP with explicit simplex-basis reuse.

This additive adapter leaves the frozen cold baseline unchanged. The initial
model comes from vendor.master._build_lp. Later route columns have the same
coverage, signed energy, gross-charge and objective coefficients. Shared BESS
rows and variable bounds are never reconstructed or changed. Native variable
order differs from the canonical master after the first addition; returned raw
vectors are always converted back to canonical order for the original replay.

API: PersistentRMP().solve(inst, cols, integer, time_limit, log_path,
                          threads=1, mip_gap=1e-6) -> (RMPSolution, diagnostics).
Use close() in a finally block. Only append-only pools in one instance and LPs
are supported. Each call's allowance includes validation, model updates,
basis restoration and optimization, exactly as the cold adapter does.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import time

import numpy as np
from scipy import sparse

import master
from master import RMPSolution
from rmp_solver import _empty_solution, _validate_scope, replay_rmp


def column_fingerprint(col):
    h = hashlib.sha256()
    for value in (col.a, col.e):
        a = np.ascontiguousarray(value, dtype=np.float64)
        h.update(str(a.shape).encode()); h.update(a.tobytes())
    h.update(str(col.kind).encode()); h.update(float(col.fixed_cost).hex().encode())
    return h.hexdigest()


class PersistentRMP:
    def __init__(self):
        self.env = None; self.model = None; self.instance = None
        self.cols = []; self.fingerprints = []; self.route_vars = []
        self.shared_vars = []; self.eq = []; self.le = []
        self.shared_bounds = []; self.cc_start = None
        self.basis = None; self.calls = 0; self.basis_restorations = 0

    def close(self):
        if self.model is not None:
            self.model.dispose(); self.model = None
        if self.env is not None:
            self.env.dispose(); self.env = None

    def _initialize(self, inst, cols, log_path, mip_gap):
        import gurobipy as gp
        c, au, bu, ae, be, bounds, off, n, T, R, cc = master._build_lp(
            inst, cols, True, soc_mode="cyclic")
        self.env = gp.Env(empty=True)
        self.env.setParam("OutputFlag", int(log_path is not None))
        self.env.setParam("LogToConsole", 0)
        if log_path is not None: self.env.setParam("LogFile", str(log_path))
        self.env.start()
        self.model = gp.Model("persistent_rmp", env=self.env)
        m = self.model
        m.Params.Threads = 1; m.Params.Seed = 0; m.Params.Method = -1
        m.Params.LPWarmStart = 1
        m.Params.MIPGap = mip_gap
        m.Params.FeasibilityTol = 1e-8; m.Params.OptimalityTol = 1e-8
        m.Params.IntFeasTol = 1e-8
        lb = np.asarray([0.0 if lo is None else lo for lo, hi in bounds])
        ub = np.asarray([np.inf if hi is None else hi for lo, hi in bounds])
        variables = m.addMVar(len(c), lb=lb, ub=ub, obj=c, name="v")
        eq = m.addMConstr(sparse.csr_matrix(ae), variables, "=", be, name="eq")
        le = m.addMConstr(sparse.csr_matrix(au), variables, "<", bu, name="ub")
        m.update()
        self.eq = list(eq.tolist()); self.le = list(le.tolist())
        native_vars = list(variables.tolist())
        self.route_vars = native_vars[:R]; self.shared_vars = native_vars[R:]
        self.shared_bounds = list(bounds[R:]); self.cc_start = cc
        self.cols = list(cols); self.fingerprints = [column_fingerprint(c) for c in cols]
        self.instance = inst

    def _append(self, inst, cols, restore_basis=True):
        import gurobipy as gp
        if inst is not self.instance:
            raise ValueError("A persistent model cannot change instance")
        if len(cols) < len(self.cols):
            raise ValueError("Persistent RMP requires append-only route pools")
        # Validate values, not only object identity: altered earlier columns must
        # never silently retain old coefficients in the persistent model.
        for old, expected, supplied in zip(self.cols, self.fingerprints, cols):
            if old is not supplied or column_fingerprint(supplied) != expected:
                raise ValueError("Existing route column changed or was reordered")
        new = cols[len(self.cols):]
        _validate_scope(inst, new)
        for col in new:
            rows = []; values = []
            for i in np.flatnonzero(col.a):
                rows.append(self.eq[int(i)]); values.append(float(col.a[i]))
            for t in np.flatnonzero(col.e):
                rows.append(self.le[int(t)]); values.append(float(col.e[t]))
            if self.cc_start is not None:
                for t in np.flatnonzero(np.asarray(col.e) > 1e-9):
                    rows.append(self.le[self.cc_start+int(t)])
                    values.append(float(col.e[t]))
            self.route_vars.append(self.model.addVar(lb=0.0, ub=gp.GRB.INFINITY,
                obj=col.cost(inst.eps_pen), vtype=gp.GRB.CONTINUOUS,
                column=gp.Column(values, rows), name=f"route_{len(self.cols)}"))
            self.cols.append(col); self.fingerprints.append(column_fingerprint(col))
        self.model.update()
        # Coefficient-only smoke checks use this private path before any solve.
        # Production solve() always requests basis restoration.
        if not restore_basis:
            return len(new)
        if self.basis is None:
            raise ValueError("Prior optimal RMP did not provide a reusable simplex basis")
        vb, cb = self.basis
        if len(cb) != self.model.NumConstrs or len(vb)+len(new) != self.model.NumVars:
            raise AssertionError("Unexpected matrix size while extending basis")
        self.model.setAttr("VBasis", self.model.getVars(), vb+[-1]*len(new))
        self.model.setAttr("CBasis", self.model.getConstrs(), cb)
        self.model.update(); self.basis_restorations += 1
        return len(new)

    def canonical_model_check(self, inst, cols):
        """Independent coefficient comparison for smoke/audit, never timed arms."""
        if self.model is None: raise ValueError("No live model")
        c, au, bu, ae, be, bounds, off, n, T, R, cc = master._build_lp(
            inst, cols, True, soc_mode="cyclic")
        order = np.asarray([v.index for v in self.route_vars+self.shared_vars])
        actual = self.model.getA()[:, order]
        expected = sparse.vstack([sparse.csr_matrix(ae), sparse.csr_matrix(au)])
        difference = actual-expected
        residuals = {
            "matrix": float(np.max(np.abs(difference.data), initial=0.0)),
            "objective": float(np.max(np.abs(np.asarray(self.model.getAttr("Obj"))[order]-c), initial=0.0)),
            "rhs": float(np.max(np.abs(np.asarray(self.model.getAttr("RHS"))-np.r_[be, bu]), initial=0.0)),
            "lower_bounds": float(np.max(np.abs(np.asarray(self.model.getAttr("LB"))[order]
                -np.asarray([0.0 if lo is None else lo for lo, hi in bounds])), initial=0.0)),
        }
        expected_ub = np.asarray([np.inf if hi is None else hi for lo, hi in bounds])
        actual_ub = np.asarray(self.model.getAttr("UB"))[order]
        finite = np.isfinite(expected_ub)
        residuals["upper_bounds"] = float(np.max(np.abs(actual_ub[finite]-expected_ub[finite]), initial=0.0))
        senses = self.model.getAttr("Sense")
        structure = bool(cc == self.cc_start and senses == ["="]*len(be)+["<"]*len(bu)
                         and np.all(actual_ub[~finite] >= 1e100))
        return {"passed": structure and max(residuals.values()) == 0.0,
                "residuals": residuals, "structure": structure,
                "variables": len(c), "constraints": len(be)+len(bu)}

    def solve(self, inst, cols, integer, time_limit, log_path, threads=1, mip_gap=1e-6):
        started = time.perf_counter()
        if integer or threads != 1 or not np.isfinite(time_limit) or time_limit <= 0:
            raise ValueError("Only one-thread LPs with a positive finite allowance are supported")
        if not np.isfinite(mip_gap) or mip_gap != 1e-6:
            raise ValueError("Preserve the frozen adapter's default MIPGap parameter")
        import gurobipy as gp
        from gurobipy import GRB
        _validate_scope(inst, [])
        if log_path is not None:
            log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
        initial = self.model is None
        if initial:
            _validate_scope(inst, cols)
            self._initialize(inst, cols, log_path, mip_gap); added = len(cols)
        else:
            self.model.Params.LogFile = str(log_path) if log_path is not None else ""
            self.model.Params.OutputFlag = int(log_path is not None)
            added = self._append(inst, cols)
        m = self.model; self.calls += 1
        built = time.perf_counter(); remaining = time_limit-(built-started)
        R = len(cols); n = inst.n_trips; T = inst.T
        diag = {"method": "restricted_master_lp", "integer": False, "columns": R,
            "time_limit_seconds": float(time_limit), "objective": None, "bound": None,
            "gap": None, "solution_count": 0, "threads": 1, "seed": 0,
            "mip_gap_tolerance": float(mip_gap), "validation": None,
            "usable_optimal_lp": False, "solver_version": list(gp.gurobi.version()),
            "model_build_seconds": built-started, "solver_budget_seconds": max(0.0, remaining),
            "variables": m.NumVars, "constraints": m.NumConstrs, "nonzeros": m.NumNZs,
            "integer_variables": m.NumIntVars, "binary_variables": m.NumBinVars,
            "persistent_model": True, "initial_model_build": initial,
            "columns_added": added, "explicit_basis_restored": not initial,
            "basis_restoration_count": self.basis_restorations,
            "gurobi_method": m.Params.Method, "lp_warm_start": m.Params.LPWarmStart,
            "log_path": str(log_path.resolve()) if log_path is not None else None}
        if remaining <= 0:
            diag.update(status="budget_exhausted_before_optimize", native_status=None,
                solve_seconds=0.0, total_seconds=time.perf_counter()-started)
            return _empty_solution(inst, R, False, diag["status"]), diag
        m.Params.TimeLimit = remaining
        solve_start = time.perf_counter(); m.optimize(); stopped = time.perf_counter()
        names = {GRB.OPTIMAL: "optimal", GRB.INFEASIBLE: "infeasible",
            GRB.INF_OR_UNBD: "infeasible_or_unbounded", GRB.UNBOUNDED: "unbounded",
            GRB.TIME_LIMIT: "time_limit", GRB.INTERRUPTED: "interrupted",
            GRB.NUMERIC: "numeric", GRB.SUBOPTIMAL: "suboptimal"}
        status = names.get(m.Status, f"status_{m.Status}")
        diag.update(status=status, native_status=m.Status, solution_count=m.SolCount,
            solve_seconds=stopped-solve_start, solver_runtime_seconds=float(m.Runtime),
            solve_end_to_end_seconds=stopped-started, node_count=float(m.NodeCount),
            iterations=float(m.IterCount))
        try: diag["solver_peak_memory_gb"] = float(m.MaxMemUsed)
        except (AttributeError, gp.GurobiError): diag["solver_peak_memory_gb"] = None
        solution = _empty_solution(inst, R, False, status)
        if m.SolCount:
            vec = np.asarray(m.getAttr("X", self.route_vars+self.shared_vars))
            _, oX, oG, oC, oD, oS, oNb, _ = master._layout(inst, R)
            offsets = (oX, oG, oC, oD, oS, oNb)
            bounds = [(0, None)]*R+self.shared_bounds
            diag["objective"] = float(m.ObjVal)
            diag["validation"] = replay_rmp(inst, cols, vec, offsets, bounds, False, m.ObjVal)
            if m.Status == GRB.OPTIMAL:
                ep = np.asarray(m.getAttr("Pi", self.eq)); ip = np.asarray(m.getAttr("Pi", self.le))
                nu = -ip[self.cc_start:self.cc_start+T] if self.cc_start is not None else np.zeros(T)
                solution = RMPSolution("optimal", float(m.ObjVal), vec[:R], vec[oG:oG+T],
                    ep[:n], -ip[:T], False, float(vec[oNb]), vec[oC:oC+T], vec[oD:oD+T], nu)
                solution.soc = vec[oS:oS+T+1]
                self.basis = (list(m.getAttr("VBasis")), list(m.getAttr("CBasis")))
                diag.update(usable_optimal_lp=True, bound=float(m.ObjVal), gap=0.0,
                    basis_available=True, basis_basic_variables=sum(v == 0 for v in self.basis[0]))
        solution.native_status = m.Status; solution.solver_bound = diag["bound"]
        solution.solver_gap = diag["gap"]
        diag["validation_seconds"] = time.perf_counter()-stopped
        diag["total_seconds"] = time.perf_counter()-started
        return solution, diag
