"""Print the rows of Tables 5, 6 and 17 from the stored summary records.

Run from this folder:  python3 make_small_tables.py
Uses only the standard library. Table numbers are those of the revised manuscript.
"""
import csv
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent


def rows(path):
    with open(HERE / path, newline='') as f:
        return list(csv.DictReader(f))


def num(x):
    """Manuscript style: integers with {,} from 100 s, otherwise three significant digits."""
    if x >= 100:
        return f"{round(x):,}".replace(',', '{,}')
    return f"{x:.{2 - (len(str(int(x))) - 1) if x >= 1 else 2}f}"


def summary(values):
    return f"{num(median(values))} [{num(min(values))}, {num(max(values))}]"


def table5():
    """Table 5 (tab:lpscaling): median [min, max] of the algorithm-stop time of each arm.
    Direct arms: all six runs per cell (all native optimal and validated post hoc against the full family).
    CG: runs that stopped at the pricing tolerance; TL when all six reached the 1,800-s limit."""
    w = rows('opte-lp-scaling-20261012/lp_analysis_final_20261012/lp_scaling_workers.csv')
    print('% Table 5 (tab:lpscaling)')
    for L in ('4', '15'):
        for n in ('100', '400', '1000'):
            cells = []
            for method in ('dual', 'barrier', 'cg'):
                sel = [r for r in w if r['task_locations'] == L and r['n_tasks'] == n and r['method'] == method]
                assert len(sel) == 6
                done = [float(r['solve_end_to_end_seconds']) for r in sel
                        if r['status'] in ('optimal', 'optimal_to_pricing_tolerance')]
                cells.append(summary(done) if len(done) == 6 else ('TL' if not done else 'mixed'))
            print(f"{L} & {int(n):,} & ".replace(',', '{,}') + ' & '.join(cells) + r' \\')


def table6():
    """Table 6 (tab:directlarge): direct MIPs on the four 1,000-task inputs."""
    print('% Table 6 (tab:directlarge)')
    for r in rows('opte-direct-mip1000-20261012/direct_mip1000_analysis_20261012/mip1000_comparison.csv'):
        f = lambda x, d: f"{float(x):,.{d}f}".replace(',', '{,}')
        print(f"{r['points']} & {int(r['draw_seed']) + 1} & {f(r['prior_lp_objective'], 3)} & {f(r['incumbent'], 3)} & "
              f"{f(r['historical_reported_incumbent'], 1)} & {float(r['full_family_integrality_gap_pct']):.2f} & "
              f"{float(r['solve_end_to_end_seconds']):.2f} " + r'\\')


def table17():
    """Table 17 (tab:cgreuse): CG with rebuilt master, CG with reused master, direct barrier; 15 locations."""
    w = rows('opte-cg-reuse-20261013/cg_reuse_analysis_final_20261013/worker_outcomes.csv')
    print('% Table 17 (tab:cgreuse)')
    for n in ('100', '400', '1000'):
        cells = []
        for variant in ('cold', 'reuse', 'barrier'):
            sel = [r for r in w if r['n_tasks'] == n and r['variant'] == variant]
            assert len(sel) == 6
            done = [float(r['solve_end_to_end_seconds']) for r in sel
                    if r['status'] in ('optimal', 'optimal_to_pricing_tolerance')]
            cells.append(summary(done) if len(done) == 6 else ('TL' if not done else 'mixed'))
        print(f"{int(n):,} & ".replace(',', '{,}') + ' & '.join(cells) + r' \\')


if __name__ == '__main__':
    table5(); table6(); table17()
