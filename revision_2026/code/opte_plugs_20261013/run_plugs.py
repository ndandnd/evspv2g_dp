"""Fixed18-input four-arm connector study, plus excluded tiny calibration.

All arms are fresh processes. --plan is read-only; --preflight serializes inputs
without optimization. Source, input and hardware checks precede every timed arm.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import traceback
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent;RUNTIME=ROOT/'runtime'
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(RUNTIME))
from plug_instances import build_case,case_specs,calibration_spec,instance_record,input_checks
from plug_problem import PlugProblem,verify_snapshot,seed_columns
from plug_solvers import solve_arm,ARMS
from lp_scaling_models import peak_rss_bytes
from run_lp_scaling import environment_record,run_child_bounded
from run_pilot import write_json

THREAD_VARS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
DEPENDENCIES=tuple(sorted({'PROTOCOL.md','plug_instances.py','input_manifest.json','run_plugs.py',
    'runtime/plug_problem.py','runtime/plug_pricing.py','runtime/plug_master.py','runtime/plug_solvers.py',
    'runtime/frozen_snapshot.json'}|{'runtime/'+n for n in json.loads((RUNTIME/'frozen_snapshot.json').read_text())['files']}))


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def source_hashes():
    verify_snapshot();return {name:sha(ROOT/name) for name in DEPENDENCIES}


def canonical_spec(name):
    if name in ('calibration',calibration_spec()['case']):return calibration_spec()
    return next((s for s in case_specs() if s['case']==name),None)


def arm_order(spec):
    index=0 if spec==calibration_spec() else case_specs().index(spec)
    k=index%len(ARMS);return list(ARMS[k:]+ARMS[:k])


def experiment_plan():
    return [{'block_index':i,'case_name':s['case'],'repeat':0,'arms':arm_order(s),
        'budget_seconds_per_arm':1800,'cg_cap_seconds':600,'watchdog_grace_seconds_per_arm':600,
        'memory_cap_bytes':64*1024**3} for i,s in enumerate(case_specs())]


def protocol():
    return {'name':'Station/time active truck plug constraints', 'planned_inputs':18,'planned_arms':72,
        'arms':list(ARMS),'budget_seconds':1800,'cg_cap_seconds':600,'watchdog_grace_seconds':600,
        'memory_cap_bytes':64*1024**3,'threads':1,'seed':0,'max_cg_iterations':20000,
        'cg_stabilization_beta':.5,'cg_pricing_tolerance':1e-6,'cg_method':-1,'cg_lp_warm_start':1,
        'direct_lp_method':2,'barrier_crossover':'automatic_default','direct_mip_method':2,'pool_mip_method':-1,
        'mip_gap_tolerance':1e-6,'mip_gap_absolute_tolerance':1e-10,
        'feasibility_tolerance':1e-8,'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,
        'phase1':'Minimize task artificials, zero real/shared costs; full route/seed pricing before positive infeasibility evidence',
        'occupancy':'One full connector per strictly positive charging OR discharging event; wait/travel/task/BESS excluded',
        'family':'All shared DP paths plus fixed original singleton witnesses; occupancy included in route identity',
        'enrichment':0,'branch_and_price':False,'cross_arm_warm_start':False,
        'integer_pool':'All real columns accepted before cutoff plus original singleton seeds; no artificials; unfinished pricing output is discarded and elapsed overrun charged',
        'bound_scope':'Restricted pool MIP bound is not global. Independent LP pricing and native direct full-family bounds are separately reported after timing.',
        'timing_scope':'Imports/input generation/serialization excluded. Graph/seed initialization, Phase I/II, pricing, RMP and direct model/environment construction and optimization included. CG integer pool filtering/checkpoint serialization included. Final raw serialization and physical/independent certificates excluded, separately timed.',
        'memory_scope':'Cumulative process RSS at algorithm stop and after worker diagnostics; independent audit separate',
        'solver_environment':'Gurobi12.0.3; AMD EPYC9654; one bound CPU and one solver/math thread; same host within each block'}


def input_binding(spec,raw):
    saved=json.loads((ROOT/'input_manifest.json').read_text())
    record=saved['excluded_calibration'] if spec==calibration_spec() else next((r for r in saved['cases'] if r['spec']==spec),None)
    if record is None or record['instance_sha256']!=raw['sha256']:raise ValueError('Input differs from prospectively frozen manifest')
    return record


def manifest(spec,a,raw):
    return {'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'case':spec,'repeat':0,
        'study':'station_time_plugs','variant':a.arm,'method':a.arm,
        'excluded_calibration':spec==calibration_spec(),
        'budget_seconds':a.budget,'cg_cap_seconds':a.cg_cap,'worker_watchdog_grace_seconds':a.watchdog_grace,
        'max_cg_iterations':a.max_cg_iterations,'instance_sha256':raw['sha256'],
        'environment':environment_record(),'code_sha256':source_hashes(),'protocol':protocol(),
        'require_gurobi':a.require_gurobi,'require_cpu_model':a.require_cpu_model,
        'require_single_affinity_cpu':a.require_single_affinity_cpu,
        'scheduler_memory_per_node_mib':os.environ.get('SLURM_MEM_PER_NODE')}


def check_environment(a):
    env=environment_record()
    if '.'.join(map(str,env['gurobi']))!=a.require_gurobi:raise ValueError('Wrong declared Gurobi version')
    compact=lambda s:''.join(s.split())
    if a.require_cpu_model and compact(a.require_cpu_model) not in compact(env['cpu_model']):raise ValueError('Wrong CPU model')
    if a.require_single_affinity_cpu:
        if len(env.get('cpu_affinity') or [])!=1:raise ValueError('Exactly one bound CPU required')
        if os.environ.get('SLURM_MEM_PER_NODE')!='65536':raise ValueError('Equal64GiB node-memory allocation required')
        if a.arm!='all' and any(os.environ.get(k)!='1' for k in THREAD_VARS):raise ValueError('Math thread environment must equal1')
    return env


def evidence(folder):
    return {str(p.relative_to(folder)):sha(p) for p in folder.rglob('*') if p.is_file()
        and p.name not in ('result.json','progress.json') and not p.name.endswith('.tmp')}


def preflight(output):
    if output.exists():raise ValueError('Fresh output required')
    output.mkdir(parents=True);rows=[]
    for spec in case_specs()+[calibration_spec()]:
        inst,caps=build_case(spec);problem=PlugProblem(inst,caps);raw=instance_record(inst,caps);input_binding(spec,raw)
        seeds=seed_columns(problem)
        if len(seeds)!=inst.n_trips:raise ValueError('Missing fixed physical singleton')
        folder=output/spec['case'];folder.mkdir();write_json(folder/'instance.json',raw)
        rows.append({'case':spec,'instance_sha256':raw['sha256'],'checks':input_checks(inst,caps),
            'verified_singletons':len(seeds),'finite_connector_rows':len(problem.finite_cells)})
    write_json(output/'preflight.json',{'passed':True,'optimization_performed':False,
        'code_sha256':source_hashes(),'plan':experiment_plan(),'cases':rows})
    print(json.dumps({'passed':True,'main_inputs':18,'excluded_calibration_inputs':1,'optimization_performed':False}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',action='store_true');p.add_argument('--preflight',action='store_true')
    p.add_argument('--case-name');p.add_argument('--output',type=Path)
    p.add_argument('--arm',choices=('all',)+ARMS,default='all')
    p.add_argument('--budget',type=float,default=1800);p.add_argument('--cg-cap',type=float,default=600)
    p.add_argument('--watchdog-grace',type=float,default=600);p.add_argument('--max-cg-iterations',type=int,default=20000)
    p.add_argument('--expected-instance-sha256');p.add_argument('--require-gurobi',default='12.0.3')
    p.add_argument('--require-cpu-model',default='AMD EPYC 9654');p.add_argument('--require-single-affinity-cpu',action='store_true')
    a=p.parse_args()
    if a.plan:print(json.dumps(experiment_plan(),indent=2));return 0
    if a.output is None:p.error('--output required')
    if a.preflight:preflight(a.output);return 0
    if not all(math.isfinite(x) and x>0 for x in (a.budget,a.cg_cap)) or a.cg_cap>=a.budget:p.error('CG cap must be positive and below total budget')
    if not math.isfinite(a.watchdog_grace) or a.watchdog_grace<0 or a.max_cg_iterations<1:p.error('Invalid watchdog/iteration bound')
    spec=canonical_spec(a.case_name)
    if spec is None:p.error('Use one of18 main cases or calibration')
    if a.output.exists():raise ValueError('Fresh output required; prior evidence immutable')
    inst,caps=build_case(spec);raw=instance_record(inst,caps);input_binding(spec,raw)
    if a.expected_instance_sha256 and a.expected_instance_sha256!=raw['sha256']:raise ValueError('Mismatched paired input')
    problem=PlugProblem(inst,caps)
    a.output.mkdir(parents=True);write_json(a.output/'instance.json',raw);write_json(a.output/'manifest.json',manifest(spec,a,raw))
    try:env_record=check_environment(a)
    except Exception as exc:
        write_json(a.output/'result.json',{'status':'environment_rejected','error':repr(exc),'incumbent_validated':False,
            'variant':a.arm,'instance_sha256':raw['sha256'],'evidence_sha256':evidence(a.output)});return 1
    if a.arm=='all':
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        for name in THREAD_VARS:env[name]='1'
        records=[]
        for position,arm in enumerate(arm_order(spec)):
            folder=a.output/arm
            command=[sys.executable,str(Path(__file__).resolve()),'--case-name',spec['case'],'--arm',arm,
                '--output',str(folder.resolve()),'--budget',str(a.budget),'--cg-cap',str(a.cg_cap),
                '--watchdog-grace',str(a.watchdog_grace),'--max-cg-iterations',str(a.max_cg_iterations),
                '--require-gurobi',a.require_gurobi,'--require-cpu-model',a.require_cpu_model,
                '--expected-instance-sha256',raw['sha256']]
            if a.require_single_affinity_cpu:command.append('--require-single-affinity-cpu')
            write_json(a.output/'progress.json',{'active_arm':arm,'completed':records})
            execution=run_child_bounded(command,env,a.budget+a.watchdog_grace)
            path=folder/'result.json'
            if execution['external_timeout'] or not path.exists():
                folder.mkdir(parents=True,exist_ok=True)
                # An original completed result, if any, survives as a distinct
                # artifact when a later infrastructure timeout is observed.
                if path.exists():path.rename(folder/'result_before_external_timeout.json')
                write_json(path,{'status':'external_timeout' if execution['external_timeout'] else 'worker_failed',
                    'objective':None,'incumbent_validated':False,'variant':arm,'method':arm,
                    'instance_sha256':raw['sha256'],'external_execution':execution,
                    'algorithm_time_censor_bound_valid':False,'partial_evidence_sha256':evidence(folder)})
            result=json.loads(path.read_text());same=False
            if (folder/'manifest.json').is_file():
                child=json.loads((folder/'manifest.json').read_text())['environment']
                same=all(child.get(k)==env_record.get(k) for k in ('host','cpu_model','cpu_affinity','gurobi'))
            records.append({'arm':arm,'position':position,'status':result.get('status'),
                'objective':result.get('objective'),'incumbent_validated':result.get('incumbent_validated',False),
                'seconds':result.get('solve_end_to_end_seconds'),'same_environment':same,
                'external_execution':execution,'result_sha256':sha(path)})
        write_json(a.output/'block_summary.json',{'completed':True,'arm_order':arm_order(spec),
            'instance_sha256':raw['sha256'],'results':records,'environment_consistent':all(r['same_environment'] for r in records)})
        return int(any(r['external_execution']['returncode']!=0 or not r['same_environment'] for r in records))
    try:result=solve_arm(problem,a.arm,a.budget,a.output,a.cg_cap,a.max_cg_iterations);exitcode=0
    except Exception as exc:
        result={'status':'error','incumbent_validated':False,'error':repr(exc),'traceback':traceback.format_exc()};exitcode=1
    result.update(variant=a.arm,instance_sha256=raw['sha256'],process_peak_rss_after_diagnostics_bytes=peak_rss_bytes())
    result['evidence_sha256']=evidence(a.output);write_json(a.output/'result.json',result)
    print(json.dumps({'case':spec['case'],'arm':a.arm,**{k:result.get(k) for k in
        ('status','objective','bound','restricted_pool_bound','incumbent_validated','solve_end_to_end_seconds')}}),flush=True)
    return exitcode


if __name__=='__main__':raise SystemExit(main())
