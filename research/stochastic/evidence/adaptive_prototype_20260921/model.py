"""Fixed-skeleton stochastic energy LP; all active controls obey information.

Only NumPy and SciPy are needed. This is an energy subproblem, not route pricing.
The node at slot t is identified by observations[0:t+1]: its newest signal is
available BEFORE the slot's truck/BESS/generator controls are selected. Positive
unused supply may spill passively, as in the reference balance inequality.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

Mode = Literal["open_loop", "tree", "perfect_information"]


@dataclass(frozen=True)
class Trip:
    name: str
    start: int
    end: int
    energy: float


@dataclass(frozen=True)
class Truck:
    name: str
    capacity: float
    rate: float
    initial: float
    terminal: float
    connected: tuple[bool, ...]
    withdrawal: tuple[float, ...]
    trips: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    name: str
    probability: float
    delta: tuple[float, ...]
    observations: tuple[str, ...]


@dataclass(frozen=True)
class Problem:
    trips: tuple[Trip, ...]
    trucks: tuple[Truck, ...]
    scenarios: tuple[Scenario, ...]
    generation_cap: tuple[float, ...]
    generation_cost: tuple[float, ...]
    charging_cap: tuple[float, ...]
    bess_capacity: float = 0.0
    bess_rate: float = 0.0
    bess_initial: float = 0.0
    bess_terminal: float = 0.0
    truck_charge_efficiency: float = 1.0
    bess_charge_efficiency: float = 1.0
    throughput_cost: float = 0.05
    discharge_cost: float = 0.01
    fixed_asset_cost: float = 0.0

    @property
    def T(self) -> int:
        return len(self.generation_cap)

    def validate(self) -> dict[str, int]:
        T = self.T
        if T < 1 or not self.scenarios or not self.trucks:
            raise ValueError("A nonempty horizon, scenario set, and fleet are required")
        if len({s.name for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario names must be unique")
        if len({v.name for v in self.trucks}) != len(self.trucks):
            raise ValueError("Truck names must be unique")
        if len({r.name for r in self.trips}) != len(self.trips):
            raise ValueError("Trip names must be unique")
        for a in (self.generation_cap, self.generation_cost, self.charging_cap):
            if len(a) != T or any(np.isnan(v) or v < 0 for v in a):
                raise ValueError("Cap/cost vectors need T nonnegative entries")
        if not np.isfinite(self.generation_cost).all():
            raise ValueError("Generation costs must be finite")
        p = [s.probability for s in self.scenarios]
        if not np.isfinite(p).all() or min(p) <= 0 or abs(sum(p) - 1) > 1e-10:
            raise ValueError("Scenario probabilities must be positive and sum to one")
        for s in self.scenarios:
            if len(s.delta) != T or len(s.observations) != T or not np.isfinite(s.delta).all():
                raise ValueError("Every scenario needs T finite loads and T observations")
        for eta in (self.truck_charge_efficiency, self.bess_charge_efficiency):
            if not 0 < eta <= 1:
                raise ValueError("Charging efficiency must be in (0, 1]")
        if self.throughput_cost <= 0 or self.discharge_cost < 0:
            raise ValueError("Use positive throughput cost and nonnegative degradation")
        if min(self.bess_capacity, self.bess_rate, self.bess_initial, self.bess_terminal) < 0:
            raise ValueError("BESS parameters must be nonnegative")
        if max(self.bess_initial, self.bess_terminal) > self.bess_capacity:
            raise ValueError("BESS boundary energy exceeds capacity")
        trip_by_name = {r.name: r for r in self.trips}
        for r in self.trips:
            if not 0 <= r.start < r.end <= T or r.energy < 0:
                raise ValueError("Invalid trip interval/energy")
        coverage = Counter(r for v in self.trucks for r in v.trips)
        if set(coverage) != set(trip_by_name) or any(n != 1 for n in coverage.values()):
            raise ValueError("Every required trip must be assigned exactly once")
        for v in self.trucks:
            if len(v.connected) != T or len(v.withdrawal) != T:
                raise ValueError("Each skeleton needs T parking and withdrawal entries")
            if min(v.capacity, v.rate, v.initial, v.terminal, *v.withdrawal) < 0:
                raise ValueError("Truck energy parameters must be nonnegative")
            if max(v.initial, v.terminal) > v.capacity:
                raise ValueError("Truck boundary energy exceeds capacity")
            occupied = np.zeros(T, dtype=int)
            trip_withdrawal = np.zeros(T)
            for name in v.trips:
                r = trip_by_name[name]
                occupied[r.start:r.end] += 1
                trip_withdrawal[r.start] += r.energy
            if np.any(occupied > 1) or np.any(occupied & np.array(v.connected, dtype=int)):
                raise ValueError("Overlapping trips or a charger connection during a trip")
            if np.any(np.asarray(v.withdrawal) + 1e-10 < trip_withdrawal):
                raise ValueError("Skeleton withdrawal omits required trip traction")
        return dict(coverage)


def node_key(scenario: Scenario, t: int, mode: Mode):
    if mode == "open_loop":
        return (t,)
    if mode == "tree":
        return scenario.observations[:t + 1]
    if mode == "perfect_information":
        return (scenario.name, t)
    raise ValueError(f"Unknown information mode: {mode}")


def solve(problem: Problem, mode: Mode, *, truck_mode: Mode | None = None,
          fixed_truck_profiles: tuple[tuple[float, ...], ...] | None = None) -> dict:
    """Minimize expected operating cost with hard service/boundary constraints.

    truck_mode='open_loop', mode='tree' is the extra committed-truck comparator:
    BESS and generation obey the same observed history as in the adaptive arm.
    It isolates vehicle-energy flexibility without giving other assets foresight.
    fixed_truck_profiles optionally pins one signed grid-energy vector per truck
    (positive charge, negative discharge), shared by every scenario.
    No emergency supply is hidden in this LP; infeasibility is returned explicitly.
    """
    coverage = problem.validate()
    truck_mode = mode if truck_mode is None else truck_mode
    T, J, W = problem.T, len(problem.trucks), len(problem.scenarios)
    pins = None if fixed_truck_profiles is None else np.asarray(fixed_truck_profiles, dtype=float)
    if pins is not None:
        if pins.shape != (J, T) or not np.isfinite(pins).all():
            raise ValueError("Fixed profiles must have finite shape (trucks, slots)")
        limits = np.array([[v.rate if v.connected[t] else 0. for t in range(T)] for v in problem.trucks])
        if np.any(np.abs(pins) > limits + 1e-10):
            raise ValueError("Fixed profile exceeds truck rate or charges away from its station")
    n = 0
    idx = {}
    bounds = []
    objective = []
    eq_rows, ub_rows, eq_rhs, ub_rhs = [], [], [], []

    def variable(key, lower, upper, cost=0.0):
        nonlocal n
        idx[key] = n
        bounds.append((lower, upper))
        objective.append(cost)
        n += 1
        return n - 1

    def eq(coefs, rhs):
        eq_rows.append(coefs)
        eq_rhs.append(rhs)

    def ub(coefs, rhs):
        ub_rows.append(coefs)
        ub_rhs.append(rhs)

    # States are scenario indexed; common initial states plus shared controls
    # and deterministic traction imply equal states on every shared history.
    for w, scenario in enumerate(problem.scenarios):
        p = scenario.probability
        for j, truck in enumerate(problem.trucks):
            for t in range(T):
                rate = truck.rate if truck.connected[t] else 0.0
                pc = None if pins is None else max(pins[j, t], 0.)
                pd = None if pins is None else max(-pins[j, t], 0.)
                variable((w, "tc", j, t), 0 if pc is None else pc, rate if pc is None else pc,
                         p * problem.throughput_cost)
                variable((w, "td", j, t), 0 if pd is None else pd, rate if pd is None else pd,
                         p * (problem.throughput_cost + problem.discharge_cost))
            for t in range(T + 1):
                fixed = truck.initial if t == 0 else truck.terminal if t == T else None
                variable((w, "ts", j, t), 0 if fixed is None else fixed,
                         truck.capacity if fixed is None else fixed)
            for t in range(T):
                eq({idx[w, "ts", j, t + 1]: 1, idx[w, "ts", j, t]: -1,
                    idx[w, "tc", j, t]: -problem.truck_charge_efficiency,
                    idx[w, "td", j, t]: 1}, -truck.withdrawal[t])
        for t in range(T):
            variable((w, "bc", t), 0, problem.bess_rate, p * problem.throughput_cost)
            variable((w, "bd", t), 0, problem.bess_rate,
                     p * (problem.throughput_cost + problem.discharge_cost))
            variable((w, "g", t), 0, problem.generation_cap[t], p * problem.generation_cost[t])
        for t in range(T + 1):
            fixed = problem.bess_initial if t == 0 else problem.bess_terminal if t == T else None
            variable((w, "bs", t), 0 if fixed is None else fixed,
                     problem.bess_capacity if fixed is None else fixed)
        for t in range(T):
            eq({idx[w, "bs", t + 1]: 1, idx[w, "bs", t]: -1,
                idx[w, "bc", t]: -problem.bess_charge_efficiency, idx[w, "bd", t]: 1}, 0)
            balance = {idx[w, "g", t]: -1, idx[w, "bc", t]: 1, idx[w, "bd", t]: -1}
            charger = {idx[w, "bc", t]: 1}
            for j in range(J):
                balance[idx[w, "tc", j, t]] = 1
                balance[idx[w, "td", j, t]] = -1
                charger[idx[w, "tc", j, t]] = 1
            ub(balance, -scenario.delta[t])
            if np.isfinite(problem.charging_cap[t]):
                ub(charger, problem.charging_cap[t])

    def controls(w, t, family):
        if family == "truck":
            return [idx[w, k, j, t] for j in range(J) for k in ("tc", "td")]
        return [idx[w, k, t] for k in ("bc", "bd", "g")]

    na_rows = 0
    for family, information in (("truck", truck_mode), ("other", mode)):
        for t in range(T):
            groups = defaultdict(list)
            for w, scenario in enumerate(problem.scenarios):
                groups[node_key(scenario, t, information)].append(w)
            for group in groups.values():
                representative = controls(group[0], t, family)
                for w in group[1:]:
                    for a, b in zip(representative, controls(w, t, family)):
                        eq({a: 1, b: -1}, 0)
                        na_rows += 1

    def matrix(rows):
        rr, cc, vv = [], [], []
        for i, row in enumerate(rows):
            for j, value in row.items():
                rr.append(i)
                cc.append(j)
                vv.append(value)
        return coo_matrix((vv, (rr, cc)), shape=(len(rows), n)).tocsr()

    Aeq, Aub = matrix(eq_rows), matrix(ub_rows)
    beq, bub, c = np.array(eq_rhs), np.array(ub_rhs), np.array(objective)
    opt = linprog(c, A_eq=Aeq, b_eq=beq, A_ub=Aub, b_ub=bub,
                  bounds=bounds, method="highs")
    common = dict(mode=mode, truck_mode=truck_mode, success=bool(opt.success),
                  fixed_truck_profiles=None if pins is None else pins.tolist(),
                  solver_status=int(opt.status), message=opt.message, coverage=coverage,
                  variables=n, equalities=len(eq_rows), inequalities=len(ub_rows),
                  nonanticipativity_equalities=na_rows)
    if not opt.success:
        return common | dict(operating_cost=None, total_cost=None)
    x = opt.x
    lo = np.array([v[0] for v in bounds])
    hi = np.array([v[1] for v in bounds])
    finite_hi = np.isfinite(hi)
    dual_value = float(beq @ opt.eqlin.marginals + bub @ opt.ineqlin.marginals
                       + lo @ opt.lower.marginals
                       + hi[finite_hi] @ opt.upper.marginals[finite_hi])
    residual = max(0., float(np.max(np.abs(Aeq @ x - beq))),
                   float(np.max(Aub @ x - bub)), float(np.max(lo - x)),
                   float(np.max(x - hi)))
    scenarios = {}
    max_simultaneous = 0.0
    for w, scenario in enumerate(problem.scenarios):
        truck_charge = np.array([[x[idx[w, "tc", j, t]] for t in range(T)] for j in range(J)])
        truck_discharge = np.array([[x[idx[w, "td", j, t]] for t in range(T)] for j in range(J)])
        truck_soc = [[float(x[idx[w, "ts", j, t]]) for t in range(T + 1)] for j in range(J)]
        bess_charge = np.array([x[idx[w, "bc", t]] for t in range(T)])
        bess_discharge = np.array([x[idx[w, "bd", t]] for t in range(T)])
        generation = np.array([x[idx[w, "g", t]] for t in range(T)])
        passive_spill = (generation + truck_discharge.sum(axis=0) + bess_discharge
                         - truck_charge.sum(axis=0) - bess_charge - np.array(scenario.delta))
        charge = truck_charge.sum() + bess_charge.sum()
        discharge = truck_discharge.sum() + bess_discharge.sum()
        operating = (generation @ np.array(problem.generation_cost)
                     + problem.throughput_cost * (charge + discharge)
                     + problem.discharge_cost * discharge)
        max_simultaneous = max(max_simultaneous, float(np.minimum(truck_charge, truck_discharge).max()),
                               float(np.minimum(bess_charge, bess_discharge).max()))
        scenarios[scenario.name] = dict(probability=scenario.probability,
            delta=list(scenario.delta), observation_history=[list(scenario.observations[:t+1]) for t in range(T)],
            truck_charge=truck_charge.tolist(), truck_discharge=truck_discharge.tolist(), truck_soc=truck_soc,
            bess_charge=bess_charge.tolist(), bess_discharge=bess_discharge.tolist(),
            bess_soc=[float(x[idx[w, "bs", t]]) for t in range(T + 1)],
            generation=generation.tolist(), passive_spill=passive_spill.tolist(), operating_cost=float(operating))
    return common | dict(operating_cost=float(opt.fun), fixed_asset_cost=problem.fixed_asset_cost,
        total_cost=float(opt.fun + problem.fixed_asset_cost), maximum_primal_residual=residual,
        primal_dual_gap=abs(float(opt.fun) - dual_value), maximum_simultaneous_flow=max_simultaneous,
        scenarios=scenarios)
