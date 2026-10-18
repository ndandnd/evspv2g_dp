"""Run on the cluster login node (directory listing only): one validation job per printed input."""
import json, os
H = os.path.expanduser('~')
C = {'grid': f'{H}/opte-grid-scaling-20261016', 'transition': f'{H}/opte-transition-20261017',
     'tasks': f'{H}/opte-task-scaling-20261016', 'equal': f'{H}/opte-equal-mip-20261015'}
RT = {'grid': 'opte_grid_scaling_20261016', 'transition': 'opte_transition_20261017',
      'tasks': 'opte_task_scaling_20261016', 'equal': 'opte_equal_mip_20261015'}
RES = {'grid': 'results', 'transition': 'results', 'tasks': 'results_9654', 'equal': 'results'}
ex = lambda p: os.path.exists(f'{p}/result.json')
jobs = []
for coh in ('grid', 'transition', 'tasks', 'equal'):
    root = C[coh]; runtime = f'{root}/code/experiments/{RT[coh]}/runtime'
    for case in sorted(os.listdir(f'{root}/{RES[coh]}')):
        arms = []
        base = f'{root}/{RES[coh]}/{case}'
        if ex(f'{base}/cg_pool_mip'): arms.append(f'cg1800:cg:{base}/cg_pool_mip')
        if coh == 'grid':
            d = f'{root}/results_mem72/{case}/direct_mip'
            arms.append(f'direct:direct:{d}:1800,3600' if ex(d) else f'direct:direct:{base}/direct_mip:1800,3600')
            if ex(f'{root}/results_3600/{case}/cg_pool_mip'): arms.append(f'cg3600:cg:{root}/results_3600/{case}/cg_pool_mip')
        else:
            if ex(f'{base}/direct_mip'): arms.append(f'direct:direct:{base}/direct_mip:1800')
            if coh == 'transition' and os.path.isdir(f'{root}/results_3600/{case}'):
                if ex(f'{root}/results_3600/{case}/cg_pool_mip'): arms.append(f'cg3600:cg:{root}/results_3600/{case}/cg_pool_mip')
                if ex(f'{root}/results_3600/{case}/direct_mip'): arms.append(f'direct3600:direct:{root}/results_3600/{case}/direct_mip:3600')
        rec = json.load(open(f'{base}/cg_pool_mip/instance.json')) if ex(f'{base}/cg_pool_mip') else json.load(open(f'{base}/direct_mip/instance.json'))
        L = len(rec['dist']); n = rec['n_tasks']
        mem = 4 if L <= 31 else 8 if L <= 51 else 16 if L <= 91 else 24
        if coh == 'equal' and n >= 4000: mem = max(mem, 16)
        jobs.append({'cohort': coh, 'case': case, 'runtime': runtime, 'arms': arms, 'mem_gb': mem, 'L': L, 'n': n})
json.dump(jobs, open('jobs.json', 'w'), indent=1)
print(len(jobs), {c: sum(j['cohort'] == c for j in jobs) for c in C}, sum(len(j['arms']) for j in jobs))
