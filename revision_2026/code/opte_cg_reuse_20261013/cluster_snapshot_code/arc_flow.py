"""Direct integer arc flow for the lossless full-recharge truck-pricing DAG.

Public API:
    build_graph(inst) -> Graph
    solve_arc_flow(inst, relax, time_limit, log_path, threads=1) -> dict

``time_limit`` is an end-to-end wall-clock allowance from function entry; graph
and model construction consume it. Only the remaining allowance reaches Gurobi.
The graph has exactly the vendor DP's wait, charging, discharging, positive-time
deadhead and task arcs, including its served-task flag. Forward/backward pruning
removes only states absent from every source-to-terminal path. Trucks start and
finish full at the depot and must serve a task. The aggregate stationary battery
is continuous in dispatch and periodic, with integer count in the MIP.

This implementation deliberately rejects off-lattice input and unsupported
extensions instead of reproducing the vendor DP's rounding. In particular it
does not claim to cover arbitrary off-grid initial columns or periodic trucks.
The pilot's lossless, uncapped-charge initial singletons use full-rate charging
and a lattice remainder, so they are paths in this graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import time
from typing import Any

import numpy as np
from scipy import sparse


WAIT, CHARGE, DISCHARGE, TRAVEL, TASK = range(5)
KIND_NAMES = ("wait", "charge", "discharge", "travel", "task")


@dataclass
class Graph:
    states: np.ndarray                 # (time, location, SoC-index, served)
    tail: np.ndarray
    head: np.ndarray
    kind: np.ndarray
    task: np.ndarray                   # task index, or -1
    energy: np.ndarray                 # signed grid draw at tail time
    source: int
    sink: int
    step: float
    unpruned_states: int
    unpruned_arcs: int

    @property
    def n_nodes(self):
        return len(self.states)

    @property
    def n_arcs(self):
        return len(self.tail)


def _integer(value, label, tol=1e-8):
    if not np.isfinite(value) or abs(value - round(value)) > tol:
        raise ValueError(f"{label} must be integral; got {value!r}")
    return int(round(value))


def validate_instance(inst):
    """Return validated integer travel times/energy shifts and task shifts."""
    T = _integer(inst.T, "T")
    if T <= 0 or inst.n_trips < 1:
        raise ValueError("Positive horizon and at least one task are required")
    if abs(inst.eta) > 1e-12:
        raise ValueError("This pilot supports eta=0 only")
    step = float(inst.soc_step)
    if not np.isfinite(step) or step <= 0:
        raise ValueError("soc_step must be positive and finite")
    Gidx = _integer(inst.G / step, "G / soc_step")
    rate = _integer(inst.rho / step, "rho / soc_step")
    if Gidx <= 0 or rate < 0 or inst.energy_per_dist < 0:
        raise ValueError("Invalid capacity, rate, or travel energy")
    if not all(np.isfinite(x) and x > 0 for x in (inst.c_v, inst.c_b, inst.c_g)):
        raise ValueError("Positive finite truck, stationary, and generation costs required")
    if not np.isfinite(inst.eps_pen) or inst.eps_pen < 0:
        raise ValueError("Nonnegative finite throughput cost required")
    deg = float(getattr(inst, "deg_cost", 0.0))
    if not np.isfinite(deg) or deg < 0:
        raise ValueError("Nonnegative finite discharge cost required")
    for attr in ("fuel_budget", "max_trucks"):
        if np.isfinite(getattr(inst, attr, float("inf"))):
            raise ValueError(f"Unsupported pilot extension: {attr}")
    if getattr(inst, "nb_fixed", -1.0) is not None and inst.nb_fixed >= 0:
        raise ValueError("Unsupported pilot extension: nb_fixed")
    dist = np.asarray(inst.dist, dtype=float)
    if dist.ndim != 2 or dist.shape[0] != dist.shape[1]:
        raise ValueError("dist must be square")
    L = dist.shape[0]
    if not 0 <= inst.depot < L:
        raise ValueError("Invalid depot")
    dt = np.zeros_like(dist, dtype=int)
    de = np.zeros_like(dist, dtype=int)
    for a in range(L):
        for b in range(L):
            dt[a, b] = _integer(dist[a, b], f"travel time {a}->{b}")
            de[a, b] = _integer(dist[a, b] * inst.energy_per_dist / step,
                                f"travel energy {a}->{b} / soc_step")
            if dt[a, b] < 0 or de[a, b] < 0:
                raise ValueError("Negative travel time or energy")
            if a != b and dt[a, b] <= 0:
                raise ValueError("Distinct locations require positive travel time")
    stations = list(inst.charge_locs)
    if len(set(stations)) != len(stations) or any(h < 0 or h >= L for h in stations):
        raise ValueError("Invalid or duplicate charging locations")
    if sorted(tr.idx for tr in inst.trips) != list(range(inst.n_trips)):
        raise ValueError("Task indices must be unique 0..n-1")
    shifts = {}
    for tr in inst.trips:
        st, en = _integer(tr.start, "task start"), _integer(tr.end, "task end")
        if not 0 <= st < en <= T:
            raise ValueError("Every task must have positive duration within the horizon")
        if not (0 <= tr.sloc < L and 0 <= tr.eloc < L):
            raise ValueError("Invalid task location")
        shifts[tr.idx] = _integer(tr.energy / step, f"task {tr.idx} energy / soc_step")
        if shifts[tr.idx] < 0:
            raise ValueError("Negative task energy")
    delta = np.asarray(inst.Delta, dtype=float)
    if delta.shape != (T,) or not np.all(np.isfinite(delta)):
        raise ValueError("Delta must be a finite horizon-length vector")
    caps = np.broadcast_to(np.asarray(inst.gen_cap, dtype=float), (T,))
    if np.any(np.isnan(caps)) or np.any(caps < 0):
        raise ValueError("Invalid generation capacity")
    cc = np.asarray(inst.charge_cap, dtype=float)
    if cc.ndim != 0 or np.isnan(cc) or cc < 0:
        raise ValueError("charge_cap must be a nonnegative scalar")
    return T, L, Gidx, rate, step, dt, de, shifts, stations


def build_graph(inst) -> Graph:
    T, L, Gidx, rate, step, dt, de, shifts, stations = validate_instance(inst)
    S = Gidx + 1
    states = np.asarray([(t, loc, s, k) for t in range(T + 1)
                         for loc in range(L) for s in range(S) for k in range(2)],
                        dtype=np.int32)
    def node(t, loc, s, k):
        return (((t * L + loc) * S + s) * 2 + k)
    starts = {}
    for tr in inst.trips:
        starts.setdefault((tr.start, tr.sloc), []).append(tr)
    tail, head, kind, task, energy = [], [], [], [], []
    def add(u, v, typ, tid=-1, e=0.0):
        tail.append(u); head.append(v); kind.append(typ); task.append(tid); energy.append(e)
    station_set = set(stations)
    for t in range(T):
        for loc in range(L):
            for s in range(S):
                for k in range(2):
                    u = node(t, loc, s, k)
                    add(u, node(t + 1, loc, s, k), WAIT)
                    if loc in station_set:
                        for d in range(1, min(rate, Gidx - s) + 1):
                            add(u, node(t + 1, loc, s + d, k), CHARGE, e=d * step)
                        for d in range(1, min(rate, s) + 1):
                            add(u, node(t + 1, loc, s - d, k), DISCHARGE, e=-d * step)
                    for other in range(L):
                        if other != loc and t + dt[loc, other] <= T and s >= de[loc, other]:
                            add(u, node(t + dt[loc, other], other, s - de[loc, other], k), TRAVEL)
                    for tr in starts.get((t, loc), ()):
                        sh = shifts[tr.idx]
                        if s >= sh:
                            add(u, node(tr.end, tr.eloc, s - sh, 1), TASK, tr.idx)
    tail = np.asarray(tail, dtype=np.int32); head = np.asarray(head, dtype=np.int32)
    kind = np.asarray(kind, dtype=np.int8); task = np.asarray(task, dtype=np.int32)
    energy = np.asarray(energy, dtype=float)
    source = node(0, inst.depot, Gidx, 0)
    sink = node(T, inst.depot, Gidx, 1)
    reachable = np.zeros(len(states), dtype=bool); reachable[source] = True
    # Arc enumeration is topological by tail time. Every arc advances time.
    for u, v in zip(tail, head):
        if reachable[u]:
            reachable[v] = True
    coreachable = np.zeros(len(states), dtype=bool); coreachable[sink] = True
    for u, v in zip(tail[::-1], head[::-1]):
        if coreachable[v]:
            coreachable[u] = True
    active = reachable & coreachable
    active[source] = True; active[sink] = True
    keep = reachable[tail] & coreachable[head]
    mapping = np.full(len(states), -1, dtype=np.int32)
    mapping[active] = np.arange(int(active.sum()), dtype=np.int32)
    return Graph(states[active], mapping[tail[keep]], mapping[head[keep]], kind[keep],
                 task[keep], energy[keep], int(mapping[source]), int(mapping[sink]),
                 step, len(states), len(tail))


def shortest_path_reduced_cost(inst, graph: Graph, alpha, mu, nu=None):
    """Independent scalar DAG sweep for checking the vendor DP/current duals.

    Returns the true minimum route reduced cost even when it is nonnegative;
    unlike the pricing API it does not suppress routes at a stopping tolerance.
    """
    alpha = np.asarray(alpha, dtype=float); mu = np.asarray(mu, dtype=float)
    nu = np.zeros(inst.T) if nu is None else np.asarray(nu, dtype=float)
    if alpha.shape != (inst.n_trips,) or mu.shape != (inst.T,) or nu.shape != (inst.T,):
        raise ValueError("Dual vectors have incompatible dimensions")
    if not all(np.all(np.isfinite(v)) for v in (alpha, mu, nu)):
        raise ValueError("Dual vectors must be finite")
    label = np.full(graph.n_nodes, np.inf); label[graph.source] = 0.0
    for a, (u, v) in enumerate(zip(graph.tail, graph.head)):
        e = graph.energy[a]; t = graph.states[u, 0]; tid = graph.task[a]
        cost = (mu[t] * e + nu[t] * max(e, 0.0) + inst.eps_pen * abs(e)
                + getattr(inst, "deg_cost", 0.0) * max(-e, 0.0))
        if tid >= 0:
            cost -= alpha[tid]
        candidate = label[u] + cost
        if candidate < label[v]:
            label[v] = candidate
    return float(inst.c_v + label[graph.sink])


def _matrices(inst, graph):
    """Sparse model, with columns [arcs, fleet, generation, charge, discharge, SoC, Nb]."""
    E, N, T, n = graph.n_arcs, graph.n_nodes, inst.T, inst.n_trips
    f = E; g = f + 1; ch = g + T; dis = ch + T; soc = dis + T; nb = soc + T + 1
    V = nb + 1
    c = np.zeros(V); c[:E] = inst.eps_pen * abs(graph.energy)
    c[:E] += getattr(inst, "deg_cost", 0.0) * np.maximum(-graph.energy, 0.0)
    c[f] = inst.c_v; c[g:g + T] = inst.c_g; c[ch:ch + T] = inst.eps_pen
    c[dis:dis + T] = inst.eps_pen + getattr(inst, "deg_cost", 0.0); c[nb] = inst.c_b
    lb = np.zeros(V); ub = np.full(V, np.inf)
    # Exact cover and one served task on each acyclic source/sink path imply fleet <= n.
    ub[:E + 1] = n
    ub[g:g + T] = np.broadcast_to(np.asarray(inst.gen_cap, dtype=float), (T,))
    er, ec, ev = [], [], []
    def eq(row, col, value):
        er.append(row); ec.append(col); ev.append(value)
    for a, (u, v, tid) in enumerate(zip(graph.tail, graph.head, graph.task)):
        eq(u, a, -1.0); eq(v, a, 1.0)
        if tid >= 0:
            eq(N + tid, a, 1.0)
    eq(graph.source, f, 1.0); eq(graph.sink, f, -1.0)
    for t in range(T):
        row = N + n + t
        eq(row, soc + t + 1, 1.0); eq(row, soc + t, -1.0)
        eq(row, ch + t, -1.0); eq(row, dis + t, 1.0)
    eq(N + n + T, soc + T, 1.0); eq(N + n + T, soc, -1.0)
    beq = np.zeros(N + n + T + 1); beq[N:N + n] = 1.0
    Aeq = sparse.coo_matrix((ev, (er, ec)), shape=(len(beq), V)).tocsr()
    ur, uc, uv = [], [], []
    def le(row, col, value):
        ur.append(row); uc.append(col); uv.append(value)
    cc_active = np.isfinite(inst.charge_cap)
    ccrow = 4 * T + 1
    bub = np.zeros(ccrow + (T if cc_active else 0)); bub[:T] = -inst.Delta
    if cc_active:
        bub[ccrow:] = inst.charge_cap
    for a, e in enumerate(graph.energy):
        if e:
            t = graph.states[graph.tail[a], 0]
            le(t, a, e)
            if cc_active and e > 0:
                le(ccrow + t, a, e)
    for t in range(T):
        le(t, g + t, -1.0); le(t, ch + t, 1.0); le(t, dis + t, -1.0)
        le(2 * T + 1 + t, ch + t, 1.0); le(2 * T + 1 + t, nb, -inst.rho)
        le(3 * T + 1 + t, dis + t, 1.0); le(3 * T + 1 + t, nb, -inst.rho)
        if cc_active:
            le(ccrow + t, ch + t, 1.0)
    for t in range(T + 1):
        le(T + t, soc + t, 1.0); le(T + t, nb, -inst.G)
    Aub = sparse.coo_matrix((uv, (ur, uc)), shape=(len(bub), V)).tocsr()
    return c, lb, ub, Aeq, beq, Aub, bub, dict(fleet=f, g=g, charge=ch, discharge=dis, soc=soc, nb=nb)


def decompose_paths(graph: Graph, arc_flow, tol=1e-7):
    """Decompose nonnegative (possibly fractional) DAG flow into truck paths."""
    residual = np.asarray(arc_flow, dtype=float).copy()
    residual[abs(residual) < tol] = 0.0
    out = [[] for _ in range(graph.n_nodes)]
    for a, u in enumerate(graph.tail):
        if residual[a] > tol:
            out[u].append(a)
    paths = []
    while any(residual[a] > tol for a in out[graph.source]):
        u = graph.source; arcs = []
        while u != graph.sink:
            choices = [a for a in out[u] if residual[a] > tol]
            if not choices:
                raise ValueError(f"Positive flow path dead-ends at node {u}")
            a = choices[0]; arcs.append(a); u = int(graph.head[a])
            if len(arcs) > graph.n_nodes:
                raise ValueError("Cycle in purported DAG")
        weight = float(min(residual[a] for a in arcs))
        residual[arcs] -= weight
        paths.append({"weight": weight, "arcs": arcs,
                      "tasks": [int(graph.task[a]) for a in arcs if graph.task[a] >= 0]})
    if np.max(np.abs(residual), initial=0.0) > max(tol * 20, 1e-5):
        raise ValueError("Path decomposition leaves positive residual flow")
    return paths


def replay_solution(inst, graph, x, offsets, objective, integer, tol=1e-5):
    """Independently replay paths and aggregate physical balances; raise if invalid."""
    paths = decompose_paths(graph, x[:graph.n_arcs])
    coverage = np.zeros(inst.n_trips); truck_grid = np.zeros(inst.T)
    truck_chg = np.zeros(inst.T); weighted_throughput = 0.0; weighted_discharge = 0.0
    trips = {tr.idx: tr for tr in inst.trips}
    stations = set(inst.charge_locs)
    for path in paths:
        weight = path["weight"]
        if integer and abs(weight - round(weight)) > tol:
            raise ValueError("Noninteger path weight in integer incumbent")
        if not path["tasks"] or len(set(path["tasks"])) != len(path["tasks"]):
            raise ValueError("Empty-task or repeated-task path")
        u = graph.source
        for a in path["arcs"]:
            if int(graph.tail[a]) != u:
                raise ValueError("Discontinuous decomposed route")
            st = graph.states[u]; en = graph.states[graph.head[a]]
            t, loc, si, served = (int(v) for v in st)
            nt, nloc, nsi, nserved = (int(v) for v in en)
            kind = int(graph.kind[a]); e = float(graph.energy[a]); tid = int(graph.task[a])
            expected_delta = 0.0
            if kind == WAIT:
                ok = nt == t + 1 and nloc == loc and nserved == served
            elif kind in (CHARGE, DISCHARGE):
                ok = (nt == t + 1 and nloc == loc and loc in stations and nserved == served
                      and abs(e) <= inst.rho + tol and (e > 0 if kind == CHARGE else e < 0))
                expected_delta = e
            elif kind == TRAVEL:
                ok = nt == t + inst.deadhead_time(loc, nloc) and nserved == served and nloc != loc
                expected_delta = -inst.deadhead_energy(loc, nloc)
            elif kind == TASK:
                tr = trips[tid]
                ok = (t == tr.start and nt == tr.end and loc == tr.sloc and nloc == tr.eloc
                      and nserved == 1)
                expected_delta = -tr.energy; coverage[tid] += weight
            else:
                raise ValueError("Unknown arc kind")
            if not ok or abs((nsi - si) * graph.step - expected_delta) > tol:
                raise ValueError(f"Physical transition mismatch for arc {a}")
            if kind not in (CHARGE, DISCHARGE) and abs(e) > tol:
                raise ValueError("Non-energy arc draws grid energy")
            truck_grid[t] += weight * e; truck_chg[t] += weight * max(e, 0.0)
            weighted_throughput += weight * abs(e); weighted_discharge += weight * max(-e, 0.0)
            u = int(graph.head[a])
        if u != graph.sink:
            raise ValueError("Route does not finish at full-charge depot terminal")
    f, g0, c0, d0, s0, nb0 = (offsets[k] for k in ("fleet", "g", "charge", "discharge", "soc", "nb"))
    g=x[g0:g0+inst.T]; charge=x[c0:c0+inst.T]; discharge=x[d0:d0+inst.T]
    soc=x[s0:s0+inst.T+1]; nb=float(x[nb0])
    fleet = sum(p["weight"] for p in paths)
    cap = np.broadcast_to(np.asarray(inst.gen_cap), (inst.T,))
    residuals = {
        "coverage": float(np.max(abs(coverage - 1.0), initial=0.0)),
        "fleet": abs(fleet - x[f]),
        "power": float(np.max(np.maximum(inst.Delta + truck_grid + charge - discharge - g, 0), initial=0.0)),
        "bess_dynamics": float(np.max(abs(np.diff(soc) - charge + discharge), initial=0.0)),
        "bess_periodic": abs(float(soc[-1] - soc[0])),
        "bess_capacity": float(np.max(np.maximum(soc - inst.G * nb, 0), initial=0.0)),
        "bess_rate": float(max(np.max(charge-inst.rho*nb, initial=0.0), np.max(discharge-inst.rho*nb, initial=0.0))),
        "generation_cap": float(np.max(np.maximum(g-cap, 0), initial=0.0)),
        "charging_cap": float(np.max(np.maximum(truck_chg + charge-inst.charge_cap, 0), initial=0.0)),
        "nonnegative": float(np.max(np.maximum(-x, 0), initial=0.0)),
        "nb_integrality": abs(nb-round(nb)) if integer else 0.0,
    }
    replay_obj = (inst.c_v * fleet + inst.c_b * nb + inst.c_g * float(g.sum())
                  + inst.eps_pen * (weighted_throughput + float(charge.sum()+discharge.sum()))
                  + getattr(inst, "deg_cost", 0.0) * (weighted_discharge + float(discharge.sum())))
    residuals["objective"] = abs(replay_obj-objective)
    if any(v > tol * max(1.0, abs(objective)) if k == "objective" else v > tol
           for k, v in residuals.items()):
        raise ValueError(f"Incumbent replay failed: {residuals}")
    # State sequences make the schedule independently readable without rebuilding graph IDs.
    schedules = [{"weight": p["weight"], "tasks": p["tasks"],
                  "states": [graph.states[graph.source].tolist()]
                            + [graph.states[graph.head[a]].tolist() for a in p["arcs"]],
                  "kinds": [KIND_NAMES[int(graph.kind[a])] for a in p["arcs"]],
                  "energy": [float(graph.energy[a]) for a in p["arcs"]]} for p in paths]
    return {"passed": True, "residuals": residuals, "fleet": float(fleet), "nb": nb,
            "replayed_objective": float(replay_obj), "paths": schedules,
            "generation": g.tolist(), "battery_charge": charge.tolist(),
            "battery_discharge": discharge.tolist(), "battery_soc": soc.tolist()}


def solve_arc_flow(inst, relax: bool, time_limit: float, log_path, threads=1) -> dict[str, Any]:
    """Solve the exact pilot DAG formulation; return JSON-safe diagnostics/schedules."""
    started = time.perf_counter()
    if not np.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("A positive finite end-to-end time limit is required")
    if threads != 1:
        raise ValueError("The matched pilot protocol requires threads=1")
    import gurobipy as gp
    from gurobipy import GRB
    graph = build_graph(inst)
    graph_done = time.perf_counter()
    c, lb, ub, Aeq, beq, Aub, bub, offsets = _matrices(inst, graph)
    result = {"method": "arc_flow_lp" if relax else "arc_flow_mip", "relax": bool(relax),
              "n_tasks": inst.n_trips, "time_limit_seconds": float(time_limit),
              "graph_seconds": graph_done-started, "graph_nodes": graph.n_nodes,
              "graph_arcs": graph.n_arcs, "unpruned_states": graph.unpruned_states,
              "unpruned_arcs": graph.unpruned_arcs, "objective": None, "bound": None,
              "gap": None, "solution_count": 0, "validation": None,
              "threads": 1, "seed": 0, "solver_version": list(gp.gurobi.version())}
    if log_path is not None:
        log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
        result["log_path"] = str(log_path.resolve())
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 1 if log_path is not None else 0)
        env.setParam("LogToConsole", 0)
        if log_path is not None:
            env.setParam("LogFile", str(log_path))
        env.start()
        with gp.Model("direct_dp_dag", env=env) as model:
            model.Params.Threads = 1; model.Params.Seed = 0
            model.Params.MIPGap = 1e-6; model.Params.FeasibilityTol = 1e-8
            model.Params.OptimalityTol = 1e-8; model.Params.IntFeasTol = 1e-8
            vtype = np.full(len(c), GRB.CONTINUOUS)
            if not relax:
                vtype[:graph.n_arcs + 1] = GRB.INTEGER; vtype[offsets["nb"]] = GRB.INTEGER
            x = model.addMVar(len(c), lb=lb, ub=ub, obj=c, vtype=vtype, name="v")
            model.addMConstr(Aeq, x, "=", beq, name="eq")
            model.addMConstr(Aub, x, "<", bub, name="ub")
            model.update()
            built = time.perf_counter()
            result.update(model_build_seconds=built-graph_done, variables=model.NumVars,
                          constraints=model.NumConstrs, nonzeros=model.NumNZs,
                          integer_variables=model.NumIntVars, binary_variables=model.NumBinVars)
            remaining = time_limit-(built-started)
            result["solver_budget_seconds"] = max(0.0, remaining)
            if remaining <= 0:
                result.update(status="budget_exhausted_before_optimize", native_status=None,
                              solve_seconds=0.0, total_seconds=time.perf_counter()-started)
                return result
            model.Params.TimeLimit = remaining
            solve_start = time.perf_counter(); model.optimize(); solved = time.perf_counter()
            names = {GRB.OPTIMAL:"optimal", GRB.INFEASIBLE:"infeasible", GRB.INF_OR_UNBD:"infeasible_or_unbounded",
                     GRB.UNBOUNDED:"unbounded", GRB.TIME_LIMIT:"time_limit", GRB.INTERRUPTED:"interrupted",
                     GRB.NUMERIC:"numeric", GRB.SUBOPTIMAL:"suboptimal"}
            result.update(status=names.get(model.Status, f"status_{model.Status}"), native_status=model.Status,
                          solve_seconds=solved-solve_start, solver_runtime_seconds=model.Runtime,
                          solution_count=model.SolCount, node_count=float(model.NodeCount),
                          iterations=float(model.IterCount), solve_end_to_end_seconds=solved-started)
            for attr, key in (("ObjBound", "bound"), ("MIPGap", "gap"), ("MaxMemUsed", "solver_peak_memory_gb")):
                try:
                    val = float(getattr(model, attr)); result[key] = val if math.isfinite(val) else None
                except (AttributeError, gp.GurobiError):
                    pass
            if model.SolCount:
                result["objective"] = float(model.ObjVal)
                if relax and model.Status == GRB.OPTIMAL:
                    result["bound"] = float(model.ObjVal); result["gap"] = 0.0
                vec = np.asarray(x.X)
                result["validation"] = replay_solution(inst, graph, vec, offsets, model.ObjVal, not relax)
            result["validation_seconds"] = time.perf_counter()-solved
            result["total_seconds"] = time.perf_counter()-started
    return result
