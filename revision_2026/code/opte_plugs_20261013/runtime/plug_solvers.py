"""Four bounded connector-aware arms; certificates are independently replayed.

Public solve_arm(problem, arm, budget, output, cg_cap=600, max_iter=20000).
Each invocation is fresh. Pool MIP has one shared deadline including Phase I,
economic CG, checkpoint preparation and the cold restricted integer solve.
"""
from __future__ import annotations
import gzip
import json
from pathlib import Path
import time
import numpy as np
from plug_problem import (PlugColumn,seed_columns,artificial_columns,column_key,columns_record,
    rmp_matrices,direct_matrices,build_extended_graph,replay_pool)
from plug_pricing import price_route,reduced_cost
from plug_master import PlugMaster
from arc_flow import decompose_paths,KIND_NAMES
from direct_mip_1000 import primal_check,integer_indices
from lp_scaling_models import peak_rss_bytes
from run_pilot import safe,write_json

TOL=1e-6
ARMS=('cg_lp','direct_lp','cg_pool_mip','direct_mip')


def save_columns(path,cols):
    with gzip.open(path,'wt') as f:json.dump(safe(columns_record(cols)),f)


def generate_pool(problem,started,deadline,output,max_iter=20000):
    cols=seed_columns(problem)+artificial_columns(problem);keys={column_key(c) for c in cols}
    master=PlugMaster(problem);snapshots={};calls=[];prices=[];trace=[];previous=None;status='iteration_limit'
    def remaining():
        if time.perf_counter()>=deadline:raise TimeoutError('CG phase budget exhausted')
    def pricing(alpha,mu,nu,pi,factor):
        remaining();t=time.perf_counter();candidate,rc=price_route(problem,alpha,mu,nu,pi,factor)
        seed_rc=min(reduced_cost(problem,c,alpha,mu,nu,pi,factor) for c in seeds)
        prices.append({'phase':master.phase,'seconds':time.perf_counter()-t,'graph_min_reduced_cost':rc,
            'seed_min_reduced_cost':seed_rc,'elapsed_seconds':time.perf_counter()-started})
        remaining();return candidate,rc,seed_rc
    seeds=cols[:problem.inst.n_trips];error=None;stopping_price=None
    try:
        for iteration in range(max_iter):
            remaining();solution,diag=master.solve(cols,deadline,output/'logs'/f'cg_{len(calls):05d}.log');calls.append(diag)
            if solution is None:
                status='cg_'+diag['status'];break
            snapshots[master.phase]={'solution':solution,'columns':list(cols),'elapsed_seconds':time.perf_counter()-started}
            trace.append({'iteration':iteration,'phase':master.phase,'columns':len(cols),'objective':solution['objective'],
                'artificial_mass':solution['artificial_mass'],'elapsed_seconds':time.perf_counter()-started})
            if iteration%25==0:write_json(output/'progress.json',{'phase':master.phase,'trace':trace})
            remaining()
            if master.phase=='feasibility' and solution['artificial_mass']<=1e-7:
                master.economic_phase();previous=None;continue
            alpha,mu,nu,pi=(solution[k] for k in ('alpha','mu','nu','plug_price'))
            if master.phase=='feasibility':
                # With unlimited generation, PhaseI dispatch can always meet
                # demand at zero cost. Its exact route feasibility dual has
                # shared prices zero; only coverage and connector rows remain.
                mu=np.zeros(problem.inst.T);nu=np.zeros(problem.inst.T)
                candidate,rc,seed_rc=pricing(alpha,mu,nu,pi,0)
            else:
                current=(alpha,mu,nu,pi)
                stabilized=current if previous is None else tuple(.5*p+.5*q for p,q in zip(previous,current))
                candidate,_,_=pricing(*stabilized,1)
                previous=tuple(x.copy() for x in current)
                true_rc=np.inf if candidate is None else reduced_cost(problem,candidate,*current,1)
                if true_rc < -TOL and column_key(candidate) not in keys:
                    cols.append(candidate);keys.add(column_key(candidate));continue
                candidate,rc,seed_rc=pricing(*current,1)
            minimum=min(rc,seed_rc)
            if minimum>=-TOL:
                stopping_price={'phase':master.phase,'graph_min_reduced_cost':rc,'seed_min_reduced_cost':seed_rc,
                    'minimum_reduced_cost':minimum,'elapsed_seconds':time.perf_counter()-started}
                status='phase1_priced_out_positive' if master.phase=='feasibility' else 'candidate_priced_out'
                break
            if candidate is not None and rc < -TOL and column_key(candidate) not in keys:
                cols.append(candidate);keys.add(column_key(candidate))
            else:
                status='negative_existing_column_or_seed';break
    except TimeoutError as exc:status='cg_budget_exhausted';error=str(exc)
    except Exception as exc:status='cg_error';error=repr(exc)
    finally:restorations=master.basis_restorations;master.close()
    report={'status':status,'error':error,'rmp_calls':calls,'pricing_calls':prices,'trace':trace,
        'stopping_price':stopping_price,'basis_restorations':restorations,'columns':len(cols),
        'elapsed_seconds':time.perf_counter()-started,'active_phase':calls[-1]['phase'] if calls else 'feasibility',
        'phase1_infeasibility_independently_certified':False,'lp_optimality_independently_certified':False,
        'phase1_scope':'Zero physical/shared objective, minimum task artificials; positive priced-out value requires independent global dual check',
        'cutoff_policy':'Unprocessed price output crossing the phase deadline is discarded; full elapsed time is charged'}
    return cols,snapshots,report


def save_checkpoints(output,cols,snapshots,report):
    write_json(output/'cg_trace.json',report);save_columns(output/'cg_all_columns.json.gz',cols)
    for phase,snapshot in snapshots.items():
        prefix='phase1' if phase=='feasibility' else 'phase2';sol=snapshot['solution']
        save_columns(output/f'{prefix}_stopping_columns.json.gz',snapshot['columns'])
        np.savez_compressed(output/f'{prefix}_stopping_primal.npz',
            x=sol['vector'],**{k:sol[k] for k in ('alpha','mu','nu','plug_price','native_eq_dual','native_ub_dual','native_reduced_cost')})
        write_json(output/f'{prefix}_stopping.json',{'objective':sol['objective'],'artificial_mass':sol['artificial_mass'],
            'columns':len(snapshot['columns']),'elapsed_seconds':snapshot['elapsed_seconds'],'native_status':2,'phase':phase})


def solve_matrix(mat,integer_indices_,deadline,started,log_path,relax,scope,method=None):
    import gurobipy as gp
    method=(2 if relax else -1) if method is None else method
    if method not in (-1,2):raise ValueError('Unsupported fixed solver method')
    began=time.perf_counter();log_path.parent.mkdir(parents=True,exist_ok=True)
    result={'status':'budget_exhausted_before_optimize','native_status':None,'objective':None,'bound':None,
        'bound_scope':scope,'solution_count':0,'threads':1,'seed':0,'solver_method':method,
        'cold_solve':True,'external_incumbent_or_basis_start':False,'feasibility_tolerance':1e-8,
        'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,'mip_gap_tolerance':1e-6,
        'mip_gap_absolute_tolerance':1e-10,'solver_version':list(gp.gurobi.version()),'trace':[]}
    data=None
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',1);env.setParam('LogToConsole',0);env.setParam('LogFile',str(log_path));env.start()
        with gp.Model('connector_constrained_'+scope,env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.Method=method
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8;model.Params.IntFeasTol=1e-8
            model.Params.MIPGap=1e-6;model.Params.MIPGapAbs=1e-10
            types=np.full(len(mat.c),gp.GRB.CONTINUOUS)
            if not relax:types[integer_indices_]=gp.GRB.INTEGER
            variables=model.addMVar(len(mat.c),lb=mat.lb,ub=mat.ub,obj=mat.c,vtype=types)
            eq=model.addMConstr(mat.ae,variables,'=',mat.be);le=model.addMConstr(mat.au,variables,'<',mat.bu)
            model.update();built=time.perf_counter();left=deadline-built
            result.update(model_build_seconds=built-began,remaining_solver_budget_seconds=max(0.,left),
                variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,integer_variables=model.NumIntVars,
                crossover_parameter=int(model.Params.Crossover))
            if left<=0:
                result.update(solve_end_to_end_seconds=built-started,process_peak_rss_at_stop_bytes=peak_rss_bytes())
                return None,result
            model.Params.TimeLimit=left;last=-30.
            def callback(m,where):
                nonlocal last
                if where!=gp.GRB.Callback.MIP:return
                elapsed=time.perf_counter()-started
                if elapsed-last<30:return
                last=elapsed
                finite=lambda x:float(x) if abs(x)<gp.GRB.INFINITY else None
                result['trace'].append({'elapsed_seconds':elapsed,'incumbent':finite(m.cbGet(gp.GRB.Callback.MIP_OBJBST)),
                    'bound':finite(m.cbGet(gp.GRB.Callback.MIP_OBJBND)),'bound_scope':scope})
            solve_started=time.perf_counter();model.optimize(callback);stop=time.perf_counter()
            names={2:'optimal',3:'infeasible',4:'infeasible_or_unbounded',5:'unbounded',9:'time_limit',11:'interrupted',12:'numeric',13:'suboptimal'}
            result.update(status=names.get(model.Status,str(model.Status)),native_status=int(model.Status),
                solution_count=int(model.SolCount),solve_end_to_end_seconds=stop-started,solve_seconds=stop-solve_started,
                solver_runtime_seconds=float(model.Runtime),process_peak_rss_at_stop_bytes=peak_rss_bytes())
            if not relax:
                for attribute,key in (('ObjBound','bound'),('MIPGap','native_gap'),('NodeCount','node_count')):
                    try:
                        value=float(getattr(model,attribute));result[key]=value if np.isfinite(value) and abs(value)<gp.GRB.INFINITY else None
                    except (AttributeError,gp.GurobiError):result[key]=None
            if model.SolCount:
                result['objective']=float(model.ObjVal);data={'x':np.asarray(variables.X)}
                if relax and model.Status==gp.GRB.OPTIMAL:
                    result['bound']=float(model.ObjVal)
                    data.update(native_eq_dual=np.asarray(eq.Pi),native_ub_dual=np.asarray(le.Pi),native_reduced_cost=np.asarray(variables.RC))
    return data,result


def direct_to_columns(problem,graph,seeds,vector,off):
    cols=[];weights=[]
    for route in decompose_paths(graph,vector[:graph.n_arcs]):
        arcs=route['arcs'];a=np.zeros(problem.inst.n_trips);e=np.zeros(problem.inst.T);z=np.zeros_like(problem.capacities)
        nodes=[int(graph.tail[arcs[0]])]+[int(graph.head[i]) for i in arcs]
        states=[]
        for node in nodes:
            t,h,s,k=map(int,graph.states[node]);states.append([t,h,float(s*graph.step),k])
        kinds=[];draws=[];tasks=[]
        for edge in arcs:
            t,h=map(int,graph.states[graph.tail[edge],:2]);kind=KIND_NAMES[int(graph.kind[edge])];draw=float(graph.energy[edge])
            kinds.append(kind);draws.append(draw);e[t]+=draw
            if kind in ('charge','discharge'):z[problem.station_index[h],t]+=1
            if graph.task[edge]>=0:tid=int(graph.task[edge]);a[tid]+=1;tasks.append(tid)
        cols.append(PlugColumn('truck',a,e,float(problem.inst.c_v+getattr(problem.inst,'deg_cost',0.)*np.maximum(-e,0).sum()),z,
            {'family':'dp_path','states':states,'kinds':kinds,'energy':draws,'task_ids':tasks},'direct_decomposition'))
        weights.append(route['weight'])
    for j,col in enumerate(seeds):
        weight=vector[off['seed_start']+j]
        if weight>1e-7:cols.append(col);weights.append(float(weight))
    T=problem.inst.T
    canonical=np.r_[weights,vector[off['g']:off['g']+T],vector[off['charge']:off['charge']+T],
        vector[off['discharge']:off['discharge']+T],vector[off['soc']:off['soc']+T+1],vector[off['nb']]]
    return cols,canonical


def solve_arm(problem,arm,budget,output,cg_cap=600,max_iter=20000):
    if arm not in ARMS or not np.isfinite(budget) or budget<=0:raise ValueError('Unsupported arm or budget')
    if arm=='cg_pool_mip' and not 0<cg_cap<budget:raise ValueError('CG phase cap must lie inside total deadline')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);started=time.perf_counter();deadline=started+budget
    data=None;mat=None;cols=[];graph=None;result={'method':arm,'budget_seconds':budget,'threads':1,'seed':0,
        'family':'DP_paths_union_fixed_original_singleton_witnesses_with_connector_rows','incumbent_validated':False,
        'global_optimality_independently_certified':False,'connector_definition':'One for positive charge OR discharge block; waiting and BESS excluded'}
    if arm.startswith('direct'):
        graph=build_extended_graph(problem.inst);seeds=seed_columns(problem);graph_done=time.perf_counter()
        mat=direct_matrices(problem,graph,seeds);mat_done=time.perf_counter()
        indices=integer_indices(graph,mat.offsets,len(mat.c));relax=arm=='direct_lp'
        data,native=solve_matrix(mat,indices,deadline,started,output/'logs'/f'{arm}.log',relax,'full_family',method=2)
        result.update(native);result.update(graph_seconds=graph_done-started,matrix_seconds=mat_done-graph_done,
            graph_nodes=graph.n_nodes,graph_arcs=graph.n_arcs,unpruned_arcs=graph.unpruned_arcs)
    else:
        phase_deadline=min(deadline,started+cg_cap) if arm=='cg_pool_mip' else deadline
        allcols,snapshots,report=generate_pool(problem,started,phase_deadline,output,max_iter)
        result['cg']=report;result['cg_cap_seconds']=cg_cap if arm=='cg_pool_mip' else budget
        if arm=='cg_lp':
            stopped=time.perf_counter();result.update(status=report['status'],solve_end_to_end_seconds=stopped-started,
                process_peak_rss_at_stop_bytes=peak_rss_bytes(),bound=None,bound_scope='No global bound claimed before independent pricing replay')
            last=snapshots.get('economic')
            if last:
                cols=last['columns'];mat=rmp_matrices(problem,cols,'economic');data={'x':last['solution']['vector']}
                result.update(objective=last['solution']['objective'],native_status=2,native_status_scope='Last economic RMP only')
            else:result.update(objective=None,native_status=None)
            save_checkpoints(output,allcols,snapshots,report)
        else:
            # All accepted real columns survive, including the last append after
            # a solved LP. Artificials never enter the integer pool.
            cols=[c for c in allcols if c.kind=='truck'];save_checkpoints(output,allcols,snapshots,report)
            save_columns(output/'pool_columns.json.gz',cols);mat=rmp_matrices(problem,cols,'economic')
            indices=np.r_[np.arange(len(cols)),mat.offsets[5]].astype(int)
            data,native=solve_matrix(mat,indices,deadline,started,output/'logs/pool_mip.log',False,'restricted_pool_only')
            result.update(native);result['restricted_pool_bound']=result.pop('bound',None)
            result.update(full_family_bound=None,global_integer_optimality_claimed=False,status_scope='Restricted integer pool only')
    stopped=started+result['solve_end_to_end_seconds']
    write_json(output/'native_stop.json',result)
    if data is not None:
        path='direct_primal.npz' if arm.startswith('direct') else 'pool_primal.npz'
        np.savez_compressed(output/path,**data)
        indices=(integer_indices(graph,mat.offsets,len(mat.c)) if arm=='direct_mip' else
            np.r_[np.arange(len(cols)),mat.offsets[5]].astype(int) if arm=='cg_pool_mip' else np.array([],dtype=int))
        result['matrix_primal_check']=primal_check(mat.c,mat.lb,mat.ub,mat.ae,mat.be,mat.au,mat.bu,data['x'],result['objective'],indices)
        try:
            if arm.startswith('direct'):
                cols,canonical=direct_to_columns(problem,graph,seeds,data['x'],mat.offsets)
                replaymat=rmp_matrices(problem,cols,'economic')
            else:canonical=data['x'];replaymat=mat
            result['validation']=replay_pool(problem,cols,canonical,replaymat,result['objective'],arm.endswith('mip'))
            save_columns(output/'selected_replay_columns.json.gz',cols)
            np.savez_compressed(output/'selected_replay_primal.npz',x=canonical)
            result['incumbent_validated']=bool(result['matrix_primal_check']['passed'] and result['validation']['passed'])
        except Exception as exc:result['validation']={'passed':False,'error':repr(exc)}
    result.update(diagnostic_seconds=time.perf_counter()-stopped,total_including_checks_seconds=time.perf_counter()-started,
        process_peak_rss_after_diagnostics_bytes=peak_rss_bytes())
    return safe(result)
