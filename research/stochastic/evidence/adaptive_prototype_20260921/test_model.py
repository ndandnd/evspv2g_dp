"""Small semantic checks for information, physics, and accounting."""
from dataclasses import replace
import unittest

import numpy as np

from demo import oracle_gap_counterexample, suffix_counterexample, tiny_problem
from model import node_key, solve


class EnergyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.problem = tiny_problem()
        cls.solutions = {m: solve(cls.problem, m) for m in ("open_loop", "tree", "perfect_information")}
        cls.solutions["committed"] = solve(cls.problem, "tree", truck_mode="open_loop")

    def assertClose(self, left, right, tol=1e-7):
        np.testing.assert_allclose(left, right, atol=tol, rtol=0)

    def assertPhysics(self, p, solution):
        self.assertTrue(solution["success"], solution["message"])
        self.assertLess(solution["maximum_primal_residual"], 1e-7)
        self.assertLess(solution["primal_dual_gap"], 1e-7)
        self.assertLess(solution["maximum_simultaneous_flow"], 1e-7)
        costs = []
        for scenario in p.scenarios:
            z = solution["scenarios"][scenario.name]
            charge, discharge = np.array(z["truck_charge"]), np.array(z["truck_discharge"])
            soc = np.array(z["truck_soc"])
            for j, truck in enumerate(p.trucks):
                self.assertClose(np.diff(soc[j]), p.truck_charge_efficiency * charge[j] - discharge[j] - truck.withdrawal)
                self.assertClose([soc[j, 0], soc[j, -1]], [truck.initial, truck.terminal])
                self.assertLessEqual(float(soc[j].max()), truck.capacity + 1e-7)
                self.assertGreaterEqual(float(soc[j].min()), -1e-7)
                for t, connected in enumerate(truck.connected):
                    self.assertGreaterEqual(charge[j, t], -1e-7)
                    self.assertGreaterEqual(discharge[j, t], -1e-7)
                    self.assertLessEqual(max(charge[j, t], discharge[j, t]), (truck.rate if connected else 0) + 1e-7)
            bc, bd, bs = (np.array(z[key]) for key in ("bess_charge", "bess_discharge", "bess_soc"))
            g = np.array(z["generation"])
            self.assertClose(np.diff(bs), p.bess_charge_efficiency * bc - bd)
            self.assertClose([bs[0], bs[-1]], [p.bess_initial, p.bess_terminal])
            self.assertGreaterEqual(float(bs.min()), -1e-7)
            self.assertLessEqual(float(bs.max()), p.bess_capacity + 1e-7)
            self.assertGreaterEqual(float(min(bc.min(), bd.min(), g.min())), -1e-7)
            self.assertLessEqual(float(max(bc.max(), bd.max())), p.bess_rate + 1e-7)
            self.assertTrue(np.all(g <= np.array(p.generation_cap) + 1e-7))
            self.assertTrue(np.all(charge.sum(axis=0) + bc <= np.array(p.charging_cap) + 1e-7))
            supply = g + discharge.sum(axis=0) + bd - charge.sum(axis=0) - bc
            self.assertTrue(np.all(supply + 1e-7 >= np.array(scenario.delta)))
            self.assertClose(supply - scenario.delta, z["passive_spill"])
            cost = float(g @ p.generation_cost + p.throughput_cost * (charge.sum() + discharge.sum() + bc.sum() + bd.sum())
                         + p.discharge_cost * (discharge.sum() + bd.sum()))
            self.assertAlmostEqual(cost, z["operating_cost"], places=7)
            costs.append(scenario.probability * cost)
        self.assertAlmostEqual(sum(costs), solution["operating_cost"], places=7)
        self.assertAlmostEqual(sum(costs) + p.fixed_asset_cost, solution["total_cost"], places=7)

    def test_one_scenario_recovery(self):
        for scenario in self.problem.scenarios:
            p = replace(self.problem, scenarios=(replace(scenario, probability=1.),))
            costs = []
            for mode in ("open_loop", "tree", "perfect_information"):
                z = solve(p, mode)
                self.assertPhysics(p, z)
                costs.append(z["operating_cost"])
            self.assertClose(costs, [costs[0]] * 3)

    def test_duplicate_scenario_probability_split(self):
        a, b = self.problem.scenarios
        p = replace(self.problem, scenarios=(replace(a, probability=.2), replace(a, name="sunny_copy", probability=.3), b))
        for mode in ("open_loop", "tree", "perfect_information"):
            z = solve(p, mode)
            self.assertPhysics(p, z)
            self.assertAlmostEqual(z["operating_cost"], self.solutions[mode]["operating_cost"], places=7)
            if mode != "perfect_information":
                for key in ("truck_charge", "truck_discharge", "truck_soc", "bess_charge", "bess_discharge", "bess_soc", "generation"):
                    self.assertClose(z["scenarios"]["sunny"][key], z["scenarios"]["sunny_copy"][key])

    def test_all_control_nonanticipativity_and_shared_states(self):
        z = self.solutions["tree"]["scenarios"]
        a, b = self.problem.scenarios
        for t in range(self.problem.T):
            if node_key(a, t, "tree") == node_key(b, t, "tree"):
                for key in ("truck_charge", "truck_discharge"):
                    self.assertClose(np.array(z[a.name][key])[:, t], np.array(z[b.name][key])[:, t])
                for key in ("bess_charge", "bess_discharge", "generation"):
                    self.assertClose(z[a.name][key][t], z[b.name][key][t])
        # Information arrives at slot 2. Inherited states at slot 2 still agree;
        # charging actions from that slot onward may differ.
        self.assertClose(np.array(z[a.name]["truck_soc"])[:, :3], np.array(z[b.name]["truck_soc"])[:, :3])
        self.assertClose(z[a.name]["bess_soc"][:3], z[b.name]["bess_soc"][:3])
        self.assertGreater(np.max(np.abs(np.array(z[a.name]["truck_charge"])[:, 2:] - np.array(z[b.name]["truck_charge"])[:, 2:])), .5)

    def test_open_loop_actions_and_committed_vehicle_comparator(self):
        for arm in ("open_loop", "committed"):
            z = self.solutions[arm]["scenarios"]
            for key in ("truck_charge", "truck_discharge", "truck_soc"):
                self.assertClose(z["sunny"][key], z["dark"][key])
            if arm == "open_loop":
                for key in ("bess_charge", "bess_discharge", "bess_soc", "generation"):
                    self.assertClose(z["sunny"][key], z["dark"][key])

    def test_objective_nesting_and_strict_value(self):
        order = [self.solutions[m]["operating_cost"] for m in ("perfect_information", "tree", "committed", "open_loop")]
        self.assertTrue(all(a + 1e-5 < b for a, b in zip(order, order[1:])), order)
        # Independent total energy lower bound in the dark: 8 demand + 2 trip
        # traction = 10 generation. Cyclic stores give no net initial-energy gift.
        for mode in self.solutions:
            self.assertAlmostEqual(sum(self.solutions[mode]["scenarios"]["dark"]["generation"]), 10., places=7)

    def test_independent_physics_cost_and_dual_reconstruction(self):
        for z in self.solutions.values():
            self.assertPhysics(self.problem, z)

    def test_coverage_missing_duplicate_and_overlapping_charging_rejected(self):
        self.assertEqual(self.problem.validate(), {"A": 1, "B": 1})
        a, b = self.problem.trucks
        bad_fleets = ((a, replace(b, trips=("A",))),
                      (replace(a, withdrawal=(0.,)*5), b),
                      (replace(a, connected=(True,)*5), b))
        for fleet in bad_fleets:
            with self.assertRaises(ValueError):
                replace(self.problem, trucks=fleet).validate()

    def test_branched_histories_do_not_recombine(self):
        a = replace(self.problem.scenarios[0], observations=("sunny", "same", "same", "same", "same"))
        b = replace(self.problem.scenarios[1], observations=("dark", "same", "same", "same", "same"))
        for t in range(self.problem.T):
            self.assertNotEqual(node_key(a, t, "tree"), node_key(b, t, "tree"))
        p = replace(self.problem, scenarios=(a, b))
        tree = solve(p, "tree")
        self.assertAlmostEqual(tree["operating_cost"], self.solutions["perfect_information"]["operating_cost"], places=7)

    def test_no_observation_recovers_open_loop(self):
        scenarios = tuple(replace(s, observations=("none",)*5) for s in self.problem.scenarios)
        z = solve(replace(self.problem, scenarios=scenarios), "tree")
        self.assertAlmostEqual(z["operating_cost"], self.solutions["open_loop"]["operating_cost"], places=7)

    def test_absent_bess_and_lossy_batteries(self):
        cases = (replace(self.problem, bess_capacity=0., bess_rate=0., bess_initial=0., bess_terminal=0.),
                 replace(self.problem, truck_charge_efficiency=.9, bess_charge_efficiency=.8, generation_cap=(2.5,)*5))
        for p in cases:
            solutions = [solve(p, m) for m in ("perfect_information", "tree", "open_loop")]
            for z in solutions:
                self.assertPhysics(p, z)
            self.assertTrue(all(a["operating_cost"] <= b["operating_cost"] + 1e-7 for a, b in zip(solutions, solutions[1:])))

    def test_infeasible_instance_has_no_fabricated_cost(self):
        p = replace(self.problem, generation_cap=(1.,)*5)
        for mode in ("open_loop", "tree", "perfect_information"):
            z = solve(p, mode)
            self.assertFalse(z["success"])
            self.assertEqual(z["solver_status"], 2)
            self.assertIsNone(z["operating_cost"])
            self.assertIsNone(z["total_cost"])

    def test_common_suffix_counterexample(self):
        c = suffix_counterexample()
        self.assertEqual(c["common_duty_optimum"], 3.)
        self.assertEqual(c["independent_suffix_optimum_with_split_rewards"], -2.)
        self.assertFalse(c["common_incidence_preserved"])
        self.assertNotEqual(c["one_required_task_correct_reward"], c["one_required_task_wrong_reward_in_two_suffixes"])

    def test_zero_oracle_gap_does_not_eliminate_causal_vehicle_value(self):
        c = oracle_gap_counterexample()
        z = c["solutions"]
        for result in z.values():
            self.assertTrue(result["success"])
            self.assertLess(result["maximum_primal_residual"], 1e-7)
            self.assertLess(result["primal_dual_gap"], 1e-7)
        self.assertClose(c["oracle_truck_flexibility_gap"], 0.)
        self.assertClose(c["causal_truck_flexibility_gap"], .78)
        # No baseline reoptimization ambiguity: the pinned truck profile is
        # numerically identical in the causal and perfect-information arms.
        for scenario in z["fixed_profile_tree"]["scenarios"]:
            for key in ("truck_charge", "truck_discharge", "truck_soc"):
                self.assertClose(z["fixed_profile_tree"]["scenarios"][scenario][key],
                                 z["fixed_profile_perfect_information"]["scenarios"][scenario][key])


if __name__ == "__main__":
    unittest.main(verbosity=2)
