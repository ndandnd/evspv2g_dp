"""Plug-study integer arms under the agreed protocol (17 Oct 2026). New file; nothing else in runtime/ changed.

cg_pool_mip -- structure of opte_grid_scaling_20261016/runtime/run_grid.py solve_cg_then_pool:
  the plug study's own two-phase CG (plug_solvers.generate_pool, unchanged: plug rows in the
  master, plug duals as arc costs in pricing, seeds checked at every pricing call) runs to pricing
  convergence, with only a safety cap; its time is reported separately. Checkpoint I/O is outside
  both clocks. A cold restricted MIP (plug_solvers.solve_matrix, unchanged, Method -1) over all
  accepted real routes plus the original singleton seeds then gets --mip-budget seconds on its own
  clock, which starts before its matrices are built.

direct_mip -- opte_grid_scaling_20261016/runtime/direct_mip_traced.py with the plug study's
  matrices (plug_problem.direct_matrices, unchanged: one plug-row coefficient on every charge or
  discharge arc and on each seed's occupied cells). Clock starts before graph construction, root
  barrier LP included (Method 2). Every incumbent and bound is time-stamped; the best incumbent at
  or before --snapshot seconds is the reported value.

Validation after the timed stop: matrix primal check (plug rows are part of the inequality block),
then plug_problem.replay_pool (physical replay of every selected route, occupancy recomputed from
the route witnesses and compared to each finite plug capacity, aggregate master replay).
"""
from __future__ import annotations
import gzip
import json
import math
from pathlib import Path
import time
import numpy as np
from plug_problem import seed_columns,rmp_matrices,direct_matrices,build_extended_graph,replay_pool
from plug_solvers import generate_pool,save_checkpoints,save_columns,solve_matrix,direct_to_columns
from direct_mip_1000 import primal_check,integer_indices
from lp_scaling_models import peak_rss_bytes
from run_pilot import safe,write_json

TOL=1e-6


def _validate(problem,cols,vector,mat,objective,indices):
    """Matrix check on the solved model plus physical/plug replay of the selected routes."""
    out={'matrix_primal_check':primal_check(mat.c,mat.lb,mat.ub,mat.ae,mat.be,mat.au,mat.bu,vector,objective,indices)}
    try:
        out['validation']=replay_pool(problem,cols,vector,mat,objective,True)
    except Exception as exc:out['validation']={'passed':False,'error':repr(exc)}
    out['incumbent_validated']=bool(out['matrix_primal_check']['passed'] and out['validation'].get('passed'))
    return out


def _plug_summary(problem,validation):
    """Compact plug-row record of a replayed schedule (occupancy from route witnesses)."""
    if not validation or not validation.get('passed'):return None
    occ=np.asarray(validation['occupancy'],float);cells=problem.finite_cells
    used=occ.ravel()[cells];cap=problem.capacity_vector
    depot_row=problem.station_index[problem.inst.depot]
    depot_cells=np.zeros(problem.capacities.shape,bool);depot_cells[depot_row,:]=True;depot_cells=depot_cells.ravel()[cells]
    binding=np.abs(used-cap)<=TOL
    return {'finite_plug_rows':int(len(cells)),'max_connector_violation':validation['max_connector_violation'],
        'binding_rows':int(binding.sum()),'binding_rows_depot':int((binding&depot_cells).sum()),
        'peak_depot':float(occ[depot_row].max()),
        'peak_nondepot':float(np.delete(occ,depot_row,axis=0).max()) if occ.shape[0]>1 else None,
        'truck_blocks_charging_or_discharging':float(occ.sum())}


def solve_cg_then_pool(problem,cg_cap,mip_budget,output,max_iter=200000):
    output=Path(output);started=time.perf_counter();inst=problem.inst
    allcols,snapshots,report=generate_pool(problem,started,started+cg_cap,output,max_iter)
    cg_stopped=time.perf_counter()
    # Checkpoints (outside both clocks): all CG columns, both phase snapshots, and the integer pool.
    save_checkpoints(output,allcols,snapshots,report)
    cols=[c for c in allcols if c.kind=='truck'];save_columns(output/'pool_columns.json.gz',cols)
    last=snapshots.get('economic');lp=None
    if last:lp={'objective':float(last['solution']['objective']),'elapsed_seconds':last['elapsed_seconds'],
        'columns':len(last['columns'])}
    priced_out=report['status']=='candidate_priced_out'
    stop=report.get('stopping_price') or {}
    checkpoint_seconds=time.perf_counter()-cg_stopped
    # The restricted MIP gets its own budget, starting before its matrices are built.
    mip_started=time.perf_counter()
    mat=rmp_matrices(problem,cols,'economic');indices=np.r_[np.arange(len(cols)),mat.offsets[5]].astype(int)
    data,mip=solve_matrix(mat,indices,mip_started+mip_budget,mip_started,output/'logs'/'pool_mip.log',False,'restricted_pool_only')
    mip_stopped=mip_started+mip['solve_end_to_end_seconds']
    mip['restricted_pool_bound']=mip.pop('bound',None)
    out={'method':'plug_cg_to_convergence_then_restricted_mip',
        'family':'DP_paths_union_fixed_original_singleton_witnesses_with_connector_rows',
        'cg_cap_seconds':cg_cap,'mip_budget_seconds':mip_budget,'max_cg_iterations':max_iter,'threads':1,'seed':0,
        'cg_status':report['status'],'cg_priced_out':priced_out,'cg_error':report.get('error'),
        'cg_seconds':cg_stopped-started,'cg_lp':lp,'cg_columns_total':len(allcols),'pool_columns':len(cols),
        'original_singletons_in_pool':inst.n_trips,'cg_rmp_calls':len(report['rmp_calls']),
        'cg_pricing_calls':len(report['pricing_calls']),
        'cg_stopping_min_reduced_cost':stop.get('minimum_reduced_cost'),
        # Lagrangian bound (paper, Section 6): pricing at the final RMP duals found no route or seed with
        # reduced cost below -TOL, and every route serves at least one task, so at most n routes are used.
        'full_family_lp_lower_bound':(lp['objective']-inst.n_trips*TOL) if (lp and priced_out) else None,
        'full_family_lp_lower_bound_exact_rc':(lp['objective']+inst.n_trips*min(0.,stop['minimum_reduced_cost']))
            if (lp and priced_out) else None,
        'checkpoint_seconds':checkpoint_seconds,'mip_seconds':mip_stopped-mip_started,
        'total_seconds':mip_stopped-started,
        # Readout for the matched-total-time comparison: CG plus the MIP stage, excluding checkpoint I/O.
        'cg_total_readout_seconds':(cg_stopped-started)+(mip_stopped-mip_started),
        'status':mip['status'],'status_scope':'Restricted-pool integer model only',
        'native_status':mip.get('native_status'),'objective':mip.get('objective'),
        'restricted_pool_bound':mip.get('restricted_pool_bound'),'native_pool_gap':mip.get('native_gap'),
        'solution_count':mip.get('solution_count',0),
        'global_integer_optimality_claimed':False,'branch_and_price':False,'incumbent_validated':False,
        'process_peak_rss_at_stop_bytes':mip.get('process_peak_rss_at_stop_bytes',peak_rss_bytes()),
        'cg':report,'restricted_mip':mip}
    write_json(output/'native_stop.json',out)
    if data is not None:
        np.savez_compressed(output/'pool_primal.npz',**data)
        out.update(_validate(problem,cols,data['x'],mat,out['objective'],indices))
        out['plug_rows']=_plug_summary(problem,out['validation'])
        if out['validation'].get('passed'):
            selected=[cols[j] for j in np.flatnonzero(data['x'][:len(cols)]>TOL)]
            save_columns(output/'selected_replay_columns.json.gz',selected)
            # Cost replay from the selected physical routes alone (route cost + shared-energy cost terms).
            out['objective_replay']={'native_objective':out['objective'],
                'replayed_objective':out['validation']['aggregate']['replayed_objective'],
                'abs_difference':out['validation']['aggregate']['residuals']['objective']}
    out['diagnostic_seconds']=time.perf_counter()-mip_stopped
    out['process_peak_rss_after_diagnostics_bytes']=peak_rss_bytes()
    return safe(out)


def _direct_replay(problem,graph,seeds,vector,off,objective):
    cols,canonical=direct_to_columns(problem,graph,seeds,vector,off)
    mat=rmp_matrices(problem,cols,'economic')
    validation=replay_pool(problem,cols,canonical,mat,objective,True)
    return cols,canonical,validation


def solve_direct_mip_traced(problem,budget,output,snapshot_seconds=1800.,soft_mem_limit_gb=None):
    import gurobipy as gp
    from gurobipy import GRB
    output=Path(output);started=time.perf_counter();inst=problem.inst
    graph=build_extended_graph(inst);seeds=seed_columns(problem);graph_done=time.perf_counter()
    mat=direct_matrices(problem,graph,seeds);matrices_done=time.perf_counter()
    c,lb,ub,ae,be,au,bu,off=mat.c,mat.lb,mat.ub,mat.ae,mat.be,mat.au,mat.bu,mat.offsets
    indices=integer_indices(graph,off,len(c))
    result={'method':'plug_direct_full_family_mip_traced','family':'DP_paths_union_fixed_original_singleton_witnesses_with_connector_rows',
      'budget_seconds':budget,'snapshot_seconds':snapshot_seconds,'soft_mem_limit_gb':soft_mem_limit_gb,
      'threads':1,'seed':0,'solver_method':2,'mip_gap_tolerance':1e-6,'mip_gap_absolute_tolerance':1e-10,
      'feasibility_tolerance':1e-8,'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,
      'cold_solve':True,'external_incumbent_or_basis_start':False,'solver_version':list(gp.gurobi.version()),
      'graph_seconds':graph_done-started,'matrix_build_seconds':matrices_done-graph_done,
      'graph_nodes':graph.n_nodes,'graph_arcs':graph.n_arcs,'unpruned_arcs':graph.unpruned_arcs,
      'seed_count':len(seeds),'finite_plug_rows':int(len(problem.finite_cells)),'plug_row_start':int(mat.plug_start),
      'objective':None,'bound':None,'gap':None,'status':None,'native_status':None,'solution_count':0,
      'incumbent_validated':False,'validation':None,'matrix_primal_check':None,'trace':[]}
    log=output/'logs'/'direct_mip.log';log.parent.mkdir(parents=True,exist_ok=True)
    events=result['incumbent_events']=[];bounds=result['bound_observations']=[];kept=[]
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',1);env.setParam('LogToConsole',0);env.setParam('LogFile',str(log));env.start()
        with gp.Model('connector_constrained_full_family_traced',env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.Method=2
            model.Params.MIPGap=1e-6;model.Params.MIPGapAbs=1e-10
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8;model.Params.IntFeasTol=1e-8
            types=np.full(len(c),GRB.CONTINUOUS);types[indices]=GRB.INTEGER
            x=model.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=types,name='v')
            model.addMConstr(ae,x,'=',be,name='eq');model.addMConstr(au,x,'<',bu,name='ub')
            model.update();built=time.perf_counter();remaining=budget-(built-started)
            result.update(gurobi_build_seconds=built-matrices_done,model_build_seconds=built-graph_done,
              variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,
              integer_variables=model.NumIntVars,binary_variables=model.NumBinVars,solver_budget_seconds=max(0.,remaining))
            if remaining<=0:
                result.update(status='budget_exhausted_before_optimize',solve_end_to_end_seconds=built-started)
                return safe(result)
            model.Params.TimeLimit=remaining;last_trace=-10.;last_bound=[-1.]
            if soft_mem_limit_gb:model.Params.SoftMemLimit=soft_mem_limit_gb
            root={'seconds':None,'line':None,'objective':None,'node_bound':None}
            def observe(m,where):
                nonlocal last_trace
                def finite(value):return float(value) if abs(value)<GRB.INFINITY else None
                def work():
                    try:return float(m.cbGet(GRB.Callback.WORK))
                    except Exception:return None
                if where==GRB.Callback.MIPSOL:
                    elapsed=time.perf_counter()-started
                    value=float(m.cbGet(GRB.Callback.MIPSOL_OBJ));bound=finite(m.cbGet(GRB.Callback.MIPSOL_OBJBND))
                    kept.append(np.asarray(m.cbGetSolution(x)).copy())
                    events.append({'elapsed_seconds':elapsed,'objective':value,'bound':bound,'work':work(),'vector_index':len(kept)-1})
                    if bound is not None:bounds.append({'elapsed_seconds':elapsed,'bound':bound,'source':'MIPSOL'})
                    return
                if where==GRB.Callback.MESSAGE:
                    if root['line'] is None:
                        text=m.cbGet(GRB.Callback.MSG_STRING)
                        if text.startswith('Root relaxation:'):
                            root['line']=text.strip()
                            if text.startswith('Root relaxation: objective'):
                                root['seconds']=time.perf_counter()-started;root['work']=work()
                                try:root['objective']=float(text.split('objective')[1].split(',')[0])
                                except ValueError:pass
                    return
                if where==GRB.Callback.MIPNODE:
                    elapsed=time.perf_counter()-started
                    if root['node_bound'] is None and m.cbGet(GRB.Callback.MIPNODE_NODCNT)==0 and m.cbGet(GRB.Callback.MIPNODE_STATUS)==GRB.OPTIMAL:
                        root['node_bound']=finite(m.cbGet(GRB.Callback.MIPNODE_OBJBND));root['node_seconds']=elapsed
                    if elapsed-last_bound[0]>=1.:
                        last_bound[0]=elapsed;value=finite(m.cbGet(GRB.Callback.MIPNODE_OBJBND))
                        if value is not None:bounds.append({'elapsed_seconds':elapsed,'bound':value,'source':'MIPNODE'})
                    return
                if where!=GRB.Callback.MIP:return
                elapsed=time.perf_counter()-started
                if elapsed-last_bound[0]>=1.:
                    last_bound[0]=elapsed;value=finite(m.cbGet(GRB.Callback.MIP_OBJBND))
                    if value is not None:bounds.append({'elapsed_seconds':elapsed,'bound':value,'source':'MIP'})
                if elapsed-last_trace<10:return
                last_trace=elapsed
                result['trace'].append({'elapsed_seconds':elapsed,'incumbent':finite(m.cbGet(GRB.Callback.MIP_OBJBST)),
                  'bound':finite(m.cbGet(GRB.Callback.MIP_OBJBND)),'nodes':float(m.cbGet(GRB.Callback.MIP_NODCNT)),
                  'solutions':int(m.cbGet(GRB.Callback.MIP_SOLCNT)),'work':work()})
                write_json(output/'progress.json',{'status':'optimizing','trace':result['trace']})
            solving=time.perf_counter();model.optimize(observe);stopped=time.perf_counter()
            labels={GRB.OPTIMAL:'optimal',GRB.TIME_LIMIT:'time_limit',GRB.INFEASIBLE:'infeasible',
              GRB.INF_OR_UNBD:'infeasible_or_unbounded',GRB.UNBOUNDED:'unbounded',GRB.INTERRUPTED:'interrupted',
              GRB.NUMERIC:'numeric',GRB.SUBOPTIMAL:'suboptimal',GRB.MEM_LIMIT:'memory_limit'}
            result.update(status=labels.get(model.Status,str(model.Status)),native_status=int(model.Status),
              solution_count=int(model.SolCount),solve_end_to_end_seconds=stopped-started,solve_seconds=stopped-solving,
              solver_runtime_seconds=float(model.Runtime),node_count=float(model.NodeCount),iterations=float(model.IterCount),
              barrier_iterations=int(model.BarIterCount),process_peak_rss_at_stop_bytes=peak_rss_bytes())
            for attr,key in (('ObjBound','bound'),('ObjBoundC','continuous_native_bound'),('MIPGap','gap'),
                ('MaxMemUsed','solver_peak_memory_gb'),('Work','solver_work'),('ConstrVio','native_constraint_violation'),
                ('BoundVio','native_bound_violation'),('IntVio','native_integrality_violation')):
                try:
                    value=float(getattr(model,attr));result[key]=value if math.isfinite(value) and abs(value)<GRB.INFINITY else None
                except (AttributeError,gp.GurobiError):result[key]=None
            result.update(root_lp_solved_seconds=root['seconds'],root_relaxation_log_line=root['line'],
              root_lp_objective_log=root['objective'],root_lp_work=root.get('work'),
              root_node_bound=root['node_bound'],root_node_seconds=root.get('node_seconds'))
            if result.get('bound') is not None:bounds.append({'elapsed_seconds':stopped-started,'bound':result['bound'],'source':'final_ObjBound'})
            final=np.asarray(x.X) if model.SolCount else None
            if model.SolCount:result['objective']=float(model.ObjVal)
    # Persist the timed record before any post-stop diagnostics can fail.
    write_json(output/'native_stop.json',safe(result))
    for event in events:
        vec=kept[event['vector_index']]
        np.savez_compressed(output/f"incumbent_{event['vector_index']:03d}.npz",x=vec)
        event['matrix_primal_check']=primal_check(c,lb,ub,ae,be,au,bu,vec,event['objective'],indices)
    before=[e for e in events if e['elapsed_seconds']<=snapshot_seconds]
    best=min(before,key=lambda e:e['objective']) if before else None
    result['snapshot_incumbent_objective']=best and best['objective']
    result['snapshot_incumbent_found_seconds']=best and best['elapsed_seconds']
    seen=[o for o in bounds if o['elapsed_seconds']<=snapshot_seconds]
    last=max(seen,key=lambda o:o['bound']) if seen else None
    result['snapshot_bound']=last and last['bound'];result['snapshot_bound_observed_seconds']=last and last['elapsed_seconds']
    # Full physical and plug-row replay of the reported (snapshot) incumbent and of the final incumbent.
    if best is not None:
        vec=kept[best['vector_index']]
        try:
            _,_,val=_direct_replay(problem,graph,seeds,vec,off,best['objective'])
            best['physical_replay_passed']=bool(val['passed']);result['snapshot_validation']=val
            result['snapshot_plug_rows']=_plug_summary(problem,val)
        except Exception as exc:
            best['physical_replay_passed']=False;result['snapshot_validation']={'passed':False,'error':repr(exc)}
        result['snapshot_incumbent_validated']=bool(best['matrix_primal_check']['passed'] and best['physical_replay_passed'])
    if final is not None:
        np.savez_compressed(output/'direct_mip_primal.npz',x=final)
        result['matrix_primal_check']=primal_check(c,lb,ub,ae,be,au,bu,final,result['objective'],indices)
        try:
            cols,canonical,val=_direct_replay(problem,graph,seeds,final,off,result['objective'])
            result['validation']=val;result['plug_rows']=_plug_summary(problem,val)
            save_columns(output/'selected_replay_columns.json.gz',cols)
            np.savez_compressed(output/'selected_replay_primal.npz',x=canonical)
        except Exception as exc:result['validation']={'passed':False,'error':repr(exc)}
        result['incumbent_validated']=bool(result['matrix_primal_check']['passed'] and result['validation'].get('passed'))
    result['diagnostic_seconds']=time.perf_counter()-started-result['solve_end_to_end_seconds']
    result['total_including_checks_seconds']=time.perf_counter()-started
    result['process_peak_rss_after_diagnostics_bytes']=peak_rss_bytes()
    return safe(result)
