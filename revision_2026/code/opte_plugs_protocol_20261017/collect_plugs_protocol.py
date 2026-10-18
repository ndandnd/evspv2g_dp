"""Collect the 36 plug integer arms run under the agreed protocol (opte_plugs_protocol_20261017).

Reads only local files: the new results folder (block_<i>/<arm>/{result,manifest,instance}.json),
original_reference.json (input hashes of the original study) and the original collector output
output/opte-plugs-final-20261015/plug_results.json (LP columns; the LP arms are not rerun).
No optimization, no network, no scheduler calls. Fails loudly on any rejected check.

Writes protocol_results.json, protocol_arms.csv and protocol_table.md into --out. The table has the
layout of plug_table.md (LP columns unchanged from the original study, the two integer columns from
the new runs) plus: CG time to convergence, pool-MIP time, LB*, gaps to LB*, and the change in the
best integer cost versus the unlimited policy on the same physical input.

LB* = max(z_RMP - n*1e-6 when CG priced out, direct final ObjBound); gap = 100(U - LB*)/U, where U is
the arm's incumbent (direct: best incumbent at or before the snapshot time, default 1,800 s).

Usage (main):  python3 -I collect_plugs_protocol.py --results <copied results dir> --out <dir>
Usage (smoke): python3 -I collect_plugs_protocol.py --results <smoke dir> --out <dir> --blocks 0,2 \
                   --expect cg_cap=300,mip_budget=60,direct_budget=900,snapshot=900 --require-cpu ''
"""
from pathlib import Path
import argparse, csv, hashlib, json, math

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
ORIGINAL = PROJECT / 'output/opte-plugs-final-20261015/plug_results.json'
ARMS = ('cg_pool_mip', 'direct_mip')
TOL = 1e-6
MAIN = {'cg_cap': 14400.0, 'mip_budget': 1800.0, 'direct_budget': 1800.0, 'snapshot': 1800.0}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fmt(v, d=2):
    return '—' if v is None else f'{v:,.{d}f}'


def arm_record(folder, arm, ref, expect, require_cpu, gurobi, code):
    r, m, inst = read(folder / 'result.json'), read(folder / 'manifest.json'), read(folder / 'instance.json')
    i = ref['block_index']
    require(m['arm'] == r['arm'] == arm and m['task']['block_index'] == i and m['case'] == ref['spec'], f'{i}/{arm} identity')
    require(inst['sha256'] == m['instance_sha256'] == r['instance_sha256'] == ref['instance_sha256'], f'{i}/{arm} input hash differs from original')
    require(inst['plug_capacities'] == ref['plug_capacities'], f'{i}/{arm} plug capacities differ from original')
    budgets = {'cg_cap': m['cg_cap_seconds'], 'mip_budget': m['mip_budget_seconds'],
               'direct_budget': m['direct_budget_seconds'], 'snapshot': m['snapshot_seconds']}
    keys = ('cg_cap', 'mip_budget') if arm == 'cg_pool_mip' else ('direct_budget', 'snapshot')
    require(all(budgets[k] == expect[k] for k in keys), f'{i}/{arm} budgets {budgets} != {expect}')
    if code is not None:
        require(m['code_sha256'] == code, f'{i}/{arm} code differs from the preflight record')
    env = m['environment']
    require('.'.join(map(str, env['gurobi'])) == gurobi, f'{i}/{arm} Gurobi {env["gurobi"]}')
    if require_cpu:
        require(require_cpu in env['cpu_model'] and len(env.get('cpu_affinity') or []) == 1, f'{i}/{arm} CPU/affinity')
    require(r['status'] not in ('error', 'environment_rejected'), f'{i}/{arm} status {r["status"]}: {r.get("error")}')
    row = {'block': i, 'case': ref['case_name'], 'policy': ref['spec']['plug_policy'], 'arm': arm, 'status': r['status'],
           'native_status': r.get('native_status'), 'host': env['host'], 'cpu_model': env['cpu_model'],
           'cpu_affinity': env.get('cpu_affinity'), 'slurm_job': (m.get('slurm') or {}).get('SLURM_JOB_ID'),
           'restart_count': (m.get('slurm') or {}).get('SLURM_RESTART_COUNT'), 'started_utc': m['started_utc'],
           'peak_rss_at_stop_bytes': r.get('process_peak_rss_at_stop_bytes'),
           'peak_rss_after_diagnostics_bytes': r.get('process_peak_rss_after_diagnostics_bytes'),
           'result_sha256': sha(folder / 'result.json'), 'manifest_sha256': sha(folder / 'manifest.json')}
    if arm == 'cg_pool_mip':
        lp = r.get('cg_lp') or {}
        row.update(cg_status=r['cg_status'], cg_priced_out=r['cg_priced_out'], cg_seconds=r['cg_seconds'],
                   cg_lp=lp.get('objective'), cg_columns=r.get('cg_columns_total'), pool_columns=r.get('pool_columns'),
                   cg_rmp_calls=r.get('cg_rmp_calls'), cg_lower_bound=r.get('full_family_lp_lower_bound'),
                   mip_seconds=r['mip_seconds'], cg_total_readout_seconds=r['cg_total_readout_seconds'],
                   objective=r.get('objective'), U=r.get('objective'), restricted_pool_bound=r.get('restricted_pool_bound'),
                   solution_count=r.get('solution_count'), incumbent_validated=r.get('incumbent_validated'))
        if r['cg_priced_out']:
            require(finite(lp.get('objective')) and finite(r['full_family_lp_lower_bound'])
                    and abs(r['full_family_lp_lower_bound'] - (lp['objective'] - ref['spec']['n_tasks'] * TOL)) < 1e-9, f'{i}/cg bound')
        if r.get('objective') is not None:
            v = r['validation']
            require(r['incumbent_validated'] is True and r['matrix_primal_check']['passed'] and v['passed'], f'{i}/cg validation')
            require(v['max_connector_violation'] <= TOL, f'{i}/cg plug rows violated')
            require(abs(v['aggregate']['replayed_objective'] - r['objective']) <= TOL * max(1, abs(r['objective'])), f'{i}/cg objective replay')
            row.update(max_connector_violation=v['max_connector_violation'], replayed_objective=v['aggregate']['replayed_objective'],
                       plug_rows=r.get('plug_rows'), selected_routes=len(v['selected_route_proofs']))
        else:
            require(r.get('solution_count', 0) == 0, f'{i}/cg missing objective with solutions')
    else:
        U = r.get('snapshot_incumbent_objective')
        row.update(direct_seconds=r.get('solve_end_to_end_seconds'), graph_arcs=r.get('graph_arcs'), variables=r.get('variables'),
                   root_lp_solved_seconds=r.get('root_lp_solved_seconds'), objective=r.get('objective'), U=U,
                   U_found_seconds=r.get('snapshot_incumbent_found_seconds'), bound=r.get('bound'),
                   snapshot_bound=r.get('snapshot_bound'), native_gap=r.get('gap'), node_count=r.get('node_count'),
                   solution_count=r.get('solution_count'), incumbents=len(r.get('incumbent_events') or []),
                   incumbent_validated=r.get('incumbent_validated'), snapshot_incumbent_validated=r.get('snapshot_incumbent_validated'))
        events = r.get('incumbent_events') or []
        require(all(e['matrix_primal_check']['passed'] for e in events), f'{i}/direct incumbent matrix check')
        if U is not None:
            v = r['snapshot_validation']
            require(r['snapshot_incumbent_validated'] is True and v['passed'] and v['max_connector_violation'] <= TOL, f'{i}/direct snapshot replay')
            require(abs(v['aggregate']['replayed_objective'] - U) <= TOL * max(1, abs(U)), f'{i}/direct objective replay')
            row.update(max_connector_violation=v['max_connector_violation'], replayed_objective=v['aggregate']['replayed_objective'],
                       plug_rows=r.get('snapshot_plug_rows'), selected_routes=len(v['selected_route_proofs']))
        if r.get('objective') is not None:
            require(r['incumbent_validated'] is True and r['validation']['max_connector_violation'] <= TOL, f'{i}/direct final validation')
    return row


def collect(results, blocks, expect, require_cpu, original, gurobi='12.0.3', code=None):
    ref = {b['block_index']: b for b in read(HERE / 'original_reference.json')['blocks']}
    orig = {b['block']: b for b in read(original)['blocks']}
    rows, out = [], []
    for i in blocks:
        group = {arm: arm_record(results / f'block_{i}' / arm, arm, ref[i], expect, require_cpu, gurobi, code) for arm in ARMS}
        rows += list(group.values())
        cg, dm, ob = group['cg_pool_mip'], group['direct_mip'], orig[i]
        require(ob['case'] == ref[i]['case_name'] and ob['physical_sha256'] == ref[i]['physical_sha256'], f'block {i} original LP record')
        lp_rel = None
        if cg['cg_priced_out']:
            lp_rel = abs(cg['cg_lp'] - ob['lp_direct']) / abs(ob['lp_direct'])
            require(lp_rel <= TOL, f'block {i}: new CG LP {cg["cg_lp"]} differs from original LP {ob["lp_direct"]}')
        cands = [(cg['cg_lower_bound'], 'CG') if cg['cg_priced_out'] else None, (dm['bound'], 'direct') if dm['bound'] is not None else None]
        cands = [c for c in cands if c is not None]
        lb, src = max(cands) if cands else (None, None)
        ups = [u for u in (cg['U'], dm['U'], dm['objective']) if u is not None]
        if lb is not None and ups:
            require(lb <= min(ups) + TOL * max(1, abs(min(ups))), f'block {i}: LB* {lb} above an incumbent {min(ups)}')
        gap = lambda U: None if U is None or lb is None else 100 * (U - lb) / U
        best = min(ups) if ups else None
        out.append({'block': i, 'case': ref[i]['case_name'], 'physical_case': ref[i]['spec']['physical_case'],
                    'policy': ref[i]['spec']['plug_policy'], 'n_tasks': ref[i]['spec']['n_tasks'],
                    'depot_plugs': ref[i]['spec']['depot_plugs'], 'nondepot_plugs': ref[i]['spec']['nondepot_plugs'],
                    'original_lp': ob, 'new_cg_lp': cg['cg_lp'], 'new_cg_lp_rel_diff_vs_original_lp': lp_rel,
                    'cg_pool_mip': cg, 'direct_mip': dm, 'LB_star': lb, 'LB_star_source': src,
                    'gap_cg_pool_pct': gap(cg['U']), 'gap_direct_pct': gap(dm['U']), 'best_U': best,
                    'hosts': sorted({cg['host'], dm['host']})})
    by_case = {}
    for b in out:
        by_case.setdefault(b['physical_case'], {})[b['policy']] = b
    for trip in by_case.values():
        base = trip.get('unlimited')
        for b in trip.values():
            b['best_U_change_vs_unlimited_pct'] = (None if base is None or base['best_U'] is None or b['best_U'] is None
                                                  else 100 * (b['best_U'] - base['best_U']) / base['best_U'])
            b['LB_star_change_vs_unlimited_pct'] = (None if base is None or base['LB_star'] is None or b['LB_star'] is None
                                                   else 100 * (b['LB_star'] - base['LB_star']) / base['LB_star'])
    return rows, out


def table(blocks):
    L = ['| Blk | Input (n/L/step, draw) | Policy (nondepot/depot plugs) | LP value (direct) | CG−direct rel. diff | CG LP s | Direct LP s | Direct/CG | Binding rows CG / direct (depot) | Positive plug prices CG / direct | Peak occ. depot / nondepot (direct) | LP Δ vs unlimited | CG-pool MIP cost (status) | Direct MIP cost (status) | CG s to convergence (status) | Pool MIP s | LB* (source) | Gap CG-pool | Gap direct | Best cost Δ vs unlimited |',
         '|---:|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---|---|---|---:|---:|---:|---:|---:|']
    for b in blocks:
        o = b['original_lp']
        n, Lc, step, draw = b['case'].split('_')[1:5]
        inp = f"{n[1:]}/{Lc[1:]}/{step[1:].replace('p', '.')} kWh, {draw}"
        pol = b['policy'] if b['depot_plugs'] is None else f"{b['policy']} ({b['nondepot_plugs']}/{b['depot_plugs']})"
        oc, od, pc, pd = o['occ_cg'], o['occ_direct'], o['price_cg'], o['price_direct']
        bind = '—' if b['policy'] == 'unlimited' else f"{oc['binding_rows']} ({oc['binding_rows_depot']}) / {od['binding_rows']} ({od['binding_rows_depot']})"
        pr = '—' if b['policy'] == 'unlimited' else f"{pc['positive_price_rows']} / {pd['positive_price_rows']}"
        peak = f"{od['peak_depot']:.3g} / {od['peak_nondepot']:.3g}"
        lpd = '0.000%' if abs(o['lp_increase_vs_unlimited_pct']) < 1e-9 else format(o['lp_increase_vs_unlimited_pct'], '+.3f') + '%'
        cg, dm = b['cg_pool_mip'], b['direct_mip']
        cps = f"{fmt(cg['U'])} ({cg['status']})"
        dms = f"{fmt(dm['U'])} ({dm['status']}; bound {fmt(dm['bound'])})"
        cgs = f"{cg['cg_seconds']:.1f} ({'priced out' if cg['cg_priced_out'] else cg['cg_status']})"
        pct = lambda v: '—' if v is None else f'{v:.2f}%'
        sgn = lambda v: '—' if v is None else ('0.000%' if abs(v) < 1e-9 else f'{v:+.3f}%')
        L.append(f"| {b['block']} | {inp} | {pol} | {o['lp_direct']:.6f} | {o['lp_rel_diff']:.1e} | {o['cg_lp_seconds']:.1f} | "
                 f"{o['direct_lp_seconds']:.1f} | {o['direct_over_cg_time']:.2f} | {bind} | {pr} | {peak} | {lpd} | {cps} | {dms} | "
                 f"{cgs} | {cg['mip_seconds']:.1f} | {fmt(b['LB_star'])} ({b['LB_star_source'] or '—'}) | {pct(b['gap_cg_pool_pct'])} | "
                 f"{pct(b['gap_direct_pct'])} | {sgn(b['best_U_change_vs_unlimited_pct'])} |")
    return '\n'.join(L) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--results', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--original', type=Path, default=ORIGINAL)
    p.add_argument('--blocks', default=','.join(map(str, range(18))))
    p.add_argument('--expect', default=','.join(f'{k}={v:g}' for k, v in MAIN.items()))
    p.add_argument('--require-cpu', default='EPYC 9654')
    p.add_argument('--require-gurobi', default='12.0.3')
    p.add_argument('--preflight', default=str(HERE / 'cluster/preflight_cluster.json'),
                   help="every arm manifest's code_sha256 must equal this preflight's ('' to skip)")
    a = p.parse_args()
    blocks = [int(x) for x in a.blocks.split(',')]
    expect = {k: float(v) for k, v in (kv.split('=') for kv in a.expect.split(','))}
    code = read(a.preflight)['code_sha256'] if a.preflight else None
    rows, out = collect(a.results.resolve(), blocks, expect, a.require_cpu, a.original, a.require_gurobi, code)
    a.out.mkdir(parents=True, exist_ok=True)
    counts = {'blocks': len(out), 'arms': len(rows),
              'cg_priced_out': sum(b['cg_pool_mip']['cg_priced_out'] for b in out),
              'cg_pool_with_schedule': sum(b['cg_pool_mip']['U'] is not None for b in out),
              'direct_with_schedule_by_snapshot': sum(b['direct_mip']['U'] is not None for b in out),
              'direct_optimal': sum(b['direct_mip']['status'] == 'optimal' for b in out),
              'max_new_vs_original_lp_rel_diff': max((b['new_cg_lp_rel_diff_vs_original_lp'] or 0) for b in out),
              'hosts': sorted({r['host'] for r in rows}), 'requeued_arms': [f"{r['block']}/{r['arm']}" for r in rows if r['restart_count'] not in (None, '0')]}
    doc = {'collector_sha256': sha(__file__), 'results': str(a.results), 'expect': expect, 'counts': counts, 'blocks': out, 'arms': rows}
    (a.out / 'protocol_results.json').write_text(json.dumps(doc, indent=1, allow_nan=False) + '\n')
    cols = ['block', 'case', 'policy', 'arm', 'status', 'U', 'objective', 'bound', 'restricted_pool_bound', 'cg_status', 'cg_priced_out',
            'cg_seconds', 'cg_lp', 'cg_lower_bound', 'cg_columns', 'pool_columns', 'mip_seconds', 'direct_seconds', 'U_found_seconds',
            'root_lp_solved_seconds', 'incumbents', 'solution_count', 'incumbent_validated', 'max_connector_violation',
            'replayed_objective', 'host', 'cpu_model', 'slurm_job', 'restart_count', 'peak_rss_at_stop_bytes']
    with (a.out / 'protocol_arms.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows({k: r.get(k) for k in cols} for r in rows)
    (a.out / 'protocol_table.md').write_text(table(out))
    print(json.dumps(counts, indent=1))


if __name__ == '__main__':
    main()
