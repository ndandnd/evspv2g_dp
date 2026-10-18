"""LaTeX rows for the main-text task-count table from task_scaling_rows.json."""
import json
rows = json.load(open('task_scaling_rows.json'))
R = {(r['n'], r['step'], r['draw']): r for r in rows}
fm = lambda x: '\\dots' if x is None else f"{x:,.0f}".replace(',', '{,}')
def cells(r):
    if r is None: return ['\\dots'] * 5
    cg = '\\dots' if not r['cg_done'] else fm(r['cg_s']) + ('' if r['cg_conv'] else '$^\\ast$')
    if not r['direct_done']: root = '\\dots'
    else: root = 'unfin.' if r.get('root_s') is None else fm(r['root_s'])
    gp = None if not r['cg_done'] else r.get('gap_pool')
    if not r['direct_done']: gd = '\\dots'
    elif r.get('d_U1800') is None: gd = 'none'
    elif r['d1800_is_fallback'] and (r.get('gap_d1800') or 0) > 20: gd = 'fallback'
    else: gd = f"{max(0, r['gap_d1800']):.2f}"
    gps = '\\dots' if gp is None else f"{max(0, gp):.2f}"
    # bold the better schedule when both exist
    if gp is not None and r['direct_done'] and r.get('gap_d1800') is not None:
        if gp < r['gap_d1800'] - 1e-6: gps = '\\textbf{' + gps + '}'
        elif r['gap_d1800'] < gp - 1e-6: gd = '\\textbf{' + gd + '}'
    if not r['direct_done']: opt = '\\dots'
    elif r.get('d_status') == 'optimal': opt = fm(r.get('d_solve_s'))
    else: opt = 'TL'
    return [cg, root, gps, gd, opt]
out = []
for n in sorted({k[0] for k in R}):
    for d in (0, 1):
        c25, c12 = cells(R.get((n, '25', d))), cells(R.get((n, '12.5', d)))
        lab = fm(n) if d == 0 else ''
        out.append(f"{lab} & {d + 1} & " + ' & '.join(c25 + c12) + ' \\\\')
    if n != max(k[0] for k in R): out.append('\\addlinespace[2pt]')
open('main_table_rows.tex', 'w').write('\n'.join(out) + '\n')
print('\n'.join(out))
