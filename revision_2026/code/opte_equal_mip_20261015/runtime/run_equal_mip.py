"""Equal-MIP-time comparison of CG-plus-restricted-MIP and the direct arc-flow MIP.

Arm cg_pool_mip: column generation runs until pricing finds no column with
reduced cost below -1e-6 (safety cap --cg-cap, default 14,400 s). Its time,
LP value and route pool are recorded. A cold restricted-pool MIP then receives
--mip-budget seconds (default 1,800) measured from the start of its own model
construction. The CG time is not charged to the MIP budget.

Arm direct_mip: the direct arc-flow MIP of Appendix A.1 with a barrier root,
cold, --direct-budget seconds (3,600 on the panel, 16,200 otherwise) measured from graph construction.
Every incumbent and a bound trace are time-stamped, so the state at 1,800 s
(equal MIP time) and at the CG arm's total time are both read from one run.

Solver code is the frozen code of the earlier studies; only the CG/MIP deadline
split (here) and the direct-arm callback (direct_mip_traced.py) are new.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
sys.dont_write_bytecode=True
RUNTIME=Path(__file__).resolve().parent
sys.path.insert(0,str(RUNTIME))
import followup_inputs as extension_inputs  # sets frozen/ and frozen/vendor on sys.path
import panel_instances
from lp_scaling_instances import instance_record
from lp_scaling_models import peak_rss_bytes
from run_lp_scaling import environment_record
from run_pilot import safe,write_json,verify_vendor
import phase_models
from phase_models import generate_pool,solve_pool_mip,save_columns,TOL
from direct_mip_traced import solve_mip_traced,primal_check
import numpy as np

ARMS=('cg_pool_mip','direct_mip')
THREAD_VARS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
DEFAULTS={'cg_cap':14400.0,'mip_budget':1800.0,'snapshot':1800.0,'max_cg_iterations':200000,'soft_mem_limit_gb':36.0}
# The direct arm runs at least as long as the CG arm can (cap + MIP), except on the panel where CG takes minutes.
DIRECT_BUDGET={'panel':3600.0,'scaling':16200.0,'paper':16200.0}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def case_specs():
    """Panel inputs of Table 19, then the seven scaling and four original 1,000-task inputs."""
    rows=[{**s,'cohort':'panel','source_spec':dict(s)} for s in panel_instances.case_specs()]
    return rows+list(extension_inputs.case_specs())


def build_case(spec):
    canonical=next((s for s in case_specs() if s['case']==spec.get('case')),None)
    if spec!=canonical:raise ValueError('Undeclared input')
    if spec['cohort']!='panel':return extension_inputs.build_case(spec)
    inst=panel_instances.build_case(spec['source_spec']);raw=instance_record(inst)
    saved=json.loads((RUNTIME/'panel_input_manifest.json').read_text())['panel_inputs']
    row=next((r for r in saved if r['case']==spec['case']),None)
    if row is None or row['spec']!=spec['source_spec'] or row['instance_sha256']!=raw['sha256']:
        raise ValueError('Panel input differs from the Table 19 LP-panel input')
    return inst


def solve_cg_then_pool(inst,cg_cap,mip_budget,output,max_iter):
    output=Path(output);started=time.perf_counter()
    cols,last,phase=generate_pool(inst,started,started+cg_cap,output,cg_cap,max_iter)
    cg_stopped=time.perf_counter()
    save_columns(output/'cg_pool_columns.json.gz',cols);write_json(output/'cg_phase.json',phase)
    lp=None
    if last:
        sol=last['solution'];save_columns(output/'cg_stopping_columns.json.gz',last['columns'])
        np.savez_compressed(output/'cg_stopping_primal.npz',x=sol.x,g=sol.g,charge=sol.charge,
            discharge=sol.discharge,soc=sol.soc,nb=sol.nb,alpha=sol.alpha,mu=sol.mu,nu=sol.nu)
        lp={'objective':float(sol.obj),'elapsed_seconds':last['elapsed_seconds'],'columns':len(last['columns'])}
    checkpoint_seconds=time.perf_counter()-cg_stopped
    # The restricted MIP gets its own budget, starting before its model is built.
    mip_started=time.perf_counter()
    payload,mip=solve_pool_mip(inst,cols,mip_started+mip_budget,output,mip_started)
    mip_stopped=mip_started+mip.get('pipeline_stop_seconds',time.perf_counter()-mip_started)
    priced_out=phase['status']=='candidate_priced_out'
    # The n*eps bound needs the final DP call itself to return no column (colgen can also stop on a rejected column).
    calls=phase.get('pricing_calls') or []
    dp_empty=bool(calls) and calls[-1].get('candidates')==0
    validation=sum(float(c.get('validation_seconds') or 0) for c in phase.get('rmp_calls') or [])
    out={'method':'cg_to_convergence_then_restricted_mip','family':'DP_paths_union_real_singleton_seeds',
        'cg_cap_seconds':cg_cap,'mip_budget_seconds':mip_budget,'threads':1,'seed':0,
        'cg_status':phase['status'],'cg_priced_out':priced_out,'final_pricing_call_empty':dp_empty,
        'cg_inloop_validation_seconds':validation,
        'cg_seconds':cg_stopped-started,'cg_lp':lp,
        # Lagrangian bound of the paper (Section 6): every column prices out to within TOL and each truck serves a task.
        'full_family_lp_lower_bound':(lp['objective']-inst.n_trips*TOL) if (lp and priced_out and dp_empty) else None,
        'checkpoint_seconds':checkpoint_seconds,'mip_seconds':mip_stopped-mip_started,
        'total_seconds':mip_stopped-started,
        # Readout used for the matched-total-time comparison: CG plus the MIP stage, excluding checkpoint I/O.
        'cg_total_readout_seconds':(cg_stopped-started)+(mip_stopped-mip_started),
        'status':mip['status'],'status_scope':'Restricted-pool integer model only',
        'native_status':mip.get('native_status'),'objective':mip.get('objective'),
        'restricted_pool_bound':mip.get('restricted_pool_bound'),
        'global_integer_optimality_claimed':False,'branch_and_price':False,
        'incumbent_validated':False,'process_peak_rss_at_stop_bytes':mip.get('process_peak_rss_at_stop_bytes',peak_rss_bytes()),
        'cg_phase':phase,'restricted_mip':mip}
    write_json(output/'native_stop.json',out)
    if payload:
        np.savez_compressed(output/'restricted_primal.npz',x=payload['x'])
        p=payload;objective=mip['objective']
        out['matrix_primal_check']=primal_check(p['c'],p['lb'],p['ub'],p['ae'],p['be'],p['au'],p['bu'],p['x'],objective,p['integer'])
        try:
            from rmp_solver import replay_rmp
            from extension_models import build_extended_graph,validate_extended_selected_columns
            aggregate=replay_rmp(inst,cols,p['x'],p['offsets'],p['bounds'],True,objective,tol=TOL)
            graph=build_extended_graph(inst)
            physical=validate_extended_selected_columns(inst,graph,cols,p['x'][:len(cols)],tol=TOL)
            out['validation']={'aggregate':aggregate,'selected_paths':physical,
                'passed':bool(aggregate['original_model_feasible'] and physical['passed'])}
            out['incumbent_validated']=bool(out['matrix_primal_check']['passed'] and out['validation']['passed'])
            out.update(graph_nodes=graph.n_nodes,graph_arcs=graph.n_arcs)
        except Exception as exc:out['validation']={'passed':False,'error':repr(exc)}
    out['diagnostic_seconds']=time.perf_counter()-mip_stopped
    return safe(out)


def check_environment(a):
    env=environment_record()
    if '.'.join(map(str,env['gurobi']))!=a.require_gurobi:raise ValueError('Wrong Gurobi version')
    if a.require_cpu_model and ''.join(a.require_cpu_model.split()) not in ''.join(env['cpu_model'].split()):
        raise ValueError('Wrong CPU model')
    if a.require_single_cpu:
        if len(env.get('cpu_affinity') or [])!=1:raise ValueError('Exactly one bound CPU required')
        if any(os.environ.get(k)!='1' for k in THREAD_VARS):raise ValueError('Math threads must equal 1')
    return env


def plan():
    """Long CG arms first so the queue does not end on a multi-hour tail."""
    specs=case_specs();order=[]
    first=[s for s in specs if s['cohort']=='scaling']
    for s in first+[s for s in specs if s['cohort']=='panel']+[s for s in specs if s['cohort']=='paper']:
        order+=[(s['case'],'cg_pool_mip'),(s['case'],'direct_mip')]
    return [{'task_index':i,'case':c,'cohort':next(s['cohort'] for s in specs if s['case']==c),'arm':arm}
            for i,(c,arm) in enumerate(order)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',action='store_true');p.add_argument('--preflight',type=Path)
    p.add_argument('--task-index',type=int);p.add_argument('--case-name');p.add_argument('--arm',choices=ARMS)
    p.add_argument('--results',type=Path)
    p.add_argument('--cg-cap',type=float,default=DEFAULTS['cg_cap'])
    p.add_argument('--mip-budget',type=float,default=DEFAULTS['mip_budget'])
    p.add_argument('--direct-budget',type=float,default=None)
    p.add_argument('--soft-mem-limit-gb',type=float,default=DEFAULTS['soft_mem_limit_gb'])
    p.add_argument('--snapshot',type=float,default=DEFAULTS['snapshot'])
    p.add_argument('--max-cg-iterations',type=int,default=DEFAULTS['max_cg_iterations'])
    p.add_argument('--require-gurobi',default='12.0.3');p.add_argument('--require-cpu-model',default='AMD EPYC 9654')
    p.add_argument('--require-single-cpu',action='store_true')
    a=p.parse_args()
    if a.plan:print(json.dumps(plan(),indent=1));return 0
    if a.preflight:
        rows=[]
        for s in case_specs():
            inst=build_case(s);rows.append({'case':s['case'],'cohort':s['cohort'],'n_tasks':inst.n_trips,
                'instance_sha256':instance_record(inst)['sha256']})
        a.preflight.parent.mkdir(parents=True,exist_ok=True)
        write_json(a.preflight,{'inputs':rows,'plan':plan(),'code_sha256':{n.name:sha(n) for n in RUNTIME.glob('*.py')}})
        print(json.dumps({'inputs':len(rows),'tasks':len(plan())}));return 0
    if a.task_index is not None:
        row=plan()[a.task_index];a.case_name,a.arm=row['case'],row['arm']
    spec=next((s for s in case_specs() if s['case']==a.case_name),None)
    if spec is None or a.arm is None:p.error('Declared --case-name and --arm (or --task-index) required')
    if a.direct_budget is None:a.direct_budget=DIRECT_BUDGET[spec['cohort']]
    output=a.results/spec['case']/a.arm
    if output.exists():raise ValueError('Fresh output required; existing evidence is never overwritten')
    inst=build_case(spec);raw=instance_record(inst)
    output.mkdir(parents=True)
    write_json(output/'instance.json',raw)
    manifest={'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'case':spec,'arm':a.arm,
        'cg_cap_seconds':a.cg_cap,'mip_budget_seconds':a.mip_budget,'direct_budget_seconds':a.direct_budget,
        'snapshot_seconds':a.snapshot,'soft_mem_limit_gb':a.soft_mem_limit_gb,'max_cg_iterations':a.max_cg_iterations,'pricing_tolerance':TOL,
        'instance_sha256':raw['sha256'],'environment':environment_record(),'vendor_manifest':verify_vendor(),
        'code_sha256':{n.name:sha(n) for n in RUNTIME.glob('*.py')},
        'slurm':{k:os.environ.get(k) for k in ('SLURM_JOB_ID','SLURM_ARRAY_JOB_ID','SLURM_ARRAY_TASK_ID','SLURM_MEM_PER_NODE','SLURMD_NODENAME','SLURM_RESTART_COUNT')}}
    write_json(output/'manifest.json',manifest)
    try:check_environment(a)
    except Exception as exc:
        write_json(output/'result.json',{'status':'environment_rejected','error':repr(exc)});return 1
    try:
        if a.arm=='cg_pool_mip':result=solve_cg_then_pool(inst,a.cg_cap,a.mip_budget,output,a.max_cg_iterations)
        else:result=solve_mip_traced(inst,a.direct_budget,output,a.snapshot,a.soft_mem_limit_gb)
        code=0
    except Exception as exc:
        result={'status':'error','error':repr(exc),'traceback':traceback.format_exc()};code=1
        if (output/'native_stop.json').exists():result['native_stop']=json.loads((output/'native_stop.json').read_text())
    result.update(case=spec['case'],cohort=spec['cohort'],arm=a.arm,instance_sha256=raw['sha256'],
        process_peak_rss_after_diagnostics_bytes=peak_rss_bytes())
    write_json(output/'result.json',safe(result))
    print(json.dumps({k:result.get(k) for k in ('case','arm','status','objective','bound','cg_status','cg_seconds',
        'full_family_lp_lower_bound','incumbent_validated')}),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
