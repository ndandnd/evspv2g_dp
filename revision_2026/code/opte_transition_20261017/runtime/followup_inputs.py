"""Eleven exact prior physical inputs; seven new pairs and four pool diagnostics."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
RUNTIME=Path(__file__).resolve().parent;ROOT=RUNTIME.parent
sys.path.insert(0,str(RUNTIME))
import scaling_instances as scaling
import lp_scaling_instances as paper
from lp_scaling_instances import instance_record
from scaling_instances import estimate_graph

SCALING_NAMES=('scale_n1000_L30_d50_s0','scale_n1000_L30_d50_s1',
    'scale_n1000_L50_d50_s0','scale_n1000_L50_d50_s1',
    'scale_n1000_L15_d25_s0','scale_n1000_L15_d25_s1','scale_n4000_L15_d50_s0')
PAPER_NAMES=tuple(f'diag2_L{L:02d}_n1000_s{s}' for L in (4,15) for s in (0,1))


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def case_specs():
    result=[]
    for cohort,names,source in [('scaling',SCALING_NAMES,scaling),('paper',PAPER_NAMES,paper)]:
        pool={r['case']:r for r in source.case_specs()}
        for name in names:
            spec=pool[name]
            result.append({**spec,'cohort':cohort,'source_spec':dict(spec)})
    return result


def verify_snapshot():
    record=json.loads((RUNTIME/'copy_manifest.json').read_text())
    for name,item in record['files'].items():
        if sha(RUNTIME/name)!=item['sha256']:raise ValueError('Copied input or source changed: '+name)
    scaling.verify_snapshot();return record


def build_case(spec):
    canonical=next((s for s in case_specs() if s['case']==spec.get('case')),None)
    if spec!=canonical:raise ValueError('Only the11 fixed original inputs are authorized')
    verify_snapshot()
    source=scaling if spec['cohort']=='scaling' else paper
    inst=source.build_case(spec['source_spec']);raw=instance_record(inst)
    saved=json.loads((RUNTIME/'inputs'/f"{spec['case']}.json").read_text())
    if raw!=saved:raise ValueError('Exact prior physical payload differs')
    manifest=RUNTIME/'input_manifest.json'
    row=next((r for r in json.loads(manifest.read_text())['inputs'] if r['case']==spec['case']),None)
    if row is None or row['spec']!=spec or row['instance_sha256']!=raw['sha256']:raise ValueError('Declared input binding differs')
    return inst


def load_matched_input(name,path):
    spec=next((s for s in case_specs() if s['case']==name),None)
    if spec is None:raise ValueError('Unknown declared extension input')
    inst=build_case(spec);raw=json.loads(Path(path).read_text())
    if raw!=instance_record(inst):raise ValueError('Worker instance differs from frozen exact physical input')
    return spec,inst,raw
