"""Regression tests for feasibility and the exact-pricing certificate contract."""
import unittest
from unittest.mock import patch
import numpy as np
from instance import Instance,Trip
from master import Column
from colgen import column_generation,single_trip_column,_col_key,_flatten_col
from column_validation import replay_column

def tiny(T=3):
 return Instance(T=T,D=np.zeros(T),P=np.zeros(T),trips=[Trip(0,0,1,0,0,1.)],dist=np.zeros((1,1)),G=1.,rho=1.,eta=0.,energy_per_dist=0.,c_g=5e-6,c_v=1.,c_b=1.,eps_pen=0.,soc_step=1.)

class CGContracts(unittest.TestCase):
 def test_capacity_seed_rejected_even_free_start(self):
  i=tiny(6);i.G=2.;i.dist=np.array([[0.,1.],[1.,0.]]);i.energy_per_dist=1.;i.trips=[Trip(0,1,2,1,1,1.)]
  self.assertIsNone(single_trip_column(i,i.trips[0]));self.assertIsNone(single_trip_column(i,i.trips[0],free_start=True))
  r=column_generation(i,scenario='solar',start='cold',enrich=0,do_milp=True)
  self.assertFalse(r['converged']);self.assertIsNone(r['full_lp_lower_bound']);self.assertGreater(r['artificial_selected'],.99)
  self.assertFalse(r['mip'].has_incumbent)
 def test_reconstruction_witness_finds_improvement(self):
  i=tiny();i.D=np.array([0.,1.,0.]);i.P=np.array([0.,0.,1.])
  r=column_generation(i,scenario='solar',start='cold',enrich=0,do_milp=False)
  self.assertTrue(r['converged']);self.assertAlmostEqual(r['lp_obj'],1.000005,places=10)
  self.assertLessEqual(r['full_lp_lower_bound'],1.000005)
  self.assertTrue(r['iterations'][-1]['exact_fallback'])
 def test_initial_balance_infeasibility_is_repaired(self):
  i=tiny(4);i.D=np.array([0.,0.,1.,0.]);i.P=np.array([0.,1.,0.,1.]);i.gen_cap=0.;i.c_g=1.
  r=column_generation(i,scenario='v2g_fleet',start='cold',enrich=0,do_milp=False)
  self.assertEqual(r['phase1']['status'],'feasible');self.assertTrue(r['converged'])
  self.assertAlmostEqual(r['lp_obj'],1.)
 def test_key_retains_energy_and_cost(self):
  a=Column('truck',np.ones(1),np.array([.001,0,0]),1.)
  b=Column('truck',np.ones(1),np.array([.002,0,0]),1.)
  c=Column('truck',a.a,a.e,2.)
  self.assertEqual(len({_col_key(a),_col_key(b),_col_key(c)}),3)
 def test_zero_iteration_solves_once_without_certificate(self):
  import colgen
  with patch('colgen.solve_lp',wraps=colgen.solve_lp) as solve:
   r=column_generation(tiny(),scenario='solar',start='cold',max_iter=0,enrich=0,do_milp=False)
   self.assertEqual(solve.call_count,1)
  self.assertFalse(r['converged']);self.assertIsNone(r['full_lp_lower_bound'])
 def test_invalid_warm_profile_rejected_and_budget_recorded(self):
  i=tiny();bad=Column('truck',np.ones(1),np.array([1.,0,0]),1.,'charge during task')
  r=column_generation(i,scenario='solar',start='cold',max_iter=0,enrich=0,do_milp=False,extra_cols=[bad],warm_max_candidates=1)
  self.assertEqual(r['warm_import']['rejected'],1);self.assertEqual(r['warm_import']['accepted'],0)
 def test_warm_scan_is_bounded(self):
  i=tiny();seed=single_trip_column(i,i.trips[0])
  r=column_generation(i,scenario='solar',start='cold',max_iter=0,enrich=0,do_milp=False,extra_cols=[seed]*10,warm_max_candidates=2)
  self.assertEqual(r['warm_import']['scanned'],2);self.assertEqual(r['warm_import']['stop'],'scan_limit')
 def test_flat_transform_preserves_activity_cost(self):
  i=tiny();i.eps_pen=.1;col=single_trip_column(i,i.trips[0]);flat=_flatten_col(col,i)
  self.assertAlmostEqual(flat.cost(i.eps_pen),col.cost(i.eps_pen)+i.c_g*sum(col.e))
 def test_seed_grid_and_independent_replay_with_loss(self):
  i=tiny(5);i.eta=.5;i.rho=2.;i.charge_cap=2.
  c=single_trip_column(i,i.trips[0]);self.assertIsNotNone(c);self.assertTrue(replay_column(i,c,allow_discharge=False))
 def test_pricing_mismatch_raises_without_certificate(self):
  i=tiny();c=single_trip_column(i,i.trips[0])
  with patch('colgen.price_truck_dp',return_value=[(c,-1.)]):
   with self.assertRaisesRegex(RuntimeError,'disagree'):
    column_generation(i,scenario='solar',start='cold',enrich=0,do_milp=False)

if __name__=='__main__':unittest.main()
