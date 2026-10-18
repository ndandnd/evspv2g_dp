"""Independent bounded verifier checks; tiny enumerated cases only.

The verifier itself never optimizes. Four explicitly bounded SciPy/HiGHS calls
here compare a completely enumerated route family with the direct arc family.
These are excluded correctness tests, not main performance observations.
"""
from __future__ import annotations
import argparse,copy,json,sys,tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import verify_plugs as v
import numpy as np
from scipy.optimize import linprog,milp,Bounds,LinearConstraint
from plug_pricing import price_route
from plug_problem import direct_matrices,rmp_matrices,column_key


def main(output,calibration):
    if output.exists():raise ValueError('Fresh test output required')
    output.mkdir(parents=True);checks=[]
    def ok(name,condition,**details):
        checks.append({'name':name,'passed':bool(condition),**details})
        if not condition:raise AssertionError(name)
    def reject(name,fn):
        try:fn()
        except (ValueError,KeyError,IndexError,TypeError):ok(name,True);return
        ok(name,False)
    inst,caps=v.inputs.build_case(v.inputs.calibration_spec());p=v.PlugProblem(inst,caps);g=v.build_extended_graph(inst);seeds=v.fixed_seeds(p)
    reports=[]
    for arm in ('cg_lp','direct_lp','cg_pool_mip','direct_mip'):
        report=v.verify_worker(calibration/arm,local_test=True);reports.append(report)
        ok('raw_calibration_'+arm,report['passed'] and report['accepted_feasible_incumbent']
           and (not arm.endswith('_lp') or report['accepted_common_family_lp']),gap=report.get('full_family_gap'))
    ok('local_results_not_cluster_acceptance',all(not r['metadata']['cluster_protocol_accepted'] for r in reports))
    strict=v.verify_worker(calibration/'direct_lp')
    ok('local_controls_rejected_by_production_verifier',not strict['passed'])
    occ=sum((s.occupancy for s in seeds),np.zeros_like(caps))
    t=next(t for t in range(inst.T) if occ[0,t]==2 and sum(s.e[t] for s in seeds)<=inst.rho)
    ok('two_half_rate_trucks_still_two_connectors',occ[0,t]==2,total_energy=float(sum(s.e[t] for s in seeds)),rate=inst.rho)
    malformed=copy.deepcopy(seeds[0]);malformed.occupancy[0,t]=.5
    reject('fractional_connector_count_rejected',lambda:v.physical_column(p,malformed,seeds))
    malformed=copy.deepcopy(seeds[0]);malformed.occupancy=np.roll(malformed.occupancy,1,axis=1)
    reject('wrong_block_occupancy_rejected',lambda:v.physical_column(p,malformed,seeds))
    # Independent 2-station representation and nonuniform station/time prices.
    multi=copy.deepcopy(inst);multi.stations=[0,1];mp=v.PlugProblem(multi,np.ones((2,inst.T)));mg=v.build_extended_graph(multi)
    ms=v.fixed_seeds(mp);rng=np.random.default_rng(811731);diff=[];witnesses=[]
    for factor in (0,1):
        for draw in range(6):
            alpha=rng.uniform(-70,150,inst.n_trips);mu=rng.uniform(-20,30,inst.T);nu=rng.uniform(0,4,inst.T)
            pi=rng.uniform(0,9,(2,inst.T))+np.arange(inst.T)[None,:]*.13+np.arange(2)[:,None]*1.17
            candidate,value=price_route(mp,alpha,mu,nu,pi,factor)
            independent=v.scalar_graph_price(mp,mg,alpha,mu,nu,pi,factor)
            diff.append(abs(value-independent));witnesses.append(v.physical_column(mp,candidate,ms))
    ok('twelve_multisite_phaseI_phaseII_prices_match',max(diff)<1e-8,maximum_difference=max(diff))
    # An exhaustively enumerable instance; original singleton profiles stay physical.
    tiny=copy.deepcopy(multi);tiny.T=6;tiny.D=tiny.D[:6];tiny.P=tiny.P[:6];tiny.G=1.5
    tp=v.PlugProblem(tiny,np.ones((2,6)));tg=v.build_extended_graph(tiny);ts=v.fixed_seeds(tp)
    adjacency=[[] for _ in range(tg.n_nodes)]
    for edge,tail in enumerate(tg.tail):adjacency[int(tail)].append(edge)
    paths=[]
    def visit(node,path):
        if node==tg.sink:paths.append(path);return
        if len(paths)>1000:raise AssertionError('Tiny enumeration exceeded predeclared limit')
        for edge in adjacency[node]:visit(int(tg.head[edge]),path+[edge])
    visit(tg.source,[])
    cols=[v.graph_column(tp,tg,path) for path in paths]+ts
    for col in cols:v.physical_column(tp,col,ts)
    ok('all_tiny_routes_enumerated',0<len(paths)<=1000,paths=len(paths),nodes=tg.n_nodes,arcs=tg.n_arcs)
    for factor in (0,1):
        alpha=np.array([61.,74.]);mu=np.arange(6)*2.-3.;nu=np.arange(6)*.2;pi=np.array([[1,6,2,5,3,4],[7,1,8,2,9,3.]])
        brute=min(factor*c.cost(tiny.eps_pen)-alpha@c.a+mu@c.e+nu@np.maximum(c.e,0)+(pi*c.occupancy).sum() for c in cols[:-len(ts)])
        _,dp=price_route(tp,alpha,mu,nu,pi,factor)
        ok('complete_enumeration_price_phase_'+str(factor),abs(dp-brute)<1e-8,dp=dp,enumerated=brute)
    models={'paths':v.independent_rmp(tp,cols,'economic'),'arcs':v.independent_direct(tp,tg,ts)};values={}
    for label,model in models.items():
        c,lb,ub,ae,be,au,bu,off,plug_start=model
        runtime=rmp_matrices(tp,cols,'economic') if label=='paths' else direct_matrices(tp,tg,ts)
        ok('independent_'+label+'_matrix_matches',np.array_equal(c,runtime.c) and np.array_equal(lb,runtime.lb)
            and np.array_equal(ub,runtime.ub) and (ae!=runtime.ae).nnz==0 and np.array_equal(be,runtime.be)
            and (au!=runtime.au).nnz==0 and np.array_equal(bu,runtime.bu))
        lp=linprog(c,A_ub=au,b_ub=bu,A_eq=ae,b_eq=be,bounds=list(zip(lb,ub)),method='highs',options={'time_limit':5})
        require_indices=v.integer_indices(tg,off,len(c)) if label=='arcs' else np.r_[np.arange(len(cols)),off[5]].astype(int)
        integer=np.zeros(len(c),dtype=int);integer[require_indices]=1
        mip=milp(c,integrality=integer,bounds=Bounds(lb,ub),constraints=[LinearConstraint(ae,be,be),LinearConstraint(au,-np.inf,bu)],
            options={'time_limit':5,'mip_rel_gap':1e-9})
        ok(label+'_bounded_HiGHS_LP_IP_optimal',lp.success and mip.success,LP=lp.fun,IP=mip.fun)
        values[label]={'LP':float(lp.fun),'IP':float(mip.fun)}
        for kind,solution in [('LP',lp),('IP',mip)]:
            if label=='arcs':v.audit_direct_vector(tp,tg,ts,solution.x,float(solution.fun),kind=='IP')
            else:v.audit_pool_vector(tp,cols,solution.x,float(solution.fun),kind=='IP')
    ok('enumerated_routes_direct_arc_LP_and_IP_agree',all(abs(values['paths'][k]-values['arcs'][k])<1e-7 for k in ('LP','IP')),values=values)
    direct=v.independent_direct(mp,mg,ms);c,lb,ub,ae,be,au,bu,off,plugstart=direct
    ok('shared_BESS_does_not_use_truck_connectors',au[plugstart:,mg.n_arcs:off['seed_start']].nnz==0)
    active=(mg.kind==v.arc_flow.CHARGE)|(mg.kind==v.arc_flow.DISCHARGE)
    ok('both_active_directions_one_connector_other_events_zero',np.array_equal(np.asarray(au[plugstart:,:mg.n_arcs].sum(axis=0)).ravel(),active.astype(float)))
    zero=v.PlugProblem(inst,np.zeros_like(caps));zpath=ROOT/'checks_v1/required_checks/zero_plugs_cg_lp/phase1_stopping_primal.npz'
    with np.load(zpath,allow_pickle=False) as data:
        certificate=v.family_certificate(zero,g,v.fixed_seeds(zero),*[data[k] for k in ('alpha','mu','nu','plug_price')],'feasibility')
    ok('zero_plug_phaseI_positive_bound',certificate['phase1_positive_bound_infeasibility_evidence'] and certificate['global_economic_bound'] is None,
       bound=certificate['full_family_lower_bound'])
    with np.load(calibration/'cg_lp/phase2_stopping_primal.npz',allow_pickle=False) as data:
        cert=v.family_certificate(p,g,seeds,*[data[k] for k in ('alpha','mu','nu','plug_price')])
    final=cert['repaired_prices'];d=cert['final_price_diagnostics'];penalty=float(caps.ravel()@np.asarray(final['plug_price']).ravel())
    ok('finite_capacity_dual_constant_included',abs(d['dual_objective']-(sum(final['alpha'])+np.asarray(final['mu'])@inst.Delta-penalty))<1e-10 and penalty>0,
       capacity_penalty=penalty)
    # Mutated saved raw vectors are rejected before acceptance, even under local override.
    import shutil
    with tempfile.TemporaryDirectory(prefix='plugs-verifier-check-') as temp:
        dest=Path(temp)/'worker';shutil.copytree(calibration/'direct_lp',dest)
        with (dest/'direct_primal.npz').open('ab') as stream:stream.write(b'tamper')
        tampered=v.verify_worker(dest,local_test=True)
        ok('changed_raw_hash_rejected',not tampered['passed'] and 'Changed evidence' in tampered.get('error',''))
    report={'passed':True,'checks':checks,'count':len(checks),'verifier_sha256':v.sha(ROOT/'verify_plugs.py'),
        'runtime_sha256':__import__('run_plugs').source_hashes(),'calibration_reports':reports,
        'main_optimization_performed':False,'tiny_HiGHS_solves':4,'per_solve_seconds_limit':5,
        'scope':'Excluded correctness tests; no cluster or main benchmark execution; verifier itself uses no optimizer'}
    (output/'checks.json').write_text(json.dumps(v.safe(report),indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':True,'checks':len(checks),'enumerated_paths':len(paths)}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path)
    p.add_argument('--calibration',type=Path,default=ROOT/'checks_v2/calibration')
    a=p.parse_args();main(a.output,a.calibration)
