"""Run the reproducible tiny comparison and the common-duty counterexample."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import scipy

from model import Problem, Scenario, Trip, Truck, solve


def tiny_problem() -> Problem:
    """Two committed one-trip duties, a signal at t=2, and fixed cyclic assets.

    Net demand is identical until the reveal. Dark needs the generator's whole
    10-unit daily budget. Sunny has renewable surplus in slots 2 and 3. Units
    are normalized per slot; no empirical weather/cost claim is intended.
    """
    trips = (Trip("A", 1, 2, 1.), Trip("B", 1, 2, 1.))
    trucks = tuple(Truck(f"truck_{r.name}", 2., 1., 2., 2.,
                         (True, False, True, True, True), (0., 1., 0., 0., 0.), (r.name,))
                   for r in trips)
    scenarios = (
        Scenario("sunny", .5, (2., 2., -4., -4., 0.), ("no_signal", "no_signal", "sunny", "none", "none")),
        Scenario("dark", .5, (2., 2., 2., 2., 0.), ("no_signal", "no_signal", "dark", "none", "none")),
    )
    return Problem(trips, trucks, scenarios, (2.,)*5, (1.,)*5, (3.,)*5,
                   bess_capacity=1., bess_rate=1., bess_initial=.5, bess_terminal=.5,
                   fixed_asset_cost=6.7)


def suffix_counterexample() -> dict:
    """Finite route-choice counterexample; costs already include p_k.

    A and B are two mutually exclusive post-reveal one-trip duty options. Each
    has a different task incidence. A common-duty column must choose the same
    option in both classes. Splitting the coverage reward does not enforce that.
    """
    probabilities = np.array([.5, .5])
    costs = np.array([[0., 10.], [10., 0.]])  # [class, route A or B]
    alpha = np.array([2., 2.])
    common = probabilities @ costs - alpha
    allocated = probabilities[:, None] * (costs - alpha[None, :])
    choices = allocated.argmin(axis=1)
    return dict(
        route_task_incidence={"A": [1, 0], "B": [0, 1]},
        class_probabilities=probabilities.tolist(),
        unweighted_energy_costs=costs.tolist(), coverage_duals=alpha.tolist(),
        feasible_common_duty_reduced_costs=common.tolist(),
        common_duty_optimum=float(common.min()),
        independent_suffix_optimum_with_split_rewards=float(allocated.min(axis=1).sum()),
        independent_suffix_routes=["AB"[i] for i in choices],
        common_incidence_preserved=bool(np.all(choices == choices[0])),
        one_required_task_correct_reward=-2.,
        one_required_task_wrong_reward_in_two_suffixes=-4.,
        scope="Finite exact counterexample to independent unrestricted suffix minimization; no pricing algorithm claim.")


def oracle_gap_counterexample() -> dict:
    """Zero PI truck-flexibility value can coexist with positive causal value.

    The *same supplied vehicle profile* is pinned for both fixed-profile arms.
    All assets, duties, loads, prices, and boundary rules are otherwise identical.
    """
    base = tiny_problem()
    scenarios = (
        Scenario("late_small_surplus", .5, (1., 2., 3., 0., -1.),
                 ("no_signal", "no_signal", "late_small_surplus", "none", "none")),
        Scenario("early_large_surplus", .5, (1., 2., -2., -4., 2.),
                 ("no_signal", "no_signal", "early_large_surplus", "none", "none")),
    )
    p = replace(base, scenarios=scenarios, bess_capacity=3., bess_initial=3., bess_terminal=3.)
    profiles = ((0., 0., 0., 1., 0.),) * 2
    solutions = {
        "fixed_profile_tree": solve(p, "tree", fixed_truck_profiles=profiles),
        "adaptive_tree": solve(p, "tree"),
        "fixed_profile_perfect_information": solve(p, "perfect_information", fixed_truck_profiles=profiles),
        "adaptive_perfect_information": solve(p, "perfect_information"),
    }
    return dict(
        scope="Synthetic counterexample, not an estimate for the campaign instance",
        solutions=solutions,
        oracle_truck_flexibility_gap=solutions["fixed_profile_perfect_information"]["operating_cost"] - solutions["adaptive_perfect_information"]["operating_cost"],
        causal_truck_flexibility_gap=solutions["fixed_profile_tree"]["operating_cost"] - solutions["adaptive_tree"]["operating_cost"],
        conclusion="A zero fixed-profile/adaptive oracle gap does not bound the gain of adaptive trucks over a causal fixed-profile controller.")


def run() -> dict:
    p = tiny_problem()
    solutions = {mode: solve(p, mode) for mode in ("open_loop", "tree", "perfect_information")}
    solutions["committed_trucks_causal_dispatch"] = solve(p, "tree", truck_mode="open_loop")
    return dict(numpy_version=np.__version__, scipy_version=scipy.__version__,
                solver="SciPy linprog / HiGHS", scope="Synthetic fixed-skeleton energy LP; fixed assets and duties",
                observation="At the start of slot 2, before controls, a weather signal reveals sunny/dark. No weather signal in slots 0/1.",
                spill="Excess supply is passively discarded; no controllable generation or storage action uses unavailable information.",
                solutions=solutions, counterexample=suffix_counterexample(),
                oracle_gap_counterexample=oracle_gap_counterexample())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("results.json"))
    args = parser.parse_args()
    result = run()
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for name, solution in result["solutions"].items():
        print(f"{name}: success={solution['success']} operating={solution['operating_cost']:.6f} total={solution['total_cost']:.6f}")
    print("Counterexample:", json.dumps(result["counterexample"]))
    gap_example = result["oracle_gap_counterexample"]
    print("Oracle-gap counterexample:", json.dumps({k: gap_example[k] for k in ("oracle_truck_flexibility_gap", "causal_truck_flexibility_gap")}))
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
