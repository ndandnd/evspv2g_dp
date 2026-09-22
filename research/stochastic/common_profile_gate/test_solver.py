"""Small semantic checks for the portable common-profile LP.

Run ``python -m unittest -v test_solver`` from this directory. Gurobi's tiny
cross-backend test is skipped if gurobipy is absent; a present but failing
license is a failure, not an unreported fallback. Temporary run artifacts are
created below this directory and removed after successful or failed tests.
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

import solver


def example():
    # The truck must replenish two traction units after slot 0. Opposing solar
    # slots produce strict adaptive <= common <= inherited economic nesting.
    return {"metadata": {"purpose": "analytic semantic fixture"},
            "physics": {"G": 4., "rho": 2., "eta": 0., "c_g": 1., "c_b": 0.,
                        "eps_pen": .01, "deg_cost": 0., "gen_cap": 4., "charge_cap": None},
            "fleet": [{"multiplicity": 1., "connected": [False, True, True],
                       "withdraw": [2., 0., 0.], "incidence": [1.], "profile": [0., 0., 2.]}],
            "bess": {"units": 0., "initial": 0.}, "dates": ["solar-early", "solar-late"],
            "deltas": [[0., -2., 2.], [0., 2., -2.]], "probabilities": [.8, .2],
            "fixed_asset_cost": 10.}


class CommonProfileSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="test_solver_", dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.count = 0

    def solve(self, data, backend="scipy", mode="both", time_limit=30.):
        self.count += 1
        out = Path(self.tmp.name) / str(self.count)
        result = solver.solve_case(data, out, backend=backend, mode=mode, time_limit=time_limit)
        return result, out

    def assert_complete(self, result):
        self.assertEqual(result["state"], "complete", json.dumps(result, indent=2))
        for label in ("inherited", "common"):
            if label not in result:
                continue
            for phase in ("shortage", "cost"):
                p = result[label]["phases"][phase]
                self.assertTrue(p["optimality_certified"])
                self.assertLess(p["primal_residuals"]["maximum_violation"], 1e-7)
                self.assertLess(p["duality"]["stationarity_inf"], 1e-7)
                self.assertLess(p["duality"]["dual_sign_violation"], 1e-7)
                self.assertAlmostEqual(p["duality"]["primal_minus_dual"], 0., places=7)

    def test_one_scenario_pinned_analytic_and_independent_adaptive(self):
        data = example()
        data.update(dates=data["dates"][:1], deltas=data["deltas"][:1], probabilities=[1.])
        result, out = self.solve(data)
        self.assert_complete(result)
        # Pinned late charge needs four generated units; adaptive early charge
        # takes the two free solar units and needs two generated units later.
        self.assertAlmostEqual(result["inherited"]["solution"]["expected_total_cost"], 14.02)
        self.assertAlmostEqual(result["common"]["solution"]["expected_total_cost"], 12.02)
        with np.load(out / "common_cost_primal.npz") as p:
            np.testing.assert_allclose(p["truck_charge"], [[0., 2., 0.]], atol=1e-7)
            np.testing.assert_allclose(p["truck_soc"], [[4., 2., 4., 4.]], atol=1e-7)

    def test_duplicate_scenarios_preserve_objectives(self):
        base = example()
        original, _ = self.solve(base)
        repeated = copy.deepcopy(base)
        repeated.update(dates=base["dates"] * 2, deltas=base["deltas"] * 2,
                        probabilities=[p / 2 for p in base["probabilities"]] * 2)
        duplicate, _ = self.solve(repeated)
        self.assert_complete(original)
        self.assert_complete(duplicate)
        for label in ("inherited", "common"):
            a, b = original[label]["solution"], duplicate[label]["solution"]
            self.assertAlmostEqual(a["expected_emergency"], b["expected_emergency"])
            self.assertAlmostEqual(a["expected_total_cost"], b["expected_total_cost"])

    def test_strict_relaxation_hierarchy_and_static_regret(self):
        data = example()
        common, _ = self.solve(data)
        self.assert_complete(common)
        daily = []
        for date, delta in zip(data["dates"], data["deltas"]):
            one = copy.deepcopy(data)
            one.update(dates=[date], deltas=[delta], probabilities=[1.])
            solved, _ = self.solve(one, mode="common")
            self.assert_complete(solved)
            daily.append(solved["common"]["solution"]["expected_total_cost"])
        adaptive = float(np.asarray(data["probabilities"]) @ daily)
        static = common["common"]["solution"]["expected_total_cost"]
        inherited = common["inherited"]["solution"]["expected_total_cost"]
        self.assertAlmostEqual(adaptive, 12.02)
        self.assertAlmostEqual(static, 12.42)
        self.assertAlmostEqual(inherited, 13.62)
        self.assertLess(adaptive, static)
        self.assertLess(static, inherited)
        self.assertAlmostEqual(common["comparison"]["inherited_profile_regret"], 1.2)

    def test_optimized_profile_can_be_frozen_and_replayed(self):
        data = example()
        result, _ = self.solve(data)
        frozen = copy.deepcopy(data)
        for truck, profile in zip(frozen["fleet"], result["common"]["solution"]["profile_per_unit"]):
            truck["profile"] = profile
        replay, _ = self.solve(frozen, mode="pinned")
        self.assert_complete(replay)
        self.assertAlmostEqual(result["common"]["solution"]["expected_total_cost"],
                               replay["inherited"]["solution"]["expected_total_cost"])

    def test_positive_shortage_is_lexicographic_and_unpriced(self):
        data = example()
        data["physics"].update(gen_cap=0., c_g=1e6)
        result, _ = self.solve(data)
        self.assert_complete(result)
        for label in ("inherited", "common"):
            solution = result[label]["solution"]
            self.assertGreater(solution["expected_emergency"], 0)
            self.assertIsNone(solution["expected_total_cost"])
            self.assertFalse(solution["zero_shortage_all"])
            self.assertAlmostEqual(solution["expected_emergency"], result[label]["phases"]["shortage"]["objective"])
        self.assertTrue(result["comparison"]["reliability_hierarchy_pass"])
        self.assertIsNone(result["comparison"]["economic_hierarchy_pass"])
        self.assertIsNone(result["comparison"]["inherited_profile_regret"])

    def test_invalid_inherited_profile_does_not_override_bounds(self):
        data = example()
        data["fleet"][0]["profile"] = [2., 0., 0.]  # disconnected slot
        result, _ = self.solve(data)
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(result["inherited"]["state"], "infeasible")
        self.assertIsNone(result["inherited"]["phases"]["shortage"]["objective"])
        self.assertNotIn("cost", result["inherited"]["phases"])
        self.assertFalse(result["inherited"]["phases"]["shortage"]["optimality_certified"])
        self.assertIsNone(result["inherited"]["solution"])
        self.assertTrue(result["common"]["complete"])
        self.assertFalse(result["comparison"]["available"])

    def test_multiplicity_is_aggregated_once(self):
        data = example()
        data["fleet"][0]["multiplicity"] = 2.
        data["physics"]["gen_cap"] = 8.
        result, out = self.solve(data)
        self.assert_complete(result)
        for label in ("inherited", "common"):
            with np.load(out / f"{label}_cost_primal.npz") as p:
                self.assertAlmostEqual(p["truck_charge"].sum() - p["truck_discharge"].sum(), 4.)
                np.testing.assert_allclose(p["truck_soc"][:, [0, -1]], 8.)
            s = result[label]["solution"]
            np.testing.assert_allclose(np.asarray(s["profile"]), 2 * np.asarray(s["profile_per_unit"]))

    def test_bess_boundary_and_scenario_recourse(self):
        data = example()
        data["bess"] = {"units": 1., "initial": 0.}
        result, out = self.solve(data)
        self.assert_complete(result)
        with np.load(out / "common_cost_primal.npz") as p:
            self.assertEqual(p["bess_charge"].shape, (2, 3))
            np.testing.assert_allclose(p["bess_soc"][:, [0, -1]], 0., atol=1e-7)
            np.testing.assert_allclose(np.diff(p["bess_soc"], axis=1),
                                       p["bess_charge"] - p["bess_discharge"], atol=1e-7)

    def test_guarded_physics_and_probabilities(self):
        for key, value in (("eta", .1), ("deg_cost", .01), ("charge_cap", 100),
                           ("discharge_efficiency", .9)):
            data = example()
            data["physics"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                solver.load_input(data)
        for probabilities in ([1., 0.], [.4, .4]):
            data = example()
            data["probabilities"] = probabilities
            with self.assertRaises(ValueError):
                solver.load_input(data)

    @unittest.skipUnless(importlib.util.find_spec("gurobipy"), "gurobipy is not installed")
    def test_native_gurobi_matches_scipy_and_retains_logs(self):
        highs, _ = self.solve(example())
        gurobi, out = self.solve(example(), backend="gurobi")
        self.assert_complete(highs)
        self.assert_complete(gurobi)
        self.assertIn("gurobi", gurobi["versions"])
        for label in ("inherited", "common"):
            self.assertAlmostEqual(highs[label]["solution"]["expected_total_cost"],
                                   gurobi[label]["solution"]["expected_total_cost"])
            for phase in ("shortage", "cost"):
                text = (out / f"{label}_{phase}.log").read_text()
                self.assertIn("Gurobi Optimizer", text)
                self.assertIn("Optimal", text)
                self.assertFalse(gurobi[label]["phases"][phase]["is_mip"])


if __name__ == "__main__":
    unittest.main()
