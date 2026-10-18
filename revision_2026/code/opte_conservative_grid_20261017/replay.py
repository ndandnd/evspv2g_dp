"""Physical replay of route columns against the TRUE energies (independent of the DP).

The replay never reads the grid levels or the grid energy shifts. It reads only the
route events (which deadhead, which task, which block a grid action happens in, and
the grid amount the column books in that block) and recomputes everything else from
the instance: task times/locations/energies, deadhead times and energies
(dist x energy_per_dist), the true per-block limit rho, capacity G.

Physical execution rule (part of the conservative method, not a post-hoc repair):
  * traction: the true task / deadhead energy is used;
  * discharge: exactly the booked amount leaves the battery;
  * charge: the booked amount is drawn, except that charging stops when the battery
    is full: stored = min(booked*(1-eta), G - s). The unused part is 'clipped'.
Checks: route continuity (time and place), task times and places, charging only at
charging locations and at most once per block, booked profile equals the column's
energy vector, coverage vector equals the tasks on the route, |grid| <= rho,
0 <= SoC <= G after every event, final SoC = G (full recharge).
"""
from __future__ import annotations
import numpy as np

TOL = 1e-7


def singleton_trace(inst, col):
    """Event list for a frozen single-task seed column (no DP trace): depot -> start
    location, the task, end location -> depot, then the booked grid profile."""
    (idx,) = np.flatnonzero(col.a > 0.5)
    tr = inst.trips[int(idx)]
    assert tr.idx == int(idx)
    o = inst.depot
    ev = []
    if tr.sloc != o:
        d = inst.deadhead_time(o, tr.sloc)
        ev.append(dict(kind="dead", start=tr.start - d, end=tr.start, frm=o, to=tr.sloc))
    ev.append(dict(kind="task", start=tr.start, end=tr.end, frm=tr.sloc, to=tr.eloc, task=tr.idx))
    if tr.eloc != o:
        ev.append(dict(kind="dead", start=tr.end, end=tr.end + inst.deadhead_time(tr.eloc, o),
                       frm=tr.eloc, to=o))
    for t in np.flatnonzero(np.abs(col.e) > 1e-12):
        ev.append(dict(kind="grid", start=int(t), end=int(t) + 1, frm=o, to=o, grid=float(col.e[t])))
    return ev


def replay(inst, col):
    if getattr(col, "trace", None) is None:
        events = singleton_trace(inst, col)
    elif not getattr(col, "trace_complete", False):
        return {"ok": False, "reasons": ["trace_incomplete"]}
    else:
        events = col.trace
    G, rho, eta, T = inst.G, inst.rho, inst.eta, inst.T
    stations = set(getattr(inst, "charge_locs", None) or [inst.depot])
    reasons = []
    events = sorted(events, key=lambda ev: (ev["start"], ev["end"]))
    t, loc, s = 0, inst.depot, G
    s_min_seen, s_max_seen, clipped = s, s, 0.0
    booked = np.zeros(T); executed = np.zeros(T); tasks = []
    grid_blocks = set()
    step = getattr(col, "step", None)
    invariant_violations = 0          # proof check: real SoC >= grid SoC after every event
    for ev in events:
        if ev["start"] < t - 0:
            reasons.append("overlap_or_time_reversal")
        if ev["frm"] != loc:
            reasons.append("location_discontinuity")
        k = ev["kind"]
        if k == "dead":
            a, b = ev["frm"], ev["to"]
            if a == b or ev["end"] - ev["start"] != inst.deadhead_time(a, b):
                reasons.append("deadhead_time")
            s -= float(inst.dist[a, b] * inst.energy_per_dist)
        elif k == "task":
            tr = inst.trips[ev["task"]]
            if (tr.idx != ev["task"] or tr.start != ev["start"] or tr.end != ev["end"]
                    or tr.sloc != ev["frm"] or tr.eloc != ev["to"]):
                reasons.append("task_mismatch")
            s -= float(tr.energy)
            tasks.append(tr.idx)
        elif k == "grid":
            if ev["frm"] not in stations or ev["to"] != ev["frm"]:
                reasons.append("grid_not_at_station")
            if ev["end"] != ev["start"] + 1 or ev["start"] in grid_blocks:
                reasons.append("grid_block")
            grid_blocks.add(ev["start"])
            e = float(ev["grid"])
            booked[ev["start"]] += e
            if abs(e) > rho + TOL:
                reasons.append("rate")
            if e > 0:
                gain = (1 - eta) * e
                stored = min(gain, max(G - s, 0.0))
                clipped += gain - stored
                s += stored
                executed[ev["start"]] += stored / (1 - eta)
            else:
                s += e
                executed[ev["start"]] += e
        else:
            reasons.append("unknown_event")
        t, loc = ev["end"], ev["to"]
        if step is not None and "lev_after" in ev and s < ev["lev_after"] * step - TOL:
            invariant_violations += 1
        s_min_seen, s_max_seen = min(s_min_seen, s), max(s_max_seen, s)
        if s < -TOL:
            reasons.append("negative_soc")
        if s > G + TOL:
            reasons.append("above_capacity")
    if loc != inst.depot or t > T:
        reasons.append("does_not_end_at_depot_in_horizon")
    if abs(s - G) > TOL:
        reasons.append("final_soc_not_full")
    if sorted(tasks) != sorted(np.flatnonzero(col.a > 0.5).tolist()) or len(set(tasks)) != len(tasks):
        reasons.append("coverage_mismatch")
    if np.max(np.abs(booked - col.e)) > 1e-9:
        reasons.append("profile_mismatch")
    return {"ok": not reasons, "reasons": sorted(set(reasons)),
            "clipped_kwh": clipped * 100, "final_kwh": s * 100,
            "min_soc_kwh": s_min_seen * 100, "max_soc_kwh": s_max_seen * 100,
            "booked_charge_kwh": float(np.maximum(booked, 0).sum() * 100),
            "executed_charge_kwh": float(np.maximum(executed, 0).sum() * 100),
            "feasible_as_booked": (not reasons) and clipped * 100 <= 1e-6,
            "real_below_grid_events": invariant_violations,
            "executed": executed}


def replay_unclipped(inst, col):
    """Same replay but WITHOUT the stop-when-full rule (diagnostic only)."""
    G = inst.G
    events = singleton_trace(inst, col) if getattr(col, "trace", None) is None else col.trace
    s, smin, smax = G, G, G
    for ev in sorted(events, key=lambda ev: (ev["start"], ev["end"])):
        if ev["kind"] == "dead":
            s -= float(inst.dist[ev["frm"], ev["to"]] * inst.energy_per_dist)
        elif ev["kind"] == "task":
            s -= float(inst.trips[ev["task"]].energy)
        else:
            e = float(ev["grid"]); s += (1 - inst.eta) * e if e > 0 else e
        smin, smax = min(smin, s), max(smax, s)
    return {"final_kwh": s * 100, "min_soc_kwh": smin * 100, "max_soc_kwh": smax * 100}
