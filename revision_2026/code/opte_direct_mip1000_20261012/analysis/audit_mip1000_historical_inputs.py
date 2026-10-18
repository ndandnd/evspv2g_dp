"""Read-only reconstruction of the four DIAG2 historical input identities.

Execute only selected, inspected instance/random-generation functions from the
recorded Git revision; never import or execute the historical experiment driver.
The old JSON contains rounded incumbents, not route vectors, so this audit does
not independently certify feasibility of the old reported solutions.
"""
import argparse
import ast
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import numpy as np
from instance import Instance, Trip
from lp_scaling_instances import instance_record


def main():
    p=argparse.ArgumentParser();p.add_argument('--repository',required=True,type=Path)
    p.add_argument('--lp-results',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh audit output required')
    revision='14835daa884cd62ed865375696524a43eeab96a3'
    def git(*args):return subprocess.check_output(['git','-C',str(a.repository),*args])
    def source(name):return git('show',revision+':'+name).decode()
    hashes={name:hashlib.sha256(git('show',revision+':'+name)).hexdigest() for name in
      ('recreate_arxiv.py','overnight3.py','overnight13.py','instance.py','pricing_truck.py','colgen.py','master.py','data/delta.csv')}
    # Instance representation and data must be byte-identical to the snapshot.
    for name in ('instance.py','data/delta.csv'):
        if hashlib.sha256((ROOT/'vendor'/name).read_bytes()).hexdigest()!=hashes[name]:
            raise ValueError('Historical instance/data dependency differs: '+name)
    namespace={'np':np,'csv':csv,'os':os,'Instance':Instance,'Trip':Trip,
               '__file__':str(ROOT/'vendor/recreate_arxiv.py')}
    chosen=[]
    for node in ast.parse(source('recreate_arxiv.py')).body:
        if isinstance(node,ast.FunctionDef) and node.name in ('load_delta_units','gen_trips','build_instance'):chosen.append(node)
        elif isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('SOLAR_MULT','_COORDS') for t in node.targets):chosen.append(node)
    exec(compile(ast.Module(body=chosen,type_ignores=[]),'historical_generator_only','exec'),namespace)
    random_function=next(n for n in ast.parse(source('overnight3.py')).body if isinstance(n,ast.FunctionDef) and n.name=='rand_trips')
    exec(compile(ast.Module(body=[random_function],type_ignores=[]),'historical_rand_trips_only','exec'),namespace)
    pool=list(namespace['_COORDS'])+[(.75,.75),(-.75,.75),(.75,-.75)]
    rows=[]
    for L in (4,15):
        for seed in (0,1):
            name=f'diag2_L{L:02d}_n1000_s{seed}'
            tasks=namespace['rand_trips'](L,1000,200+seed)
            inst=namespace['build_instance'](L,1.0,[(6,20)],trip_list=tasks,duration=1.0,coords_override=pool[:L],stations='all',pv_scale=2.0)
            inst.c_g,inst.c_b,inst.rho,inst.c_v=40.0,36.0,1.75,45.0
            raw=instance_record(inst);saved=json.loads((a.lp_results/(name+'_r0')/'instance.json').read_text())
            if raw!=saved:raise ValueError('Historical input differs: '+name)
            shard=10+seed if L==4 else 22+seed
            historical_file=a.repository/'results/arxiv'/f'overnight13_diag2_s{shard}of24.json'
            historical=next(r for r in json.loads(historical_file.read_text()) if r['L']==L and r['n_tasks']==1000 and r['seed']==seed)
            if historical['commit']!='14835da':raise ValueError('Unexpected recorded result commit')
            lp=[json.loads((a.lp_results/f'{name}_r{repeat}'/method/'result.json').read_text())['objective']
                for repeat in range(3) for method in ('dual','barrier')]
            if max(lp)-min(lp)>1e-6:raise ValueError('Prior LP objectives disagree')
            rows.append({'case':name,'matched_input':True,'instance_sha256':raw['sha256'],
              'historical_result_file':str(historical_file),'historical_file_sha256':hashlib.sha256(historical_file.read_bytes()).hexdigest(),
              'historical_record':historical,'prior_lp_objective':lp[0],'prior_lp_range':[min(lp),max(lp)],
              'historical_lp_rounding_difference':historical['lp_obj']-lp[0],
              'reported_historical_incumbent_gap_vs_prior_lp_pct':100*(historical['total']-lp[0])/abs(historical['total'])})
    report={'passed':True,'recorded_revision':revision,'historical_source_sha256':hashes,'cases':rows,
      'source_changes_scope':'Between 14835da and frozen 3fa6257: coordinate tail extended but original first15 preserved; pricing adds pinned boundary support; initialization bypasses singleton only for pinned modes; master changes finite fleet cap artificial counting. None is active for these full/full uncapped DIAG2 inputs.',
      'provenance_limit':'Historical JSON gives rounded costs/statuses without raw solution vectors or full runtime environment. Cost comparison uses exactly reconstructed inputs and the same implemented family, but does not replay old incumbents or support cross-hardware/backend timing comparison.',
      'optimization_performed':False}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'cases':len(rows),'output':str(a.output)}))


if __name__=='__main__':main()
