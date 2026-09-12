"""Manual, bounded timing probe: run directly; not a timing-sensitive unit test."""
from pathlib import Path
import importlib.util
import json
import sys
import time
import numpy as np
CANDIDATE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CANDIDATE))
from recreate_arxiv import build_instance, BREAKS2
from pricing_truck import price_truck_dp
from pricing_contract import prepare_pricing


def benchmark():
    spec=importlib.util.spec_from_file_location('reference_pricing',CANDIDATE.parent/'reference/pricing_truck.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    rng=np.random.default_rng(20260912);rows=[]
    for points in (2,4,10):
        inst=build_instance(points,2.,BREAKS2);inst.rho=1.75;inst.soc_step=.25
        prepared=prepare_pricing(inst)
        draws=[(rng.uniform(0,40,inst.n_trips),rng.uniform(0,5,inst.T),rng.uniform(0,1,inst.T)) for _ in range(3)]
        funcs={'reference':lambda a,m,n:old.price_truck_dp(inst,a,m,nu=n),
               'candidate_uncached':lambda a,m,n:price_truck_dp(inst,a,m,nu=n,use_cache=False),
               'candidate_cached':lambda a,m,n:price_truck_dp(inst,a,m,nu=n,prepared=prepared)}
        times={k:[] for k in funcs};worst=0.
        for a,m,n in draws:
            outputs={k:f(a,m,n) for k,f in funcs.items()}
            for result in outputs.values():
                assert bool(result)==bool(outputs['reference'])
                if result:worst=max(worst,abs(result[0][1]-outputs['reference'][0][1]))
            assert worst<1e-9
            for rep in range(5):
                for k in list(funcs)[rep%3:]+list(funcs)[:rep%3]:
                    t=time.perf_counter();funcs[k](a,m,n);times[k].append(time.perf_counter()-t)
        med={k:float(np.median(v)) for k,v in times.items()}
        rows.append(dict(points=points,trips=inst.n_trips,T=inst.T,levels=prepared.nlevels,draws=3,repeats=5,
                         seconds_median=med,reference_over_cached=med['reference']/med['candidate_cached'],
                         uncached_over_cached=med['candidate_uncached']/med['candidate_cached'],
                         max_minimum_difference=worst))
    return rows


if __name__=='__main__':print(json.dumps(benchmark(),indent=2))
