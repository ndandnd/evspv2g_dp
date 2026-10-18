"""Find and physically replay graph paths for selected vendor truck columns.

This performs reachability, never optimization.  It is intended for validation
outside benchmark timing.  Matching a column's task vector and grid-energy
profile establishes an actual path witness, not merely an objective match.
"""
from __future__ import annotations

from typing import Any

import numpy as np

try:
    from .arc_flow import CHARGE, DISCHARGE, KIND_NAMES, TASK, TRAVEL, WAIT, Graph
except ImportError:
    from arc_flow import CHARGE, DISCHARGE, KIND_NAMES, TASK, TRAVEL, WAIT, Graph


def _fail(reason: str, **details) -> dict[str, Any]:
    return {"passed": False, "reason": reason, **details}


def find_column_path(inst, graph: Graph, col, tol: float = 1e-7) -> dict[str, Any]:
    """Find one full-recharge, task-serving DAG path with exactly col.a and col.e.

    An arc may not cross the start of a required task unless it is that task's
    own arc.  All other task arcs are excluded.  Every block of each non-energy
    arc must have zero column draw, and an energy arc must match the column's
    draw in its one block.  A topological reachability sweep then needs no
    additional task-history state: each required start must have been served.
    The returned path is independently replayed against instance data.
    """
    if not np.isfinite(tol) or tol <= 0:
        return _fail("invalid_tolerance")
    if getattr(col, "kind", None) != "truck":
        return _fail("artificial_column" if getattr(col, "kind", None) == "artificial"
                     else "unsupported_column_kind")
    coverage = np.asarray(col.a, dtype=float)
    profile = np.asarray(col.e, dtype=float)
    if coverage.shape != (inst.n_trips,) or profile.shape != (inst.T,):
        return _fail("column_dimensions")
    if not np.all(np.isfinite(coverage)) or not np.all(np.isfinite(profile)):
        return _fail("nonfinite_column")
    if not np.isfinite(col.fixed_cost):
        return _fail("nonfinite_column_cost")
    if np.max(np.minimum(abs(coverage), abs(coverage - 1)), initial=0) > tol:
        return _fail("nonbinary_task_vector")
    chosen = np.flatnonzero(coverage > .5)
    if not len(chosen):
        return _fail("no_task_served")
    if abs(inst.eta) > tol:
        return _fail("unsupported_charging_loss")
    if abs(graph.step - inst.soc_step) > tol or graph.step <= 0:
        return _fail("graph_step_mismatch")
    off_grid = np.max(abs(profile / graph.step - np.rint(profile / graph.step)), initial=0.0)
    if off_grid > tol:
        return _fail("off_grid_profile", max_residual=float(off_grid))
    if graph.states.ndim != 2 or graph.states.shape[1] != 4:
        return _fail("invalid_graph_state_shape")
    if not (0 <= graph.source < graph.n_nodes and 0 <= graph.sink < graph.n_nodes):
        return _fail("invalid_graph_endpoints")
    expected_source = np.array([0, inst.depot, inst.G / graph.step, 0])
    expected_sink = np.array([inst.T, inst.depot, inst.G / graph.step, 1])
    boundary_error = max(float(np.max(abs(graph.states[graph.source] - expected_source))),
                         float(np.max(abs(graph.states[graph.sink] - expected_sink))))
    if boundary_error > tol:
        return _fail("graph_boundary_mismatch", max_residual=boundary_error)
    by_task = {int(tr.idx): tr for tr in inst.trips}
    if set(by_task) != set(range(inst.n_trips)):
        return _fail("invalid_instance_task_indices")
    selected_tasks = sorted((by_task[int(i)] for i in chosen), key=lambda tr: (tr.start, tr.idx))
    if any(left.end > right.start for left, right in zip(selected_tasks, selected_tasks[1:])):
        return _fail("overlapping_selected_tasks")

    tail_t = graph.states[graph.tail, 0]
    head_t = graph.states[graph.head, 0]
    if np.any(tail_t < 0) or np.any(head_t > inst.T) or np.any(head_t <= tail_t):
        return _fail("graph_not_positive_time_dag")
    required_starts = np.zeros(inst.T, dtype=int)
    for tr in selected_tasks:
        if not (0 <= tr.start < tr.end <= inst.T):
            return _fail("invalid_selected_task_time")
        required_starts[tr.start] += 1
    start_prefix = np.r_[0, np.cumsum(required_starts)]
    crossed = start_prefix[head_t] - start_prefix[tail_t]
    task_arc = graph.kind == TASK
    energy_arc = np.isin(graph.kind, [CHARGE, DISCHARGE])
    is_chosen = np.zeros(inst.n_trips, dtype=bool)
    is_chosen[chosen] = True
    chosen_task_arc = np.zeros(graph.n_arcs, dtype=bool)
    valid_task_id = task_arc & (graph.task >= 0) & (graph.task < inst.n_trips)
    chosen_task_arc[valid_task_id] = is_chosen[graph.task[valid_task_id]]
    # Checking each chosen task's exact event time also prevents a malformed
    # graph from satisfying another task's required start with the same ID.
    for task_id in chosen:
        tr = by_task[int(task_id)]
        mask = chosen_task_arc & (graph.task == task_id)
        chosen_task_arc[mask] &= (tail_t[mask] == tr.start) & (head_t[mask] == tr.end)
    allowed = np.where(task_arc, chosen_task_arc & (crossed == 1), crossed == 0)
    active_prefix = np.r_[0, np.cumsum(abs(profile) > tol)]
    zero_span = active_prefix[head_t] == active_prefix[tail_t]
    energy_match = ((head_t == tail_t + 1)
                    & (abs(graph.energy - profile[tail_t]) <= tol))
    allowed &= np.where(energy_arc, energy_match, zero_span & (abs(graph.energy) <= tol))
    indices = np.flatnonzero(allowed)
    # Stable topological ordering works even if graph storage order changes.
    if len(indices) and np.any(np.diff(tail_t[indices]) < 0):
        indices = indices[np.argsort(tail_t[indices], kind="stable")]
    reached = np.zeros(graph.n_nodes, dtype=bool)
    reached[graph.source] = True
    parent = np.full(graph.n_nodes, -1, dtype=np.int64)
    for arc in indices:
        u, v = int(graph.tail[arc]), int(graph.head[arc])
        if reached[u] and not reached[v]:
            reached[v] = True
            parent[v] = arc
    if not reached[graph.sink]:
        return _fail("no_matching_graph_path", required_task_ids=chosen.tolist(),
                     allowed_arcs=int(len(indices)), reachable_states=int(reached.sum()))
    path = []
    current = graph.sink
    while current != graph.source:
        arc = int(parent[current])
        if arc < 0 or len(path) >= graph.n_nodes:
            return _fail("invalid_parent_chain")
        path.append(arc)
        current = int(graph.tail[arc])
    path.reverse()
    return _replay(inst, graph, col, path, tol)


def _replay(inst, graph: Graph, col, path: list[int], tol: float) -> dict[str, Any]:
    """Use original physical data, not graph energy shifts, to replay the path."""
    by_task = {int(tr.idx): tr for tr in inst.trips}
    station_set = set(inst.charge_locs)
    actual_a, actual_e = np.zeros(inst.n_trips), np.zeros(inst.T)
    physical_soc = float(inst.G)
    physical_traction = 0.0
    max_soc_error = max_bound_error = max_arc_error = 0.0
    states = [graph.states[graph.source].astype(int).tolist()]
    soc_trace = [physical_soc]
    served = 0
    previous_node = graph.source
    kinds, task_ids, energies = [], [], []
    for arc in path:
        u, v = int(graph.tail[arc]), int(graph.head[arc])
        if u != previous_node:
            return _fail("disconnected_witness")
        t, loc, soc, _ = map(int, graph.states[u])
        t2, loc2, soc2, k2 = map(int, graph.states[v])
        kind, task_id, energy = int(graph.kind[arc]), int(graph.task[arc]), float(graph.energy[arc])
        duration = t2 - t
        traction = 0.0
        if kind == WAIT:
            if duration != 1 or loc != loc2 or task_id != -1:
                return _fail("invalid_wait_arc")
            max_arc_error = max(max_arc_error, abs(energy))
        elif kind in (CHARGE, DISCHARGE):
            if duration != 1 or loc != loc2 or loc not in station_set or task_id != -1:
                return _fail("invalid_connection_arc")
            if (kind == CHARGE and energy <= 0) or (kind == DISCHARGE and energy >= 0):
                return _fail("wrong_energy_arc_sign")
            max_arc_error = max(max_arc_error, max(0.0, abs(energy) - inst.rho))
            actual_e[t] += energy
            physical_soc += (1 - inst.eta) * max(energy, 0) + min(energy, 0)
        elif kind == TRAVEL:
            if loc == loc2 or task_id != -1:
                return _fail("invalid_deadhead_arc")
            max_arc_error = max(max_arc_error, abs(duration - float(inst.dist[loc, loc2])), abs(energy))
            traction = float(inst.dist[loc, loc2]) * inst.energy_per_dist
        elif kind == TASK:
            if task_id not in by_task:
                return _fail("unknown_task_arc")
            tr = by_task[task_id]
            if (t, t2, loc, loc2) != (tr.start, tr.end, tr.sloc, tr.eloc):
                return _fail("task_event_mismatch")
            traction = float(tr.energy)
            actual_a[task_id] += 1.0
            task_ids.append(task_id)
            served = 1
            max_arc_error = max(max_arc_error, abs(energy))
        else:
            return _fail("unknown_arc_kind")
        if k2 != served:
            return _fail("served_flag_mismatch")
        physical_soc -= traction
        physical_traction += traction
        max_soc_error = max(max_soc_error, abs(physical_soc - soc2 * graph.step))
        max_bound_error = max(max_bound_error, max(0.0, -physical_soc, physical_soc - inst.G))
        previous_node = v
        states.append(graph.states[v].astype(int).tolist())
        soc_trace.append(float(physical_soc))
        kinds.append(KIND_NAMES[kind])
        energies.append(energy)
    if previous_node != graph.sink:
        return _fail("wrong_terminal_node")
    coverage_residual = float(np.max(abs(actual_a - col.a), initial=0))
    profile_residual = float(np.max(abs(actual_e - col.e), initial=0))
    boundary_residual = abs(physical_soc - inst.G)
    closure_residual = abs(float(np.sum(actual_e)) - physical_traction)
    expected_fixed_cost = inst.c_v + getattr(inst, "deg_cost", 0.0) * float(np.maximum(-actual_e, 0).sum())
    fixed_cost_residual = abs(expected_fixed_cost - col.fixed_cost)
    expected_cost = expected_fixed_cost + inst.eps_pen * float(abs(actual_e).sum())
    column_cost = col.fixed_cost + inst.eps_pen * float(abs(np.asarray(col.e)).sum())
    cost_residual = abs(expected_cost - column_cost)
    residuals = {"coverage": coverage_residual, "profile": profile_residual,
                 "soc_recursion": max_soc_error, "soc_bounds": max_bound_error,
                 "arc_physics": max_arc_error, "full_boundary": boundary_residual,
                 "daily_energy_closure": closure_residual, "fixed_cost": fixed_cost_residual,
                 "total_column_cost": cost_residual}
    largest = float(max(residuals.values()))
    passed = largest <= tol
    return {"passed": passed, "reason": "matched_and_replayed" if passed else "physical_replay_mismatch",
            "arc_indices": [int(a) for a in path], "states": states,
            "state_schema": ["time", "location", "soc_index", "served_task"],
            "kinds": kinds, "task_ids": task_ids, "energy": energies,
            "profile": actual_e.tolist(), "task_coverage": actual_a.tolist(),
            "soc": soc_trace, "traction_energy": float(physical_traction),
            "column_cost": float(expected_cost), "residuals": residuals,
            "max_residual": largest, "tolerance": tol}


def validate_selected_columns(inst, graph: Graph, cols, x, tol: float = 1e-7) -> dict[str, Any]:
    """Return physical path witnesses for every column with LP/MIP weight > tol.

    Weights may be fractional.  Selected artificial columns always fail.  Exact
    duplicate real columns share their computed witness within this call.
    """
    weights = np.asarray(x, dtype=float)
    if weights.shape != (len(cols),):
        return _fail("weight_dimensions", witnesses=[])
    if not np.all(np.isfinite(weights)) or np.any(weights < -tol):
        return _fail("invalid_weights", witnesses=[])
    if not np.isfinite(tol) or tol <= 0:
        return _fail("invalid_tolerance", witnesses=[])
    selected = np.flatnonzero(weights > tol)
    cache = {}
    witnesses = []
    artificial_mass = 0.0
    max_residual = 0.0
    for index in selected:
        col = cols[int(index)]
        if getattr(col, "kind", None) == "artificial":
            artificial_mass += float(weights[index])
        arr_a, arr_e = np.asarray(col.a), np.asarray(col.e)
        key = (getattr(col, "kind", None), arr_a.shape, arr_a.dtype.str, arr_a.tobytes(),
               arr_e.shape, arr_e.dtype.str, arr_e.tobytes(), float(col.fixed_cost))
        if key not in cache:
            cache[key] = find_column_path(inst, graph, col, tol)
        witness = cache[key]
        max_residual = max(max_residual, float(witness.get("max_residual", 0.0)))
        witnesses.append({"column_index": int(index), "weight": float(weights[index]),
                          "label": str(getattr(col, "label", "")), "witness": witness})
    passed = all(row["witness"]["passed"] for row in witnesses)
    return {"passed": passed, "reason": "all_selected_columns_witnessed" if passed else "selected_column_failure",
            "selected_count": int(len(selected)), "selected_mass": float(weights[selected].sum()),
            "artificial_mass": artificial_mass, "max_residual": max_residual,
            "distinct_witnesses": len(cache), "witnesses": witnesses, "tolerance": tol,
            "scope": "Selected real column paths only; this does not verify aggregate master constraints or column-generation optimality."}
