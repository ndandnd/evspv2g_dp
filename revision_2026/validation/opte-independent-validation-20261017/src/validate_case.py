"""Stage 2 of the independent validation: schedules and bounds of one input.

Code independence. This process imports numpy, scipy (one small per-battery LP),
gurobipy (a vendor-master cross-check after all checks) and the original published
code in vendor/ (instance, master, colgen). It never imports arc_flow,
extension_models, column_witness, rmp_solver, phase_models, direct_mip_traced,
direct_mip_1000 or any runner; this is asserted at exit. The pricing-graph topology
is rebuilt here from the physical input, the saved vectors are decoded against it,
and every route is replayed against the vendor Instance's physical definitions
(task times/places/energy, deadhead time/energy, charging places and rate, SoC range).

Per input (stage-1 record from rebuild_input.py) and per saved arm directory:
  cg:     restricted-MIP vector restricted_primal.npz over cg_pool_columns.json.gz;
          stopping duals cg_stopping_primal.npz -> independent Lagrangian bound.
  direct: incumbent_XXX.npz chosen by the reading rule (best incumbent at or before
          each reading time) and the final direct_mip_primal.npz.
Gurobi ObjBound values are copied as solver evidence; they are not recomputed.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np

TOL = 1e-6
FORBIDDEN = ('arc_flow', 'extension_models', 'column_witness', 'rmp_solver', 'phase_models',
             'direct_mip_traced', 'direct_mip_1000', 'barrier_mip_solver', 'run_grid', 'run_transition',
             'run_task_scaling', 'run_equal_mip', 'followup_inputs', 'panel_instances')
WAIT, CHARGE, DISCHARGE, TRAVEL, TASK = range(5)
KINDS = ('wait', 'charge', 'discharge', 'travel', 'task')


class Fail(Exception):
    pass


def require(ok, msg):
    if not ok:
        raise Fail(msg)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def as_int(x, label, tol=1e-8):
    require(np.isfinite(x) and abs(x - round(x)) <= tol, f'{label} not integral: {x}')
    return int(round(x))


# ----------------------------------------------------------------------------- saved records
def load_result(path, skip=('cg_phase',)):
    """Top-level sections of a runner result.json, without parsing the (up to 2 GB) CG iteration log."""
    import mmap, re
    with open(path, 'rb') as fh:
        if Path(path).stat().st_size < 50_000_000:
            return json.loads(fh.read())
        m = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        keys = [(mt.start(), mt.end(), mt.group(1).decode()) for mt in re.finditer(rb'\n  "([A-Za-z0-9_]+)": ', m)]
        end = m.rfind(b'}')
        out = {}
        for (s0, s1, k), nxt in zip(keys, keys[1:] + [(end, end, None)]):
            if k in skip:
                out[k] = {'_skipped_by_validator': True}; continue
            raw = m[s1:nxt[0]].rstrip()
            if raw.endswith(b','):
                raw = raw[:-1]
            out[k] = json.loads(raw)
        m.close()
        return out


# ----------------------------------------------------------------------------- input
def instance_from_record(raw, V):
    require(raw['eta'] == 0 and raw['truck_boundary'] == 'full/full' and raw['stationary_boundary'] == 'periodic',
            'unsupported boundary/efficiency scope')
    require(raw['generation_cap'] == raw['charging_cap'] == 'unbounded', 'unsupported cap')
    delta = np.asarray(raw['Delta'], dtype=float)
    inst = V.Instance(T=raw['T'], D=np.maximum(delta, 0), P=np.maximum(-delta, 0),
                      trips=[V.Trip(**tr) for tr in raw['trips']], dist=np.asarray(raw['dist'], dtype=float),
                      G=raw['G'], rho=raw['rho'], eta=0, energy_per_dist=raw['energy_per_dist'],
                      c_g=raw['c_g'], c_v=raw['c_v'], c_b=raw['c_b'], eps_pen=raw['eps_pen'],
                      depot=raw['depot'], soc_step=raw['soc_step'], deg_cost=raw['deg_cost'],
                      stations=list(raw['charge_locations']))
    require(np.array_equal(inst.Delta, delta), 'Delta reconstruction')
    require(sorted(tr.idx for tr in inst.trips) == list(range(inst.n_trips)), 'task indices')
    require(all(inst.trips[i].idx == i for i in range(inst.n_trips)), 'task order')
    require(not np.isfinite(inst.gen_cap) and not np.isfinite(inst.charge_cap), 'caps must be unbounded')
    return inst


# ----------------------------------------------------------------------------- topology
class Topology:
    """States (t, loc, soc index, served) of the truck pricing DAG and its arcs.

    Transition set (rebuilt here, not imported): wait one block; charge/discharge
    d levels (1 <= d <= floor(rho/step)) for one block at a charging place; deadhead
    to another place (travel time and energy from dist); a task from its start place
    and time to its end place and time, using its energy and setting served = 1.
    States not on any source-sink path are removed. Arc order: by tail state, then
    wait, charge d = 1.., discharge d = 1.., travel by destination, tasks in input
    order -- the enumeration order of the original builder, so saved vectors can be
    decoded. A wrong order is caught by the flow-conservation and replay checks.
    """

    def __init__(self, inst):
        T = as_int(inst.T, 'T'); step = float(inst.soc_step)
        L = inst.dist.shape[0]
        Gidx = as_int(inst.G / step, 'G/step')
        rho_eff = math.floor(inst.rho / step) * step
        rate = as_int(rho_eff / step, 'rate')
        dt = np.zeros((L, L), dtype=np.int64); de = np.zeros((L, L), dtype=np.int64)
        for a in range(L):
            for b in range(L):
                dt[a, b] = as_int(inst.dist[a, b], 'travel time')
                de[a, b] = as_int(inst.dist[a, b] * inst.energy_per_dist / step, 'travel energy')
        shifts = np.array([as_int(tr.energy / step, 'task energy') for tr in inst.trips], dtype=np.int64)
        S = Gidx + 1
        self.T, self.L, self.S, self.Gidx, self.rate, self.step = T, L, S, Gidx, rate, step
        self.rho_eff = rho_eff
        node = lambda t, loc, s, k: ((t * L + loc) * S + s) * 2 + k
        station = np.zeros(L, dtype=bool); station[list(inst.charge_locs)] = True
        starts = {}
        for tr in inst.trips:
            starts.setdefault((int(tr.start), int(tr.sloc)), []).append(tr)
        LOC, SS, KK = [x.ravel() for x in np.meshgrid(np.arange(L), np.arange(S), np.arange(2), indexing='ij')]
        A, B = np.nonzero(~np.eye(L, dtype=bool))
        parts = []
        for t in range(T):
            tl, hl, rk, kd, tk, dv = [], [], [], [], [], []
            U = node(t, LOC, SS, KK)
            tl.append(U); hl.append(node(t + 1, LOC, SS, KK)); rk.append(np.zeros(len(U), np.int64))
            kd.append(np.full(len(U), WAIT, np.int8)); tk.append(np.full(len(U), -1, np.int64)); dv.append(np.zeros(len(U), np.int64))
            for d in range(1, rate + 1):
                m = station[LOC] & (SS + d <= Gidx)
                tl.append(U[m]); hl.append(node(t + 1, LOC[m], SS[m] + d, KK[m])); rk.append(np.full(m.sum(), d))
                kd.append(np.full(m.sum(), CHARGE, np.int8)); tk.append(np.full(m.sum(), -1)); dv.append(np.full(m.sum(), d))
            for d in range(1, rate + 1):
                m = station[LOC] & (SS - d >= 0)
                tl.append(U[m]); hl.append(node(t + 1, LOC[m], SS[m] - d, KK[m])); rk.append(np.full(m.sum(), rate + d))
                kd.append(np.full(m.sum(), DISCHARGE, np.int8)); tk.append(np.full(m.sum(), -1)); dv.append(np.full(m.sum(), -d))
            ok = t + dt[A, B] <= T
            a_, b_ = A[ok], B[ok]
            if len(a_):
                pa = np.repeat(a_, S * 2); pb = np.repeat(b_, S * 2)
                ps = np.tile(np.repeat(np.arange(S), 2), len(a_)); pk = np.tile(np.arange(2), S * len(a_))
                m = ps >= de[pa, pb]
                pa, pb, ps, pk = pa[m], pb[m], ps[m], pk[m]
                tl.append(node(t, pa, ps, pk)); hl.append(node(t + dt[pa, pb], pb, ps - de[pa, pb], pk))
                rk.append(2 * rate + 1 + pb); kd.append(np.full(len(pa), TRAVEL, np.int8)); tk.append(np.full(len(pa), -1)); dv.append(np.zeros(len(pa), np.int64))
            for loc in range(L):
                for j, tr in enumerate(starts.get((t, loc), ())):
                    sh = shifts[tr.idx]
                    s_ = np.repeat(np.arange(sh, S), 2); k_ = np.tile(np.arange(2), S - sh)
                    tl.append(node(t, loc, s_, k_)); hl.append(node(int(tr.end), int(tr.eloc), s_ - sh, 1))
                    rk.append(np.full(len(s_), 2 * rate + 1 + L + j)); kd.append(np.full(len(s_), TASK, np.int8))
                    tk.append(np.full(len(s_), tr.idx)); dv.append(np.zeros(len(s_), np.int64))
            tl = np.concatenate(tl); hl = np.concatenate(hl); rk = np.concatenate(rk)
            order = np.lexsort((rk, tl))
            parts.append((tl[order].astype(np.int64), hl[order].astype(np.int64), np.concatenate(kd)[order],
                          np.concatenate(tk)[order].astype(np.int32), np.concatenate(dv)[order].astype(np.int8)))
        n_states = (T + 1) * L * S * 2
        source = node(0, inst.depot, Gidx, 0); sink = node(T, inst.depot, Gidx, 1)
        reach = np.zeros(n_states, bool); reach[source] = True
        for tl, hl, *_ in parts:
            reach[hl[reach[tl]]] = True
        coreach = np.zeros(n_states, bool); coreach[sink] = True
        for tl, hl, *_ in reversed(parts):
            coreach[tl[coreach[hl]]] = True
        active = reach & coreach; active[source] = active[sink] = True
        mapping = np.full(n_states, -1, np.int64); mapping[active] = np.arange(active.sum())
        tails, heads, kinds, tasks, dvs = [], [], [], [], []
        self.unpruned_arcs = 0
        for tl, hl, kd, tk, dv in parts:
            self.unpruned_arcs += len(tl)
            keep = reach[tl] & coreach[hl]
            tails.append(mapping[tl[keep]]); heads.append(mapping[hl[keep]]); kinds.append(kd[keep]); tasks.append(tk[keep]); dvs.append(dv[keep])
        del parts
        self.tail = np.concatenate(tails).astype(np.int32); self.head = np.concatenate(heads).astype(np.int32)
        self.kind = np.concatenate(kinds); self.task = np.concatenate(tasks); self.dsoc = np.concatenate(dvs)
        idx = np.flatnonzero(active)
        k = idx % 2; r = idx // 2; s = r % S; r //= S; loc = r % L; t = r // L
        self.states = np.stack([t, loc, s, k], axis=1).astype(np.int32)
        self.unpruned_states = n_states
        self.source, self.sink = int(mapping[source]), int(mapping[sink])
        self.n_nodes, self.n_arcs = len(idx), len(self.tail)
        tt = self.states[self.tail, 0]
        require(np.all(np.diff(tt) >= 0), 'arcs not ordered by tail time')
        self.layer = np.searchsorted(tt, np.arange(T + 1))
        self.tail_time = tt
        self.energy = self.dsoc.astype(float) * step


# ----------------------------------------------------------------------------- replay
def replay_route(inst, V, steps):
    """steps: list of (tail_state, head_state, kind, task, energy); states (t, loc, soc_idx, served)."""
    step = inst.soc_step; G = inst.G
    require(len(steps) > 0, 'empty route')
    require(tuple(steps[0][0]) == (0, inst.depot, round(G / step), 0), 'start boundary')
    require(tuple(steps[-1][1]) == (inst.T, inst.depot, round(G / step), 1), 'terminal boundary')
    a = np.zeros(inst.n_trips); e = np.zeros(inst.T); served = 0; tasks = []
    for i, (u, v, kind, task, en) in enumerate(steps):
        if i:
            require(tuple(steps[i - 1][1]) == tuple(u), 'route not contiguous')
        t, loc, s, k = map(int, u); nt, nloc, ns, nk = map(int, v)
        require(0 <= t < nt <= inst.T, 'time must advance within horizon')
        require(k == served, 'served flag')
        require(0 <= s * step <= G + 1e-12 and 0 <= ns * step <= G + 1e-12, 'SoC bound')
        change = (ns - s) * step
        if kind == TASK:
            tr = inst.trips[int(task)]
            require((t, nt, loc, nloc) == (tr.start, tr.end, tr.sloc, tr.eloc), 'task time/place')
            require(abs(change + tr.energy) <= 1e-9 and en == 0, 'task energy')
            require(int(task) not in tasks, 'task repeated in route')
            a[tr.idx] += 1; tasks.append(int(task)); served = 1
        elif kind == TRAVEL:
            require(loc != nloc and nt - t == inst.deadhead_time(loc, nloc) and en == 0, 'travel time')
            require(abs(change + inst.deadhead_energy(loc, nloc)) <= 1e-9, 'travel energy')
        elif kind == WAIT:
            require(nt == t + 1 and loc == nloc and change == 0 and en == 0, 'wait')
        elif kind in (CHARGE, DISCHARGE):
            require(nt == t + 1 and loc == nloc and loc in inst.charge_locs, 'charging place/time')
            require(abs(change - en) <= 1e-9 and abs(en) <= inst.rho + 1e-12, 'charging energy/rate')
            require(en > 0 if kind == CHARGE else en < 0, 'charging sign')
        else:
            raise Fail('unknown transition')
        require(nk == served, 'served flag transition')
        e[t] += en
    require(served == 1, 'route serves no task')
    fixed = inst.c_v + inst.deg_cost * np.maximum(-e, 0).sum()
    return V.Column('truck', a, e, fixed, 'replayed'), tasks


def replay_singleton(inst, V, tr, col):
    """One-task route of the declared family: depart full, deadhead, task, deadhead back, recharge."""
    o = inst.depot
    dep = tr.start - inst.deadhead_time(o, tr.sloc); ret = tr.end + inst.deadhead_time(tr.eloc, o)
    require(dep >= 0 and ret <= inst.T, 'singleton outside horizon')
    a = np.zeros(inst.n_trips); a[tr.idx] = 1
    e = np.asarray(col.e, float)
    require(np.array_equal(col.a, a), 'singleton coverage')
    require(np.all(np.abs(e[:ret]) <= 1e-12) and np.all(e >= -1e-12) and np.all(e <= inst.rho + 1e-12), 'singleton profile')
    soc = inst.G - inst.deadhead_energy(o, tr.sloc); low = soc
    soc -= tr.energy; low = min(low, soc)
    soc -= inst.deadhead_energy(tr.eloc, o); low = min(low, soc)
    require(low >= -1e-9, 'singleton SoC below zero')
    for t in range(ret, inst.T):
        soc += e[t]
        require(soc <= inst.G + 1e-9, 'singleton overcharge')
    require(abs(soc - inst.G) <= 1e-9, 'singleton not full at end')
    require(abs(col.fixed_cost - inst.c_v) <= 1e-12, 'singleton fixed cost')
    vendor = V.single_trip_column(inst, tr, ice=False, free_start=False)
    require(vendor is not None and np.array_equal(vendor.e, e) and np.array_equal(vendor.a, a), 'not the vendor singleton')
    return V.Column('truck', a, e.copy(), inst.c_v, f'single[{tr.idx}]')


def route_steps(top, arcs):
    return [(top.states[top.tail[x]], top.states[top.head[x]], int(top.kind[x]), int(top.task[x]), float(top.energy[x]))
            for x in arcs]


def check_path_arcs(top, arcs):
    arcs = [int(x) for x in arcs]
    require(all(0 <= x < top.n_arcs for x in arcs), 'arc index out of range')
    require(int(top.tail[arcs[0]]) == top.source and int(top.head[arcs[-1]]) == top.sink, 'path ends')
    require(all(int(top.head[x]) == int(top.tail[y]) for x, y in zip(arcs[:-1], arcs[1:])), 'path not contiguous')
    return arcs


def aggregate(inst, routes, g, ch, dis, soc, nb, integer=True):
    """routes: list of (weight, Column). Physical master residuals and the recomputed objective."""
    T = inst.T
    w = np.array([x for x, _ in routes], float)
    cov = sum((x * c.a for x, c in routes), np.zeros(inst.n_trips))
    grid = sum((x * c.e for x, c in routes), np.zeros(T))
    obj = (sum(x * c.cost(inst.eps_pen) for x, c in routes) + inst.c_g * g.sum() + inst.c_b * nb
           + inst.eps_pen * (ch.sum() + dis.sum()) + inst.deg_cost * dis.sum())
    res = {'coverage': float(np.max(np.abs(cov - 1))),
           'balance': float(np.maximum(inst.Delta + grid + ch - dis - g, 0).max()),
           'bess_dynamics': float(np.abs(np.diff(soc) - ch + dis).max()),
           'bess_periodic': float(abs(soc[-1] - soc[0])),
           'bess_capacity': float(np.maximum(soc - inst.G * nb, 0).max()),
           'bess_charge_rate': float(np.maximum(ch - inst.rho * nb, 0).max()),
           'bess_discharge_rate': float(np.maximum(dis - inst.rho * nb, 0).max()),
           'nonnegativity': float(max(0, -g.min(), -ch.min(), -dis.min(), -soc.min(), -nb, -(w.min() if len(w) else 0))),
           'integrality': float(max(np.abs(w - np.rint(w)).max() if len(w) else 0, abs(nb - round(nb)))) if integer else 0.0}
    return res, float(obj)


def vendor_crosscheck(inst, V, cols, U):
    """Original published master (Gurobi backend) over the replayed routes: optimal dispatch and battery count."""
    t0 = time.perf_counter()
    sol = V.solve_milp(inst, cols, time_limit=600, solver='gurobi', soc_mode='cyclic', mip_gap=1e-9)
    ok = sol.status in ('optimal', 'feasible')
    return {'status': sol.status, 'objective': float(sol.obj) if ok else None,
            'bound': getattr(sol, 'solver_bound', None), 'routes_selected': float(np.sum(sol.x)) if ok else None,
            'not_above_reported': bool(ok and sol.obj <= U + 1e-6 * max(1.0, abs(U))),
            'seconds': time.perf_counter() - t0}


# ----------------------------------------------------------------------------- arms
def seeds_of(inst, V):
    out = []
    for tr in inst.trips:
        c = V.single_trip_column(inst, tr, ice=False, free_start=False)
        if c is not None:
            out.append((tr, c))
    return out


def load_columns(path, V):
    with gzip.open(path, 'rt') as fh:
        raw = json.load(fh)
    return [V.Column(c['kind'], np.asarray(c['a'], float), np.asarray(c['e'], float), float(c['fixed_cost']), c.get('label', ''))
            for c in raw]


def validate_cg(inst, V, top, seeds, folder, out, use_hints=True):
    res = load_result(folder / 'result.json')
    out.update(status=res.get('status'), reported_objective=res.get('objective'),
               reported_cg_lp=(res.get('cg_lp') or {}).get('objective'),
               reported_full_family_bound=res.get('full_family_lp_lower_bound'),
               cg_priced_out=res.get('cg_priced_out'), final_pricing_call_empty=res.get('final_pricing_call_empty'),
               restricted_mip_status=(res.get('restricted_mip') or {}).get('status'),
               runner_graph=(res.get('graph_nodes'), res.get('graph_arcs')))
    if res.get('graph_arcs') is not None:
        require((res['graph_nodes'], res['graph_arcs']) == (top.n_nodes, top.n_arcs), 'rebuilt graph size differs from runner record')
    cols = load_columns(folder / 'cg_pool_columns.json.gz', V)
    x = np.load(folder / 'restricted_primal.npz')['x']
    R, T = len(cols), inst.T
    require(len(x) == R + 4 * T + 2, 'restricted vector length')
    w = x[:R]; g = x[R:R + T]; ch = x[R + T:R + 2 * T]; dis = x[R + 2 * T:R + 3 * T]; soc = x[R + 3 * T:R + 4 * T + 1]; nb = x[R + 4 * T + 1]
    int_res = float(max(np.abs(w - np.rint(w)).max(), abs(nb - round(nb))))
    require(int_res <= TOL, f'restricted vector not integral ({int_res})')
    sel = np.flatnonzero(np.rint(w) > 0)
    hints = {}
    for row in ((res.get('validation') or {}).get('selected_paths') or {}).get('witnesses', []):
        hints[int(row['column_index'])] = row['witness']
    seed_by_task = {tr.idx: (tr, c) for tr, c in seeds}
    routes = []; how = {'singleton': 0, 'path_from_saved_hint': 0, 'path_found_by_search': 0}; transitions = 0
    for r in sel:
        col = cols[int(r)]
        require(col.kind == 'truck', 'non-truck column selected')
        tasks = np.flatnonzero(col.a > 0.5)
        if (len(tasks) == 1 and tasks[0] in seed_by_task and
                np.array_equal(seed_by_task[tasks[0]][1].e, col.e) and abs(col.fixed_cost - inst.c_v) <= 1e-12):
            tr, _ = seed_by_task[tasks[0]]
            rc = replay_singleton(inst, V, tr, col); how['singleton'] += 1
        else:
            arcs = None; h = hints.get(int(r))
            if use_hints and h and h.get('arc_indices'):
                try:
                    arcs = check_path_arcs(top, h['arc_indices']); how['path_from_saved_hint'] += 1
                except Fail:
                    arcs = None
            if arcs is None:
                arcs = find_route(top, inst, col); how['path_found_by_search'] += 1
            rc, _ = replay_route(inst, V, route_steps(top, arcs)); transitions += len(arcs)
            require(np.max(np.abs(rc.a - col.a)) <= 1e-9 and np.max(np.abs(rc.e - col.e)) <= 1e-9
                    and abs(rc.fixed_cost - col.fixed_cost) <= 1e-9, 'stored column differs from its replayed route')
        routes.append((float(np.rint(w[r])), rc))
    resid, obj = aggregate(inst, routes, g, ch, dis, soc, nb)
    U = res['objective']
    out.update(selected_routes=len(routes), route_realization=how, transitions_replayed=transitions,
               residuals=resid, max_residual=max(resid.values()), recomputed_objective=obj,
               objective_abs_diff=abs(obj - U), battery_count=float(round(nb)))
    require(max(resid.values()) <= TOL, f'physical master residual {resid}')
    require(abs(obj - U) <= 1e-6 * max(1.0, abs(U)), f'objective {obj} vs reported {U}')
    out['vendor_master_check'] = vendor_crosscheck(inst, V, [c for _, c in routes], U)
    out['schedule_validated'] = True
    out['validated_objective'] = U
    # Stopping duals -> Lagrangian bound (independent of the restricted master and of z_RMP).
    p = folder / 'cg_stopping_primal.npz'
    if p.exists():
        d = np.load(p)
        out['dual_certificate'] = lagrangian_bound(inst, top, seeds, d['alpha'], d['mu'], d['nu'])
    else:
        out['dual_certificate'] = {'available': False, 'reason': 'no stopping duals saved'}
    return routes


def find_route(top, inst, col):
    """Search the rebuilt DAG for a source-sink path with exactly this column's tasks and profile."""
    e = np.asarray(col.e, float); tasks = sorted(np.flatnonzero(col.a > 0.5), key=lambda i: inst.trips[i].start)
    m = len(tasks); pos = {int(i): j for j, i in enumerate(tasks)}
    zero = np.abs(e) <= 1e-12; cz = np.r_[0, np.cumsum(~zero)]
    tt = top.tail_time; ht = top.states[top.head, 0]
    span_zero = (cz[ht] - cz[tt]) == 0
    kind = top.kind
    ok_short = ((kind == WAIT) | (kind == CHARGE) | (kind == DISCHARGE)) & (np.abs(top.energy - e[tt]) <= 1e-9)
    ok_travel = (kind == TRAVEL) & span_zero
    tk = top.task
    is_col_task = (kind == TASK) & np.isin(tk, tasks) & span_zero
    jt = np.full(top.n_arcs, -1); jt[is_col_task] = [pos[int(i)] for i in tk[is_col_task]]
    F = np.zeros((top.n_nodes, m + 1), bool); F[top.source, 0] = True
    for t in range(top.T):
        sl = slice(top.layer[t], top.layer[t + 1])
        tl, hl = top.tail[sl], top.head[sl]
        st = ok_short[sl] | ok_travel[sl]
        np.logical_or.at(F, hl[st], F[tl[st]])
        ct = is_col_task[sl]
        if ct.any():
            j = jt[sl][ct]; src = F[tl[ct], j]
            F[hl[ct][src], j[src] + 1] = True
    require(F[top.sink, m], 'no route in the rebuilt graph realizes the stored column')
    Bk = np.zeros_like(F); Bk[top.sink, m] = True
    for t in reversed(range(top.T)):
        sl = slice(top.layer[t], top.layer[t + 1])
        tl, hl = top.tail[sl], top.head[sl]
        st = ok_short[sl] | ok_travel[sl]
        np.logical_or.at(Bk, tl[st], Bk[hl[st]])
        ct = is_col_task[sl]
        if ct.any():
            j = jt[sl][ct]; good = Bk[hl[ct], j + 1]
            Bk[tl[ct][good], j[good]] = True
    starts = np.searchsorted(top.tail, np.arange(top.n_nodes + 1))
    u, j, arcs = top.source, 0, []
    while u != top.sink:
        cand = np.arange(starts[u], starts[u + 1])
        nxt = None
        for a_ in cand:
            if (ok_short[a_] or ok_travel[a_]) and Bk[top.head[a_], j]:
                nxt = (a_, j); break
            if is_col_task[a_] and jt[a_] == j and Bk[top.head[a_], j + 1]:
                nxt = (a_, j + 1); break
        require(nxt is not None, 'route extraction failed')
        arcs.append(int(nxt[0])); u = int(top.head[nxt[0]]); j = nxt[1]
    return arcs


def validate_direct(inst, V, top, seeds, folder, readings, out, final=True):
    res = load_result(folder / 'result.json')
    out.update(status=res.get('status'), reported_objective=res.get('objective'), reported_bound=res.get('bound'),
               runner_graph=(res.get('graph_nodes'), res.get('graph_arcs')), budget_seconds=res.get('budget_seconds'),
               solve_end_to_end_seconds=res.get('solve_end_to_end_seconds'), root_lp_solved_seconds=res.get('root_lp_solved_seconds'))
    require(res.get('status') not in (None, 'error', 'environment_rejected'), f"direct run status {res.get('status')}")
    require((res['graph_nodes'], res['graph_arcs']) == (top.n_nodes, top.n_arcs), 'rebuilt graph size differs from runner record')
    require(res.get('unpruned_arcs') in (None, top.unpruned_arcs) and res.get('unpruned_states') in (None, top.unpruned_states),
            'unpruned graph size differs')
    events = res.get('incumbent_events') or []
    first = events[0] if events else None
    picks = {}
    for T_ in readings:
        before = [e for e in events if e['elapsed_seconds'] <= T_]
        best = min(before, key=lambda e: e['objective']) if before else None
        picks[str(int(T_))] = best
    todo = {}
    for key, ev in picks.items():
        if ev is not None:
            todo.setdefault(('incumbent', int(ev['vector_index'])), (folder / f"incumbent_{int(ev['vector_index']):03d}.npz", ev['objective']))
    if final and res.get('objective') is not None and (folder / 'direct_mip_primal.npz').exists():
        todo[('final', -1)] = (folder / 'direct_mip_primal.npz', res['objective'])
    checked = {}
    for (kind_, idx), (path, U) in todo.items():
        rec = {'file': path.name, 'reported_objective': U}
        try:
            rec.update(validate_direct_vector(inst, V, top, seeds, np.load(path)['x'], U))
            rec['validated'] = True
        except Fail as exc:
            rec.update(validated=False, failure=str(exc))
        checked[f'{kind_}_{idx}'] = rec
    out['vectors'] = checked
    out['readings'] = {}
    for key, ev in picks.items():
        if ev is None:
            out['readings'][key] = {'incumbent': None}
            continue
        rec = checked[f"incumbent_{int(ev['vector_index'])}"]
        out['readings'][key] = {'vector_index': int(ev['vector_index']), 'elapsed_seconds': ev['elapsed_seconds'],
                                'objective': ev['objective'], 'validated': rec['validated'],
                                'is_first_incumbent': first is not None and int(ev['vector_index']) == int(first['vector_index']),
                                'is_one_truck_per_task_schedule': rec.get('one_truck_per_task_singletons')}
    out['first_incumbent'] = None if first is None else {'vector_index': int(first['vector_index']), 'objective': first['objective'],
                                                         'elapsed_seconds': first['elapsed_seconds']}
    if 'final_-1' in checked:
        out['final_validated'] = checked['final_-1']['validated']
    return checked


def validate_direct_vector(inst, V, top, seeds, x, U):
    E, T, K = top.n_arcs, inst.T, len(seeds)
    f = E; g0 = f + 1; c0 = g0 + T; d0 = c0 + T; s0 = d0 + T; nbi = s0 + T + 1; k0 = nbi + 1
    require(len(x) == k0 + K, f'vector length {len(x)} vs {k0 + K}')
    require(np.all(np.isfinite(x)), 'nonfinite vector')
    ints = np.r_[x[:E + 1], x[nbi], x[k0:]]
    int_res = float(np.abs(ints - np.rint(ints)).max())
    require(int_res <= TOL, f'integer part not integral ({int_res})')
    flow = np.rint(x[:E]).astype(np.int64); fleet = int(round(x[f])); sw = np.rint(x[k0:]).astype(np.int64)
    require(flow.min(initial=0) >= 0 and fleet >= 0 and sw.min(initial=0) >= 0 and sw.max(initial=0) <= 1, 'integer bounds')
    net = (np.bincount(top.head, weights=flow, minlength=top.n_nodes) - np.bincount(top.tail, weights=flow, minlength=top.n_nodes))
    net[top.source] += fleet; net[top.sink] -= fleet
    require(np.all(net == 0), 'flow conservation fails on the rebuilt graph')
    rawnet = (np.bincount(top.head, weights=x[:E], minlength=top.n_nodes) - np.bincount(top.tail, weights=x[:E], minlength=top.n_nodes))
    rawnet[top.source] += x[f]; rawnet[top.sink] -= x[f]
    # decompose integer flow into unit paths
    pos = np.flatnonzero(flow > 0)
    left = {int(a): int(flow[a]) for a in pos}
    out_arcs = {}
    for a in pos:
        out_arcs.setdefault(int(top.tail[a]), []).append(int(a))
    routes = []; transitions = 0
    for _ in range(fleet):
        u = top.source; arcs = []
        while u != top.sink:
            nxt = next((a for a in out_arcs.get(u, ()) if left[a] > 0), None)
            require(nxt is not None, 'flow path dead-ends')
            left[nxt] -= 1; arcs.append(nxt); u = int(top.head[nxt])
        col, _ = replay_route(inst, V, route_steps(top, arcs)); transitions += len(arcs)
        routes.append((1.0, col))
    require(all(v == 0 for v in left.values()), 'flow left after path decomposition')
    for (tr, c), wj in zip(seeds, sw):
        if wj:
            routes.append((float(wj), replay_singleton(inst, V, tr, c)))
    g = x[g0:g0 + T]; ch = x[c0:c0 + T]; dis = x[d0:d0 + T]; soc = x[s0:s0 + T + 1]; nb = x[nbi]
    resid, obj = aggregate(inst, routes, g, ch, dis, soc, nb)
    resid['flow_conservation_raw'] = float(np.abs(rawnet).max())
    require(max(resid.values()) <= TOL, f'physical master residual {resid}')
    require(abs(obj - U) <= 1e-6 * max(1.0, abs(U)), f'objective {obj} vs reported {U}')
    vc = vendor_crosscheck(inst, V, [c for _, c in routes], U)
    return {'routes': len(routes), 'dag_routes': fleet, 'singleton_routes': int(sw.sum()),
            'one_truck_per_task_singletons': bool(fleet == 0 and int(sw.sum()) == inst.n_trips),
            'transitions_replayed': transitions, 'residuals': resid, 'max_residual': max(resid.values()),
            'recomputed_objective': obj, 'objective_abs_diff': abs(obj - U), 'battery_count': float(round(nb)),
            'vendor_master_check': vc}


# ----------------------------------------------------------------------------- bound
def lagrangian_bound(inst, top, seeds, alpha, mu, nu):
    """Valid lower bound on the full integer (and LP) model from any multipliers (alpha free, 0 <= mu <= c_g).

    z >= sum(alpha) + sum(mu*Delta) + n*min(0, rc_min) + Nbmax*min(0, c_b + v*(mu)),
    rc_min = min reduced cost over all routes of the family (DAG paths by an exact DP on the
    rebuilt graph, and the singletons), v* = least dispatch cost of one battery (small LP),
    Nbmax = U/c_b for any known schedule cost U (filled in by the aggregator; here the term is
    reported separately). Route weight is at most n because every route serves a task.
    """
    alpha = np.asarray(alpha, float); mu_raw = np.asarray(mu, float); nu = np.asarray(nu, float)
    mu = np.clip(mu_raw, 0.0, inst.c_g)
    eps, deg = inst.eps_pen, inst.deg_cost
    e = top.energy; t_ = top.tail_time
    cost = mu[t_] * e + eps * np.abs(e) + deg * np.maximum(-e, 0.0)
    has = top.task >= 0
    cost[has] -= alpha[top.task[has]]
    label = np.full(top.n_nodes, np.inf); label[top.source] = 0.0
    for t in range(top.T):
        sl = slice(top.layer[t], top.layer[t + 1])
        np.minimum.at(label, top.head[sl], label[top.tail[sl]] + cost[sl])
    rc_graph = float(inst.c_v + label[top.sink])
    rc_seed = min(c.cost(eps) - c.a @ alpha + c.e @ mu for _, c in seeds)
    rc_min = min(rc_graph, float(rc_seed))
    from scipy.optimize import linprog
    T = inst.T
    # variables: chg (T), dis (T), s (T+1); one battery, cyclic
    c = np.r_[eps + mu, eps + deg - mu, np.zeros(T + 1)]
    Aeq = np.zeros((T + 1, 3 * T + 1)); beq = np.zeros(T + 1)
    for t in range(T):
        Aeq[t, 2 * T + t + 1] = 1; Aeq[t, 2 * T + t] = -1; Aeq[t, t] = -1; Aeq[t, T + t] = 1
    Aeq[T, 3 * T] = 1; Aeq[T, 2 * T] = -1
    bounds = [(0, inst.rho)] * (2 * T) + [(0, inst.G)] * (T + 1)
    lp = linprog(c, A_eq=Aeq, b_eq=beq, bounds=bounds, method='highs')
    require(lp.success, 'battery LP failed')
    base = float(alpha.sum() + mu @ inst.Delta)
    return {'available': True, 'dual_objective_part': base, 'rc_min_graph': rc_graph, 'rc_min_singletons': float(rc_seed),
            'rc_min': rc_min, 'fleet_term': inst.n_trips * min(0.0, rc_min),
            'battery_unit_value': float(lp.fun), 'battery_reduced_cost': float(inst.c_b + lp.fun),
            'mu_clipped_max': float(np.abs(mu - mu_raw).max()), 'nu_max_abs': float(np.abs(nu).max()) if nu.size else 0.0,
            'bound_before_battery_term': base + inst.n_trips * min(0.0, rc_min),
            'priced_out_at_1e-6': bool(rc_min >= -1e-6)}


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--record', required=True, type=Path)
    ap.add_argument('--vendor', required=True, type=Path)
    ap.add_argument('--arm', action='append', default=[], help='label:kind:path[:readings], kind cg|direct, readings like 1800,3600')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--no-hints', action='store_true', help='ignore saved route witnesses; find every route by search')
    a = ap.parse_args()
    t0 = time.perf_counter()
    sys.path.insert(0, str(a.vendor))
    import instance as _i, master as _m, colgen as _c
    import gurobipy as gp
    gp.setParam('OutputFlag', 0); gp.setParam('Threads', 1); gp.setParam('Seed', 0)

    class V:
        Instance, Trip, Column, solve_milp, single_trip_column = _i.Instance, _i.Trip, _m.Column, staticmethod(_m.solve_milp), staticmethod(_c.single_trip_column)
    stage1 = json.loads(a.record.read_text())
    raw = stage1['record']
    body = {k: v for k, v in raw.items() if k != 'sha256'}
    require(hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() == raw['sha256'], 'record hash')
    inst = instance_from_record(raw, V)
    report = {'case': stage1['case'], 'cohort': stage1['cohort'], 'instance_sha256': raw['sha256'], 'n_tasks': inst.n_trips,
              'locations': int(inst.dist.shape[0]), 'soc_step': inst.soc_step, 'c_b': inst.c_b, 'c_g': inst.c_g,
              'c_v': inst.c_v, 'arms': {}}
    tb = time.perf_counter(); top = Topology(inst)
    report['graph'] = {'nodes': top.n_nodes, 'arcs': top.n_arcs, 'unpruned_states': top.unpruned_states,
                       'unpruned_arcs': top.unpruned_arcs, 'build_seconds': time.perf_counter() - tb}
    seeds = seeds_of(inst, V)
    require(len(seeds) == inst.n_trips, 'some task has no singleton route')
    for spec in a.arm:
        parts = spec.split(':')
        label, kind, path = parts[0], parts[1], Path(parts[2])
        readings = [float(x) for x in parts[3].split(',')] if len(parts) > 3 and parts[3] else [1800.0]
        arm = {'kind': kind, 'path': str(path)}
        try:
            saved = json.loads((path / 'instance.json').read_text())
            res = load_result(path / 'result.json')
            man = json.loads((path / 'manifest.json').read_text())
            arm['input_checks'] = {'saved_instance_equals_rebuilt': saved == raw,
                                   'result_hash_matches': res.get('instance_sha256') == raw['sha256'],
                                   'manifest_hash_matches': man.get('instance_sha256') == raw['sha256'],
                                   'manifest_spec_equals_declared': man.get('case') == stage1['spec']}
            require(all(arm['input_checks'].values()), f"input check failed {arm['input_checks']}")
            arm['manifest'] = {'slurm': man.get('slurm'), 'cpu_model': (man.get('environment') or {}).get('cpu_model'),
                               'gurobi': (man.get('environment') or {}).get('gurobi')}
            used = stage1.get('runtime_sha256') or {}
            ran = man.get('code_sha256') or {}
            arm['code_checks'] = {'runtime_files_compared': sorted(set(used) & set(ran)),
                                  'runtime_files_differing': sorted(k for k in set(used) & set(ran) if used[k] != ran[k]),
                                  'vendor_files_differing': sorted(k for k, row in ((man.get('vendor_manifest') or {}).get('files') or {}).items()
                                                                   if (a.vendor / k).exists() and sha(a.vendor / k) != row.get('sha256'))}
            if kind == 'cg':
                validate_cg(inst, V, top, seeds, path, arm, use_hints=not a.no_hints)
            else:
                validate_direct(inst, V, top, seeds, path, readings, arm)
            arm['passed'] = True
        except Fail as exc:
            arm.update(passed=False, failure=str(exc))
        except FileNotFoundError as exc:
            arm.update(passed=False, failure=f'missing file: {exc.filename}')
        report['arms'][label] = arm
    loaded = sorted(m for m in sys.modules if m.split('.')[0] in FORBIDDEN)
    report['forbidden_modules_loaded'] = loaded
    require(not loaded, f'forbidden modules loaded: {loaded}')
    report['validator_sha256'] = sha(__file__)
    report['vendor_sha256'] = {p.name: sha(p) for p in sorted(a.vendor.glob('*.py'))}
    report['seconds'] = time.perf_counter() - t0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o)))
    print(json.dumps({'case': report['case'], 'arms': {k: v.get('passed') for k, v in report['arms'].items()},
                      'seconds': round(report['seconds'], 1)}))


if __name__ == '__main__':
    main()
