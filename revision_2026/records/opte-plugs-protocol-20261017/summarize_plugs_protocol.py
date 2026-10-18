"""Own summary of the plug-limit integer rerun (agreed protocol). Does not edit the hashed collector.

Inputs (read only): collected/protocol_results.json (collector output, hash-checked arms),
raw/block_<i>/<arm>/result.json (truck/battery counts, route task counts), and the original study
output/opte-plugs-final-20261015/plug_results.json (old integer values).
Handles the two known collector nits:
 (1) best cost uses only the 1,800-s readings: CG-pool incumbent and the direct incumbent at <= 1,800 s
     (the collector also includes the direct final incumbent);
 (2) the direct bound is shown as '-' when the root LP did not finish (Gurobi reports 0.0).
Writes summary/summary.json and summary/summary_table.md.
Usage: python3 -I summarize_plugs_protocol.py
"""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
COL = HERE / 'collected/protocol_results.json'
RAW = HERE / 'raw'
OLD = PROJECT / 'output/opte-plugs-final-20261015/plug_results.json'
OUT = HERE / 'summary'


def read(p):
    return json.loads(Path(p).read_text())


def ival(x):
    return None if x is None else int(round(x))


def composition(res, key):
    v = res.get(key)
    if not v:
        return None
    a = v['aggregate']
    tasks = [len(p['replay']['tasks']) for p in v['selected_route_proofs']]
    return {'trucks': ival(a['truck_count']), 'batteries': ival(a['battery_count']),
            'single_task_routes': sum(1 for t in tasks if t == 1), 'tasks': sum(tasks)}


def fmt(v, d=2):
    return '—' if v is None else f'{v:,.{d}f}'


def pct(v, d=2, sign=False):
    if v is None:
        return '—'
    if abs(v) < 0.5 * 10 ** (-d):
        v = 0.0
    return f'{v:+.{d}f}%' if sign else f'{v:.{d}f}%'


def main():
    col = read(COL)
    old = {b['block']: b for b in read(OLD)['blocks']}
    blocks = []
    for b in col['blocks']:
        i = b['block']
        cg, dm = b['cg_pool_mip'], b['direct_mip']
        rc = read(RAW / f'block_{i}/cg_pool_mip/result.json')
        rd = read(RAW / f'block_{i}/direct_mip/result.json')
        root_done = dm.get('root_lp_solved_seconds') is not None
        d_bound = dm['bound'] if (root_done and dm['bound'] is not None) else None
        cg_lb = cg['cg_lower_bound'] if cg['cg_priced_out'] else None
        cands = [(v, s) for v, s in ((cg_lb, 'CG'), (d_bound, 'direct')) if v is not None]
        lb, src = max(cands) if cands else (None, None)
        assert abs(lb - b['LB_star']) < 1e-9, i
        ups = [u for u in (cg['U'], dm['U']) if u is not None]          # 1,800-s readings only
        best = min(ups) if ups else None
        assert (dm['objective'] is None) == (dm['U'] is None) and (dm['U'] is None or abs(dm['objective'] - dm['U']) <= 1e-6 * abs(dm['U'])), f'block {i}: final direct incumbent differs from 1,800-s incumbent'
        ob = old[i]
        blocks.append({
            'block': i, 'case': b['case'], 'physical_case': b['physical_case'], 'policy': b['policy'],
            'n_tasks': b['n_tasks'], 'nondepot_plugs': b['nondepot_plugs'], 'depot_plugs': b['depot_plugs'],
            'lp': ob_lp(ob), 'lp_increase_vs_unlimited_pct': ob['lp_increase_vs_unlimited_pct'],
            'LB_star': lb, 'LB_star_source': src,
            'cg': {'U': cg['U'], 'status': cg['status'], 'cg_seconds': cg['cg_seconds'], 'mip_seconds': cg['mip_seconds'],
                   'restricted_pool_bound': rc.get('restricted_pool_bound'), 'pool_columns': cg['pool_columns'],
                   'gap_pct': None if cg['U'] is None else 100 * (cg['U'] - lb) / cg['U'],
                   'internal_pool_gap_pct': None if cg['U'] is None else 100 * (cg['U'] - rc['restricted_pool_bound']) / cg['U'],
                   'host': cg['host'], 'slurm_job': cg['slurm_job'], 'peak_rss_gb': cg['peak_rss_at_stop_bytes'] / 1e9,
                   'composition': composition(rc, 'validation')},
            'direct': {'U': dm['U'], 'U_found_seconds': dm['U_found_seconds'], 'status': dm['status'], 'bound': d_bound,
                       'root_lp_solved_seconds': dm.get('root_lp_solved_seconds'), 'root_finished': root_done,
                       'gap_pct': None if dm['U'] is None else 100 * (dm['U'] - lb) / dm['U'],
                       'host': dm['host'], 'slurm_job': dm['slurm_job'], 'peak_rss_gb': dm['peak_rss_at_stop_bytes'] / 1e9,
                       'composition': composition(rd, 'snapshot_validation'),
                       'final_composition': composition(rd, 'validation')},
            'best_U': best,
            'old': {'cg_U': ob['cg_pool']['objective'] if ob['cg_pool']['accepted_incumbent'] else None,
                    'cg_status': ob['cg_pool']['status'], 'cg_status_cg': ob['cg_pool']['cg_status'],
                    'direct_U': ob['direct_mip']['objective'] if ob['direct_mip']['accepted_incumbent'] else None,
                    'direct_status': ob['direct_mip']['status'], 'direct_bound': ob['direct_mip']['native_bound']},
        })
    base = {b['physical_case']: b for b in blocks if b['policy'] == 'unlimited'}
    for b in blocks:
        u = base[b['physical_case']]
        b['best_U_change_vs_unlimited_pct'] = 100 * (b['best_U'] / u['best_U'] - 1)
        # Interval for opt(policy)/opt(unlimited) - 1 from bounds and incumbents (both are 1,800-s readings).
        b['optimum_change_interval_pct'] = [100 * (b['LB_star'] / u['best_U'] - 1), 100 * (b['best_U'] / u['LB_star'] - 1)]
        b['cg_vs_cg_change_pct'] = 100 * (b['cg']['U'] / u['cg']['U'] - 1)
        b['proven'] = (b['direct']['status'] == 'optimal' and u['direct']['status'] == 'optimal')
    OUT.mkdir(exist_ok=True)
    (OUT / 'summary.json').write_text(json.dumps({'source_collector_sha256': col['collector_sha256'], 'blocks': blocks}, indent=1) + '\n')

    def comp(c):
        return '—' if c is None else f"{c['trucks']}/{c['batteries']}"
    L = ['| Blk | Input | Policy | LP Δ vs unl. | LB* (src) | CG-pool cost (status) | T/B (1-task routes) | Gap | Direct cost ≤1,800 s (status) | T/B | Gap | Opt. Δ vs unl. (interval) | Old CG-pool | Old direct |',
         '|---:|---|---|---:|---:|---|---|---:|---|---|---:|---|---:|---:|']
    for b in blocks:
        n, Lc, step, draw = b['case'].split('_')[1:5]
        inp = f"{n[1:]}/{Lc[1:]}/{step[1:].replace('p', '.')}, {draw}"
        pol = b['policy'] if b['depot_plugs'] is None else f"{b['policy']} ({b['nondepot_plugs']}/{b['depot_plugs']})"
        cg, dm, o = b['cg'], b['direct'], b['old']
        cc = cg['composition']
        trivial = dm['composition'] is not None and dm['composition']['single_task_routes'] == dm['composition']['tasks']
        dmc = fmt(dm['U']) + (' [all 1-task]' if trivial else '') + f" ({dm['status']}" + ('' if dm['root_finished'] else '; root LP unfinished') + ')'
        lo, hi = b['optimum_change_interval_pct']
        if b['policy'] == 'unlimited':
            iv = '—'
        elif abs(hi - lo) < 1e-6:
            iv = pct(lo, 3, True) + ' (proven)'
        else:
            iv = f'[{pct(lo, 3, True)}, {pct(hi, 3, True)}]'
        L.append(f"| {b['block']} | {inp} | {pol} | {pct(b['lp_increase_vs_unlimited_pct'], 3, True)} | {fmt(b['LB_star'])} ({b['LB_star_source']}) | "
                 f"{fmt(cg['U'])} ({cg['status']}) | {comp(cc)} ({cc['single_task_routes']}) | {pct(cg['gap_pct'])} | {dmc} | {comp(dm['composition'])} | "
                 f"{pct(dm['gap_pct'])} | {iv} | {fmt(o['cg_U'])} | {fmt(o['direct_U'])} |")
    (OUT / 'summary_table.md').write_text('\n'.join(L) + '\n')
    print('\n'.join(L))


def ob_lp(ob):
    return ob['lp_direct']


if __name__ == '__main__':
    main()
