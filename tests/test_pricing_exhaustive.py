"""Independent physical enumeration: copied from the review, not the new DP."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instance import Instance, Trip
from pricing_truck import price_truck_dp

def enumerate_paths(inst,alpha,mu,nu,mode,allow_discharge,ice):
    starts=range(int(inst.G)+1) if mode=='periodic' else [1 if mode=='pin1' else inst.G]
    best=float('inf');physical=set();leaves=0
    def walk(t,loc,s,mask,cost,e,s0):
        nonlocal best,leaves
        if t==inst.T:
            if loc==0 and mask and (mode=='free' or s==s0):
                best=min(best,inst.c_v+cost);physical.add((mask,tuple(e)));leaves+=1
            return
        walk(t+1,loc,s,mask,cost,e+[0.],s0)
        if not ice and loc in inst.charge_locs:
            for ss in range(int(inst.G)+1):
                if ss==s:continue
                grid=(ss-s)/(1-inst.eta) if ss>s else ss-s
                if abs(grid)>inst.rho+1e-10 or (grid<0 and not allow_discharge):continue
                arc=mu[t]*grid+inst.eps_pen*abs(grid)+nu[t]*max(grid,0)+inst.deg_cost*max(-grid,0)
                walk(t+1,loc,ss,mask,cost+arc,e+[grid],s0)
        for dest in range(2):
            if dest==loc:continue
            dt=int(inst.dist[loc,dest]);ds=0 if ice else inst.deadhead_energy(loc,dest)
            if t+dt<=inst.T and s>=ds:walk(t+dt,dest,s-ds,mask,cost,e+[0.]*dt,s0)
        for tr in inst.trips:
            ds=0 if ice else tr.energy
            if tr.start==t and tr.sloc==loc and s>=ds:
                walk(tr.end,tr.eloc,s-ds,mask|(1<<tr.idx),cost-alpha[tr.idx],e+[0.]*(tr.end-t),s0)
    for s0 in starts:walk(0,0,s0,0,0.,[],s0)
    return best,physical,leaves


class ExhaustivePricing(unittest.TestCase):
    def test_128_independent_aligned_cases(self):
        rng=np.random.default_rng(20260912);cases=[];worst=0.;totalleaves=0
        for seed in range(16):
            trips=[]
            for i in range(3):
                t=int(rng.integers(0,4));trips.append(Trip(i,t,t+1,int(rng.integers(0,2)),int(rng.integers(0,2)),float(rng.integers(0,3))))
            inst=Instance(T=4,D=np.zeros(4),P=np.zeros(4),trips=trips,dist=np.array([[0.,1.],[1.,0.]]),G=2.,rho=2.,eta=.5 if seed%2 else 0.,energy_per_dist=1.,c_g=1.,c_v=1.,c_b=0.,eps_pen=.03,soc_step=1.,deg_cost=.2 if seed%3 else 0.,stations=[0,1] if seed%4 else [0])
            alpha=rng.uniform(-2,7,3);mu=rng.uniform(0,4,4);nu=rng.uniform(0,1,4)
            for mode in ['cyclic','free','periodic','pin1']:
                for ice in [False,True]:
                    allow_discharge=bool(seed%3)
                    exact,physical,leaves=enumerate_paths(inst,alpha,mu,nu,mode,allow_discharge,ice)
                    totalleaves+=leaves
                    out=price_truck_dp(inst,alpha,mu,nu=nu,soc_mode=mode,ice=ice,allow_discharge=allow_discharge)
                    cold=price_truck_dp(inst,alpha,mu,nu=nu,soc_mode=mode,ice=ice,allow_discharge=allow_discharge,use_cache=False)
                    assert len(out)==len(cold)
                    for (oc,orr),(cc,crr) in zip(out,cold):
                        assert orr==crr and np.array_equal(oc.a,cc.a) and np.array_equal(oc.e,cc.e)
                    if exact < -1e-6:
                        assert out,(seed,mode,ice,exact)
                        col,rc=out[0]
                        direct=col.cost(inst.eps_pen)-col.a@alpha+col.e@mu+np.maximum(col.e,0)@nu
                        mask=sum((1<<i) for i,x in enumerate(col.a) if x>.5)
                        assert (mask,tuple(col.e)) in physical,(seed,mode,ice,col.a,col.e)
                        error=max(abs(exact-rc),abs(direct-rc));worst=max(worst,error)
                        assert error<1e-9,(seed,mode,ice,exact,rc,direct)
                    else:assert not out,(seed,mode,ice,exact)
                    cases.append(dict(seed=seed,mode=mode,ice=ice,feasible_terminal_paths=leaves))
        self.assertEqual(len(cases),128)
        self.assertEqual(totalleaves,1278)
        self.assertLess(worst,1e-9)
        print(f"Independent enumeration: {len(cases)} cases, {totalleaves} paths, max error {worst:.3g}")

if __name__ == "__main__":
    unittest.main()
