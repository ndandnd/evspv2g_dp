"""Figure: where the MIP over CG routes overtakes the direct arc-flow MIP (agreed protocol, EPYC 9654).
(a) direct root LP time vs number of locations (all inputs), (b) gap at 1,800 s of both methods, inputs with <= 4 tasks per location.
Sources: grid_rows.json (Table 8 series and map x tasks grid) and transition_rows.json (six draws per cell)."""
import json, collections
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
G = json.load(open('../opte-grid-results-20261016/grid_rows.json')); T = json.load(open('transition_rows.json'))
rows = {}
for r in G: rows[(r['L'], r['n'], r['draw'])] = r
for r in T: rows[(r['L'], r['n'], r['draw'])] = r            # identical inputs: keep the transition rerun
rows = list(rows.values())
plt.rcParams.update({'font.size': 9, 'font.family': 'serif'})
fig, (a, b) = plt.subplots(1, 2, figsize=(7.2, 3.1))
CAP = 3600
for r in rows:
    y = r['d_root'] if r['d_root'] is not None else CAP
    ok = not r['d_initial']
    a.scatter(r['L'], y, s=14, marker='o' if r['d_root'] is not None else '^',
              facecolors=('#c0392b' if ok else 'none'), edgecolors='#c0392b', linewidths=0.8, alpha=0.8)
a.axhline(1800, ls='--', lw=0.9, color='k'); a.text(11, 1830, '1,800-s budget', ha='left', va='bottom', fontsize=7)
a.axhline(CAP, ls=':', lw=0.6, color='grey'); a.text(124, CAP - 60, 'root not solved', ha='right', va='top', fontsize=7, color='grey')
a.set_xlabel('Task locations'); a.set_ylabel('Direct MIP: root relaxation solved at (s)'); a.set_ylim(0, 3800)
a.set_title('(a) Direct MIP root relaxation', fontsize=9)
a.scatter([], [], s=14, facecolors='#c0392b', edgecolors='#c0392b', label='schedule found by 1,800 s')
a.scatter([], [], s=14, facecolors='none', edgecolors='#c0392b', label='starting schedule only')
a.legend(loc='upper left', bbox_to_anchor=(0.0, 0.93), fontsize=7, frameon=False)
sel = [r for r in rows if r['n'] <= 4 * r['L']]
med = collections.defaultdict(lambda: {'cg': [], 'd': []})
for r in sel:
    b.scatter(r['L'] - 0.6, r['gap_cg'], s=12, marker='o', color='#1f4e9a', alpha=0.6, linewidths=0)
    b.scatter(r['L'] + 0.6, r['gap_d'], s=12, marker='s', facecolors='none', edgecolors='#c0392b', alpha=0.8, linewidths=0.8)
    med[r['L']]['cg'].append(r['gap_cg']); med[r['L']]['d'].append(r['gap_d'])
Ls = sorted(med)
import statistics as S
b.plot(Ls, [S.median(med[L]['cg']) for L in Ls], color='#1f4e9a', lw=1.2, label='MIP over CG routes, 1,800 s (median)')
b.plot(Ls, [S.median(med[L]['d']) for L in Ls], color='#c0392b', lw=1.2, label='direct MIP, 1,800 s (median)')
R36 = json.load(open('../opte-3600-results-20261017/rows_3600.json'))
m36 = collections.defaultdict(list)
for r in R36: m36[r['L']].append(r['d36'])
L36 = sorted(m36)
b.plot(L36, [S.median(m36[L]) for L in L36], color='#c0392b', lw=1.0, ls='--', marker='s', ms=3, mfc='white', label='direct MIP, 3,600 s (median)')
b.set_xlabel('Task locations'); b.set_ylabel('Gap to best known lower bound (%)'); b.set_ylim(-2, 70)
b.set_title('(b) Gap after 1,800 s or 3,600 s of MIP time', fontsize=9)
b.legend(loc='center right', fontsize=7, frameon=False)
for ax in (a, b): ax.set_xlim(10, 125); ax.grid(alpha=0.25, lw=0.5)
fig.tight_layout(); fig.savefig('figure/Fig_breakpoint.pdf'); fig.savefig('figure/Fig_breakpoint.png', dpi=200)
print('inputs in (a):', len(rows), ' in (b):', len(sel))
