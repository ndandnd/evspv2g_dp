"""Certify only prospectively selected CG-reuse barrier executions.

No optimization, copying, scheduler access, or changes to raw outcomes. The
separate unselected-original report preserves evidence from interrupted blocks
without creating duplicate logical identities in the selected report. By default
all 18 selected blocks must be complete. --allow-incomplete creates an explicitly
labelled checkpoint and records every omitted slot.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import time

from cg_reuse_recovery import digest, load_recovery_map
from direct_common_certificate import certify_direct_worker
from run_cg_reuse import experiment_plan
from run_pilot import safe

ROOT = Path(__file__).resolve().parent


def selected_workers(base, recovery_map=None, require_complete=True):
    base = Path(base).resolve()
    recoveries, provenance = load_recovery_map(recovery_map, base)
    plan = experiment_plan()
    allowed = {(b['case_name'], b['repeat']) for b in plan}
    discovered = collections.defaultdict(list)
    for path in sorted(base.rglob('manifest.json')):
        data = json.loads(path.read_text())
        if data.get('variant') != 'all': continue
        key = data.get('case', {}).get('case'), data.get('repeat')
        if key not in allowed: raise ValueError('Unexpected block identity')
        discovered[key].append(path.parent.resolve())
    selected, unselected, omitted = [], [], []
    for b in plan:
        key = b['case_name'], b['repeat']; recovery = recoveries.get(key)
        matches = discovered.get(key, [])
        metadata = {'case': key[0], 'repeat': key[1], 'block_index': b['block_index']}
        if recovery:
            known = {recovery['original'], recovery['recovery']}
            if any(p not in known for p in matches):
                raise ValueError('Unregistered additional block attempt')
            folder = recovery['recovery']; attempt = 'recovery'
            original = recovery['original']/'barrier'
            if (original/'result.json').is_file():
                unselected.append({**metadata, 'attempt': 'original', 'folder': original,
                                   'reason': 'Whole-block prospective recovery selected'})
        else:
            if len(matches) > 1: raise ValueError('Duplicate original block identity')
            folder = matches[0] if matches else base/f"block_{b['block_index']}"
            attempt = 'original'
        worker = folder/'barrier'; summary = folder/'block_summary.json'
        block_complete = (summary.is_file() and json.loads(summary.read_text()).get('completed') is True)
        if not block_complete and require_complete:
            raise ValueError(f"Selected block {b['block_index']} has not completed")
        if not (worker/'result.json').is_file():
            omitted.append({**metadata, 'attempt': attempt, 'folder': str(worker),
                            'reason': 'Selected barrier has no saved result'})
            continue
        selected.append({**metadata, 'attempt': attempt, 'folder': worker,
                         'selected_block_complete': block_complete})
    return selected, unselected, omitted, provenance


def certify_collection(base, output, recovery_map=None, allow_incomplete=False):
    output = Path(output)
    if output.exists(): raise FileExistsError('Use a fresh output directory')
    selected, unselected, omitted, provenance = selected_workers(base, recovery_map, not allow_incomplete)
    output.mkdir(parents=True)
    started = time.perf_counter()
    sources = {name: digest(ROOT/name) for name in
        ('certify_cg_reuse_selected.py', 'cg_reuse_recovery.py', 'direct_common_certificate.py',
         'verify_lp_scaling.py', 'CG_REUSE_RECOVERY_POLICY.md')}
    outputs = {}
    for label, executions in (('selected_barrier_certificate', selected),
                              ('unselected_original_barrier_certificate', unselected)):
        rows = []
        for item in executions:
            folder = item['folder']
            before = {str(p.relative_to(folder)): digest(p) for p in folder.rglob('*') if p.is_file()}
            row = certify_direct_worker(folder)
            after = {str(p.relative_to(folder)): digest(p) for p in folder.rglob('*') if p.is_file()}
            if before != after:
                raise ValueError(f'Saved worker changed during independent verification: {folder}')
            row.update(execution_selection={k: str(v) if isinstance(v, Path) else v
                                             for k, v in item.items()},
                       raw_artifacts_unchanged_during_check=True)
            rows.append(row)
            print(json.dumps({'scope': label, 'block_index': item['block_index'],
                              'attempt': item['attempt'], 'supplementary_certified': row.get('supplementary_certified')}), flush=True)
        report = {'post_hoc': True, 'primary_results_changed': False,
            'scope': label, 'checkpoint': allow_incomplete,
            'selected_for_logical_comparisons': label == 'selected_barrier_certificate',
            'planned_logical_barrier_outcomes': 18, 'workers': len(rows),
            'supplementary_certified_workers': sum(bool(r.get('supplementary_certified')) for r in rows),
            'checker_sha256': sources['direct_common_certificate.py'],
            'selection_source_sha256': sources, 'recovery_map': provenance,
            'omitted_selected_slots': omitted if label == 'selected_barrier_certificate' else [], 'results': rows}
        path = output/(label+'.json'); path.write_text(json.dumps(safe(report), indent=2)+'\n')
        outputs[label] = {'path': str(path.resolve()), 'sha256': digest(path), 'workers': len(rows),
                          'supplementary_certified_workers': report['supplementary_certified_workers']}
    manifest = {'no_optimization': True, 'input': str(Path(base).resolve()), 'checkpoint': allow_incomplete,
        'outputs': outputs, 'recovery_map': provenance, 'source_sha256': sources,
        'total_diagnostic_seconds': time.perf_counter()-started,
        'usage': 'Pass only selected_barrier_certificate.json to summarize_cg_reuse.py --supplement. The other report is unselected execution evidence.'}
    (output/'selection_manifest.json').write_text(json.dumps(safe(manifest), indent=2)+'\n')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--recovery-map', type=Path); p.add_argument('--allow-incomplete', action='store_true')
    a = p.parse_args()
    result = certify_collection(a.input, a.output, a.recovery_map, a.allow_incomplete)
    print(json.dumps(result['outputs'], indent=2))


if __name__ == '__main__': main()
