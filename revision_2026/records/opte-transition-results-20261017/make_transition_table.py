import json, statistics as S, collections
R = json.load(open('transition_rows.json'))
cells = collections.defaultdict(list)
for r in R: cells[(r['L'], r['n'])].append(r)
fm = lambda x: f"{x:,.0f}".replace(',', '{,}')
out = []
for (L, n), rs in sorted(cells.items()):
    roots = [r['d_root'] for r in rs if r['d_root'] is not None]
    opt = sum(1 for r in rs if r['d_opt_by_T']); st = sum(1 for r in rs if r['d_initial'])
    better = sum(1 for r in rs if r['gap_cg'] < r['gap_d'] - 0.01); worse = sum(1 for r in rs if r['gap_d'] < r['gap_cg'] - 0.01)
    root = f"{fm(S.median(roots))} [{fm(min(roots))}, {fm(max(roots))}]" if len(roots) == len(rs) else '--'
    out.append(f"{L} & {n} & {rs[0]['arcs']/1e6:.1f} & {root} & {opt} & {st} & {S.median(r['gap_cg'] for r in rs):.2f} & {S.median(r['gap_d'] for r in rs):.2f} & {better} / {len(rs)-better-worse} / {worse} \\\\")
open('transition_rows.tex', 'w').write('\n'.join(out) + '\n'); print('\n'.join(out))
