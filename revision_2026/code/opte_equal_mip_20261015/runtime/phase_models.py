"""Unchanged pricing/persistent LP algorithms, new bounded integer pipeline.

No branch-and-price. Apply a600second phase deadline to the frozen CG driver,
then solve its accepted real route pool until the shared1800second deadline.
A noninterruptible pricing call can overrun the phase deadline; its unprocessed
output is discarded and the overrun is charged to the shared deadline. Physical
graph replay is deferred until the integer algorithm stops. No external bound,
primal solution, basis or route pool is read by either timed algorithm.
"""
from __future__ import annotations
import gzip
import json
from pathlib import Path
import time
import traceback
import followup_inputs as _inputs
import numpy as np
from scipy import sparse
import colgen
import master
from persistent_rmp import PersistentRMP,column_fingerprint
from run_pilot import BudgetExpired,safe,write_json
from lp_scaling_models import peak_rss_bytes
from rmp_solver import replay_rmp,_validate_scope
from extension_models import build_extended_graph,validate_extended_selected_columns
from direct_mip_1000 import primal_check

TOL=1e-6


def save_columns(path,cols):
    with gzip.open(path,'wt') as stream:
        json.dump(safe([{'kind':c.kind,'a':c.a,'e':c.e,'fixed_cost':c.fixed_cost,'label':c.label} for c in cols]),stream)


def generate_pool(inst,started,deadline,output,cg_cap=600,max_iter=20000):
    phase_end=min(deadline,started+cg_cap);adapter=PersistentRMP()
    original_lp,original_price=colgen.solve_lp,colgen.price_truck_dp
    live_pool=[];last_optimal=None;calls=[];prices=[];trace=[];generated=None
    # These are the same physical singleton profiles retained by the direct
    # family. Construction is charged and ensures an integer fallback even if
    # no RMP reaches optimality. They are not supplied as an incumbent start.
    seeds=[colgen.single_trip_column(inst,tr,ice=False,free_start=False) for tr in inst.trips]
    if any(c is None for c in seeds):raise ValueError('Original singleton fallback is incomplete')
    def remaining():
        left=phase_end-time.perf_counter()
        if left<=0:raise BudgetExpired('Prospective CG phase budget exhausted')
        return left
    def lp(instance,columns,battery_allowed=True,solver=None,soc_mode='cyclic'):
        nonlocal live_pool,last_optimal
        if not battery_allowed or soc_mode!='cyclic':raise ValueError('Only cyclic V2G supported')
        live_pool=columns  # Observe later vendor appends; do not mutate the list.
        sol,diag=adapter.solve(instance,columns,False,remaining(),output/'logs'/f'cg_rmp_{len(calls):05d}.log')
        calls.append(diag)
        if sol.status=='optimal':
            last_optimal={'solution':sol,'columns':list(columns),'diagnostics':diag,
                'elapsed_seconds':time.perf_counter()-started}
        trace.append({'elapsed_seconds':time.perf_counter()-started,'columns':len(columns),
            'native_status':diag.get('native_status'),'objective':diag.get('objective')})
        if len(calls)==1 or len(calls)%25==0:
            write_json(output/'progress.json',{'phase':'cg','rmp_trace':trace})
        if sol.status!='optimal':raise BudgetExpired('Nonoptimal RMP: '+diag['status'])
        remaining();return sol
    def price(*args,**kwargs):
        remaining();before=time.perf_counter();answer=original_price(*args,**kwargs)
        prices.append({'seconds':time.perf_counter()-before,'candidates':len(answer),
            'elapsed_seconds':time.perf_counter()-started})
        remaining();return answer
    status='not_started';error=None
    try:
        colgen.solve_lp,colgen.price_truck_dp=lp,price
        remaining()
        generated=colgen.column_generation(inst,scenario='v2g',start='warm',tol=TOL,rc_stop=0,
            beta=.5,max_iter=max_iter,do_milp=False,verbose=False,enrich=0,
            lp_solver='gurobi',soc_mode='cyclic')
        live_pool=generated['cols']
        status='candidate_priced_out' if generated['converged'] else 'iteration_limit'
        if time.perf_counter()>phase_end:status='phase_budget_exhausted'
    except BudgetExpired as exc:status='phase_budget_exhausted';error=str(exc)
    except Exception as exc:
        # A numerical/solver failure does not erase the valid seed/accepted pool.
        status='cg_error';error=repr(exc)
    finally:
        colgen.solve_lp,colgen.price_truck_dp=original_lp,original_price
        restorations=adapter.basis_restorations;adapter.close()
    # Filtering/deduplication is part of the common pipeline budget. Every
    # accepted DP column is retained, even if added after the last solved RMP.
    real=[];seen=set();artificial=0
    for col in list(live_pool)+seeds:
        if col.kind=='artificial':artificial+=1;continue
        if col.kind!='truck':raise ValueError('Unsupported integer-pool column kind')
        key=column_fingerprint(col)
        if key not in seen:real.append(col);seen.add(key)
    out={'status':status,'error':error,'cg_cap_seconds':cg_cap,
        'elapsed_through_pool_preparation_seconds':time.perf_counter()-started,
        'cg_phase_deadline_seconds':phase_end-started,'real_pool_columns':len(real),
        'original_singletons':len(seeds),'artificial_columns_removed':artificial,
        'rmp_calls':calls,'pricing_calls':prices,'rmp_objective_trace':trace,
        'basis_restorations':restorations,'candidate_priced_out':bool(generated and generated['converged']),
        'last_optimal_rmp_available':last_optimal is not None,
        'full_family_bound_certified_during_timing':False,
        'pool_membership_scope':'Real columns accepted by frozen CG before cutoff, plus original singleton seeds; selected integer paths independently replayed after stopping; all-pool path witnesses are not claimed',
        'cutoff_policy':'Unprocessed candidates from a pricing call crossing the phase deadline are discarded; the complete call is charged to the total pipeline budget'}
    return real,last_optimal,out


def solve_pool_mip(inst,cols,deadline,output,pipeline_started):
    """Cold MIP on real columns; its native bound is restricted-pool-only."""
    import gurobipy as gp
    from gurobipy import GRB
    began=time.perf_counter()
    if began>=deadline:return None,{'status':'budget_exhausted_before_mip','objective':None,'restricted_pool_bound':None}
    if any(c.kind!='truck' for c in cols):raise ValueError('Artificial column in integer pool')
    _validate_scope(inst,cols)
    c,au,bu,ae,be,bounds,off,n,T,R,cc=master._build_lp(inst,cols,True,soc_mode='cyclic')
    c=np.asarray(c);ae=sparse.csr_matrix(ae);au=sparse.csr_matrix(au)
    lb=np.asarray([0. if lo is None else lo for lo,hi in bounds]);ub=np.asarray([np.inf if hi is None else hi for lo,hi in bounds])
    integer=np.r_[np.arange(R),off[5]].astype(int)
    log=output/'logs'/'restricted_mip.log';log.parent.mkdir(parents=True,exist_ok=True)
    report={'method':'cold_restricted_pool_mip','objective':None,'restricted_pool_bound':None,
        'bound_scope':'Restricted integer pool only; never a full-family lower bound',
        'status':None,'native_status':None,'solution_count':0,'threads':1,'seed':0,
        'mip_gap_tolerance':1e-6,'mip_gap_absolute_tolerance':1e-10,
        'feasibility_tolerance':1e-8,'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,
        'solver_method':-1,'cold_solve':True,'external_incumbent_or_basis_start':False,'trace':[]}
    vec=None
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',1);env.setParam('LogToConsole',0);env.setParam('LogFile',str(log));env.start()
        with gp.Model('cg_generated_real_pool_integer_master',env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.Method=-1
            model.Params.MIPGap=1e-6;model.Params.MIPGapAbs=1e-10
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8;model.Params.IntFeasTol=1e-8
            types=np.full(len(c),GRB.CONTINUOUS);types[integer]=GRB.INTEGER
            variables=model.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=types)
            model.addMConstr(ae,variables,'=',be);model.addMConstr(au,variables,'<',bu)
            model.update();built=time.perf_counter();left=deadline-built
            report.update(model_build_seconds=built-began,remaining_solver_budget_seconds=max(0.,left),
                variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,
                integer_variables=model.NumIntVars,solver_version=list(gp.gurobi.version()))
            if left<=0:
                report.update(status='budget_exhausted_before_mip_optimize',pipeline_stop_seconds=built-pipeline_started)
                return None,report
            model.Params.TimeLimit=left;last_trace=-30.
            def callback(m,where):
                nonlocal last_trace
                if where!=GRB.Callback.MIP:return
                elapsed=time.perf_counter()-pipeline_started
                if elapsed-last_trace<30:return
                last_trace=elapsed
                finite=lambda x:float(x) if abs(x)<GRB.INFINITY else None
                report['trace'].append({'elapsed_seconds':elapsed,
                    'incumbent':finite(m.cbGet(GRB.Callback.MIP_OBJBST)),
                    'restricted_pool_bound':finite(m.cbGet(GRB.Callback.MIP_OBJBND))})
                write_json(output/'progress.json',{'phase':'restricted_mip','trace':report['trace']})
            model.optimize(callback);stopped=time.perf_counter()
            names={GRB.OPTIMAL:'optimal',GRB.TIME_LIMIT:'time_limit',GRB.INFEASIBLE:'infeasible',
                GRB.INF_OR_UNBD:'infeasible_or_unbounded',GRB.UNBOUNDED:'unbounded',GRB.INTERRUPTED:'interrupted',GRB.NUMERIC:'numeric',GRB.SUBOPTIMAL:'suboptimal'}
            report.update(status=names.get(model.Status,str(model.Status)),native_status=int(model.Status),
                solution_count=int(model.SolCount),pipeline_stop_seconds=stopped-pipeline_started,
                restricted_stage_seconds=stopped-began,solver_runtime_seconds=float(model.Runtime),
                process_peak_rss_at_stop_bytes=peak_rss_bytes(),node_count=float(model.NodeCount))
            for attr,key in [('ObjBound','restricted_pool_bound'),('MIPGap','native_pool_gap'),('MaxMemUsed','solver_peak_memory_gb')]:
                try:
                    value=float(getattr(model,attr));report[key]=value if np.isfinite(value) and abs(value)<GRB.INFINITY else None
                except (AttributeError,gp.GurobiError):report[key]=None
            if model.SolCount:vec=np.asarray(variables.X);report['objective']=float(model.ObjVal)
    payload=None if vec is None else {'x':vec,'c':c,'lb':lb,'ub':ub,'ae':ae,'be':np.asarray(be),
        'au':au,'bu':np.asarray(bu),'integer':integer,'offsets':off,'bounds':bounds}
    return payload,report


def solve_cg_restricted_mip(inst,budget,output,cg_cap=600,max_iter=20000):
    output=Path(output);started=time.perf_counter();deadline=started+budget
    cols,last,phase=generate_pool(inst,started,deadline,output,cg_cap,max_iter)
    # Checkpoint preparation is charged to the common budget and preserves a
    # usable route pool if the subsequent integer solver fails or is interrupted.
    save_columns(output/'cg_pool_columns.json.gz',cols)
    write_json(output/'cg_phase.json',phase)
    if last:
        sol=last['solution'];save_columns(output/'cg_stopping_columns.json.gz',last['columns'])
        np.savez_compressed(output/'cg_stopping_primal.npz',x=sol.x,g=sol.g,charge=sol.charge,
            discharge=sol.discharge,soc=sol.soc,nb=sol.nb,alpha=sol.alpha,mu=sol.mu,nu=sol.nu)
    payload,mip=solve_pool_mip(inst,cols,deadline,output,started)
    stopped=started+mip.get('pipeline_stop_seconds',time.perf_counter()-started)
    out={'method':'cg_then_restricted_mip','family':'DP_paths_union_real_singleton_seeds',
        'budget_seconds':budget,'cg_cap_seconds':cg_cap,'threads':1,'seed':0,
        'status':mip['status'],'status_scope':'Restricted-pool integer model only',
        'global_integer_optimality_claimed':False,'cg_had_error':phase['status']=='cg_error',
        'native_status':mip.get('native_status'),'objective':mip.get('objective'),
        'restricted_pool_bound':mip.get('restricted_pool_bound'),'full_family_bound':None,
        'incumbent_validated':False,'solve_end_to_end_seconds':stopped-started,
        'process_peak_rss_at_stop_bytes':mip.get('process_peak_rss_at_stop_bytes',peak_rss_bytes()),
        'cg_phase':phase,'restricted_mip':mip,'external_reference_used_by_solver':False,
        'all_pool_membership_independently_verified':False,'branch_and_price':False}
    # Preserve native stopping evidence before potentially costly graph replay.
    write_json(output/'native_stop.json',out)
    if last:
        sol=last['solution']
        out['last_optimal_rmp']={'objective':float(sol.obj),'elapsed_seconds':last['elapsed_seconds'],
            'columns':len(last['columns']),'native_status':last['diagnostics'].get('native_status'),
            'full_family_bound_certified':False}
    if payload:
        np.savez_compressed(output/'restricted_primal.npz',x=payload['x'])
        objective=mip['objective'];p=payload
        out['matrix_primal_check']=primal_check(p['c'],p['lb'],p['ub'],p['ae'],p['be'],p['au'],p['bu'],p['x'],objective,p['integer'])
        try:
            aggregate=replay_rmp(inst,cols,p['x'],p['offsets'],p['bounds'],True,objective,tol=TOL)
            graph=build_extended_graph(inst)
            physical=validate_extended_selected_columns(inst,graph,cols,p['x'][:len(cols)],tol=TOL)
            out['validation']={'aggregate':aggregate,'selected_paths':physical,
                'passed':bool(aggregate['original_model_feasible'] and physical['passed'])}
            out['incumbent_validated']=bool(out['matrix_primal_check']['passed'] and out['validation']['passed'])
            out.update(graph_nodes=graph.n_nodes,graph_arcs=graph.n_arcs,
                graph_scope='Post-pipeline physical validation only')
        except Exception as exc:out['validation']={'passed':False,'error':repr(exc)}
    out['diagnostic_seconds']=time.perf_counter()-stopped
    out['total_including_checks_seconds']=time.perf_counter()-started
    return safe(out)
