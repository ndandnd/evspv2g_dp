"""LaTeX for Table 8 (n = 2L, one row per input) and Table 21 (map x tasks matrix) from grid_rows.json."""
import json
rows = json.load(open('grid_rows.json'))
fm = lambda x: f"{x:,.0f}".replace(',', '{,}')
def direct_result(r):
    if 'd_status' not in r: return '\\dots'
    if r.get('d_opt_by_T'): return f"optimal at {fm(r['d_opt_t'])}\\,s"
    if r.get('d_initial'): return f"starting schedule only ({r['gap_d']:.1f})" if r.get('gap_d') is not None else 'starting schedule only'
    return f"gap {r['gap_d']:.2f}" if r.get('gap_d') is not None else r['d_status']
# Table 8
out = []
diag = sorted([r for r in rows if r['diag']], key=lambda r: (r['L'], r['draw']))
for r in diag:
    cg = '\\dots' if r.get('cg_s') is None else fm(r['cg_s'])
    pool = '\\dots' if r.get('pool_s') is None else ('$<$1' if r['pool_s'] < 1 else fm(r['pool_s']))
    gap = '\\dots' if r.get('gap_cg') is None else f"{r['gap_cg']:.2f}"
    root = '\\dots' if 'd_status' not in r else ('not solved' if r.get('d_root') is None else fm(r['d_root']))
    out.append(f"{r['L']} & {r['n']} & {r['draw'] + 1} & {r['arcs']/1e6:.1f} & {cg} & {pool} & {gap} & {root} & {direct_result(r)} \\\\")
open('table8_rows.tex', 'w').write('\n'.join(out) + '\n')
# Table 21: two panels, one number per cell (mean over the two draws)
LS = (15, 30, 45, 60, 90, 120); NS = (120, 240, 480, 960)
def cell(L, n, which):
    rs = [r for r in rows if r['L'] == L and r['n'] == n]
    if n < 2 * L: return '--'
    if len(rs) < 2: return '\\textit{pending}'
    if which == 'cg':
        v = [r.get('gap_cg') for r in rs]
        return '\\textit{pending}' if any(x is None for x in v) else f"{sum(v)/2:.1f}"
    if any('d_status' not in r for r in rs): return '\\textit{pending}'
    tags = []
    for r in rs:
        if r.get('d_initial'): tags.append('start')
        else: tags.append(f"{r['gap_d']:.1f}")
    if tags[0] == tags[1]: return tags[0]
    return ' / '.join(sorted(tags, key=lambda t: (t == 'start', t)))
panel = lambda which: '\n'.join(f"{L} & " + ' & '.join(cell(L, n, which) for n in NS) + ' \\\\' for L in LS)
open('table21_cg_rows.tex', 'w').write(panel('cg') + '\n'); open('table21_direct_rows.tex', 'w').write(panel('direct') + '\n')
print('\n'.join(out[:4])); print(panel('cg')); print(panel('direct'))
