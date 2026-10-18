"""Stage 1 of the independent validation: rebuild one input from its declared spec.

Runs in its own process, inside the cohort's runtime code copy (the code that ran).
It imports only the instance generators and the frozen record serializer
(lp_scaling_instances.instance_record). The generators load arc_flow solely for
their input check validate_instance; the validator (stage 2) never imports it.
Output: the declared spec, the rebuilt input record and its SHA256.
"""
import argparse, hashlib, json, sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True, type=Path)
p.add_argument('--cohort', required=True, choices=('grid', 'transition', 'tasks', 'equal'))
p.add_argument('--case', required=True)
p.add_argument('--out', required=True, type=Path)
a = p.parse_args()
sys.dont_write_bytecode = True
sys.path.insert(0, str(a.runtime))
import followup_inputs  # puts frozen/ and frozen/vendor on sys.path, as in the runners
from lp_scaling_instances import instance_record

if a.cohort in ('grid', 'transition', 'tasks'):
    mod = __import__({'grid': 'grid_instances', 'transition': 'transition_instances', 'tasks': 'task_scaling_instances'}[a.cohort])
    src = next(s for s in mod.case_specs() if s['case'] == a.case)
    spec = {**src, 'cohort': 'tasks'}
    inst = mod.build_case(src)
else:
    import panel_instances
    specs = [{**s, 'cohort': 'panel', 'source_spec': dict(s)} for s in panel_instances.case_specs()] + list(followup_inputs.case_specs())
    spec = next(s for s in specs if s['case'] == a.case)
    inst = panel_instances.build_case(spec['source_spec']) if spec['cohort'] == 'panel' else followup_inputs.build_case(spec)
rec = instance_record(inst)
body = {k: v for k, v in rec.items() if k != 'sha256'}
own = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
if own != rec['sha256']:
    raise SystemExit('record hash mismatch')
a.out.write_text(json.dumps({'case': a.case, 'cohort': a.cohort, 'spec': spec, 'record': rec,
                             'runtime_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(a.runtime.glob('*.py'))},
                             'loaded_modules': sorted(m for m in sys.modules if m in (
                                 'arc_flow', 'extension_models', 'column_witness', 'rmp_solver',
                                 'phase_models', 'direct_mip_traced', 'direct_mip_1000'))}, default=str))
print(json.dumps({'case': a.case, 'sha256': rec['sha256']}))
