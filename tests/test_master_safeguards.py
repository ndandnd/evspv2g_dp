"""Small independent solver witnesses; unittest has no additional dependency."""
import copy
import unittest
from unittest.mock import patch
import numpy as np
import master
from master import Column, canonical_model, reduced_cost, solve_lp, solve_milp, validate_vector
from instance import Instance, Trip


def tiny(**kwargs):
    data = dict(T=2, D=np.ones(2), P=np.zeros(2), trips=[], dist=np.zeros((1,1)),
        G=2., rho=1., eta=0.1, energy_per_dist=0., c_g=1., c_v=1., c_b=2.,
        eps_pen=0.01, gen_cap=2., charge_cap=2.)
    data.update(kwargs)
    return Instance(**data)


def fleet_case():
    inst = tiny(D=np.zeros(2), P=np.zeros(2), max_trucks=1,
        trips=[Trip(0,0,1,0,0,0),Trip(1,1,2,0,0,0)])
    cols = [Column("truck", np.array(a), np.zeros(2), c) for a,c in
            [([1,0],1),([0,1],1),([1,1],5)]]
    return inst, cols


class MasterSafeguards(unittest.TestCase):
    def test_cbc_infeasible_values_are_not_incumbent(self):
        inst = tiny(gen_cap=0)
        sol = solve_milp(inst, [], battery_allowed=False)
        self.assertEqual(sol.status, "infeasible")
        self.assertFalse(sol.has_incumbent)
        self.assertTrue(np.isinf(sol.obj))
        self.assertEqual(sol.native_status, -1)
        self.assertEqual(solve_lp(inst, [], battery_allowed=False).status, "infeasible")

    def test_fleet_dual_restores_reduced_cost(self):
        inst, cols = fleet_case()
        sol = solve_lp(inst, cols, battery_allowed=False)
        self.assertEqual(sol.status, "optimal")
        self.assertAlmostEqual(sol.obj, 5)
        self.assertAlmostEqual(sol.fleet_dual, -3)
        np.testing.assert_allclose([reduced_cost(c, sol, inst) for c in cols], 0, atol=1e-8)
        artificial = Column("artificial", cols[0].a, cols[0].e, 1)
        self.assertAlmostEqual(reduced_cost(artificial, sol, inst), -3)
        mip = solve_milp(inst, cols, battery_allowed=False)
        self.assertEqual(mip.status, "optimal")
        self.assertTrue(mip.has_incumbent)
        self.assertAlmostEqual(mip.obj, 5)

    def test_valid_vector_rejects_missing_fractional_bounds_and_objective(self):
        inst, cols = fleet_case()
        model = canonical_model(inst, cols, False)
        sol = solve_milp(inst, cols, battery_allowed=False)
        self.assertTrue(validate_vector(model, sol.vector, True, sol.obj)[0])
        for z in (None, np.full_like(sol.vector,np.nan), sol.vector + 0.5):
            self.assertFalse(validate_vector(model,z,True)[0])
        self.assertFalse(validate_vector(model,sol.vector,True,sol.obj+1)[0])
        z=sol.vector.copy(); z[model.off[1]]=3
        self.assertFalse(validate_vector(model,z,True)[0])

    def test_lp_native_nonfeasibility_reasons_preserved(self):
        from types import SimpleNamespace
        for code, name in ((1,"limit"),(2,"infeasible"),(3,"unbounded"),(4,"numerical_error")):
            fake=SimpleNamespace(status=code,success=False,x=None,fun=None,message="test native message")
            with patch.object(master,"linprog",return_value=fake):
                sol=solve_lp(tiny(),[])
            self.assertEqual(sol.status,name)
            self.assertEqual(sol.native_status,code)
            self.assertEqual(sol.message,"test native message")
            self.assertFalse(sol.has_incumbent)

    def test_boundaries_losses_fixed_storage_and_caps(self):
        inst=tiny(D=np.array([0.,1.]), P=np.array([2.,0.]), nb_fixed=1.,
                  fuel_budget=1., gen_cap=np.array([0.,1.]), eta=0.2)
        for covering in (False,True):
            with patch.object(master,"COVERING",covering):
                for mode in ("free","cyclic"):
                    for battery in (False,True):
                        lp=solve_lp(inst,[],battery_allowed=battery,soc_mode=mode)
                        mip=solve_milp(inst,[],battery_allowed=battery,soc_mode=mode)
                        self.assertEqual(lp.status,"optimal")
                        self.assertEqual(mip.status,"optimal")
                        self.assertAlmostEqual(lp.obj,mip.obj,places=6)
                        self.assertLessEqual(mip.validation_max_violation,1e-6)
                        if mode=="cyclic": self.assertAlmostEqual(mip.soc[0],mip.soc[-1])
                        else: self.assertAlmostEqual(mip.soc[0],inst.G if battery else 0)

    def test_covering_uses_actual_coefficients_and_tiny_energy(self):
        inst=tiny(D=np.zeros(2), trips=[Trip(0,0,1,0,0,0)],charge_cap=0)
        col=Column("truck",np.ones(1),np.array([5e-10,0]),1.)
        model=canonical_model(inst,[col],False)
        self.assertEqual(model.Aub[model.cc_start,0],5e-10)
        inst.charge_cap=float('inf')
        col.a=np.array([0.25])
        for covering in (False,True):
            with patch.object(master,"COVERING",covering):
                lp=solve_lp(inst,[col],battery_allowed=False)
                mip=solve_milp(inst,[col],battery_allowed=False)
                self.assertAlmostEqual(lp.x[0],4)
                self.assertAlmostEqual(mip.x[0],4)

    def test_unsupported_boundary_fails_explicitly(self):
        with self.assertRaises(ValueError): solve_lp(tiny(),[],soc_mode="typo")

    def test_native_time_limit_with_and_without_verified_incumbent(self):
        from types import SimpleNamespace
        from gurobi_master import extract_native
        inst, cols = fleet_case()
        form = canonical_model(inst, cols, False)
        witness = solve_milp(inst, cols, battery_allowed=False)
        variables = [SimpleNamespace(X=float(x)) for x in witness.vector]
        native = SimpleNamespace(Status=9, SolCount=1, ObjVal=witness.obj,
                                 ObjBound=4., MIPGap=.2)
        sol = extract_native(native, form, variables, [], [], integer=True)
        self.assertEqual(sol.status, "feasible")
        self.assertEqual(sol.termination_reason, "time_limit")
        self.assertTrue(sol.has_incumbent)
        self.assertEqual(sol.solver_bound, 4.)
        self.assertEqual(sol.gap, .2)
        native.SolCount = 0
        sol = extract_native(native, form, variables, [], [], integer=True)
        self.assertEqual(sol.status, "time_limit")
        self.assertFalse(sol.has_incumbent)
        native.SolCount = 1
        variables[0].X += .5
        sol = extract_native(native, form, variables, [], [], integer=True)
        self.assertEqual(sol.status, "invalid_incumbent")
        self.assertFalse(sol.has_incumbent)


if __name__ == "__main__": unittest.main()
