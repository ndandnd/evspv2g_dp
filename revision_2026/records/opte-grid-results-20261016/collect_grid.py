"""Collect the map x task grid under the agreed protocol: CG to pricing convergence (time reported separately),
then the MIP over its routes 1,800 s; direct arc-flow MIP read at 1,800 s (root LP included), run to 3,600 s for bound.
Gap = 100 (U - LB*) / U, LB* = max(CG LP bound z_RMP - n*1e-6 when priced out, direct branch-and-bound bound at its end)."""
import json, glob, os, sys
R = sys.argv[1] if len(sys.argv) > 1 else 'raw'
OVR = sys.argv[2] if len(sys.argv) > 2 else None     # optional folder with reruns of direct arms (more memory)
T = 1800.0
def L(p): return json.load(open(p)) if os.path.exists(p) else None
rows = []
for c in sorted({p.split('/')[-3] for p in glob.glob(f'{R}/*/*/result.json')}):
    cg = L(f'{R}/{c}/cg_pool_mip/result.json')
    di = L(f'{OVR}/{c}/direct_mip/result.json') if OVR and os.path.exists(f'{OVR}/{c}/direct_mip/result.json') else L(f'{R}/{c}/direct_mip/result.json')
    Lc = int(c[6:9]); n = int(c.split('_n')[1][:4]); dr = int(c[-1])
    r = dict(case=c, L=Lc, n=n, draw=dr, diag=(n == 2 * Lc))
    if cg and cg.get('status') not in ('environment_rejected', 'error'):
        r.update(cg_s=cg['cg_seconds'], cg_conv=bool(cg['cg_priced_out'] and cg['final_pricing_call_empty']),
                 cg_lb=cg.get('full_family_lp_lower_bound'), pool_U=cg['objective'] if cg.get('incumbent_validated') else None,
                 pool_status=cg['restricted_mip']['status'], pool_s=cg['mip_seconds'], arcs=cg.get('graph_arcs'),
                 cg_fleet=((cg.get('validation') or {}).get('aggregate') or {}).get('truck_count'))
    if di and di.get('status') not in ('environment_rejected', 'error'):
        ev = [e for e in di.get('incumbent_events', []) if e.get('matrix_primal_check', {}).get('passed') and e.get('physical_replay_passed')]
        first = di['incumbent_events'][0]['objective'] if di.get('incumbent_events') else None
        U = min((e['objective'] for e in ev if e['elapsed_seconds'] <= T), default=None)
        opt_t = di.get('solve_end_to_end_seconds') if di.get('status') == 'optimal' else None  # construction-inclusive clock
        r.update(d_status=di['status'], d_root=di.get('root_lp_solved_seconds'), d_U=U, d_bound=di.get('bound'),
                 d_first=first, d_opt_t=opt_t, d_initial=(U is not None and first is not None and abs(U - first) < 1e-6),
                 d_opt_by_T=(opt_t is not None and opt_t <= T), d_stop=di.get('solve_seconds'), arcs=r.get('arcs') or di.get('graph_arcs'),
                 d_fleet=(di.get('validation') or {}).get('fleet'))
    lbs = [x for x in (r.get('cg_lb'), r.get('d_bound')) if x is not None and x > 0]
    r['LB'] = max(lbs) if lbs else None
    g = lambda U: None if U is None or r['LB'] is None else max(0.0, 100 * (U - r['LB']) / U)
    r['gap_cg'] = g(r.get('pool_U')); r['gap_d'] = g(r.get('d_U'))
    rows.append(r)
json.dump(rows, open('grid_rows.json', 'w'), indent=1)
for r in rows:
    print(f"L{r['L']:3d} n{r['n']:4d} d{r['draw']} {'D' if r['diag'] else ' '} arcs {r.get('arcs',0)/1e6:5.1f}M | CG {r.get('cg_s',float('nan')):7.0f}s pool {r.get('pool_s',float('nan')):5.0f}s gap {r.get('gap_cg') if r.get('gap_cg') is not None else float('nan'):6.2f} | "
          f"direct root {r.get('d_root') or float('nan'):6.0f} gap@1800 {r.get('gap_d') if r.get('gap_d') is not None else float('nan'):6.2f} {'START' if r.get('d_initial') else ''} {'OPT@%d'%r['d_opt_t'] if r.get('d_opt_t') else ''} {r.get('d_status','...')}")
