"""Record the original plug study's input hashes (read-only), for the preflight hash match.

Run once locally: python3 -I build_reference.py
Reads experiments/opte_plugs_20261013/input_manifest.json and, under
output/opte-plugs-final-20261015/raw, plugs_plan.json, every block_summary.json and
the manifest.json / instance.json of all 72 original arms (block 3 from the recovery
run, as in collect_plugs.py). Writes original_reference.json here. No optimization.
"""
from pathlib import Path
import hashlib, json

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
ORIG = PROJECT / 'experiments/opte_plugs_20261013'
RAW = PROJECT / 'output/opte-plugs-final-20261015/raw'
ARMS = ('cg_lp', 'direct_lp', 'cg_pool_mip', 'direct_mip')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def main():
    manifest = read(ORIG / 'input_manifest.json')
    plan = read(RAW / 'main/plugs_plan.json')
    if read(RAW / 'block3_recovery/plugs_plan.json') != plan:
        raise ValueError('recovery plan differs')
    sources = {'input_manifest.json': {'path': str(ORIG / 'input_manifest.json'), 'sha256': sha(ORIG / 'input_manifest.json')},
               'plugs_plan.json': {'path': str(RAW / 'main/plugs_plan.json'), 'sha256': sha(RAW / 'main/plugs_plan.json')}}
    blocks = []
    for b in plan:
        i = b['block_index']
        base = RAW / ('block3_recovery' if i == 3 else 'main') / 'results' / f'block_{i}'
        rec = next(r for r in manifest['cases'] if r['spec']['case'] == b['case_name'])
        summary = read(base / 'block_summary.json')
        block_instance = read(base / 'instance.json')
        arms = {}
        for arm in ARMS:
            m, inst = read(base / arm / 'manifest.json'), read(base / arm / 'instance.json')
            arms[arm] = {'manifest_instance_sha256': m['instance_sha256'], 'instance_json_sha256_field': inst['sha256'],
                         'manifest_file_sha256': sha(base / arm / 'manifest.json'),
                         'instance_file_sha256': sha(base / arm / 'instance.json'),
                         'budget_seconds': m['budget_seconds'], 'cg_cap_seconds': m['cg_cap_seconds'],
                         'peak_rss_after_diagnostics_bytes': read(base / arm / 'result.json').get('process_peak_rss_after_diagnostics_bytes')}
        hashes = {rec['instance_sha256'], b['instance_sha256'], summary['instance_sha256'], block_instance['sha256']}
        hashes |= {a['manifest_instance_sha256'] for a in arms.values()} | {a['instance_json_sha256_field'] for a in arms.values()}
        if len(hashes) != 1:
            raise ValueError(f'block {i}: original sources disagree {hashes}')
        blocks.append({'block_index': i, 'case_name': b['case_name'], 'spec': rec['spec'], 'instance_sha256': hashes.pop(),
                       'physical_sha256': rec['checks']['physical_sha256'], 'plug_capacities': block_instance['plug_capacities'],
                       'plug_locations': block_instance['plug_locations'], 'raw_folder': str(base.relative_to(PROJECT)),
                       'block_summary_file_sha256': sha(base / 'block_summary.json'), 'arms': arms})
    out = {'written_by': 'build_reference.py', 'sources': sources, 'blocks': blocks,
           'note': 'All sources (input_manifest, plan, block_summary, block and 72 arm manifests/instances) agree on every block hash.'}
    (HERE / 'original_reference.json').write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({'blocks': len(blocks), 'all_sources_agree': True}))


if __name__ == '__main__':
    main()
