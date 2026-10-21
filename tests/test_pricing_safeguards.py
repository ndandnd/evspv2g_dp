from pathlib import Path
import sys
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instance import Instance, Trip
from pricing_truck import price_truck_dp, _dp_cost_via_networkx_at
from pricing_battery import price_battery_dp, price_battery_lp
from pricing_contract import prepare_pricing, clear_pricing_cache, pricing_cache_info


def instance(T=2, trips=None, G=1., rho=1., step=1., eta=0.):
    return Instance(T=T, D=np.zeros(T), P=np.zeros(T), trips=trips or [],
                    dist=np.zeros((1, 1)), G=G, rho=rho, eta=eta,
                    energy_per_dist=0., c_g=1., c_v=1., c_b=0.,
                    eps_pen=0., soc_step=step)


class PricingSafeguards(unittest.TestCase):
    def test_near_tied_reconstruction(self):
        inst = instance(trips=[Trip(0,0,1,0,0,0.),Trip(1,1,2,0,0,0.)])
        for reward in (5e-6, 5e-9, 5e-11):
            alpha=np.array([1., reward]); mu=np.zeros(2)
            col, rc = price_truck_dp(inst, alpha, mu, tol=1e-12)[0]
            np.testing.assert_array_equal(col.a, [1., 1.])
            self.assertAlmostEqual(rc, col.cost(0)-col.a@alpha, places=14)

    def test_battery_near_tied_reconstruction(self):
        inst=instance()
        col, rc=price_battery_dp(inst,np.array([0.,5e-6]),step=1.)
        np.testing.assert_array_equal(col.e,[0.,-1.])
        self.assertEqual(rc,-5e-6)

    def test_overcapacity_rate_is_valid(self):
        inst=instance(trips=[Trip(0,0,1,0,0,1.)],rho=3.)
        col, rc=price_truck_dp(inst,np.array([3.]),np.ones(2))[0]
        np.testing.assert_array_equal(col.e,[0.,1.])
        self.assertEqual(rc,-1.)
        bcol,brc=price_battery_dp(inst,np.ones(2),step=1.)
        self.assertEqual(brc,-1.)
        self.assertEqual(bcol.e.sum(),-1.)

    def test_reject_unsafe_rounding(self):
        for inst in (instance(trips=[Trip(0,0,1,0,0,1.4)]),
                     instance(trips=[Trip(0,0,1,0,0,2.)],G=1.6)):
            with self.assertRaisesRegex(ValueError,'aligned'):
                price_truck_dp(inst,np.array([3.]),np.zeros(2),soc_mode='free')
        with self.assertRaisesRegex(ValueError,'aligned'):
            price_battery_dp(instance(G=1.6),np.ones(2),step=1.)

    def test_invalid_physics_and_duals(self):
        baseline=instance(trips=[Trip(0,0,1,0,0,0.)])
        modifications=(('soc_step',0.),('soc_step',-1.),('eta',1.),('rho',-1.),('G',-1.),('T',2.2))
        for attr,value in modifications:
            inst=deepcopy(baseline);setattr(inst,attr,value)
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                prepare_pricing(inst)
        for alpha,mu in (([1.,2.],[0.,0.]),([1.],[np.nan,0.])):
            with self.assertRaises(ValueError):price_truck_dp(baseline,alpha,mu)
        for attr,value in (('start',.5),('end',0),('sloc',1),('idx',2),('energy',-1.)):
            inst=deepcopy(baseline);setattr(inst.trips[0],attr,value)
            with self.subTest(attr=attr),self.assertRaises(ValueError):prepare_pricing(inst)
        with self.assertRaises(ValueError):price_truck_dp(baseline,[2.],[0.,0.],soc_mode='typo')

    def test_deadhead_grid_and_time_validation(self):
        inst=instance();inst.dist=np.array([[0.,1.],[1.,0.]])
        inst.energy_per_dist=.4
        with self.assertRaisesRegex(ValueError,'aligned'):prepare_pricing(inst)
        self.assertIsNotNone(prepare_pricing(inst,ice=True))
        inst.dist[0,1]=.5
        with self.assertRaisesRegex(ValueError,'integer'):prepare_pricing(inst,ice=True)
        inst.dist[0,1]=0.
        with self.assertRaises(ValueError):prepare_pricing(inst,ice=True)

    def test_reuse_is_immutable_and_mutation_guarded(self):
        clear_pricing_cache()
        inst=instance(trips=[Trip(0,0,1,0,0,0.)])
        prepared=prepare_pricing(inst)
        self.assertIs(prepared,prepare_pricing(deepcopy(inst)))
        with self.assertRaises(FrozenInstanceError):prepared.up=99
        with self.assertRaises(TypeError):prepared.trips_start[0][0][0]=None
        self.assertEqual(pricing_cache_info().hits,1)
        for field,value in (('rho',2.),('G',2.),('eta',.5),('depot',1),('energy_per_dist',1.)):
            changed=deepcopy(inst);setattr(changed,field,value)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'identity mismatch'):
                price_truck_dp(changed,[3.],[0.,0.],prepared=prepared)
        for mutate in (lambda x:setattr(x.trips[0],'energy',1.),
                       lambda x:setattr(x,'stations',[0,0]),
                       lambda x:x.dist.__setitem__((0,0),1.)):
            changed=deepcopy(inst);mutate(changed)
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                price_truck_dp(changed,[3.],[0.,0.],prepared=prepared)
        inst.trips[0].energy=1.
        updated=prepare_pricing(inst)
        self.assertIsNot(updated,prepared)
        self.assertEqual(updated.trips_start[0][0][0].shift,1)
        self.assertEqual(prepared.trips_start[0][0][0].shift,0)
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            price_truck_dp(inst,[3.],[0.,0.],prepared=prepared)

    def test_duals_and_costs_are_never_cached(self):
        inst=instance(trips=[Trip(0,0,1,0,0,1.)]);p=prepare_pricing(inst)
        first=price_truck_dp(inst,[4.],[0.,1.],prepared=p)[0][1]
        second=price_truck_dp(inst,[4.],[0.,2.],prepared=p)[0][1]
        self.assertEqual(second-first,1.)
        inst.c_v=2.
        third=price_truck_dp(inst,[4.],[0.,1.],prepared=p)[0][1]
        self.assertEqual(third-first,1.)
        self.assertIs(p,prepare_pricing(inst))

    def test_degradation_helpers_and_legacy_boundary(self):
        inst=instance(T=3,trips=[Trip(0,0,1,0,0,0.)]);inst.deg_cost=.5
        alpha=np.array([2.]);mu=np.array([0.,2.,0.])
        col,rc=price_truck_dp(inst,alpha,mu)[0]
        self.assertEqual(rc,-2.5)
        self.assertEqual(_dp_cost_via_networkx_at(inst,alpha,mu,step=1.),rc)
        lp,lprc=price_battery_lp(inst,mu)
        dp,dprc=price_battery_dp(inst,mu,step=1.)
        self.assertEqual(lprc,dprc)
        self.assertEqual(dprc,dp.cost(0)+dp.e@mu)
        free=instance(T=1)
        col,rc=price_battery_dp(free,np.ones(1),step=1.)
        np.testing.assert_array_equal(col.e,[-1.])


if __name__ == '__main__':unittest.main()
