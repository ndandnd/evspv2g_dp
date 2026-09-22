#!/usr/bin/env python3
"""Freeze the source/input identity before committing and launching a release."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
gate = root / 'common_profile_gate'
files = list(gate.glob('*.py')) + list(gate.glob('*.sbatch')) + [gate / 'PROTOCOL.md'] + list((gate / 'inputs').glob('*.json'))
cases = []
for policy in (17, 14):
    for year in (2022, 2023):
        name = f'policy{policy}_nb20_fit{year}'
        data = json.loads((gate / 'inputs' / (name + '.json')).read_text())
        cases.append({'name': name, 'policy': policy, 'fit_year': year,
                      'reference': data['metadata']['reference_wave16_case']})
        files += [root / 'evidence' / path for path in data['metadata']['source_hashes']]
hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}
(gate / 'manifest.json').write_text(json.dumps({'schema': 1, 'cases': cases, 'files': hashes}, indent=2, sort_keys=True) + '\n')
print(f'Registered {len(cases)} cases and {len(hashes)} files')
