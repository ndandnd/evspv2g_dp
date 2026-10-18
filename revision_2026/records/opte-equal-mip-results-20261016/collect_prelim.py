"""Preliminary collector for the equal-MIP study (not final: no earlier-study BKS, no sacct)."""
import json, glob, os, math
R = 'raw'
def load(case, arm):
    p = f'{R}/{case}/{arm}/result.json'
    return json.load(open(p)) if os.path.exists(p) else None
def at(d, T):
    inc = [e for e in d.get('incumbent_events', []) if e['elapsed_seconds'] <= T and e.get('matrix_primal_check', {}).get('passed') and e.get('physical_replay_passed')]
    U = min((e['objective'] for e in inc), default=None)
    bs = [b['bound'] for b in d.get('bound_observations', []) if b['elapsed_seconds'] <= T and b.get('bound') is not None]
    bs += [e['bound'] for e in d.get('incumbent_events', []) if e['elapsed_seconds'] <= T and e.get('bound') is not None]
    return U, max(bs, default=None)
order = ['panel', 'scaling', 'paper']
cases = sorted({p.split('/')[1] for p in glob.glob(f'{R}/*/*/result.json')})
rows = []
for c in cases:
    cg, di = load(c, 'cg_pool_mip'), load(c, 'direct_mip')
    r = {'case': c, 'cohort': (cg or di)['cohort']}
    if cg:
        r.update(cg_s=cg['cg_seconds'], cg_conv=cg['cg_priced_out'] and cg['final_pricing_call_empty'],
                 L=cg['cg_lp']['objective'], cg_lb=cg.get('full_family_lp_lower_bound'),
                 cols=cg['cg_lp']['columns'], arcs=cg.get('graph_arcs'),
                 pool_U=cg.get('objective') if cg.get('incumbent_validated') else None,
                 pool_status=cg['restricted_mip']['status'], pool_bound=cg['restricted_mip']['restricted_pool_bound'],
                 pool_mip_s=cg['mip_seconds'], cg_total=cg['cg_total_readout_seconds'])
    if di:
        root = di.get('root_lp_solved_seconds')
        U18, B18 = at(di, 1800.0)
        r.update(arcs=r.get('arcs') or di.get('graph_arcs'), d_root_s=root, d_root_line=di.get('root_relaxation_log_line'),
                 d_U1800=U18, d_B1800=B18, d_final_U=di.get('objective') if di.get('incumbent_validated') else None,
                 d_final_B=di.get('bound'), d_status=di['status'], d_solve_s=di.get('solve_seconds'), d_budget=di.get('budget_seconds'))
        if cg:
            T = cg['cg_total_readout_seconds']
            r['d_UT'], r['d_BT'] = at(di, T) if T <= di['budget_seconds'] else (None, None)
            r['truncated'] = T > di['budget_seconds']
    cands = [x for x in (r.get('pool_U'), r.get('d_final_U'), r.get('d_U1800')) if x]
    r['BKS'] = min(cands) if cands else None
    lbs = [x for x in (r.get('cg_lb'), r.get('d_final_B')) if x is not None]
    r['LBstar'] = max(lbs) if lbs else None
    rows.append(r)
rows.sort(key=lambda r: (order.index(r['cohort']), r['case']))
json.dump(rows, open('prelim_rows.json', 'w'), indent=1)
def f(x, d=0):
    return '—' if x is None else (f'{x:,.{d}f}')
def gap(U, B):
    return '—' if (U is None or B is None) else f'{100*(U-B)/B:.2f}'
print('| input | arcs | CG s | direct root s | LP L | BKS | LB* | CG+pool cost | gap% | pool | direct@1800 | gap% | direct bound@1800 | direct final (status, s) | direct @CG total |')
print('|'+'---|'*15)
for r in rows:
    print('|', r['case'], '|', f(r.get('arcs')), '|', f(r.get('cg_s'), 0) + ('' if r.get('cg_conv', True) else '*'), '|',
          f(r.get('d_root_s'), 0) if r.get('d_root_s') else 'unfinished', '|', f(r.get('L'), 1), '|', f(r.get('BKS'), 1), '|', f(r.get('LBstar'), 1), '|',
          f(r.get('pool_U'), 1), '|', gap(r.get('pool_U'), r.get('BKS')), '|', (r.get('pool_status') or '—')[:3], '|',
          f(r.get('d_U1800'), 1), '|', gap(r.get('d_U1800'), r.get('BKS')), '|', f(r.get('d_B1800'), 1), '|',
          f(r.get('d_final_U'), 1), f"({r.get('d_status','—')[:3]}, {f(r.get('d_solve_s'))})", '|',
          ('trunc' if r.get('truncated') else f(r.get('d_UT'), 1)), '|')
