"""Independent no-solve physical/vendor-matrix audit of new1000-task MIPs."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from direct_mip_1000 import load_matched_input, integer_indices
from extension_models import build_extended_graph, _seeds_with_witnesses, _hybrid_matrices, _hybrid_replay
from verify_lp_scaling import _primal
from verify_extension_results import replay_direct
from summarize_planning import original_master_check
from run_pilot import safe

TOL=1e-6


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_worker(folder):
    folder=Path(folder).resolve();started=time.perf_counter()
    out={'worker':str(folder),'passed':False,'optimization_performed':False,
      'scope':'Raw primal, independent physical paths, original vendor rows, hashes and native bound ordering; native lower bound is not independently proved'}
    try:
        result=json.loads((folder/'result.json').read_text());manifest=json.loads((folder/'manifest.json').read_text())
        out.update(case=manifest['case']['case'],status=result['status'],objective=result.get('objective'),bound=result.get('bound'))
        out['result_sha256']=sha(folder/'result.json')
        checked=[]
        for name,want in result['evidence_sha256'].items():
            if not (folder/name).is_file() or sha(folder/name)!=want:raise ValueError('Evidence changed: '+name)
            checked.append(name)
        for name,want in manifest['code_sha256'].items():
            if sha(ROOT/name)!=want:raise ValueError('Reconstruction code changed: '+name)
        for name,record in manifest['vendor_manifest']['files'].items():
            if sha(ROOT/'vendor'/name)!=record['sha256']:raise ValueError('Vendor changed: '+name)
        spec,inst,raw=load_matched_input(manifest['case']['case'],folder/'instance.json')
        if raw['sha256']!=manifest['instance_sha256'] or raw['sha256']!=result['instance_sha256']:raise ValueError('Instance mismatch')
        if result.get('budget_seconds')!=1800 or result.get('threads')!=1 or result.get('seed')!=0 or result.get('solver_method')!=-1:
            raise ValueError('Protocol budget/settings mismatch')
        if result.get('solver_version')!=[12,0,3] or result.get('mip_gap_tolerance')!=1e-6 or not result.get('cold_solve') or result.get('external_incumbent_or_basis_start'):
            raise ValueError('Protocol solver/cold-start mismatch')
        if any(result.get(k)!=1e-8 for k in ('feasibility_tolerance','optimality_tolerance','integer_feasibility_tolerance')):
            raise ValueError('Native tolerance mismatch')
        out['checked_evidence_count']=len(checked);out['instance_sha256']=raw['sha256']
        obj=result.get('objective');bound=result.get('bound')
        if bound is not None and (not math.isfinite(bound) or (obj is not None and bound>obj+TOL)):
            raise ValueError('Invalid native lower-bound ordering')
        out['native_bound_usable']=bound is not None and result['status'] in ('optimal','time_limit','interrupted')
        if obj is None:
            out.update(passed=True,incumbent_available=False);return safe(out)
        if not math.isfinite(obj):raise ValueError('Invalid objective')
        required={'direct_mip_primal.npz','physical_replay.json.gz','instance.json','manifest.json'}
        if not required.issubset(checked):raise ValueError('Missing raw evidence digest')
        graph=build_extended_graph(inst);seeds,proofs=_seeds_with_witnesses(inst)
        c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(inst,graph,seeds)
        with np.load(folder/'direct_mip_primal.npz',allow_pickle=False) as data:x=data['x']
        residuals=_primal(c,lb,ub,ae,be,au,bu,x,obj)
        ii=integer_indices(graph,off,len(c));residuals['integrality']=float(np.max(abs(x[ii]-np.rint(x[ii])),initial=0.))
        if max(residuals.values())>TOL:raise ValueError('Raw primal failed: '+str(residuals))
        recovered=_hybrid_replay(inst,graph,seeds,proofs,x,off,obj,True)
        with gzip.open(folder/'physical_replay.json.gz','rt') as f:saved=json.load(f)
        if safe(recovered)!=saved:raise ValueError('Raw vector does not reproduce saved physical decomposition')
        physical,columns=replay_direct(inst,{'objective':obj,'validation':recovered},True)
        vendor=original_master_check(inst,{'objective':obj,'validation':recovered},columns,True,0)
        out.update(passed=True,incumbent_available=True,raw_primal_residuals=residuals,
          independent_physical_replay=physical,original_vendor_master=vendor,
          native_absolute_gap=None if bound is None else obj-bound,
          native_relative_gap=None if bound is None else (obj-bound)/abs(obj))
    except Exception as exc:out['error']=repr(exc)
    out['verification_seconds']=time.perf_counter()-started
    return safe(out)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh output required')
    folders=[a.input] if (a.input/'result.json').is_file() else sorted(x.parent for x in a.input.rglob('result.json'))
    reports=[verify_worker(f) for f in folders]
    report={'checker_sha256':sha(__file__),'optimization_performed':False,'workers':reports,'passed':bool(reports) and all(r['passed'] for r in reports)}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':report['passed'],'workers':len(reports),'failures':[r for r in reports if not r['passed']]}))
