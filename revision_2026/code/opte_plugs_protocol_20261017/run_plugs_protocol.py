"""Plug-limit study, integer arms only, under the agreed protocol (17 Oct 2026).

18 blocks (6 physical inputs x 3 plug policies, inputs and capacity entries of
experiments/opte_plugs_20261013, hash-checked) x 2 arms = 36 single-arm runs.
Plan task 2*i is block i cg_pool_mip, task 2*i+1 is block i direct_mip.

cg_pool_mip: plug CG to pricing convergence (safety cap --cg-cap, default 14,400 s, time reported
  separately), then a cold restricted MIP over all real routes plus the singleton seeds,
  --mip-budget seconds (default 1,800) on its own clock.
direct_mip: direct arc-flow MIP with the same plug rows, --direct-budget seconds (default 1,800)
  from graph/model construction (root barrier LP included); best incumbent at or before
  --snapshot seconds (default 1,800) is the reported value.
The LP arms of the original study are unaffected and are not rerun.

Usage:
  python run_plugs_protocol.py --plan
  python run_plugs_protocol.py --preflight preflight.json
  python run_plugs_protocol.py --task-index K --results DIR [--require-single-cpu --require-cpu-model=9654]
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
from plug_instances import build_case,case_specs,instance_record,input_checks
from plug_problem import PlugProblem,verify_snapshot,seed_columns
from protocol_arms import solve_cg_then_pool,solve_direct_mip_traced,TOL
from lp_scaling_models import peak_rss_bytes
from run_lp_scaling import environment_record
from run_pilot import safe,write_json

ARMS=('cg_pool_mip','direct_mip')
THREAD_VARS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
DEFAULTS={'cg_cap':14400.,'mip_budget':1800.,'direct_budget':1800.,'snapshot':1800.,'max_cg_iterations':200000}
# Byte-identical copies of the original plug code (checked by --preflight and recorded in every manifest).
ORIGINAL_COPIES=('plug_instances.py','input_manifest.json','runtime/plug_problem.py','runtime/plug_pricing.py',
    'runtime/plug_master.py','runtime/plug_solvers.py','runtime/frozen_snapshot.json')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hashes():
    verify_snapshot()
    files=[p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.md','.sh','.csv')
        and not p.name.startswith('preflight') and 'cluster' not in p.relative_to(ROOT).parts[:1]]
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(files)}


def reference():
    return json.loads((ROOT/'original_reference.json').read_text())


def plan():
    return [{'task_index':2*i+k,'block_index':i,'case':s['case'],'arm':arm}
        for i,s in enumerate(case_specs()) for k,arm in enumerate(ARMS)]


def protocol(a=None):
    return {'name':'Plug-limit integer arms, agreed protocol (17 Oct 2026)','planned_blocks':18,'planned_arms':36,
        'arms':list(ARMS),'cg_cap_seconds':DEFAULTS['cg_cap'] if a is None else a.cg_cap,
        'mip_budget_seconds':DEFAULTS['mip_budget'] if a is None else a.mip_budget,
        'direct_budget_seconds':DEFAULTS['direct_budget'] if a is None else a.direct_budget,
        'snapshot_seconds':DEFAULTS['snapshot'] if a is None else a.snapshot,
        'max_cg_iterations':DEFAULTS['max_cg_iterations'] if a is None else a.max_cg_iterations,
        'threads':1,'seed':0,'cg_pricing_tolerance':TOL,'cg_stabilization_beta':.5,'cg_method':-1,'cg_lp_warm_start':1,
        'pool_mip_method':-1,'direct_mip_method':2,'mip_gap_tolerance':1e-6,'mip_gap_absolute_tolerance':1e-10,
        'feasibility_tolerance':1e-8,'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,
        'cg_clock':'From seed construction to the CG stop (pricing convergence, safety cap, or error). Checkpoint I/O excluded.',
        'pool_mip_clock':'Own clock from the start of restricted-matrix construction; cold; real routes plus original singleton seeds, no artificials.',
        'direct_clock':'From the start of graph construction (graph, seeds, plug matrices, Gurobi model, root barrier LP, branch and bound).',
        'lower_bound':'LB* = max(z_RMP - n*1e-6 when CG priced out, direct final ObjBound); gap = 100(U-LB*)/U',
        'plug_rows':'Identical to opte_plugs_20261013 (plug_problem.rmp_matrices / direct_matrices; plug duals in plug_pricing.price_route)',
        'solver_environment':'Gurobi 12.0.3; AMD EPYC 9654; one bound CPU; one solver/math thread'}


def binding(spec,raw):
    """The rebuilt input must equal the original study's input (manifest, plan, block and arm records)."""
    saved=json.loads((ROOT/'input_manifest.json').read_text())
    rec=next((r for r in saved['cases'] if r['spec']==spec),None)
    ref=next((b for b in reference()['blocks'] if b['spec']==spec),None)
    if rec is None or ref is None:raise ValueError('Undeclared input')
    if not rec['instance_sha256']==ref['instance_sha256']==raw['sha256']:raise ValueError('Input differs from the original plug study')
    if raw['plug_capacities']!=ref['plug_capacities'] or raw['plug_locations']!=ref['plug_locations']:
        raise ValueError('Plug capacity entries differ from the original plug study')
    return ref


def expected_caps(spec,inst):
    if spec['plug_policy']=='unlimited':return None
    return [spec['depot_plugs'] if loc==inst.depot else spec['nondepot_plugs'] for loc in inst.charge_locs]


def check_environment(a):
    env=environment_record()
    if '.'.join(map(str,env['gurobi']))!=a.require_gurobi:raise ValueError('Wrong Gurobi version')
    if a.require_cpu_model and ''.join(a.require_cpu_model.split()) not in ''.join(env['cpu_model'].split()):
        raise ValueError('Wrong CPU model')
    if a.require_single_cpu:
        if len(env.get('cpu_affinity') or [])!=1:raise ValueError('Exactly one bound CPU required')
        if any(os.environ.get(k)!='1' for k in THREAD_VARS):raise ValueError('Math threads must equal 1')
    return env


def preflight(path,orig_root):
    hashes=code_hashes();ref=reference();orig_root=Path(orig_root).resolve()
    copies={}
    for name in ORIGINAL_COPIES+tuple('runtime/'+n for n in json.loads((RUNTIME/'frozen_snapshot.json').read_text())['files']):
        local=sha(ROOT/name);original=sha(orig_root/name)
        copies[name]={'sha256':local,'original_path':str(orig_root/name),'original_sha256':original,'identical':original==local}
        if not copies[name]['identical']:raise ValueError('Copied file differs from the original: '+name)
    if sha(ROOT/'input_manifest.json')!=ref['sources']['input_manifest.json']['sha256']:raise ValueError('input_manifest.json differs')
    rows=[];physical={}
    for i,spec in enumerate(case_specs()):
        inst,caps=build_case(spec);raw=instance_record(inst,caps);ref_block=binding(spec,raw)
        if ref_block['block_index']!=i:raise ValueError('Block order differs')
        problem=PlugProblem(inst,caps);seeds=seed_columns(problem)
        if len(seeds)!=inst.n_trips:raise ValueError('Missing singleton seed')
        exp=expected_caps(spec,inst)
        if exp is None:ok=all(c is None for row in raw['plug_capacities'] for c in row)
        else:ok=all(all(c==exp[j] for c in row) for j,row in enumerate(raw['plug_capacities']))
        if not ok:raise ValueError('Plug policy entries wrong in block %d'%i)
        checks=input_checks(inst,caps);physical.setdefault(spec['physical_case'],set()).add(checks['physical_sha256'])
        seed_violation=0.
        if len(problem.finite_cells):
            occ=sum(s.occupancy for s in seeds).ravel()[problem.finite_cells]
            seed_violation=float((occ>problem.capacity_vector).sum())
        rows.append({'block_index':i,'case':spec['case'],'policy':spec['plug_policy'],'instance_sha256':raw['sha256'],
            'matches_input_manifest':True,'matches_plan_block_summary_and_all_four_original_arm_manifests':True,
            'physical_sha256':checks['physical_sha256'],'finite_plug_rows':int(len(problem.finite_cells)),
            'depot_plugs':spec['depot_plugs'],'nondepot_plugs':spec['nondepot_plugs'],'singleton_seeds':len(seeds),
            'all_singletons_together_exceed_cap_in_rows':int(seed_violation),
            'original_integer_arm_budgets':{arm:{k:ref_block['arms'][arm][k] for k in ('budget_seconds','cg_cap_seconds')}
                for arm in ('cg_pool_mip','direct_mip')},
            'original_peak_rss_after_diagnostics_gb':{arm:round(ref_block['arms'][arm]['peak_rss_after_diagnostics_bytes']/1e9,3)
                for arm in ('cg_pool_mip','direct_mip')}})
    if any(len(v)!=1 for v in physical.values()) or len(physical)!=6:raise ValueError('Physical input differs across policies')
    out={'passed':True,'optimization_performed':False,'inputs':len(rows),'arms':len(plan()),
        'environment':environment_record(),'code_sha256':hashes,'original_copies':copies,
        'original_reference_sha256':sha(ROOT/'original_reference.json'),'protocol':protocol(),'plan':plan(),'blocks':rows}
    write_json(path,out)
    print(json.dumps({'passed':True,'inputs':len(rows),'arms':len(plan()),'hash_matches':len(rows),'physical_inputs':len(physical)}))


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan',action='store_true');p.add_argument('--preflight',type=Path)
    p.add_argument('--original-root',type=Path,default=ROOT.parent/'opte_plugs_20261013',help='original plug code folder (preflight byte comparison)')
    p.add_argument('--task-index',type=int);p.add_argument('--results',type=Path)
    p.add_argument('--cg-cap',type=float,default=DEFAULTS['cg_cap'])
    p.add_argument('--mip-budget',type=float,default=DEFAULTS['mip_budget'])
    p.add_argument('--direct-budget',type=float,default=DEFAULTS['direct_budget'])
    p.add_argument('--snapshot',type=float,default=DEFAULTS['snapshot'])
    p.add_argument('--soft-mem-limit-gb',type=float,default=None)
    p.add_argument('--max-cg-iterations',type=int,default=DEFAULTS['max_cg_iterations'])
    p.add_argument('--require-gurobi',default='12.0.3');p.add_argument('--require-cpu-model',default='AMD EPYC 9654')
    p.add_argument('--require-single-cpu',action='store_true')
    a=p.parse_args()
    if a.plan:print(json.dumps(plan(),indent=1));return 0
    if a.preflight:preflight(a.preflight,a.original_root);return 0
    if a.task_index is None or a.results is None:p.error('--task-index and --results required')
    if not all(math.isfinite(v) and v>0 for v in (a.cg_cap,a.mip_budget,a.direct_budget,a.snapshot)) or a.max_cg_iterations<1:
        p.error('Budgets must be positive and finite')
    row=plan()[a.task_index];spec=case_specs()[row['block_index']];arm=row['arm']
    output=a.results/f"block_{row['block_index']}"/arm
    if output.exists():raise ValueError('Fresh output required; existing evidence is never overwritten')
    inst,caps=build_case(spec);raw=instance_record(inst,caps);binding(spec,raw)
    problem=PlugProblem(inst,caps)
    output.mkdir(parents=True);write_json(output/'instance.json',raw)
    manifest={'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'task':row,'case':spec,'arm':arm,
        'cg_cap_seconds':a.cg_cap,'mip_budget_seconds':a.mip_budget,'direct_budget_seconds':a.direct_budget,
        'snapshot_seconds':a.snapshot,'soft_mem_limit_gb':a.soft_mem_limit_gb,'max_cg_iterations':a.max_cg_iterations,
        'instance_sha256':raw['sha256'],'environment':environment_record(),'code_sha256':code_hashes(),
        'protocol':protocol(a),'require_gurobi':a.require_gurobi,'require_cpu_model':a.require_cpu_model,
        'require_single_cpu':a.require_single_cpu,
        'slurm':{k:os.environ.get(k) for k in ('SLURM_JOB_ID','SLURM_ARRAY_JOB_ID','SLURM_ARRAY_TASK_ID','SLURM_MEM_PER_NODE',
            'SLURMD_NODENAME','SLURM_RESTART_COUNT')}}
    write_json(output/'manifest.json',manifest)
    try:check_environment(a)
    except Exception as exc:
        write_json(output/'result.json',{'status':'environment_rejected','error':repr(exc),'arm':arm,'instance_sha256':raw['sha256']})
        return 1
    try:
        if arm=='cg_pool_mip':result=solve_cg_then_pool(problem,a.cg_cap,a.mip_budget,output,a.max_cg_iterations)
        else:result=solve_direct_mip_traced(problem,a.direct_budget,output,a.snapshot,a.soft_mem_limit_gb)
        code=0
    except Exception as exc:
        result={'status':'error','error':repr(exc),'traceback':traceback.format_exc(),'incumbent_validated':False};code=1
        if (output/'native_stop.json').exists():result['native_stop']=json.loads((output/'native_stop.json').read_text())
    result.update(block_index=row['block_index'],case=spec['case'],policy=spec['plug_policy'],arm=arm,
        instance_sha256=raw['sha256'],process_peak_rss_after_diagnostics_bytes=peak_rss_bytes())
    write_json(output/'result.json',safe(result))
    print(json.dumps({k:result.get(k) for k in ('block_index','case','arm','status','objective','snapshot_incumbent_objective',
        'bound','restricted_pool_bound','cg_status','cg_seconds','full_family_lp_lower_bound','incumbent_validated')}),flush=True)
    return code


if __name__=='__main__':raise SystemExit(main())
