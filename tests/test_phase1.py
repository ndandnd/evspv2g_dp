import copy
import unittest
from unittest.mock import patch
import numpy as np
import master
from master import Column
from instance import Instance,Trip
from phase1 import find_feasible_pool
from column_validation import replay_column

CAPS=dict(ice=False,allow_charge=True,allow_discharge=True,battery=False)


def instance(energy=1,c_v=10):
    return Instance(T=4,D=np.array([0.,0.,1.,0.]),P=np.array([0.,1.,0.,1.]),
        trips=[Trip(0,0,1,0,0,energy)],dist=np.zeros((1,1)),G=1.,rho=1.,eta=0.,
        energy_per_dist=0.,c_g=1.,c_v=c_v,c_b=10.,eps_pen=.01,soc_step=1.,gen_cap=0.)


def pool(inst):
    return [Column('truck',np.ones(1),np.array([0.,1.,0.,0.]),inst.c_v,'simple'),
            Column('artificial',np.ones(1),np.zeros(4),1e6,'art')]


class PhaseOne(unittest.TestCase):
    def test_balance_relaxation_recovers_grid_feasible_pool(self):
        inst=instance();cols=pool(inst)
        self.assertEqual(master.solve_lp(inst,cols,battery_allowed=False).status,'infeasible')
        result=find_feasible_pool(inst,cols,CAPS)
        self.assertEqual(result['status'],'feasible')
        self.assertGreater(result['telemetry']['added_columns'],0)
        self.assertTrue(all(c.kind=='truck' for c in result['cols']))
        witness=[c for c in result['cols'] if np.array_equal(c.e,[0,1,-1,1])]
        self.assertTrue(witness)
        self.assertTrue(all(replay_column(inst,c) for c in result['cols']))
        self.assertEqual(master.solve_lp(inst,result['cols'],battery_allowed=False).status,'optimal')
        self.assertTrue(result['proof']['requires_session_reset'])
        # Input columns and economic costs remain untouched.
        self.assertEqual(len(cols),2)
        self.assertEqual(cols[0].fixed_cost,10)

    def test_impossible_capacity_trip_gets_scoped_positive_bound(self):
        inst=instance(energy=2)
        art=Column('artificial',np.ones(1),np.zeros(4),1e6)
        result=find_feasible_pool(inst,[art],CAPS)
        self.assertEqual(result['status'],'infeasible_certified')
        self.assertTrue(result['proof']['exact_pricing'])
        self.assertGreater(result['proof']['full_family_lower_bound'],0)
        self.assertIn('lattice/profile',result['proof']['scope'])
        self.assertGreater(result['proof']['artificial_mass'],0)

    def test_finite_economic_artificial_penalty_does_not_prove_infeasible(self):
        inst=instance(c_v=2e6);inst.D[:]=0
        cols=pool(inst)
        economic=master.solve_lp(inst,cols,battery_allowed=False)
        self.assertEqual(economic.status,'optimal')
        self.assertGreater(economic.x[1],.9)
        result=find_feasible_pool(inst,cols,CAPS)
        self.assertEqual(result['status'],'feasible')
        self.assertTrue(all(c.kind=='truck' for c in result['cols']))
        self.assertGreater(result['proof']['real_pool_objective'],1e6)

    def test_fleet_cap_prevents_two_simultaneous_trips(self):
        inst=instance(energy=0);inst.D[:]=0;inst.P[:]=0
        inst.trips.append(Trip(1,0,1,0,0,0));inst.max_trucks=1
        result=find_feasible_pool(inst,[],CAPS)
        self.assertEqual(result['status'],'infeasible_certified')
        self.assertGreater(result['proof']['full_family_lower_bound'],.99)

    def test_budget_and_unsupported_modes_do_not_claim_infeasible(self):
        inst=instance()
        self.assertEqual(find_feasible_pool(inst,pool(inst),CAPS,max_iter=0)['status'],'unresolved')
        with patch.object(master,'COVERING',True):
            self.assertEqual(find_feasible_pool(inst,pool(inst),CAPS)['status'],'unresolved')
        self.assertEqual(find_feasible_pool(inst,pool(inst),dict(CAPS,flat_price=True))['status'],'unresolved')

    def test_improving_duplicate_is_an_error(self):
        inst=instance();cols=pool(inst)
        phase_col=copy.deepcopy(cols[0]);phase_col.fixed_cost=0
        dual=dict(alpha=np.ones(1),mu=np.zeros(4),nu=np.zeros(4),fleet_price=0.)
        with patch('phase1.StochasticTemplate.pricing_duals',return_value=dual), \
             patch('phase1.price_truck_dp',return_value=[(phase_col,-1.)]):
            with self.assertRaisesRegex(RuntimeError,'improving duplicate'):
                find_feasible_pool(inst,cols,CAPS)

    def test_restore_discharge_degradation_cost(self):
        inst=instance();inst.deg_cost=3
        result=find_feasible_pool(inst,pool(inst),CAPS)
        self.assertEqual(result['status'],'feasible')
        for col in result['cols']:
            self.assertAlmostEqual(col.fixed_cost,inst.c_v+inst.deg_cost*np.maximum(-col.e,0).sum())


if __name__=='__main__':unittest.main()
