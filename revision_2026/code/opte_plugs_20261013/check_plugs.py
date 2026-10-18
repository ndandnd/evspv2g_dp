"""Required bounded local correctness checks; all instances are excluded pilots."""
from __future__ import annotations
import argparse,copy,gzip,json,sys,time
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'runtime'))
from run_plugs import source_hashes,experiment_plan,canonical_spec,input_binding
from plug_instances import build_case,calibration_spec,instance_record
from plug_problem import (PlugProblem,PlugColumn,seed_columns,artificial_columns,column_key,rmp_matrices,direct_matrices,
    replay_column,build_extended_graph,columns_from_record)
from plug_pricing import price_route,reduced_cost
from plug_master import PlugMaster
from plug_solvers import solve_arm,solve_matrix,ARMS
from extension_models import _hybrid_matrices
from arc_flow import CHARGE,DISCHARGE
from run_pilot import write_json


def scalar_price(problem,graph,alpha,mu,nu,pi,factor):
    dist=np.full(graph.n_nodes,np.inf);dist[graph.source]=0.
    for i in range(graph.n_arcs):
        u=int(graph.tail[i]);v=int(graph.head[i]);t,h=map(int,graph.states[u,:2]);e=graph.energy[i]
        value=mu[t]*e+nu[t]*max(e,0)+factor*(problem.inst.eps_pen*abs(e)+getattr(problem.inst,'deg_cost',0)*max(-e,0))
        if graph.task[i]>=0:value-=alpha[graph.task[i]]
        if graph.kind[i] in (CHARGE,DISCHARGE):value+=pi[problem.station_index[h],t]
        dist[v]=min(dist[v],dist[u]+value)
    return float(factor*problem.inst.c_v+dist[graph.sink])


def check_all(output):
    if output.exists():raise ValueError('Fresh check evidence directory required')
    output.mkdir(parents=True);checks=[]
    def ok(name,condition,**details):
        checks.append({'name':name,'passed':bool(condition),**details})
        if not condition:raise AssertionError(name)
    def rejects(name,fn):
        try:fn()
        except (ValueError,IndexError,TypeError):ok(name,True);return
        ok(name,False)
    inst,caps=build_case(calibration_spec());p=PlugProblem(inst,caps)
    results={}
    for arm in ARMS:
        folder=output/arm;folder.mkdir();result=solve_arm(p,arm,60,folder,20)
        write_json(folder/'result.json',result);results[arm]=result
        ok('calibration_'+arm,result['incumbent_validated'] and abs(result['objective']-125.075)<1e-7,
            objective=result['objective'],status=result['status'])
    trace=results['cg_lp']['cg']['trace'];phase1=[x['artificial_mass'] for x in trace if x['phase']=='feasibility']
    ok('phase1_restores_initially_infeasible_pool',phase1[0]>0 and phase1[-1]==0,artificial_masses=phase1)
    ok('LP_and_integer_agree',max(x['objective'] for x in results.values())-min(x['objective'] for x in results.values())<1e-7)
    ok('direct_MIP_root_barrier_pool_MIP_automatic',results['direct_mip']['solver_method']==2 and
        results['cg_pool_mip']['solver_method']==-1 and results['direct_lp']['solver_method']==2)
    seeds=seed_columns(p);seed_matrix=rmp_matrices(p,seeds)
    occ=sum((c.occupancy for c in seeds),np.zeros_like(caps));overlap=np.flatnonzero(occ.ravel()>1)
    ok('two_singletons_use_two_whole_plugs',len(overlap)>0 and np.max(occ)==2)
    partial=[(j,int(t)) for j,c in enumerate(seeds) for t in np.flatnonzero((c.e>0)&(c.e<inst.rho))]
    ok('partial_charge_still_one_plug',bool(partial) and all(seeds[j].occupancy[0,t]==1 for j,t in partial))
    # The two final half-rate singleton actions total one rate unit but need two plugs.
    t=next(t for j,t in partial if sum(c.occupancy[0,t] for c in seeds)==2)
    ok('rate_proxy_is_not_connector_count',sum(c.e[t] for c in seeds)<=inst.rho and sum(c.occupancy[0,t] for c in seeds)==2,
        total_energy=float(sum(c.e[t] for c in seeds)),rate=inst.rho,actual_plugs=2)
    unlimited=PlugProblem(inst,np.full_like(caps,np.inf));graph=build_extended_graph(inst)
    direct=direct_matrices(unlimited,graph,seed_columns(unlimited));original=_hybrid_matrices(inst,graph,seeds)
    ok('unlimited_direct_matrix_is_original',np.array_equal(direct.c,original[0]) and np.array_equal(direct.lb,original[1])
        and np.array_equal(direct.ub,original[2]) and (direct.ae!=original[3]).nnz==0 and np.array_equal(direct.be,original[4])
        and (direct.au!=original[5]).nnz==0 and np.array_equal(direct.bu,original[6]))
    unlim_results={}
    for arm in ('cg_lp','direct_lp'):
        folder=output/('unlimited_'+arm);folder.mkdir();r=solve_arm(unlimited,arm,60,folder,20);write_json(folder/'result.json',r);unlim_results[arm]=r
    ok('unlimited_LP_values_equal',all(r['incumbent_validated'] for r in unlim_results.values()) and
        abs(unlim_results['cg_lp']['objective']-unlim_results['direct_lp']['objective'])<1e-7,
        cg=unlim_results['cg_lp']['objective'],original_direct=unlim_results['direct_lp']['objective'])
    ok('binding_cap_can_raise_objective',results['direct_lp']['objective']>=unlim_results['direct_lp']['objective']-1e-7)
    zero=PlugProblem(inst,np.zeros_like(caps));zero_results={}
    for arm in ('cg_lp','direct_lp'):
        folder=output/('zero_plugs_'+arm);folder.mkdir();r=solve_arm(zero,arm,60,folder,20);write_json(folder/'result.json',r);zero_results[arm]=r
    ok('zero_plugs_direct_infeasible',zero_results['direct_lp']['native_status']==3,status=zero_results['direct_lp']['status'])
    ok('phase1_positive_kept_separate',zero_results['cg_lp']['status']=='phase1_priced_out_positive' and
        zero_results['cg_lp']['objective'] is None and not zero_results['cg_lp']['incumbent_validated'])
    from verify_plugs import family_certificate,fixed_seeds
    zsol=np.load(output/'zero_plugs_cg_lp/phase1_stopping_primal.npz')
    cert=family_certificate(zero,graph,fixed_seeds(zero),*[zsol[k] for k in ('alpha','mu','nu','plug_price')],'feasibility')
    ok('independent_phase1_infeasibility_bound',cert['phase1_positive_bound_infeasibility_evidence'],bound=cert['full_family_lower_bound'])
    # Multi-site vector recurrence against independently iterated explicit DAG.
    multi=copy.deepcopy(inst);multi.stations=[0,1];mp=PlugProblem(multi,np.ones((2,inst.T)));mg=build_extended_graph(multi)
    rng=np.random.default_rng(63101);maximum=0.
    for factor in (0,1):
        for j in range(8):
            alpha=rng.normal(0,80,inst.n_trips);mu=rng.normal(0,10,inst.T);nu=rng.uniform(0,3,inst.T);pi=rng.uniform(0,8,(2,inst.T))
            col,rc=price_route(mp,alpha,mu,nu,pi,factor);oracle=scalar_price(mp,mg,alpha,mu,nu,pi,factor)
            maximum=max(maximum,abs(rc-oracle));replay_column(mp,col)
    ok('sixteen_independent_graph_pricing_checks',maximum<1e-8,maximum_difference=maximum)
    dm=direct_matrices(mp,mg,seed_columns(mp));plug=dm.au[dm.plug_start:,:mg.n_arcs]
    active=(mg.kind==CHARGE)|(mg.kind==DISCHARGE);column_sums=np.asarray(plug.sum(axis=0)).ravel()
    ok('charge_and_discharge_occupy_idle_travel_tasks_do_not',np.array_equal(column_sums,active.astype(float)) and
        np.any(mg.kind==CHARGE) and np.any(mg.kind==DISCHARGE))
    shared=range(mg.n_arcs,dm.offsets['seed_start'])
    ok('stationary_BESS_excluded_from_truck_connectors',dm.au[dm.plug_start:,list(shared)].nnz==0)
    fake=copy.deepcopy(seeds[0]);fake.occupancy=np.zeros((2,inst.T));fake.occupancy[0]=seeds[0].occupancy[0]
    changed=copy.deepcopy(fake);changed.occupancy=np.roll(fake.occupancy,1,axis=0)
    ok('dedup_retains_location_occupancy',column_key(fake)!=column_key(changed))
    # Coefficients, bounds and basis after appending and PhaseI/II conversion.
    master=PlugMaster(mp);initial=seed_columns(mp)+artificial_columns(mp)
    try:
        master.initialize(initial,output/'coefficient_master.log');ok('initial_RMP_coefficients',master.coefficient_check()['passed'])
        sol,diag=master.solve(initial,time.perf_counter()+30,output/'coefficient_master_solve.log')
        col,rc=price_route(mp,np.full(inst.n_trips,100),np.zeros(inst.T),np.zeros(inst.T),np.arange(16).reshape(2,8),1)
        initial.append(col);master.append(initial);ok('appended_RMP_coefficients',master.coefficient_check()['passed'])
        master.economic_phase();ok('economic_RMP_coefficients',master.coefficient_check()['passed'])
        mat=rmp_matrices(mp,initial,'economic');order=master.route_vars+master.shared_vars
        lower=np.array(master.model.getAttr('LB',order));upper=np.array(master.model.getAttr('UB',order));upper[upper>=1e100]=np.inf
        ok('phase2_artificial_upper_bounds_zero',np.array_equal(lower,mat.lb) and np.array_equal(upper,mat.ub))
        ok('appended_basis_restored',master.basis_restorations>=1)
    finally:master.close()
    for name,invalid in [('negative_cap',-np.ones_like(caps)),('fractional_cap',caps*.5),('nan_cap',caps*np.nan),('wrong_shape',np.ones((2,8)))]:
        rejects(name,lambda bad=invalid:PlugProblem(inst,bad))
    malformed=copy.deepcopy(seeds[0]);malformed.witness['states'][1][1]=-1
    rejects('negative_location_witness_rejected',lambda:replay_column(p,malformed))
    bad=copy.deepcopy(seeds[0]);bad.occupancy[0,0]=.5
    rejects('fractional_route_occupancy_rejected',lambda:rmp_matrices(p,[bad]))
    folder=output/'iteration_limit_pool';folder.mkdir();limited=solve_arm(p,'cg_pool_mip',60,folder,20,1);write_json(folder/'result.json',limited)
    with gzip.open(folder/'pool_columns.json.gz','rt') as f:limitedcols=columns_from_record(json.load(f))
    ok('iteration_limit_keeps_real_seed_fallback',len(limitedcols)>=inst.n_trips and all(c.kind=='truck' for c in limitedcols)
        and limited['cg']['status']=='iteration_limit')
    ok('infeasible_restricted_pool_not_global_claim',limited['native_status']==3 and
        limited['status_scope']=='Restricted integer pool only' and limited['global_integer_optimality_claimed'] is False)
    for arm in ('cg_lp','cg_pool_mip','direct_lp'):
        folder=output/('deadline_'+arm);folder.mkdir();r=solve_arm(p,arm,1e-9,folder,5e-10);write_json(folder/'result.json',r)
        ok('deadline_'+arm,r.get('objective') is None and not r['incumbent_validated'],status=r['status'])
    plan=experiment_plan();ok('all18_rotated_four_arm_blocks',len(plan)==18 and all(sorted(row['arms'])==sorted(ARMS) for row in plan))
    raw=instance_record(inst,caps);input_binding(calibration_spec(),raw)
    ok('calibration_alias_and_exact_input',canonical_spec('calibration')==calibration_spec())
    badraw=copy.deepcopy(raw);badraw['sha256']='0'*64
    rejects('tampered_input_binding_rejected',lambda:input_binding(calibration_spec(),badraw))
    report={'passed':True,'checks':checks,'count':len(checks),'source_sha256':source_hashes(),
        'main_optimization_performed':False,'only_tiny_excluded_pilots_solved':True,
        'independent_phase1_certificate':cert,'limitation':'Local Gurobi12.0.1 correctness checks; not cluster timing or main experimental outcomes'}
    write_json(output/'checks.json',report);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report=check_all(args.output);print(json.dumps({'passed':True,'checks':report['count']}))
