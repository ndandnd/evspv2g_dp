"""Fixed, full-population COMMON4 verification: one cold60-second MIP per arm.

No standalone LP, old incumbent, MIP start or selective rerun is used. A base
launcher runs its four configurations in separate processes with120s watchdogs.
The60s algorithm clock includes graph/seed/matrix/model construction; raw output
and primal replay are outside that clock. Frozen earlier modules are unchanged.
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
import planning_direct as pd
from extension_models import _hybrid_matrices, _hybrid_replay
from direct_mip_1000 import primal_check, integer_indices
from lp_scaling_models import peak_rss_bytes
from run_lp_scaling import environment_record, run_child_bounded
from run_pilot import safe, write_json, verify_vendor

BUDGET=60.0
WATCHDOG=120.0
TOL=1e-6
INPUTS=ROOT/'planning_population_inputs.json'
DEPENDENCIES=('planning_population.py','planning_population_inputs.json',
 'PLANNING_POPULATION_PROTOCOL.md','planning_direct.py','planning_direct_inputs.json',
 'direct_mip_1000.py','lp_scaling_models.py','lp_scaling_instances.py','run_lp_scaling.py',
 'extension_instances.py','extension_models.py','arc_flow.py','column_witness.py',
 'rmp_solver.py','run_pilot.py','source_manifest.json')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def specs():return json.loads(INPUTS.read_text())['cases']


def build_case(spec):
    if spec not in specs():raise ValueError('Use an unmodified fixed-population entry')
    verify_vendor()
    inst=pd.historical.build_instance(3,2.,pd.historical.BREAKS,
      trip_list=pd.rand_trips(3,spec['n_tasks'],spec['draw_seed'],salt=50000),pv_scale=spec['pv_scale'])
    inst.c_g,inst.c_b,inst.rho,inst.c_v=40.,36.,1.75,45.;inst.soc_step=.25
    pd.validate_instance(inst)
    rec=pd._instance_record(inst,spec);physical={k:v for k,v in rec.items() if k not in ('spec','sha256')}
    actual=hashlib.sha256(json.dumps(physical,sort_keys=True).encode()).hexdigest()
    if actual!=spec['physical_sha256']:raise ValueError('Fixed physical input changed')
    if list(inst.charge_locs)!=[inst.depot] or np.any(np.isfinite(inst.gen_cap)) or np.isfinite(inst.charge_cap):
        raise ValueError('Unexpected COMMON4 locations/caps')
    return inst,rec


def solve(inst,scenario,output):
    import gurobipy as gp
    from gurobipy import GRB
    start=time.perf_counter()
    graph,seeds,proofs,audit=pd.prepare_planning(inst,scenario)
    graph_done=time.perf_counter()
    c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(inst,graph,seeds)
    if not pd.SCENARIOS[scenario]['battery']:ub[off['nb']]=0.
    matrices_done=time.perf_counter();indices=integer_indices(graph,off,len(c))
    result={'method':'planning_population_mip','scenario':scenario,'budget_seconds':BUDGET,
      'family':audit['family'],'audit':audit,'n_tasks':inst.n_trips,
      'graph_nodes':graph.n_nodes,'graph_arcs':graph.n_arcs,'seed_count':len(seeds),
      'off_grid_seed_count':0,'graph_and_audit_seconds':graph_done-start,
      'matrix_seconds':matrices_done-graph_done,'solver_version':list(gp.gurobi.version()),
      'threads':1,'seed':0,'solver_method':-1,'crossover':-1,'mip_gap_tolerance':1e-6,
      'mip_gap_absolute_tolerance':1e-10,'feasibility_tolerance':1e-8,
      'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,
      'cold_solve':True,'solution_or_basis_sharing':False,'objective':None,'bound':None,'gap':None,
      'status':None,'native_status':None,'solution_count':0,'incumbent_validated':False,
      'validation':None,'matrix_primal_check':None}
    logs=output/'logs';logs.mkdir()
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',1);env.setParam('LogToConsole',0)
        env.setParam('LogFile',str(logs/'mip.log'));env.start()
        with gp.Model('COMMON4_population60',env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.Method=-1;model.Params.Crossover=-1
            model.Params.MIPGap=1e-6;model.Params.MIPGapAbs=1e-10
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8;model.Params.IntFeasTol=1e-8
            types=np.full(len(c),GRB.CONTINUOUS);types[indices]=GRB.INTEGER
            x=model.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=types,name='v')
            model.addMConstr(ae,x,'=',be,name='eq');model.addMConstr(au,x,'<',bu,name='ub')
            model.update();built=time.perf_counter();remaining=BUDGET-(built-start)
            result.update(model_build_seconds=built-graph_done,gurobi_build_seconds=built-matrices_done,
              variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,
              integer_variables=model.NumIntVars,solver_budget_seconds=max(0.,remaining))
            if remaining<=0:
                result.update(status='budget_exhausted_before_optimize',solve_end_to_end_seconds=built-start)
                return result
            model.Params.TimeLimit=remaining;optimizing=time.perf_counter();model.optimize();stopped=time.perf_counter()
            names={GRB.OPTIMAL:'optimal',GRB.TIME_LIMIT:'time_limit',GRB.INFEASIBLE:'infeasible',
              GRB.INF_OR_UNBD:'infeasible_or_unbounded',GRB.UNBOUNDED:'unbounded',
              GRB.INTERRUPTED:'interrupted',GRB.NUMERIC:'numeric',GRB.SUBOPTIMAL:'suboptimal'}
            result.update(status=names.get(model.Status,str(model.Status)),native_status=int(model.Status),
              solution_count=int(model.SolCount),solve_end_to_end_seconds=stopped-start,
              solve_seconds=stopped-optimizing,solver_runtime_seconds=float(model.Runtime),
              node_count=float(model.NodeCount),iterations=float(model.IterCount),
              barrier_iterations=int(model.BarIterCount),process_peak_rss_at_stop_bytes=peak_rss_bytes())
            for attr,key in (('ObjBound','bound'),('ObjBoundC','continuous_native_bound'),('MIPGap','gap'),
              ('MaxMemUsed','solver_peak_memory_gb'),('ConstrVio','native_constraint_violation'),
              ('BoundVio','native_bound_violation'),('IntVio','native_integrality_violation')):
                try:
                    value=float(getattr(model,attr));result[key]=value if math.isfinite(value) and abs(value)<GRB.INFINITY else None
                except (AttributeError,gp.GurobiError):result[key]=None
            if model.SolCount:
                vector=np.asarray(x.X);result['objective']=float(model.ObjVal)
                np.savez_compressed(output/'primal.npz',x=vector)
                result['matrix_primal_check']=primal_check(c,lb,ub,ae,be,au,bu,vector,model.ObjVal,indices)
                try:
                    replay=_hybrid_replay(inst,graph,seeds,proofs,vector,off,model.ObjVal,True)
                    discharge=sum(p['weight']*sum(max(-e,0.) for e in p['energy']) for p in replay['paths'])
                    discharge+=sum(p['weight']*sum(max(-e,0.) for e in p['witness']['profile']) for p in replay['singleton_paths'])
                    scenario_residuals={'forbidden_truck_discharge':0. if pd.SCENARIOS[scenario]['allow_discharge'] else discharge,
                      'forbidden_bess_count':0. if pd.SCENARIOS[scenario]['battery'] else abs(replay['nb'])}
                    replay['scenario_residuals']=scenario_residuals
                    with gzip.open(output/'physical_replay.json.gz','wt') as handle:json.dump(safe(replay),handle)
                    residuals=replay['residuals']
                    passed=replay['passed'] and max(residuals.values())<=TOL and max(scenario_residuals.values())<=TOL
                    result['validation']={'passed':passed,'residuals':residuals,'scenario_residuals':scenario_residuals,
                      'strict_tolerance':TOL,'fleet':replay['fleet'],'nb':replay['nb'],'dag_paths':len(replay['paths']),
                      'singleton_paths':len(replay['singleton_paths']),'replayed_objective':replay['replayed_objective']}
                except ValueError as exc:result['validation']={'passed':False,'error':str(exc)}
                result['incumbent_validated']=bool(result['matrix_primal_check']['passed'] and result['validation']['passed'])
            result['native_bound_consistent']=bool(result['bound'] is not None and
              (result['objective'] is None or result['bound']<=result['objective']+TOL))
            result['diagnostic_seconds']=time.perf_counter()-stopped
    result['total_including_checks_seconds']=time.perf_counter()-start
    return safe(result)


def launch_base(spec,output):
    env=os.environ.copy()
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):env[name]='1'
    reports=[]
    for scenario in pd.SCENARIO_ORDER:
        command=[sys.executable,str(Path(__file__).resolve()),'--case-name',spec['case'],
          '--scenario',scenario,'--output',str((output/scenario).resolve())]
        execution=run_child_bounded(command,env,WATCHDOG)
        report={'scenario':scenario,'command':command,'watchdog_seconds':WATCHDOG,'execution':execution}
        write_json(output/f'{scenario}_execution.json',report);reports.append(report)
        if execution['external_timeout']:
            write_json(output/f'{scenario}_external_timeout.json',{'status':'external_timeout',
              'optimization_completion_unknown':True,'native_bound_from_interrupted_output_usable':False})
    write_json(output/'base_summary.json',{'case':spec,'expected_scenarios':list(pd.SCENARIO_ORDER),
      'executions':reports,'all_children_successful':all(r['execution']['returncode']==0 for r in reports)})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case-name');p.add_argument('--index',type=int)
    p.add_argument('--scenario',choices=pd.SCENARIO_ORDER);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--launch-base',action='store_true');p.add_argument('--preflight',action='store_true');a=p.parse_args()
    population=specs()
    if a.index is not None:
        if a.case_name or not 0<=a.index<len(population):raise ValueError('Invalid exclusive population index')
        spec=population[a.index]
    else:
        spec=next((s for s in population if s['case']==a.case_name),None)
    if spec is None:raise ValueError('Unknown population case')
    if a.output.exists():raise ValueError('Fresh output directory required')
    if a.launch_base and (a.scenario or a.preflight):raise ValueError('Launch a whole base without individual-arm options')
    if not a.launch_base and a.scenario is None:raise ValueError('Worker scenario required')
    inst,record=build_case(spec)
    a.output.mkdir(parents=True)
    if a.launch_base:
        write_json(a.output/'launch_manifest.json',{'utc':dt.datetime.now(dt.timezone.utc).isoformat(),
          'case':spec,'budget_seconds':BUDGET,'watchdog_seconds':WATCHDOG,'inputs_sha256':sha(INPUTS)})
        launch_base(spec,a.output);return 0
    write_json(a.output/'instance.json',record)
    write_json(a.output/'manifest.json',{'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'case':spec,'scenario':a.scenario,
      'physical_sha256':spec['physical_sha256'],'instance_sha256':record['sha256'],'environment':environment_record(),
      'vendor_manifest':verify_vendor(),'code_sha256':{n:sha(ROOT/n) for n in DEPENDENCIES},
      'protocol':{'budget_seconds':BUDGET,'watchdog_seconds':WATCHDOG,'threads':1,'seed':0,'solver_method':-1,
        'mip_gap_tolerance':1e-6,'native_tolerances':1e-8,'standalone_lp':False,'external_warm_starts':False,
        'timing':'Physical input reconstruction/hash excluded; graph/seed/matrix/environment/model and optimization included; final serialization/replay excluded'}})
    try:
        if a.preflight:
            graph,seeds,proofs,audit=pd.prepare_planning(inst,a.scenario);matrices=_hybrid_matrices(inst,graph,seeds)
            result={'status':'preflight_only','optimization_performed':False,'audit':audit,'variables':len(matrices[0])}
        else:
            import gurobipy as gp
            if gp.gurobi.version()!=(12,0,3):raise ValueError('Protocol requires Gurobi12.0.3')
            result=solve(inst,a.scenario,a.output)
        code=0
    except Exception as exc:result={'status':'error','error':repr(exc),'traceback':traceback.format_exc()};code=1
    result.update(case=spec['case'],scenario=a.scenario,physical_sha256=spec['physical_sha256'],instance_sha256=record['sha256'])
    result['evidence_sha256']={str(f.relative_to(a.output)):sha(f) for f in a.output.rglob('*')
      if f.is_file() and f.name!='result.json' and not f.name.endswith('.tmp')}
    result['process_peak_rss_after_diagnostics_bytes']=peak_rss_bytes();write_json(a.output/'result.json',result)
    print(json.dumps({k:result.get(k) for k in ('case','scenario','status','objective','bound','gap','incumbent_validated','solve_end_to_end_seconds')}),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
