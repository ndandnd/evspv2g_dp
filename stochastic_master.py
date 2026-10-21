"""Sparse common-profile stochastic LPs with optional persistent Gurobi solves.

The first stage contains truck weights, battery count, and common initial battery
SoC. Generation and BESS dispatch are scenario recourse. Tuple builders preserve
campaign worker ordering; probabilities enter objectives, never dual aggregation.
"""
from __future__ import annotations

import hashlib
import time

import numpy as np
from scipy.optimize import OptimizeResult, linprog
from scipy.sparse import coo_matrix, csr_matrix, hstack


def _frozen(value):
    if isinstance(value, np.ndarray):
        a = np.ascontiguousarray(value)
        return ("array", a.dtype.str, a.shape, a.tobytes())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return tuple(sorted((k, _frozen(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_frozen(v) for v in value)
    if hasattr(value, "__dict__"):
        return (type(value).__name__, _frozen(vars(value)))
    return value


def _identity(value):
    return hashlib.sha256(repr(_frozen(value)).encode()).hexdigest()


def _column_identity(col):
    return _identity((col.kind, np.asarray(col.a), np.asarray(col.e), col.fixed_cost))


def _matrix(rows, columns, values, shape):
    result = coo_matrix((values, (rows, columns)), shape=shape).tocsr()
    result.eliminate_zeros()
    return result


def _weights(value, count):
    # Preserve the release worker's evaluation convention: a different number
    # of scenarios (notably one held-out day) receives uniform probabilities.
    w = np.full(count, 1 / count) if value is None else np.asarray(value, dtype=float)
    if w.ndim != 1:
        raise ValueError("weights must be one-dimensional")
    if len(w) != count:
        w = np.full(count, 1 / count)
    if not np.all(np.isfinite(w)) or not np.all(w > 0) or abs(w.sum() - 1) >= 1e-10:
        raise ValueError("scenario probabilities must be positive and sum to one")
    return w.copy()


class StructuralMutationError(ValueError):
    """A persistent model cannot silently reuse changed physical/model inputs."""


class StochasticTemplate:
    """Immutable sparse recourse template, reusable across appended truck pools.

    Instances must have identical truck physics/trips and first-stage costs;
    scenario Delta and recourse caps may differ. The equality coverage model is
    explicit here and does not depend on the mutable master.COVERING switch.
    """

    def __init__(self, instances, *, battery_allowed=True, weights=None,
                 method="saa", soc_mode="cyclic"):
        start = time.perf_counter()
        self.instances = tuple(instances)
        if not self.instances:
            raise ValueError("at least one scenario is required")
        if method not in {"saa", "mean", "minimax"}:
            raise ValueError("method must be saa, mean, or minimax")
        if soc_mode not in {"cyclic", "periodic", "free"}:
            raise ValueError("unsupported stationary battery boundary")
        self.battery_allowed, self.method, self.soc_mode = bool(battery_allowed), method, soc_mode
        self.S = len(self.instances)
        self.weights = _weights(weights, self.S)
        first = self.instances[0]
        self.T, self.n = int(first.T), int(first.n_trips)
        if self.T <= 0:
            raise ValueError("T must be positive")
        scalars = [first.G, first.rho, first.eta, first.c_g, first.c_v,
                   first.c_b, first.eps_pen, first.deg_cost]
        if not np.isfinite(scalars).all() or first.G < 0 or first.rho < 0 or not 0 <= first.eta < 1:
            raise ValueError("invalid battery physics or cost coefficients")
        common = ("T", "trips", "dist", "G", "rho", "eta", "energy_per_dist", "c_g",
                  "c_v", "c_b", "eps_pen", "deg_cost", "depot", "soc_step", "stations")
        expected = _identity({k: getattr(first, k, None) for k in common})
        for inst in self.instances:
            if _identity({k: getattr(inst, k, None) for k in common}) != expected:
                raise ValueError("scenarios must share trip physics and cost coefficients")
            if np.asarray(inst.Delta).shape != (self.T,) or not np.isfinite(inst.Delta).all():
                raise ValueError("each Delta must be finite and have length T")
            gc = np.broadcast_to(np.asarray(inst.gen_cap, dtype=float), (self.T,))
            caps = np.r_[gc, inst.charge_cap, inst.fuel_budget, inst.max_trucks]
            nbf = getattr(inst, "nb_fixed", -1.)
            if nbf is not None and not np.isfinite(nbf):
                raise ValueError("nb_fixed must be finite or None")
            if np.isnan(caps).any() or (caps < 0).any():
                raise ValueError("caps must be nonnegative and not NaN")
        self.eps = float(first.eps_pen)
        self._input_identity = self._current_identity()
        self.identity = self._input_identity
        self._build_static()
        self.stats = {"template_build_seconds": time.perf_counter() - start,
                      "template_builds": 1, "pool_builds": 0,
                      "scenario_count": self.S, "static_variables": len(self._c),
                      "static_ub_nnz": self._au.nnz, "static_eq_nnz": self._ae.nnz}

    def _current_identity(self):
        return _identity((self.instances, self.battery_allowed, self.weights,
                          self.method, self.soc_mode))

    def assert_unchanged(self):
        if self._current_identity() != self._input_identity:
            raise StructuralMutationError("stochastic template inputs changed; construct a new template")

    def _build_static(self):
        T, S, n = self.T, self.S, self.n
        nv = 2 + S * 4 * T + int(self.method == "minimax")
        c = np.zeros(nv); lb = np.zeros(nv); ub = np.full(nv, np.inf)
        c[0] = self.instances[0].c_b
        if self.method == "minimax":
            c[-1] = 1
        ur, uc, uv, er, ec, ev = [], [], [], [], [], []
        bu, be, meta, fleet_rows = [], [], [], []
        def u(row, col, value):
            if value: ur.append(row); uc.append(col); uv.append(value)
        def e(row, col, value):
            if value: er.append(row); ec.append(col); ev.append(value)
        for s, inst in enumerate(self.instances):
            G, rho = (inst.G, inst.rho) if self.battery_allowed else (0., 0.)
            g = 2 + s * 4 * T; ch = g + T; dis = g + 2 * T; soc = g + 3 * T
            state = lambda t: 1 if t == 0 else soc + t - 1
            charge_active = bool(np.isfinite(inst.charge_cap))
            fuel_active, fleet_active = np.isfinite(inst.fuel_budget), np.isfinite(inst.max_trucks)
            us = len(bu); es = len(be)
            nr = 4 * T + 1 + (T if charge_active else 0)
            rhs = np.zeros(nr + int(fuel_active) + int(fleet_active)); rhs[:T] = -inst.Delta
            eqcount = T + 1 + (n if s == 0 else 0)
            nbf = getattr(inst, "nb_fixed", -1.)
            has_fixed_nb = nbf is not None and nbf >= 0
            eqrhs = np.zeros(eqcount + int(has_fixed_nb))
            if s == 0: eqrhs[:n] = 1
            dynamics = es + (n if s == 0 else 0)
            for t in range(T):
                u(us + t, g + t, -1); u(us + t, ch + t, 1); u(us + t, dis + t, -1)
                e(dynamics + t, state(t + 1), 1); e(dynamics + t, state(t), -1)
                e(dynamics + t, ch + t, -(1 - inst.eta)); e(dynamics + t, dis + t, 1)
            if self.soc_mode == "free":
                e(dynamics + T, 1, 1); e(dynamics + T, 0, -G)
            else:
                e(dynamics + T, state(T), 1); e(dynamics + T, 1, -1)
            for t in range(T + 1):
                u(us + T + t, state(t), 1); u(us + T + t, 0, -G)
            for t in range(T):
                u(us + 2*T + 1 + t, ch + t, 1); u(us + 2*T + 1 + t, 0, -rho)
                u(us + 3*T + 1 + t, dis + t, 1); u(us + 3*T + 1 + t, 0, -rho)
            cap = us + 4*T + 1 if charge_active else None
            if charge_active:
                for t in range(T): u(cap + t, ch + t, 1)
                rhs[4*T + 1:5*T + 1] = inst.charge_cap
            extra = nr
            if fuel_active:
                for t in range(T): u(us + extra, g + t, 1)
                rhs[extra] = inst.fuel_budget; extra += 1
            if fleet_active:
                fleet_rows.append(us + extra); rhs[extra] = inst.max_trucks
            if has_fixed_nb:
                e(es + eqcount, 0, 1); eqrhs[-1] = nbf
            ub[g:g + T] = np.broadcast_to(np.asarray(inst.gen_cap, float), (T,))
            if self.method != "minimax":
                c[g:g + T] = inst.c_g * self.weights[s]
                c[ch:ch + T] = inst.eps_pen * self.weights[s]
                c[dis:dis + T] = (inst.eps_pen + inst.deg_cost) * self.weights[s]
            meta.append(dict(balance=us, cap=cap)); bu.extend(rhs); be.extend(eqrhs)
        if self.method == "minimax":
            for s, inst in enumerate(self.instances):
                row = len(bu); base = 2 + s * 4*T
                for t in range(T):
                    u(row, base+t, inst.c_g); u(row, base+T+t, inst.eps_pen)
                    u(row, base+2*T+t, inst.eps_pen + inst.deg_cost)
                u(row, nv-1, -1); bu.append(0.)
        self._c, self._lb, self._ub = c, lb, ub
        self._au = _matrix(ur, uc, uv, (len(bu), nv))
        self._ae = _matrix(er, ec, ev, (len(be), nv))
        self._bu, self._be = np.asarray(bu), np.asarray(be)
        self.meta, self.fleet_rows = meta, tuple(fleet_rows)

    def _route_block(self, cols, *, phase=False):
        ur, uc, uv, er, ec, ev = [], [], [], [], [], []
        costs = []
        for j, col in enumerate(cols):
            a, energy = np.asarray(col.a, float), np.asarray(col.e, float)
            if a.shape != (self.n,) or energy.shape != (self.T,):
                raise ValueError("column dimensions differ from template")
            if not np.isfinite(a).all() or not np.isfinite(energy).all() or not np.isfinite(col.fixed_cost):
                raise ValueError("column coefficients and cost must be finite")
            cost = float(col.kind == "artificial") if phase else float(col.cost(self.eps))
            costs.append(cost)
            for i in np.flatnonzero(a): er.append(int(i)); ec.append(j); ev.append(a[i])
            for md in self.meta:
                for t in np.flatnonzero(energy):
                    ur.append(md["balance"] + int(t)); uc.append(j); uv.append(energy[t])
                if md["cap"] is not None:
                    for t in np.flatnonzero(energy > 0):
                        ur.append(md["cap"] + int(t)); uc.append(j); uv.append(energy[t])
            if col.kind == "truck":
                for row in self.fleet_rows: ur.append(row); uc.append(j); uv.append(1.)
        return (np.asarray(costs), _matrix(ur, uc, uv, (len(self._bu), len(cols))),
                _matrix(er, ec, ev, (len(self._be), len(cols))))

    def build(self, cols, fixed=None, *, phase_cap=None, forbid_artificials=False):
        start = time.perf_counter(); self.assert_unchanged(); cols = tuple(cols); R = len(cols)
        rc, ru, re = self._route_block(cols, phase=phase_cap is not None)
        c = np.r_[rc, self._c]; au = hstack([ru, self._au], format="csr")
        ae = hstack([re, self._ae], format="csr")
        lb, ub = np.r_[np.zeros(R), self._lb], np.r_[np.full(R, np.inf), self._ub]
        if forbid_artificials:
            for r, col in enumerate(cols):
                if col.kind == "artificial": ub[r] = 0
        if fixed is not None:
            f = np.asarray(fixed, dtype=float)
            if f.shape != (R + 2,) or not np.isfinite(f).all() or (f < 0).any():
                raise ValueError("fixed must contain nonnegative finite [x..., Nb, s0]")
            lb[:R+2] = f; ub[:R+2] = f
            if forbid_artificials and any(col.kind == "artificial" and f[r] != 0 for r, col in enumerate(cols)):
                raise ValueError("fixed artificial conflicts with forbid_artificials")
        if phase_cap is not None:
            cap = np.asarray(phase_cap, dtype=float)
            try: cap = np.broadcast_to(cap, (self.S, self.T))
            except ValueError as exc: raise ValueError("phase_cap must broadcast to (S,T)") from exc
            if np.isnan(cap).any() or (cap < 0).any(): raise ValueError("invalid Phase-I generation cap")
            for s in range(self.S): ub[R+2+s*4*self.T:R+2+s*4*self.T+self.T] = cap[s]
            extra = self.S * self.T
            rows = np.concatenate([np.arange(md["balance"], md["balance"]+self.T) for md in self.meta])
            elast = _matrix(rows, np.arange(extra), -np.ones(extra), (len(self._bu), extra))
            c = np.r_[rc, np.zeros(len(self._c)), np.full(extra, 1/self.S)]
            au = hstack([au, elast], format="csr"); ae = hstack([ae, csr_matrix((len(self._be), extra))], format="csr")
            lb = np.r_[lb, np.zeros(extra)]; ub = np.r_[ub, np.full(extra, np.inf)]
        self.stats["pool_builds"] += 1
        self.stats["last_pool_build_seconds"] = time.perf_counter()-start
        self.stats["last_columns"] = R
        return c, au, self._bu.copy(), ae, self._be.copy(), lb, ub, [dict(md) for md in self.meta]

    def pricing_duals(self, result):
        """Sum raw scenario row duals; probability weighting already happened."""
        dual = np.asarray(result.ineqlin.marginals)
        mu, nu = np.zeros(self.T), np.zeros(self.T)
        for md in self.meta:
            mu -= dual[md["balance"]:md["balance"]+self.T]
            if md["cap"] is not None: nu -= dual[md["cap"]:md["cap"]+self.T]
        return dict(alpha=np.asarray(result.eqlin.marginals[:self.n]), mu=mu, nu=nu,
                    fleet_price=-float(sum(dual[row] for row in self.fleet_rows)))

    def reduced_cost(self, col, result, *, phase=False):
        d = self.pricing_duals(result)
        cost = float(col.kind == "artificial") if phase else col.cost(self.eps)
        return float(cost - np.asarray(col.a) @ d["alpha"] + np.asarray(col.e) @ d["mu"]
                     + np.where(np.asarray(col.e) > 0, col.e, 0) @ d["nu"]
                     + (d["fleet_price"] if col.kind == "truck" else 0))


def default_instance(cfg, delta):
    """Reproduce the release worker using this candidate's own model modules."""
    from recreate_arxiv import build_instance, BREAKS2
    from profile_robustness import base_curves
    inst = build_instance(cfg["points"], 2., BREAKS2, delta_hourly=delta)
    inst.rho = 1.75; inst.soc_step = .25; inst.c_g = 40.
    if "cap_factor" in cfg:
        demand, _ = base_curves(); inst.gen_cap = float(cfg["cap_factor"] * np.max(demand) / 2)
    return inst


def _configured_template(cfg, deltas, instance_factory, method):
    from colgen import SCENARIOS
    factory = instance_factory or default_instance
    return StochasticTemplate([factory(cfg, d) for d in deltas],
                              battery_allowed=SCENARIOS[cfg["arm"]]["battery"],
                              weights=cfg.get("weights"), method=method)


def _use_template(cfg, deltas, factory, method, template):
    if template is None:
        return _configured_template(cfg, deltas, factory, method)
    from colgen import SCENARIOS
    template.assert_unchanged()
    instances = tuple((factory or default_instance)(cfg, d) for d in deltas)
    expected = _identity((instances, bool(SCENARIOS[cfg["arm"]]["battery"]),
                          _weights(cfg.get("weights"), len(instances)), method, "cyclic"))
    if expected != template.identity:
        raise StructuralMutationError("supplied template differs from cfg/scenario identity")
    return template


def expected_model(cfg, deltas, cols, fixed=None, *, instance_factory=None, template=None):
    t = _use_template(cfg, deltas, instance_factory, "saa", template)
    if t.method == "minimax": raise ValueError("expected_model needs an expected-cost template")
    return t.build(cols, fixed)


def model(cfg, deltas, cols, fixed=None, *, instance_factory=None, template=None):
    t = _use_template(cfg, deltas, instance_factory, cfg.get("method", "saa"), template)
    return t.build(cols, fixed)


def phase_model(cfg, deltas, cols, cap, *, instance_factory=None, template=None):
    t = _use_template(cfg, deltas, instance_factory, cfg.get("method", "saa"), template)
    return t.build(cols, phase_cap=cap)


def lp(m, **options):
    c, au, bu, ae, be, lb, ub, _ = m
    return linprog(c, A_ub=au, b_ub=bu, A_eq=ae, b_eq=be,
                   bounds=list(zip(lb, ub)), method="highs", options=options or None)


class PersistentStochasticLP:
    """Append-only Gurobi LP; tuple-order solution/duals match the sparse builder.

    Create a new session for Phase-I/economic transitions or changed fixed
    commitments. Gurobi is imported only when this optional adapter is used.
    """

    def __init__(self, template, cols=(), *, fixed=None, phase_cap=None,
                 forbid_artificials=False, threads=1, time_limit=None, output_flag=0):
        import gurobipy as gp
        start = time.perf_counter()
        self.template = template; self.gp = gp; self.cols = []; self._signatures = []
        self.fixed = None if fixed is None else np.array(fixed, dtype=float, copy=True)
        self.phase_cap = None if phase_cap is None else np.array(phase_cap, dtype=float, copy=True)
        self.forbid_artificials = bool(forbid_artificials)
        self._settings = _identity((self.fixed, self.phase_cap, self.forbid_artificials))
        initial = tuple(cols)
        if self.fixed is not None:
            if self.fixed.shape != (len(initial)+2,) or not np.isfinite(self.fixed).all() or (self.fixed < 0).any():
                raise ValueError("fixed commitments must be finite, nonnegative [x..., Nb, s0]")
            if self.forbid_artificials and any(c.kind == "artificial" and self.fixed[i] != 0 for i,c in enumerate(initial)):
                raise ValueError("fixed artificial conflicts with forbid_artificials")
        m = template.build([], phase_cap=self.phase_cap)
        self._static_c, self._static_au, self.bu, self._static_ae, self.be, lo, hi, self.meta = m
        if self.fixed is not None:
            lo[:2] = self.fixed[-2:]; hi[:2] = self.fixed[-2:]
        self.model = gp.Model("stochastic_rmp")
        self.model.Params.OutputFlag = output_flag; self.model.Params.Threads = threads
        self.model.Params.Method = 1
        self.model.Params.OptimalityTol = 1e-8; self.model.Params.FeasibilityTol = 1e-8
        if time_limit is not None: self.model.Params.TimeLimit = time_limit
        self._static = [self.model.addVar(lb=float(l), ub=float(u), obj=float(c), name=f"recourse_{i}")
                        for i, (l,u,c) in enumerate(zip(lo,hi,self._static_c))]
        self._urows, self._erows = [], []
        for matrix, rhs, sense, destination in [(self._static_au,self.bu,"<=",self._urows),
                                               (self._static_ae,self.be,"=",self._erows)]:
            for row in range(matrix.shape[0]):
                begin, end = matrix.indptr[row:row+2]
                expr = gp.LinExpr(matrix.data[begin:end].tolist(), [self._static[k] for k in matrix.indices[begin:end]])
                destination.append(self.model.addConstr(expr <= float(rhs[row]) if sense == "<=" else expr == float(rhs[row])))
        self._routes = []; self._ru = csr_matrix((len(self.bu),0)); self._re = csr_matrix((len(self.be),0))
        self._costs = np.empty(0); self._closed = False
        self.stats = {"model_build_seconds": time.perf_counter()-start, "sync_calls":0, "added_columns":0}
        try: self.sync(initial)
        except Exception: self.close(); raise

    def _guard(self):
        if self._closed: raise RuntimeError("persistent stochastic LP is closed")
        self.template.assert_unchanged()
        if _identity((self.fixed, self.phase_cap, self.forbid_artificials)) != self._settings:
            raise StructuralMutationError("fixed/phase settings changed; create a new LP session")

    def sync(self, cols):
        self._guard(); start = time.perf_counter(); cols = tuple(cols)
        signatures = [_column_identity(c) for c in cols]
        prefix = len(self.cols)
        if len(cols) < prefix or signatures[:prefix] != self._signatures:
            raise StructuralMutationError("route prefix changed; only append full columns")
        if self.fixed is not None and len(cols)+2 != len(self.fixed):
            raise StructuralMutationError("fixed commitments cannot be extended")
        # Validate and build the entire incoming batch before mutating Gurobi.
        cost, au, ae = self.template._route_block(cols[prefix:], phase=self.phase_cap is not None)
        au, ae = au.tocsc(), ae.tocsc()
        for j,col in enumerate(cols[prefix:]):
            ur = slice(au.indptr[j],au.indptr[j+1]); er = slice(ae.indptr[j],ae.indptr[j+1])
            constraints = [self._urows[k] for k in au.indices[ur]] + [self._erows[k] for k in ae.indices[er]]
            values = np.r_[au.data[ur], ae.data[er]].tolist()
            lo = 0.; hi = 0. if self.forbid_artificials and col.kind == "artificial" else np.inf
            if self.fixed is not None:
                lo = hi = float(self.fixed[prefix+j])
                if not np.isfinite(lo) or lo < 0 or (self.forbid_artificials and col.kind == "artificial" and lo != 0):
                    raise ValueError("invalid fixed route commitment")
            self._routes.append(self.model.addVar(lb=lo, ub=hi, obj=float(cost[j]),
                                                  column=self.gp.Column(values,constraints),name=f"route_{prefix+j}"))
        self._ru = hstack([self._ru,au],format="csr"); self._re = hstack([self._re,ae],format="csr")
        self._costs = np.r_[self._costs,cost]; self.cols = list(cols); self._signatures = signatures
        self.model.update(); self.stats["sync_calls"] += 1; self.stats["added_columns"] += len(cols)-prefix
        self.stats["last_sync_seconds"] = time.perf_counter()-start
        return len(cols)-prefix

    def solve(self, cols=None, *, time_limit=None):
        if cols is not None: self.sync(cols)
        self._guard()
        # Detect mutation of an already-added Column even without a new sync.
        if [_column_identity(c) for c in self.cols] != self._signatures:
            raise StructuralMutationError("an added column was mutated")
        if time_limit is not None: self.model.Params.TimeLimit = time_limit
        start = time.perf_counter(); self.model.optimize(); duration = time.perf_counter()-start
        self.stats["last_solve_seconds"] = duration
        optimal = self.model.Status == self.gp.GRB.OPTIMAL
        status = (0 if optimal else 2 if self.model.Status == self.gp.GRB.INFEASIBLE
                  else 3 if self.model.Status == self.gp.GRB.UNBOUNDED
                  else 1 if self.model.Status in {self.gp.GRB.TIME_LIMIT, self.gp.GRB.ITERATION_LIMIT}
                  else 4)
        out = OptimizeResult(success=optimal,status=status,message=f"Gurobi status {self.model.Status}",
                             solver_status=int(self.model.Status),fun=None,x=None,meta=self.meta)
        if optimal:
            xr = np.array([v.X for v in self._routes]); xs = np.array([v.X for v in self._static])
            x = np.r_[xr,xs]; variables = self._routes+self._static
            slack = self.bu-self._ru@xr-self._static_au@xs
            eqres = self.be-self._re@xr-self._static_ae@xs
            lower = x-np.array([v.LB for v in variables]); upper = np.array([v.UB for v in variables])-x
            violation = max(0.,float(np.max(-slack,initial=0)),float(np.max(np.abs(eqres),initial=0)),
                            float(np.max(-lower,initial=0)),float(np.max(-upper,initial=0)))
            objective = float(self._costs@xr+self._static_c@xs)
            if (not np.isfinite(x).all() or not np.isfinite(slack).all()
                    or not np.isfinite(eqres).all() or violation > 1e-6):
                raise RuntimeError(f"Gurobi stochastic LP failed residual validation: {violation}")
            if not np.isfinite(objective) or not np.isclose(objective,self.model.ObjVal,rtol=1e-9,atol=1e-6):
                raise RuntimeError("Gurobi stochastic LP objective differs from reconstructed objective")
            out.update(fun=objective,x=x,
                       ineqlin=OptimizeResult(marginals=np.array([r.Pi for r in self._urows]),residual=slack),
                       eqlin=OptimizeResult(marginals=np.array([r.Pi for r in self._erows]),residual=eqres),
                       lower=OptimizeResult(residual=lower),upper=OptimizeResult(residual=upper),
                       max_primal_violation=violation)
        return out

    def close(self):
        if not self._closed: self.model.dispose(); self._closed = True

    def __enter__(self): return self
    def __exit__(self,*_): self.close()
