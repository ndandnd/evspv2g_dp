"""Append-only Gurobi deterministic LP with full identity guards.

Usage: with PersistentGurobiMaster(inst, ...) as session: sol = session.solve(cols)
Pass inst=inst on solve to assert an external instance is the same configuration.
An appended column changes only its coverage, balance, charging-cap and fleet
coefficients. Storage variables/rows remain resident; Gurobi retains its basis.
"""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
from time import perf_counter
import numpy as np
from scipy import sparse
import master
from gurobi_master import build_native, extract_native


def _identity_value(value):
    if isinstance(value, np.ndarray):
        return {"dtype":str(value.dtype), "shape":list(value.shape), "values":value.tolist()}
    if isinstance(value, np.generic):
        return value.item()
    if is_dataclass(value):
        return _identity_value(asdict(value))
    if isinstance(value, dict):
        return {str(k):_identity_value(v) for k,v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_identity_value(v) for v in value]
    return value


def configuration_key(inst, battery_allowed, soc_mode):
    """Includes every instance field, physics, demand/solar and coverage convention."""
    value = [vars(inst), bool(battery_allowed), soc_mode, bool(master.COVERING)]
    return sha256(json.dumps(_identity_value(value), sort_keys=True, separators=(",", ":"),
                             allow_nan=True).encode()).hexdigest()


def column_key(col):
    """All matrix/objective data; distinct injection profiles must not be deduplicated."""
    h = sha256(str(col.kind).encode())
    for a in (col.a, col.e, [col.fixed_cost]):
        a = np.asarray(a, dtype="<f8")
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


class PersistentGurobiMaster:
    def __init__(self, inst, battery_allowed=True, soc_mode="cyclic", threads=1):
        started = perf_counter()
        self.inst = inst
        self.battery_allowed, self.soc_mode = battery_allowed, soc_mode
        self.configuration_identity = configuration_key(inst, battery_allowed, soc_mode)
        self.static = master.canonical_model(inst, [], battery_allowed, soc_mode)
        self.model, self.static_vars, self.eq, self.ub = build_native(self.static, threads=threads)
        self.route_vars = []
        self.keys, self.costs = [], []
        self.route_eq = sparse.csr_matrix((self.static.Aeq.shape[0], 0))
        self.route_ub = sparse.csr_matrix((self.static.Aub.shape[0], 0))
        self.build_seconds = perf_counter() - started
        self.closed = False
        self.solve_count = 0
        self.last_timings = None

    def _guard(self, cols, inst):
        if self.closed:
            raise RuntimeError("persistent master is closed")
        if configuration_key(inst, self.battery_allowed, self.soc_mode) != self.configuration_identity:
            raise ValueError("persistent master configuration changed; construct a new session")
        if configuration_key(self.inst, self.battery_allowed, self.soc_mode) != self.configuration_identity:
            raise ValueError("persistent master's original instance was mutated")
        if len(cols) < len(self.keys):
            raise ValueError("persistent pool removed columns; construct a new session")
        keys = [column_key(col) for col in cols]
        if keys[:len(self.keys)] != self.keys:
            raise ValueError("persistent pool changed/reordered an existing column")
        for col in cols[len(self.keys):]:
            if (np.shape(col.a) != (self.static.n,) or np.shape(col.e) != (self.static.T,)
                or not np.all(np.isfinite(col.a)) or not np.all(np.isfinite(col.e))
                or not np.isfinite(col.cost(inst.eps_pen))):
                raise ValueError("invalid appended column dimensions or coefficients")
        return keys

    def _append(self, cols, keys):
        import gurobipy as gp
        start = len(self.keys)
        addition = cols[start:]
        if not addition:
            return
        ne, nu = self.static.Aeq.shape[0], self.static.Aub.shape[0]
        ae = sparse.lil_matrix((ne, len(addition)))
        au = sparse.lil_matrix((nu, len(addition)))
        for j, col in enumerate(addition):
            a, e = np.asarray(col.a), np.asarray(col.e)
            ae[:self.static.n, j] = a.reshape(-1, 1)
            au[:self.static.T, j] = e.reshape(-1, 1)
            if self.static.cc_start is not None:
                cc = self.static.cc_start
                au[cc:cc+self.static.T, j] = np.maximum(e, 0).reshape(-1, 1)
            if self.static.fleet_row is not None and col.kind == "truck":
                au[self.static.fleet_row, j] = 1.0
        ae, au = ae.tocsc(), au.tocsc()
        for j, col in enumerate(addition):
            coeffs, constraints = [], []
            for matrix, rows in ((ae, self.eq), (au, self.ub)):
                lo, hi = matrix.indptr[j:j+2]
                coeffs.extend(matrix.data[lo:hi].tolist())
                constraints.extend(rows[int(k)] for k in matrix.indices[lo:hi])
            cost = float(col.cost(self.inst.eps_pen))
            var = self.model.addVar(lb=0.0, obj=cost, column=gp.Column(coeffs, constraints),
                                    name=f"route_{start+j}")
            self.route_vars.append(var)
            self.costs.append(cost)
        self.route_eq = sparse.hstack((self.route_eq, ae), format="csr")
        self.route_ub = sparse.hstack((self.route_ub, au), format="csr")
        self.keys = keys
        self.model.update()

    def canonical_form(self):
        """Sparse reference in legacy route-first variable order; no dense rebuilding."""
        st, r = self.static, len(self.keys)
        return master.CanonicalRMP(np.r_[self.costs, st.c],
            sparse.hstack((self.route_ub, st.Aub), format="csr"), st.bub,
            sparse.hstack((self.route_eq, st.Aeq), format="csr"), st.beq,
            [(0, None)]*r + st.bounds, (0, *(j+r for j in st.off[1:])),
            st.n, st.T, r, st.cc_start, st.fleet_row)

    def solve(self, cols, inst=None):
        started = perf_counter()
        keys = self._guard(cols, self.inst if inst is None else inst)
        guarded = perf_counter()
        self._append(cols, keys)
        appended = perf_counter()
        self.model.optimize()
        solved = perf_counter()
        form = self.canonical_form()
        sol = extract_native(self.model, form, self.route_vars + self.static_vars, self.eq, self.ub)
        done = perf_counter()
        self.last_timings = dict(build_seconds=self.build_seconds if self.solve_count == 0 else 0.0,
            identity_seconds=guarded-started, append_seconds=appended-guarded,
            solve_seconds=solved-appended, solver_runtime_seconds=float(self.model.Runtime),
            validation_seconds=done-solved, rows=len(self.eq)+len(self.ub),
            columns=len(form.c), route_columns=len(self.keys))
        sol.timings = self.last_timings.copy()
        self.solve_count += 1
        return sol

    def close(self):
        if not self.closed:
            self.model.dispose()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
