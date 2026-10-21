"""Formulation and incremental-adapter checks against the immutable release."""
import ast
import csv
import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.sparse import coo_matrix, csr_matrix, hstack, vstack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from instance import Instance, Trip
from master import Column
from stochastic_master import (StochasticTemplate, PersistentStochasticLP,
    StructuralMutationError, expected_model, model, phase_model, lp, default_instance)

ROOT = Path(os.environ.get("V2G_REVIEW_ROOT", str(Path(__file__).resolve().parents[2])))


def legacy_functions(factory):
    """Compile only pure builder definitions; never import the campaign worker."""
    master_path = ROOT / "reference/master.py"
    worker_path = ROOT / "releases/method_union_v8/campaign_code/worker.py"
    if not master_path.exists() or not worker_path.exists():
        pytest.skip("immutable baseline files unavailable; set V2G_REVIEW_ROOT")
    tree = ast.parse(master_path.read_text())
    selected = ast.Module(body=[x for x in tree.body if isinstance(x, ast.FunctionDef)
                               and x.name in {"_layout", "_build_lp"}], type_ignores=[])
    scope = dict(np=np, Instance=Instance, Column=Column, COVERING=False)
    exec(compile(selected,str(master_path),"exec"),scope)
    tree = ast.parse(worker_path.read_text())
    selected = ast.Module(body=[x for x in tree.body if isinstance(x, ast.FunctionDef)
                               and x.name in {"expected_model", "model", "phase_model"}],type_ignores=[])
    scope.update(instance=factory,coo_matrix=coo_matrix,csr_matrix=csr_matrix,
                 hstack=hstack,vstack=vstack,SCENARIOS={"v2g":{"battery":True},"v2g_fleet":{"battery":False},"solar_bess":{"battery":True}})
    exec(compile(selected,str(worker_path),"exec"),scope)
    return scope


def assert_models_equal(expected, actual):
    for index in [0,2,4,5,6]:
        np.testing.assert_array_equal(expected[index],actual[index],err_msg=f"tuple index {index}")
    for index in [1,3]:
        assert expected[index].shape == actual[index].shape
        assert (expected[index] != actual[index]).nnz == 0
    assert expected[7] == actual[7]


def tiny(delta=(1.,2.,0.,1.), **kw):
    params=dict(T=4,D=np.maximum(delta,0.),P=np.maximum(-np.asarray(delta),0.),
                trips=[Trip(0,0,1,0,0,0),Trip(1,2,3,0,0,0)],dist=np.zeros((1,1)),
                G=4,rho=2,eta=.2,energy_per_dist=0,c_g=3,c_v=8,c_b=5,eps_pen=.025,
                gen_cap=np.array([5.,6.,7.,8.]),charge_cap=3.,soc_step=1.,deg_cost=.1)
    params.update(kw)
    return Instance(**params)


def columns():
    return [Column("truck",np.array([1.,0.]),np.array([1.,0.,-.5,0.]),8.),
            Column("truck",np.array([0.,1.]),np.array([0.,1.,0.,-.5]),8.),
            Column("truck",np.array([1.,1.]),np.array([.5,0.,0.,-.25]),9.),
            Column("artificial",np.array([1.,0.]),np.zeros(4),1000.),
            Column("artificial",np.array([0.,1.]),np.zeros(4),1000.)]


@pytest.mark.parametrize("method",["saa","minimax"])
@pytest.mark.parametrize("battery",[True,False])
@pytest.mark.parametrize("mode",["economic","phase1","fixed"])
def test_exact_tiny_coefficients(method,battery,mode):
    ds=np.array([[1.,2.,0.,1.],[2.,-1.,1.,0.],[0.,3.,-1.,2.]])
    cfg=dict(method=method,arm="v2g" if battery else "v2g_fleet",weights=[.2,.3,.5])
    factory=lambda cfg,d:tiny(d,fuel_budget=15,max_trucks=2,nb_fixed=1 if battery else 0)
    old=legacy_functions(factory);cols=columns();t=StochasticTemplate([factory(cfg,d) for d in ds],battery_allowed=battery,weights=cfg['weights'],method=method)
    if mode=="phase1":
        a=old['phase_model'](cfg,ds,cols,1.2);b=t.build(cols,phase_cap=1.2)
    else:
        fixed=np.r_[[1.,1.,0.,0.,0.],1 if battery else 0,0.] if mode=="fixed" else None
        a=old['model'](cfg,ds,cols,fixed);b=t.build(cols,fixed)
    assert_models_equal(a,b)


def test_scenario_caps_and_weights_and_cache_guard():
    ins=[tiny(),tiny((2.,0.,1.,2.),gen_cap=np.array([1.,2.,3.,4.]),charge_cap=np.inf,fuel_budget=12)]
    t=StochasticTemplate(ins,weights=[.7,.3]);cols=columns()
    first=t.build(cols[:2]);static_id=id(t._au);second=t.build(cols)
    assert id(t._au)==static_id and t.stats['template_builds']==1 and t.stats['pool_builds']==2
    assert first[-1][1]['cap'] is None
    out=lp(second);assert out.success
    d=t.pricing_duals(out)
    expected=-sum((out.ineqlin.marginals[md['balance']:md['balance']+4] for md in t.meta),np.zeros(4))
    np.testing.assert_array_equal(d['mu'],expected)
    assert np.max(np.abs(d['mu'] - .7*expected)) > 1e-4
    ins[1].gen_cap[0]=.1
    with pytest.raises(StructuralMutationError): t.build(cols)


def test_phase_artificial_and_fleet_dual_coefficients():
    t=StochasticTemplate([tiny(max_trucks=1),tiny(max_trucks=1)],weights=[.1,.9])
    cols=columns();phase=t.build(cols,phase_cap=.1)
    np.testing.assert_array_equal(phase[0][:5],[0,0,0,1,1])
    np.testing.assert_array_equal(phase[0][-8:],np.full(8,.5))
    result=lp(phase);assert result.success
    for r,col in enumerate(cols):
        direct=phase[0][r]-float(phase[1][:,r].toarray().ravel()@result.ineqlin.marginals)-float(phase[3][:,r].toarray().ravel()@result.eqlin.marginals)
        assert abs(t.reduced_cost(col,result,phase=True)-direct)<1e-8
    econ=t.build(cols,forbid_artificials=True)
    np.testing.assert_array_equal(econ[6][3:5],[0,0])


def test_fixed_and_dimension_and_identity_errors():
    t=StochasticTemplate([tiny()]);cols=columns()
    with pytest.raises(ValueError):t.build(cols,fixed=np.zeros(2))
    with pytest.raises(ValueError):t.build(cols,phase_cap=-1)
    with pytest.raises(ValueError):t.build([Column('truck',np.ones(3),np.zeros(4),1)])
    with pytest.raises(ValueError):StochasticTemplate([tiny()],weights=[0])
    with pytest.raises(ValueError):StochasticTemplate([tiny(),tiny(rho=3)])
    t.weights[0]=.5
    with pytest.raises(StructuralMutationError):t.build(cols)


def test_tuple_wrappers_and_uniform_evaluation_fallback():
    cfg=dict(method='minimax',arm='v2g',weights=[.2,.8]);ds=[np.ones(4)]
    old=legacy_functions(lambda cfg,d:tiny(d))
    for name,fn in [('expected_model',expected_model),('model',model)]:
        assert_models_equal(old[name](cfg,ds,columns()),fn(cfg,ds,columns(),instance_factory=lambda cfg,d:tiny(d)))
    assert_models_equal(old['phase_model'](cfg,ds,columns(),1),phase_model(cfg,ds,columns(),1,instance_factory=lambda cfg,d:tiny(d)))


@pytest.mark.parametrize('cell',[1,11,21])
@pytest.mark.parametrize('scenarios',[8,24,64])
def test_nine_known_pool_cells(cell,scenarios):
    snap=ROOT/'snapshots/fair_policy_validation/campaigns/weather_fair_policy_wave7'
    if not (snap/'cases.json').exists():pytest.skip('known pool snapshot unavailable')
    cfg=json.loads((snap/'cases.json').read_text())[cell]
    payload=json.loads((snap/'cases'/f'{cell:04d}'/'pool.json').read_text())
    cols=[Column(c['kind'],np.array(c['a']),np.array(c['e']),c['fixed_cost'],c['label']) for c in payload['columns']]
    from profile_robustness import base_curves
    data_path=Path(__file__).resolve().parents[1]/'data/solar_days_2023.csv'
    with data_path.open() as handle:
        rows=[r for r in csv.reader(handle) if r and not r[0].startswith('#') and r[0]!='date']
    g=np.array([[float(v) for v in r[1:25]] for r in rows]);demand,pv=base_curves()
    weather=demand[None,:]-(pv.sum()*cfg['pv']/g.sum(axis=1).mean())*g
    ds=weather[np.random.default_rng(cfg['seed']).permutation(len(weather))[:scenarios]]
    cfg=dict(cfg,method='saa');cfg.pop('weights',None)
    old=legacy_functions(default_instance)
    assert_models_equal(old['expected_model'](cfg,ds,cols),expected_model(cfg,ds,cols))


def gurobi_available():
    try:
        import gurobipy as gp
        m=gp.Model();m.Params.OutputFlag=0;m.addVar();m.optimize();m.dispose()
        return True
    except Exception:return False


@pytest.mark.skipif(not gurobi_available(),reason='Gurobi package/license unavailable')
@pytest.mark.parametrize('method',['saa','minimax'])
@pytest.mark.parametrize('phase',[False,True])
def test_persistent_matches_sparse_incrementally(method,phase):
    t=StochasticTemplate([tiny(),tiny((2.,1.,0.,2.))],weights=[.25,.75],method=method)
    cols=columns();initial=cols[:2]+cols[3:]
    phase_cap=.5 if phase else None
    with PersistentStochasticLP(t,initial,phase_cap=phase_cap) as session:
        model_id=id(session.model)
        for pool in [initial,initial+[cols[2]]]:
            session.sync(pool);got=session.solve();expected=lp(t.build(pool,phase_cap=phase_cap))
            assert got.success and expected.success
            assert abs(got.fun-expected.fun)<1e-7
            assert id(session.model)==model_id
            for col in pool:
                assert t.reduced_cost(col,got,phase=phase)>-1e-6
            # Both solvers can choose different degenerate duals; each must
            # reconstruct its own coefficient-based reduced costs exactly.
            matrix=t.build(pool,phase_cap=phase_cap)
            for i,col in enumerate(pool):
                direct=matrix[0][i]-matrix[1][:,i].toarray().ravel()@got.ineqlin.marginals-matrix[3][:,i].toarray().ravel()@got.eqlin.marginals
                assert abs(direct-t.reduced_cost(col,got,phase=phase))<1e-7
        with pytest.raises(StructuralMutationError):session.sync(initial)
        pool[-1].fixed_cost+=1
        with pytest.raises(StructuralMutationError):session.solve()


@pytest.mark.skipif(not gurobi_available(),reason='Gurobi package/license unavailable')
def test_persistent_fixed_artificials_and_infeasibility():
    t=StochasticTemplate([tiny()],battery_allowed=False);cols=columns()
    fixed=np.r_[[1,1,0,0,0],0,0]
    with PersistentStochasticLP(t,cols,fixed=fixed,forbid_artificials=True) as session:
        got=session.solve();expected=lp(t.build(cols,fixed,forbid_artificials=True))
        assert got.success==expected.success and abs(got.fun-expected.fun)<1e-7
    bad=StochasticTemplate([tiny(gen_cap=0)],battery_allowed=False)
    with PersistentStochasticLP(bad,cols,forbid_artificials=True) as session:
        got=session.solve();assert not got.success and got.x is None


def test_wrapper_rejects_foreign_template_and_return_mutation():
    factory=lambda cfg,d:tiny(d)
    cfg=dict(method='saa',arm='v2g',weights=[.25,.75]);ds=[np.ones(4),np.full(4,2.)]
    t=StochasticTemplate([factory(cfg,d) for d in ds],weights=cfg['weights'])
    out=model(cfg,ds,columns(),template=t,instance_factory=factory)
    out[2][0]=999;out[4][0]=999;out[1].data[:]=999
    again=model(cfg,ds,columns(),template=t,instance_factory=factory)
    assert again[2][0]==-1 and again[4][0]==1
    with pytest.raises(StructuralMutationError):
        model(dict(cfg,weights=[.5,.5]),ds,columns(),template=t,instance_factory=factory)
    with pytest.raises(StructuralMutationError):
        model(cfg,[np.zeros(4),ds[1]],columns(),template=t,instance_factory=factory)


@pytest.mark.skipif(not gurobi_available(),reason='Gurobi package/license unavailable')
def test_persistent_input_guards_and_empty_batch():
    t=StochasticTemplate([tiny()]);cols=columns()
    with pytest.raises(ValueError):PersistentStochasticLP(t,cols,fixed=np.full(len(cols)+2,np.nan))
    with PersistentStochasticLP(t,cols) as session:
        size=session.model.NumVars
        assert session.sync(cols)==0 and session.model.NumVars==size
        session.forbid_artificials=True
        with pytest.raises(StructuralMutationError):session.solve()
    with PersistentStochasticLP(t,cols) as session:
        t.instances[0].trips[0].energy=1
        with pytest.raises(StructuralMutationError):session.sync(cols)


def test_scenario_varying_row_structures_match_release():
    ds=[np.array([1.,2.,0.,1.]),np.array([2.,1.,0.,1.])]
    def factory(cfg,d):
        return tiny(d,charge_cap=np.inf if d[0]==1 else 3.,
                    fuel_budget=12 if d[0]==1 else np.inf,
                    max_trucks=np.inf if d[0]==1 else 2.,
                    nb_fixed=-1 if d[0]==1 else 1.)
    cfg=dict(method='minimax',arm='v2g',weights=[.8,.2]);old=legacy_functions(factory)
    assert_models_equal(old['model'](cfg,ds,columns()),model(cfg,ds,columns(),instance_factory=factory))


@pytest.mark.skipif(not gurobi_available(),reason='Gurobi package/license unavailable')
def test_persistent_keeps_same_trip_different_profile_columns():
    t=StochasticTemplate([tiny()]);base=columns()[:2]
    extra=Column('truck',base[0].a.copy(),np.array([0.,.5,-.25,0.]),8.)
    with PersistentStochasticLP(t,base) as session:
        assert session.sync(base+[extra])==1
        assert len(session.cols)==3
        got=session.solve();expected=lp(t.build(base+[extra]))
        assert got.success and abs(got.fun-expected.fun)<1e-7


def test_tiny_grid_positive_capacity_coefficient_is_not_dropped():
    inst=tiny(G=1e-9,rho=2e-10,soc_step=1e-10,eta=0.,charge_cap=2e-10)
    t=StochasticTemplate([inst])
    col=Column('truck',np.array([1.,0.]),np.array([1e-10,0.,-1e-10,0.]),8.)
    m=t.build([col]);row=t.meta[0]['cap']
    assert m[1][row,0]==1e-10
    from scipy.optimize import OptimizeResult
    dual=np.zeros(len(m[2]));dual[row]=-2.
    result=OptimizeResult(ineqlin=OptimizeResult(marginals=dual),eqlin=OptimizeResult(marginals=np.zeros(len(m[4]))))
    assert abs(t.reduced_cost(col,result)-(col.cost(inst.eps_pen)+2e-10))<1e-14
