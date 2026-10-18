"""Addendum, 18 Oct 2026: job list for the four 160- and 200-location inputs of the map extension (8 runs).

Run on the cluster login node (directory listing only). Same job schema as make_jobs.py; the worker reads it via
JOBS=$ROOT/jobs_mapx.json. Cohort 'grid' selects grid_instances in rebuild_input.py; the runtime is the extension's
copy (DIAG_L extended to 160 and 200), i.e. the code that ran. The direct MIP had an 1,800-s limit here, so the
only reading is 1,800 s (no results_mem72 / results_3600 arms exist for these inputs).
"""
import json, os
H = os.path.expanduser('~')
root = f'{H}/opte-map-extension-20261017'
runtime = f'{root}/code/experiments/opte_map_extension_20261017/runtime'
CASES = ('grid_L160_n0320_draw0', 'grid_L160_n0320_draw1', 'grid_L200_n0400_draw0', 'grid_L200_n0400_draw1')
ex = lambda p: os.path.exists(f'{p}/result.json')
jobs = []
for case in CASES:
    base = f'{root}/results/{case}'
    assert ex(f'{base}/cg_pool_mip') and ex(f'{base}/direct_mip'), case
    rec = json.load(open(f'{base}/cg_pool_mip/instance.json'))
    L = len(rec['dist']); n = rec['n_tasks']
    jobs.append({'cohort': 'grid', 'case': case, 'runtime': runtime,
                 'arms': [f'cg1800:cg:{base}/cg_pool_mip', f'direct:direct:{base}/direct_mip:1800'],
                 'mem_gb': None, 'L': L, 'n': n})
json.dump(jobs, open('jobs_mapx.json', 'w'), indent=1)
print(len(jobs), sum(len(j['arms']) for j in jobs), [(j['case'], j['L'], j['n']) for j in jobs])
