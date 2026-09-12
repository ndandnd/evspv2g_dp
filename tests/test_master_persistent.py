import copy
import importlib.util
import unittest
from unittest.mock import patch
import numpy as np
import master
from master import Column, canonical_model, reduced_cost, solve_lp, solve_milp
from persistent_master import PersistentGurobiMaster, configuration_key, column_key
from test_master_safeguards import tiny, fleet_case


class IdentityGuards(unittest.TestCase):
    def test_full_profile_and_cost_keys(self):
        inst, cols=fleet_case()
        a=cols[0]; b=copy.deepcopy(a)
        b.label="only metadata"
        self.assertEqual(column_key(a),column_key(b))
        b.e[1]=1e-12
        self.assertNotEqual(column_key(a),column_key(b))
        b=copy.deepcopy(a); b.fixed_cost+=1e-12
        self.assertNotEqual(column_key(a),column_key(b))
        before=configuration_key(inst,True,"cyclic")
        inst.P[0]+=1e-12
        self.assertNotEqual(before,configuration_key(inst,True,"cyclic"))

    def test_mutation_reorder_removal_are_rejected_without_solver(self):
        inst, cols=fleet_case()
        session=PersistentGurobiMaster.__new__(PersistentGurobiMaster)
        session.inst=inst; session.battery_allowed=True; session.soc_mode="cyclic"
        session.configuration_identity=configuration_key(inst,True,"cyclic")
        session.closed=False; session.keys=[column_key(c) for c in cols[:2]]
        session.static=canonical_model(inst,[],True)
        self.assertEqual(session._guard(cols,inst),[column_key(c) for c in cols])
        for bad in (cols[:1],list(reversed(cols)),[cols[1],cols[0]]):
            with self.assertRaises(ValueError): session._guard(bad,inst)
        cols[0].fixed_cost+=1
        with self.assertRaises(ValueError): session._guard(cols,inst)
        cols[0].fixed_cost-=1
        inst.eta+=0.01
        with self.assertRaises(ValueError): session._guard(cols,inst)
        inst.eta-=0.01
        with patch.object(master,"COVERING",not master.COVERING):
            with self.assertRaises(ValueError): session._guard(cols,inst)


@unittest.skipUnless(importlib.util.find_spec("gurobipy"),"gurobipy unavailable; run in Gurobi allocation")
class GurobiParity(unittest.TestCase):
    def compare(self, inst, cols, battery, mode):
        # Stable static storage/row IDs across updates; all matrix entries equal
        # the independent cold dense reference, with no dependency on dual choice.
        with PersistentGurobiMaster(inst,battery_allowed=battery,soc_mode=mode) as session:
            first_ids=([v.index for v in session.static_vars], [r.index for r in session.eq+session.ub])
            for k in (1,len(cols)):
                pool=cols[:k]
                actual=session.solve(pool,inst=inst)
                expected=solve_lp(inst,pool,battery_allowed=battery,soc_mode=mode)
                cold=solve_lp(inst,pool,battery_allowed=battery,soc_mode=mode,solver="gurobi")
                self.assertEqual(actual.status,expected.status)
                self.assertEqual(cold.status,expected.status)
                if expected.status=="optimal":
                    self.assertAlmostEqual(actual.obj,expected.obj,places=6)
                    self.assertAlmostEqual(cold.obj,expected.obj,places=6)
                    self.assertLessEqual(actual.validation_max_violation,1e-6)
                    self.assertGreaterEqual(min(reduced_cost(c,actual,inst) for c in pool),-1e-6)
                reference=canonical_model(inst,pool,battery,mode)
                form=session.canonical_form()
                np.testing.assert_array_equal(form.matrix.toarray(),reference.matrix.toarray())
                np.testing.assert_array_equal(form.c,reference.c)
                np.testing.assert_array_equal(form.beq,reference.beq)
                np.testing.assert_array_equal(form.bub,reference.bub)
                self.assertEqual(form.bounds,reference.bounds)
                self.assertEqual(first_ids,([v.index for v in session.static_vars], [r.index for r in session.eq+session.ub]))
            old_model=session.model
            again=session.solve(cols)
            self.assertIs(old_model,session.model)
            self.assertEqual(session.solve_count,3)
            self.assertEqual(again.timings["build_seconds"],0)
            self.assertEqual(len(session.route_vars),len(cols))

    def test_caps_boundaries_losses_covering_and_battery_modes(self):
        for covering in (False,True):
            with patch.object(master,"COVERING",covering):
                for mode in ("cyclic","free","periodic","pin1"):
                    for battery in (False,True):
                        inst,cols=fleet_case()
                        inst.D=np.array([0.,1.]); inst.P=np.array([2.,0.])
                        inst.nb_fixed=1.; inst.gen_cap=np.array([0.,1.]);inst.fuel_budget=1.;inst.eta=.2
                        self.compare(inst,[cols[2],*cols[:2]],battery,mode)

    def test_different_energy_same_cover_appends_and_mip_parity(self):
        inst,cols=fleet_case()
        inst.max_trucks=float('inf')
        base=cols[2]
        different=copy.deepcopy(base);different.e=np.array([0.,-1.]);different.fixed_cost=4
        self.compare(inst,[base,different],True,"cyclic")
        lp=solve_lp(inst,[base,different],solver="gurobi")
        mip=solve_milp(inst,[base,different],solver="gurobi")
        self.assertEqual(mip.status,"optimal")
        self.assertTrue(mip.has_incumbent)
        self.assertGreaterEqual(mip.obj,lp.obj-1e-6)
        self.assertLessEqual(mip.validation_max_violation,1e-6)

    def test_infeasible_gurobi_cannot_be_incumbent(self):
        inst=tiny(gen_cap=0)
        for solver in (solve_lp,solve_milp):
            sol=solver(inst,[],battery_allowed=False,solver="gurobi")
            self.assertFalse(sol.has_incumbent)
            self.assertIn(sol.status,("infeasible","infeasible_or_unbounded"))


if __name__=="__main__": unittest.main()
