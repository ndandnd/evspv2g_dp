"""Four cold full-family MIPs on the exact saved n=1000 LP study inputs.

No old source or result is edited. --launch runs one fresh worker process with a
budget+600s external watchdog; --preflight checks input/model without optimizing.
The solve clock includes graph, seeds, matrices, Gurobi environment/model and
optimization. Raw incumbent serialization and physical replay follow that clock.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import numpy as np
from lp_scaling_instances import case_specs, build_case, instance_record
from extension_models import build_extended_graph, _seeds_with_witnesses, _hybrid_matrices, _hybrid_replay
from lp_scaling_models import peak_rss_bytes
from run_lp_scaling import environment_record, run_child_bounded
from run_pilot import safe, write_json, verify_vendor

TOL=1e-6
DEPENDENCIES=('direct_mip_1000.py','lp_scaling_instances.py','lp_scaling_models.py',
 'run_lp_scaling.py','extension_instances.py','extension_models.py','arc_flow.py',
 'column_witness.py','rmp_solver.py','run_pilot.py','source_manifest.json')


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_matched_input(case_name, path):
    spec=next((s for s in case_specs() if s['case']==case_name and s['n_tasks']==1000),None)
    if spec is None: raise ValueError('Only the four prespecified n=1000 cases are permitted')
    raw=json.loads(Path(path).read_text())
    payload={k:v for k,v in raw.items() if k!='sha256'}
    if hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()!=raw.get('sha256'):
        raise ValueError('Saved input payload hash mismatch')
    inst=build_case(spec)
    if instance_record(inst)!=raw:
        raise ValueError('Frozen builder does not reproduce the exact saved input')
    return spec,inst,raw


def integer_indices(graph,off,length):
    return np.r_[np.arange(graph.n_arcs+1),off['nb'],np.arange(off['seed_start'],length)].astype(int)


def primal_check(c,lb,ub,ae,be,au,bu,vector,objective,indices):
    if vector.shape!=c.shape or not np.all(np.isfinite(vector)):
        return {'passed':False,'reason':'invalid_raw_primal'}
    finite=np.isfinite(ub)
    mx=lambda a:float(np.max(a,initial=0.0))
    residuals={'equalities':mx(abs(ae@vector-be)),'inequalities':mx(au@vector-bu),
      'lower_bounds':mx(lb-vector),'upper_bounds':mx(vector[finite]-ub[finite]),
      'integrality':mx(abs(vector[indices]-np.rint(vector[indices]))),
      'objective_reconstruction':abs(float(c@vector)-objective)}
    return {'passed':max(residuals.values())<=TOL,'absolute_tolerance':TOL,'residuals':residuals}


def solve_mip(inst,budget,output):
    import gurobipy as gp
    from gurobipy import GRB
    started=time.perf_counter()
    graph=build_extended_graph(inst);seeds,proofs=_seeds_with_witnesses(inst)
    graph_done=time.perf_counter()
    c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(inst,graph,seeds)
    matrices_done=time.perf_counter();indices=integer_indices(graph,off,len(c))
    result={'method':'direct_full_family_mip','family':'DP_paths_union_real_singleton_seeds',
      'budget_seconds':budget,'threads':1,'seed':0,'solver_method':-1,'mip_gap_tolerance':1e-6,
      'mip_gap_absolute_tolerance':1e-10,'feasibility_tolerance':1e-8,
      'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,
      'cold_solve':True,'external_incumbent_or_basis_start':False,
      'solver_version':list(gp.gurobi.version()),'graph_seconds':graph_done-started,
      'matrix_build_seconds':matrices_done-graph_done,'graph_nodes':graph.n_nodes,
      'graph_arcs':graph.n_arcs,'unpruned_states':graph.unpruned_states,
      'unpruned_arcs':graph.unpruned_arcs,'seed_count':len(seeds),
      'off_grid_seed_count':sum(p['off_grid_profile'] for p in proofs),
      'original_rho':float(inst.rho),'bess_rho':float(inst.rho),
      'effective_dag_truck_rho':float(np.floor(inst.rho/inst.soc_step)*inst.soc_step),
      'soc_step':float(inst.soc_step),'objective':None,'bound':None,'gap':None,
      'status':None,'native_status':None,'solution_count':0,'incumbent_validated':False,
      'validation':None,'matrix_primal_check':None,'trace':[]}
    log=output/'logs'/'direct_mip.log';log.parent.mkdir(parents=True)
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',1);env.setParam('LogToConsole',0);env.setParam('LogFile',str(log))
        env.start()
        with gp.Model('n1000_complete_DP_paths_plus_singletons',env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.Method=-1
            model.Params.MIPGap=1e-6;model.Params.MIPGapAbs=1e-10
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8
            model.Params.IntFeasTol=1e-8
            types=np.full(len(c),GRB.CONTINUOUS);types[indices]=GRB.INTEGER
            x=model.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=types,name='v')
            model.addMConstr(ae,x,'=',be,name='eq');model.addMConstr(au,x,'<',bu,name='ub')
            model.update();built=time.perf_counter();remaining=budget-(built-started)
            result.update(gurobi_build_seconds=built-matrices_done,model_build_seconds=built-graph_done,
              variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,
              integer_variables=model.NumIntVars,binary_variables=model.NumBinVars,
              solver_budget_seconds=max(0.0,remaining))
            if remaining<=0:
                result.update(status='budget_exhausted_before_optimize',solve_end_to_end_seconds=built-started)
                return result
            model.Params.TimeLimit=remaining;last_trace=-30.0
            def observe(m,where):
                nonlocal last_trace
                if where!=GRB.Callback.MIP:return
                elapsed=time.perf_counter()-started
                if elapsed-last_trace<30:return
                last_trace=elapsed
                def finite(value):return float(value) if abs(value)<GRB.INFINITY else None
                result['trace'].append({'elapsed_seconds':elapsed,
                  'incumbent':finite(m.cbGet(GRB.Callback.MIP_OBJBST)),
                  'bound':finite(m.cbGet(GRB.Callback.MIP_OBJBND)),
                  'nodes':float(m.cbGet(GRB.Callback.MIP_NODCNT)),
                  'solutions':int(m.cbGet(GRB.Callback.MIP_SOLCNT))})
                write_json(output/'progress.json',{'status':'optimizing','trace':result['trace']})
            solving=time.perf_counter();model.optimize(observe);stopped=time.perf_counter()
            labels={GRB.OPTIMAL:'optimal',GRB.TIME_LIMIT:'time_limit',GRB.INFEASIBLE:'infeasible',
              GRB.INF_OR_UNBD:'infeasible_or_unbounded',GRB.UNBOUNDED:'unbounded',
              GRB.INTERRUPTED:'interrupted',GRB.NUMERIC:'numeric',GRB.SUBOPTIMAL:'suboptimal'}
            result.update(status=labels.get(model.Status,str(model.Status)),native_status=int(model.Status),
              solution_count=int(model.SolCount),solve_end_to_end_seconds=stopped-started,
              solve_seconds=stopped-solving,solver_runtime_seconds=float(model.Runtime),
              node_count=float(model.NodeCount),iterations=float(model.IterCount),
              barrier_iterations=int(model.BarIterCount),process_peak_rss_at_stop_bytes=peak_rss_bytes())
            for attr,key in (('ObjBound','bound'),('ObjBoundC','continuous_native_bound'),('MIPGap','gap'),
                ('MaxMemUsed','solver_peak_memory_gb'),('Work','solver_work'),
                ('ConstrVio','native_constraint_violation'),('BoundVio','native_bound_violation'),
                ('IntVio','native_integrality_violation')):
                try:
                    value=float(getattr(model,attr));result[key]=value if math.isfinite(value) and abs(value)<GRB.INFINITY else None
                except (AttributeError,gp.GurobiError):result[key]=None
            if model.SolCount:
                vector=np.asarray(x.X);result['objective']=float(model.ObjVal)
                np.savez_compressed(output/'direct_mip_primal.npz',x=vector)
                result['matrix_primal_check']=primal_check(c,lb,ub,ae,be,au,bu,vector,model.ObjVal,indices)
                try:
                    replay=_hybrid_replay(inst,graph,seeds,proofs,vector,off,model.ObjVal,True)
                    with gzip.open(output/'physical_replay.json.gz','wt') as handle:
                        json.dump(safe(replay),handle)
                    residuals=replay['residuals']
                    result['validation']={'passed':replay['passed'] and max(residuals.values())<=TOL,
                      'residuals':residuals,'strict_tolerance':TOL,'fleet':replay['fleet'],'nb':replay['nb'],
                      'dag_fleet':replay['dag_fleet'],'singleton_fleet':replay['singleton_fleet'],
                      'dag_paths':len(replay['paths']),'singleton_paths':len(replay['singleton_paths']),
                      'replayed_objective':replay['replayed_objective']}
                except ValueError as exc:result['validation']={'passed':False,'error':str(exc)}
                result['incumbent_validated']=bool(result['matrix_primal_check']['passed'] and result['validation']['passed'])
            result['diagnostic_seconds']=time.perf_counter()-stopped
    result['total_including_checks_seconds']=time.perf_counter()-started
    return safe(result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case-name',required=True);p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--budget',type=float,default=1800)
    p.add_argument('--launch',action='store_true');p.add_argument('--preflight',action='store_true')
    p.add_argument('--require-gurobi',default='12.0.3');a=p.parse_args()
    if not math.isfinite(a.budget) or a.budget<=0:p.error('Positive finite budget required')
    if a.output.exists():raise ValueError('Fresh output directory required')
    spec,inst,raw=load_matched_input(a.case_name,a.input)
    import gurobipy as gp
    if '.'.join(map(str,gp.gurobi.version()))!=a.require_gurobi:
        raise ValueError('Gurobi version differs from declared protocol')
    a.output.mkdir(parents=True)
    if a.launch:
        env=os.environ.copy()
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):env[key]='1'
        command=[sys.executable,str(Path(__file__).resolve()),'--case-name',a.case_name,'--input',str(a.input.resolve()),
          '--output',str((a.output/'worker').resolve()),'--budget',str(a.budget),'--require-gurobi',a.require_gurobi]
        write_json(a.output/'launch.json',{'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'command':command,
          'watchdog_seconds':a.budget+600,'input_file_sha256':sha(a.input),'instance_sha256':raw['sha256']})
        execution=run_child_bounded(command,env,a.budget+600)
        write_json(a.output/'execution.json',execution)
        if execution['external_timeout']:
            write_json(a.output/'external_timeout.json',{'status':'external_timeout','execution':execution,
              'optimization_completion_unknown':True,'algorithm_time_censor_bound_valid':False})
        return int(execution['returncode']!=0)
    (a.output/'instance.json').write_bytes(a.input.read_bytes())
    write_json(a.output/'manifest.json',{'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      'case':spec,'instance_sha256':raw['sha256'],'input_file_sha256':sha(a.input),
      'environment':environment_record(),'vendor_manifest':verify_vendor(),
      'code_sha256':{name:sha(ROOT/name) for name in DEPENDENCIES},
      'protocol':{'budget_seconds':a.budget,'threads':1,'seed':0,'mip_gap':1e-6,'native_tolerances':1e-8,
        'external_warm_starts':False,'family':'same saved LP inputs; all DP paths union original singleton seeds',
        'timing':'Input verification and serialization excluded; graph/seed/matrix/environment/model construction plus optimization included; final raw serialization and replay excluded',
        'repeats':1,'purpose':'Separate restricted-column heuristic limitations from native complete-family MIP difficulty; no general hardness claim from four cases'}})
    try:
        if a.preflight:
            graph=build_extended_graph(inst);seeds,proofs=_seeds_with_witnesses(inst)
            matrices=_hybrid_matrices(inst,graph,seeds)
            result={'status':'preflight_only','optimization_performed':False,'graph_nodes':graph.n_nodes,
              'graph_arcs':graph.n_arcs,'seed_count':len(seeds),'variables':len(matrices[0]),
              'off_grid_seed_count':sum(p['off_grid_profile'] for p in proofs)}
        else:result=solve_mip(inst,a.budget,a.output)
        code=0
    except Exception as exc:
        result={'status':'error','error':repr(exc),'traceback':traceback.format_exc()};code=1
    result['instance_sha256']=raw['sha256']
    result['evidence_sha256']={str(f.relative_to(a.output)):sha(f) for f in a.output.rglob('*')
      if f.is_file() and f.name not in ('result.json','progress.json') and not f.name.endswith('.tmp')}
    result['process_peak_rss_after_diagnostics_bytes']=peak_rss_bytes()
    write_json(a.output/'result.json',result)
    print(json.dumps({k:result.get(k) for k in ('status','objective','bound','gap','incumbent_validated','solve_end_to_end_seconds')}),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
