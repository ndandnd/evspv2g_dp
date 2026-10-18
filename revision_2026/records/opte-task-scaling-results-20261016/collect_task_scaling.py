"""Collector for the task-count scaling study (opte_task_scaling_20261016).

Gap = 100 (U - LB*) / U. U: validated schedule cost. LB*: best valid lower bound on the
full model, max(CG LP bound z_RMP - n*1e-6 when priced out, arc-flow branch-and-bound bound
at the end of its run). The route-pool MIP bound is never used as a lower bound.
Arc-flow state at T is the best validated incumbent recorded at or before T.
"""
import json, glob, os, sys
R = sys.argv[1] if len(sys.argv) > 1 else 'raw'
def load(c, a):
    p = f'{R}/{c}/{a}/result.json'
    if not os.path.exists(p): return None
    d = json.load(open(p))
    return d if d.get('status') not in (None, 'environment_rejected') else None
def inc_at(d, T):
    ok = [e['objective'] for e in d.get('incumbent_events', []) if e['elapsed_seconds'] <= T
          and e.get('matrix_primal_check', {}).get('passed') and e.get('physical_replay_passed')]
    return min(ok, default=None)
rows = []
for c in sorted({p.split('/')[-3] for p in glob.glob(f'{R}/*/*/result.json')}):
    cg, di = load(c, 'cg_pool_mip'), load(c, 'direct_mip')
    n = int(c.split('_n')[1][:4]); step = c.split('_d')[1].split('_')[0].replace('p', '.'); draw = int(c[-1])
    r = dict(case=c, n=n, step=step, draw=draw, cg_done=cg is not None, direct_done=di is not None)
    if cg:
        r.update(cg_s=cg['cg_seconds'], cg_conv=bool(cg['cg_priced_out'] and cg['final_pricing_call_empty']),
                 cg_lb=cg.get('full_family_lp_lower_bound'), pool_U=cg['objective'] if cg.get('incumbent_validated') else None,
                 pool_status=cg['restricted_mip']['status'], arcs=cg.get('graph_arcs'), cg_total=cg['cg_total_readout_seconds'])
    if di:
        r.update(root_s=di.get('root_lp_solved_seconds'), d_U1800=inc_at(di, 1800.0), d_final_U=di['objective'] if di.get('incumbent_validated') else None,
                 d_bound=di.get('bound'), d_status=di['status'], d_solve_s=di.get('solve_end_to_end_seconds'), arcs=r.get('arcs') or di.get('graph_arcs'),
                 fallback=di['incumbent_events'][0]['objective'] if di.get('incumbent_events') else None)
        if cg: r['d_U_cgtotal'] = inc_at(di, cg['cg_total_readout_seconds']) if cg['cg_total_readout_seconds'] <= di['budget_seconds'] else None
    lbs = [x for x in (r.get('cg_lb'), r.get('d_bound')) if x is not None]
    r['LB'] = max(lbs) if lbs else None
    g = lambda U: None if U is None or r['LB'] is None else 100 * (U - r['LB']) / U
    r['gap_pool'] = g(r.get('pool_U')); r['gap_d1800'] = g(r.get('d_U1800')); r['gap_dfinal'] = g(r.get('d_final_U'))
    r['d1800_is_fallback'] = r.get('d_U1800') is not None and r.get('d_U1800') == r.get('fallback')
    rows.append(r)
json.dump(rows, open('task_scaling_rows.json', 'w'), indent=1)

def cell(vals, fmt):
    return ' / '.join(fmt(v) for v in vals)
fs = lambda v: '…' if v is None else (f'{v:,.0f}' if isinstance(v, (int, float)) else str(v))
def fgap(r, key):
    if key == 'gap_d1800':
        if not r['direct_done']: return '…'
        if r['d_U1800'] is None: return 'none'
        if r['d1800_is_fallback']: return 'fallback'
    v = r.get(key)
    return '…' if v is None else f'{v:.2f}'
def froot(r):
    if not r['direct_done']: return '…'
    return 'unfinished' if r.get('root_s') is None else f"{r['root_s']:,.0f}"
out = ['| SoC step | tasks | arcs (M) | CG LP time s | arc-flow root LP s | CG+pool gap % | arc-flow gap % at 1,800 s |', '|---|---:|---:|---:|---:|---:|---:|']
for step in ('25', '12.5'):
    for n in sorted({r['n'] for r in rows}):
        rs = sorted([r for r in rows if r['n'] == n and r['step'] == step], key=lambda r: r['draw'])
        if not rs: continue
        arcs = next((r['arcs'] for r in rs if r.get('arcs')), None)
        out.append(f"| {step} kWh | {n} | {'…' if arcs is None else f'{arcs/1e6:.2f}'} | {cell(rs, lambda r: fs(r.get('cg_s')) + ('' if r.get('cg_conv', True) else '*'))} | {cell(rs, froot)} | {cell(rs, lambda r: fgap(r, 'gap_pool'))} | {cell(rs, lambda r: fgap(r, 'gap_d1800'))} |")
open('TABLE.md', 'w').write('Two task draws per cell (draw 0 / draw 1). "…" = still running. "fallback" = arc flow has only its one-truck-per-task starting schedule. * = CG not converged within 4 h.\n\n' + '\n'.join(out) + '\n')
print('\n'.join(out))
