"""Fault-oriented benchmark contracts; no production scenario execution."""
from pathlib import Path
import json
import sys

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'benchmarks'))
import algorithm_benchmark as bench
from durable import Journal,pack,sha
from instance import Instance,Trip
from master import Column
from stochastic_master import StochasticTemplate,PersistentStochasticLP,lp
from pricing_contract import clear_pricing_cache,prepare_pricing,pricing_cache_info


def tiny():
    return Instance(T=4,D=np.ones(4),P=np.zeros(4),trips=[Trip(0,0,1,0,0,0),Trip(1,2,3,0,0,0)],
                    dist=np.zeros((1,1)),G=4,rho=2,eta=0,energy_per_dist=0,
                    c_g=3,c_v=8,c_b=5,eps_pen=.025,gen_cap=5,charge_cap=3,soc_step=1)


def seed_cols():
    return [Column('truck',np.array([1.,0.]),np.zeros(4),8.),
            Column('artificial',np.array([1.,0.]),np.zeros(4),1000.),
            Column('truck',np.array([0.,1.]),np.zeros(4),8.),
            Column('artificial',np.array([0.,1.]),np.zeros(4),1000.)]


@pytest.mark.parametrize('bad',['vector_nan','objective_nan','vector_inf'])
def test_validate_lp_rejects_nonfinite(bad):
    m=StochasticTemplate([tiny()]).build(seed_cols());r=lp(m);assert r.success
    if bad=='vector_nan':r.x[0]=np.nan
    elif bad=='vector_inf':r.x[0]=np.inf
    else:r.fun=np.nan
    with pytest.raises((ValueError,RuntimeError)):bench.validate_lp(m,r)


def test_pricing_lru_can_start_each_ablation_empty():
    clear_pricing_cache();prepare_pricing(tiny());assert pricing_cache_info().currsize==1
    clear_pricing_cache();info=pricing_cache_info()
    assert info.currsize==info.hits==info.misses==0


def test_partial_seed_journal_can_resume_to_complete_initialization(tmp_path,monkeypatch):
    original=bench.Journal;fault={'fired':False}
    class CrashAfterFirstSeed(original):
        def add(self,col,iteration):
            super().add(col,iteration)
            if not fault['fired']:
                fault['fired']=True
                raise RuntimeError('injected seed fsync interruption')
    monkeypatch.setattr(bench,'Journal',CrashAfterFirstSeed)
    monkeypatch.setattr(bench,'load_weather',lambda cfg:(['test'],[np.ones(4)]))
    monkeypatch.setattr(bench,'default_instance',lambda cfg,d:tiny())
    monkeypatch.setattr(bench,'initial_columns',lambda *a,**kw:seed_cols())
    monkeypatch.setattr(bench,'price_truck_dp',lambda *a,**kw:[])
    monkeypatch.setattr(bench,'STOP',False)
    cfg=dict(arm='v2g',seed=1,pv=1,samples=1)
    manifest=dict(execution_commit='test-only')
    with pytest.raises(RuntimeError,match='injected'):
        bench.run_cg(cfg,'sparse_highs',tmp_path/'out',manifest,tmp_path)
    bench.run_cg(cfg,'sparse_highs',tmp_path/'out',manifest,tmp_path)
    import json
    p=json.loads((tmp_path/'out/pool.json').read_text())
    assert p['certified'] and p['lp_objective']>1
    assert len(p['columns'])==2


def test_budget_after_phase_transition_never_publishes_phase_objective(tmp_path,monkeypatch):
    clock={'now':0.}
    monkeypatch.setattr(bench.time,'perf_counter',lambda:clock['now'])
    monkeypatch.setattr(bench,'load_weather',lambda cfg:(['test'],[np.ones(4)]))
    monkeypatch.setattr(bench,'default_instance',lambda cfg,d:tiny())
    monkeypatch.setattr(bench,'initial_columns',lambda *a,**kw:seed_cols())
    def price(*args,**kwargs):
        clock['now']=1801.
        return []
    monkeypatch.setattr(bench,'price_truck_dp',price)
    monkeypatch.setattr(bench,'STOP',False)
    cfg=dict(arm='v2g',seed=1,pv=1,samples=1)
    out=tmp_path/'out'
    with pytest.raises(RuntimeError,match='No economic LP'):
        bench.run_cg(cfg,'sparse_highs',out,dict(execution_commit='test-only'),tmp_path)
    assert not (out/'pool.json').exists()
    assert json.loads((out/'phase1_certificate.json').read_text())['objective']==0.
    saved=json.loads((out/'checkpoint.json').read_text())
    assert saved['phase']=='economic'
    assert saved['state']=='budget_before_feasible_economic_lp'


def test_warm_cap_survives_crash_after_column_fsync(tmp_path,monkeypatch):
    """Progress lags the accepted journal by one row at the injected failure."""
    original=bench.Journal;fault={'warm':0,'fired':False}
    class CrashBeforeWarmProgress(original):
        def add(self,col,iteration):
            super().add(col,iteration)
            if iteration==-2:
                fault['warm']+=1
                if fault['warm']==127 and not fault['fired']:
                    fault['fired']=True
                    raise RuntimeError('injected warm fsync interruption')
    class PortableSession:
        def __init__(self,template,cols=(),**kwargs):
            self.template=template;self.cols=cols
            self.kwargs={k:v for k,v in kwargs.items() if k in ('phase_cap','forbid_artificials')}
        def sync(self,cols):self.cols=cols
        def solve(self,**kwargs):
            matrix=self.template.build(self.cols,**self.kwargs)
            result=lp(matrix)
            if result.success:result.max_primal_violation=bench.validate_lp(matrix,result)
            return result
        def close(self):pass
    monkeypatch.setattr(bench,'Journal',CrashBeforeWarmProgress)
    monkeypatch.setattr(bench,'PersistentStochasticLP',PortableSession)
    monkeypatch.setattr(bench,'load_weather',lambda cfg:(['test'],[np.ones(4)]))
    monkeypatch.setattr(bench,'default_instance',lambda cfg,d:tiny())
    monkeypatch.setattr(bench,'initial_columns',lambda *a,**kw:seed_cols())
    monkeypatch.setattr(bench,'price_truck_dp',lambda *a,**kw:[])
    # This test concerns durable counters, not the independent physical checker.
    monkeypatch.setattr(bench,'replay_column',lambda *a,**kw:True)
    monkeypatch.setattr(bench,'STOP',False)
    warm=[Column('truck',np.array([1.,0.]),np.array([(i+1)*.001,0.,0.,0.]),8.) for i in range(140)]
    source=tmp_path/'warm.json';source.write_text(json.dumps({'columns':[pack(c) for c in warm]}))
    cfg=dict(arm='v2g',seed=1,pv=1,samples=1,warm_source=dict(path=source.name,sha256=sha(source)))
    manifest=dict(execution_commit='test-only');out=tmp_path/'out'
    with pytest.raises(RuntimeError,match='injected'):
        bench.run_cg(cfg,'persistent_cached_warm',out,manifest,tmp_path)
    assert json.loads((out/'warm_progress.json').read_text())['accepted']==126
    bench.run_cg(cfg,'persistent_cached_warm',out,manifest,tmp_path)
    rows=[json.loads(line) for line in (out/'accepted.columns.jsonl').read_text().splitlines()]
    assert sum(row['iteration']==-2 for row in rows)==128
    stats=json.loads((out/'warm_import.json').read_text())
    assert stats['accepted']==128 and stats['stop']=='column_limit'


def has_gurobi():
    try:
        import gurobipy as gp
        m=gp.Model();m.Params.OutputFlag=0;m.addVar();m.optimize();m.dispose();return True
    except Exception:return False


@pytest.mark.skipif(not has_gurobi(),reason='Gurobi package/license unavailable')
@pytest.mark.parametrize('phase',[False,True])
def test_benchmark_cold_native_and_persistent_same_frozen_matrix(phase):
    inst=tiny();t=StochasticTemplate([inst,tiny()],weights=[.2,.8])
    cols=seed_cols();cap=.5 if phase else None
    m=t.build(cols,phase_cap=cap,forbid_artificials=not phase)
    cold=bench.cold_lp(m,'gurobi')
    # Staged timing refactors may return a result plus metadata.
    if isinstance(cold,tuple):cold=cold[0]
    with PersistentStochasticLP(t,cols,phase_cap=cap,forbid_artificials=not phase) as session:
        native=session.solve()
        assert native.success and cold.success
        assert abs(native.fun-cold.fun)<1e-7
        assert bench.validate_lp(m,native)<=1e-6
        assert bench.validate_lp(m,cold)<=1e-6
        for result in (cold,native):
            for i,col in enumerate(cols):
                rc=m[0][i]-m[1][:,i].toarray().ravel()@result.ineqlin.marginals-m[3][:,i].toarray().ravel()@result.eqlin.marginals
                assert abs(rc-t.reduced_cost(col,result,phase=phase))<1e-7
