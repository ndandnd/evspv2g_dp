"""Pair each input's 1,800-s and 3,600-s MIP readings for both methods (agreed protocol, EPYC 9654).
Route MIP at 3,600 s: rerun with --mip-budget 3600 (same deterministic CG loop). Direct MIP at 3,600 s: grid inputs from the
original 3,600-s runs (memory reruns where they exist); transition inputs from the 3,600-s reruns.
Gap = 100 (U - LB*) / U with LB* = max(CG LP bound, direct branch-and-bound bounds of both runs)."""
import json, os, glob, collections, statistics as S
G = '../opte-grid-results-20261016'; TR = '../opte-transition-results-20261017'
def L(p): return json.load(open(p)) if os.path.exists(p) else None
def inc(d, T):
    ev = [e for e in d.get('incumbent_events', []) if e['elapsed_seconds'] <= T and e.get('matrix_primal_check', {}).get('passed') and e.get('physical_replay_passed')]
    first = d['incumbent_events'][0]['objective'] if d.get('incumbent_events') else None
    u = min((e['objective'] for e in ev), default=None)
    return u, (u is None or (first is not None and abs(u - first) < 1e-6))
rows = []
for f in sorted(glob.glob('raw3600/*/*/*/cg_pool_mip/result.json')):
    study, case = f.split('/')[1], f.split('/')[3]
    c36 = L(f)
    if study == 'grid':
        c18 = L(f'{G}/raw/{case}/cg_pool_mip/result.json')
        d = L(f'{G}/raw_mem72/{case}/direct_mip/result.json') or L(f'{G}/raw/{case}/direct_mip/result.json'); d18 = d36 = d
    else:
        c18 = L(f'{TR}/raw/{case}/cg_pool_mip/result.json'); d18 = L(f'{TR}/raw/{case}/direct_mip/result.json')
        d36 = L(f'raw3600/transition/results_3600/{case}/direct_mip/result.json')
    if not all([c36, c18, d18, d36]): continue
    Lc = int(case.split('_L')[1][:3]); n = int(case.split('_n')[1][:4])
    lbs = [x for x in (c36.get('full_family_lp_lower_bound'), c18.get('full_family_lp_lower_bound'), d18.get('bound'), d36.get('bound')) if x]
    LB = max(lbs)
    g = lambda U: None if U is None else max(0.0, 100 * (U - LB) / U)
    u18, s18 = inc(d18, 1800); u36, s36 = inc(d36, 3600)
    rows.append(dict(case=case, study=study, L=Lc, n=n, cg18=g(c18['objective']), cg36=g(c36['objective']),
                     pool36_status=c36['restricted_mip']['status'], d18=g(u18), d36=g(u36), start18=s18, start36=s36,
                     d36_opt=(d36.get('status') == 'optimal'), d36_root=d36.get('root_lp_solved_seconds'),
                     cg_time_18=c18['cg_seconds'], cg_time_36=c36['cg_seconds']))
json.dump(rows, open('rows_3600.json', 'w'), indent=1)
cells = collections.defaultdict(list)
for r in rows: cells[(r['L'], r['n'])].append(r)
print(f"{'L':>3} {'n':>4} {'k':>2} | route MIP gap median: 1,800 s -> 3,600 s | direct: start-only 1,800 -> 3,600 | direct gap median 1,800 -> 3,600 | better at 3,600 (CG/tie/direct)")
for (Lc, n), rs in sorted(cells.items()):
    b = sum(1 for r in rs if r['cg36'] < r['d36'] - 0.01); w = sum(1 for r in rs if r['d36'] < r['cg36'] - 0.01)
    print(f"{Lc:3d} {n:4d} {len(rs):2d} | {S.median(r['cg18'] for r in rs):6.2f} -> {S.median(r['cg36'] for r in rs):6.2f} | {sum(r['start18'] for r in rs)} -> {sum(r['start36'] for r in rs)} | "
          f"{S.median(r['d18'] for r in rs):6.2f} -> {S.median(r['d36'] for r in rs):6.2f} | {b}/{len(rs)-b-w}/{w}")
