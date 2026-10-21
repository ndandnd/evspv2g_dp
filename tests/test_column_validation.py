"""Shared grid-contract regressions for the independent physical replay."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from instance import Instance,Trip
from master import Column
from colgen import single_trip_column,initial_columns,SCENARIOS
from column_validation import replay_column


def tiny(T=2,scale=1.):
    return Instance(T=T,D=np.zeros(T),P=np.zeros(T),trips=[Trip(0,0,1,0,0,scale)],
        dist=np.zeros((1,1)),G=scale,rho=scale,eta=0.,energy_per_dist=0.,
        c_g=1.,c_v=1.,c_b=1.,eps_pen=0.,soc_step=scale)


class ColumnValidation(unittest.TestCase):
    def test_near_grid_profile_is_rejected(self):
        inst=tiny()
        bad=Column('truck',np.ones(1),np.array([0.,1.-5e-8]),1.)
        self.assertFalse(replay_column(inst,bad))
        good=Column('truck',np.ones(1),np.array([0.,1.]),1.)
        self.assertTrue(replay_column(inst,good))

    def test_tiny_full_level_is_real_activity(self):
        inst=tiny(T=1,scale=1e-10);inst.trips[0].energy=0.
        bad=Column('truck',np.ones(1),np.array([-1e-10]),1.)
        self.assertFalse(replay_column(inst,bad))
        inst=tiny(scale=1e-10)
        good=Column('truck',np.ones(1),np.array([0.,1e-10]),1.)
        self.assertTrue(replay_column(inst,good))
        self.assertFalse(replay_column(inst,good,allow_charge=False))
        self.assertFalse(replay_column(inst,good,ice=True))

    def test_tiny_activity_cannot_overlap_deadhead(self):
        inst=tiny(T=4,scale=1e-10)
        inst.dist=np.array([[0.,1.],[1.,0.]])
        inst.trips=[Trip(0,1,2,1,1,0.)]
        bad=Column('truck',np.ones(1),np.array([-1e-10,0.,0.,1e-10]),1.)
        self.assertFalse(replay_column(inst,bad))

    def test_nonzero_subgrid_profile_is_rejected(self):
        inst=tiny();inst.trips[0].energy=0.
        bad=Column('truck',np.ones(1),np.array([0.,1e-20]),1.)
        self.assertFalse(replay_column(inst,bad))

    def test_profile_rate_matches_pricing_floor(self):
        inst=tiny();inst.rho=1.-1e-13
        bad=Column('truck',np.ones(1),np.array([0.,1.]),1.)
        self.assertFalse(replay_column(inst,bad))
        self.assertIsNone(single_trip_column(inst,inst.trips[0]))
        inst.rho=3.
        self.assertTrue(replay_column(inst,bad))
        self.assertIsNotNone(single_trip_column(inst,inst.trips[0]))

    def test_seed_checks_individual_traction_components(self):
        inst=tiny(T=5);inst.G=3.
        inst.dist=np.array([[0.,1.],[1.,0.]])
        inst.energy_per_dist=.4
        inst.trips=[Trip(0,1,2,1,1,1.2)]
        # Total energy equals two levels, but every component is off grid.
        self.assertIsNone(single_trip_column(inst,inst.trips[0]))
        self.assertIsNone(single_trip_column(inst,inst.trips[0],free_start=True))

    def test_incidence_and_physics_must_match_admitted_family(self):
        inst=tiny();col=Column('truck',np.array([1.-5e-10]),np.array([0.,1.]),1.)
        self.assertFalse(replay_column(inst,col))
        col.a[:]=1.;inst.G=1.6
        self.assertFalse(replay_column(inst,col))
        inst.G=1.;inst.trips[0].energy=1.-5e-9
        self.assertFalse(replay_column(inst,col))

    def test_warm_initialization_passes_cache_control(self):
        for flag in (False,True):
            with patch('colgen.price_truck_dp',return_value=[]) as dp:
                initial_columns(tiny(),'warm',SCENARIOS['solar'],pricing_cache=flag)
                self.assertGreater(dp.call_count,0)
                self.assertTrue(all(call.kwargs['use_cache'] is flag for call in dp.call_args_list))

    def test_independently_enumerated_pricing_columns_replay(self):
        import test_pricing_exhaustive as audit
        original=audit.price_truck_dp
        count=0
        def checked(inst,alpha,mu,**kwargs):
            nonlocal count
            result=original(inst,alpha,mu,**kwargs)
            for col,_ in result:
                self.assertTrue(replay_column(inst,col,
                    allow_discharge=kwargs.get('allow_discharge',True),
                    ice=kwargs.get('ice',False),soc_mode=kwargs.get('soc_mode','cyclic')))
                count+=1
            return result
        with patch.object(audit,'price_truck_dp',side_effect=checked):
            audit.ExhaustivePricing().test_128_independent_aligned_cases()
        self.assertGreater(count,0)


if __name__=='__main__':unittest.main()
