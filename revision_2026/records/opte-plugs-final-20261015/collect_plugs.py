"""Collect the 72-arm station/time plug-capacity study (OPTE comment 4).

Reads only local copies in raw/ (result.json, manifest.json, instance.json,
block_summary.json, audit and receipt JSON). No optimization, no network,
no scheduler calls. Fails loudly on any rejected check.

Sources: blocks 0-2 and 4-17 from raw/main (unicorn:~/opte-plugs-20261013);
block 3 from raw/block3_recovery (recovery job 260092,
unicorn:~/opte-preemption-recovery-20261014/256373_3/submission_0001/attempts/restart_0000).
The preempted leftover raw/main/results/block_3 (no result.json) and the
calibration_* audits are ignored.
Usage: python3 -I collect_plugs.py   (writes plug_results.json, plug_arms.csv, plug_table.md)
"""
from pathlib import Path
import csv, datetime, hashlib, json, math

HERE = Path(__file__).resolve().parent
RAW = HERE / 'raw'
ARMS = ('cg_lp', 'direct_lp', 'cg_pool_mip', 'direct_mip')
VERIFIER = 'c451c31b8c0060f02d2017627844e43e0e27622d4430d602edccfa82e2b8deb1'
SNAPSHOT = 'c89eee1724a8976a33fee366de209e0d4b63c1842afd151317e0e4d6bf2f940d'
TOL = 1e-6
PRICE_TOL = 1e-9


def sha(p):
    d = hashlib.sha256()
    with open(p, 'rb') as f:
        for v in iter(lambda: f.read(1 << 20), b''):
            d.update(v)
    return d.hexdigest()


def read(p):
    return json.loads(Path(p).read_text())


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def base_for(i):
    return RAW / ('block3_recovery' if i == 3 else 'main')


def occupancy_stats(primal, inst):
    p = primal.get('physical_replay', primal)
    occ = p.get('occupancy')
    if not occ:
        return None
    require(p.get('passed') is True and p.get('max_plug_violation', math.inf) <= TOL, 'occupancy replay rejected')
    caps, locs = inst['plug_capacities'], inst['plug_locations']
    depot = inst['physical']['depot']
    require(len(occ) == len(caps), 'occupancy dims')
    cells = [(locs[j], t, float(v), caps[j][t]) for j, row in enumerate(occ) for t, v in enumerate(row)]
    require(all(v >= -TOL and (c is None or v <= c + TOL) for _, _, v, c in cells), 'occupancy exceeds cap')
    bind = [(l, t) for l, t, v, c in cells if c is not None and abs(v - c) <= TOL]
    return {
        'finite_rows': sum(c is not None for *_, c in cells),
        'active_rows': sum(v > TOL for _, _, v, _ in cells),
        'binding_rows': len(bind),
        'binding_rows_depot': sum(l == depot for l, _ in bind),
        'binding_rows_nondepot': sum(l != depot for l, _ in bind),
        'peak_depot': max(v for l, _, v, _ in cells if l == depot),
        'peak_nondepot': max(v for l, _, v, _ in cells if l != depot),
        'total_truck_blocks': sum(v for _, _, v, _ in cells),
        'max_plug_violation': p['max_plug_violation'],
    }


def price_stats(cert, inst):
    if not cert:
        return None
    pi = cert['repaired_prices'].get('plug_price')
    caps, locs, depot = inst['plug_capacities'], inst['plug_locations'], inst['physical']['depot']
    pos = [(locs[j], t, v, caps[j][t]) for j, row in enumerate(pi or []) for t, v in enumerate(row)
           if v is not None and v > PRICE_TOL]
    for _, _, _, c in pos:
        require(c is not None, 'positive price on unlimited row')
    return {'positive_price_rows': len(pos),
            'positive_price_rows_depot': sum(l == depot for l, *_ in pos),
            'sum_K_pi': sum(c * v for *_, v, c in pos)}


def expected_caps(policy, n, n_loc, depot_index):
    if policy == 'unlimited':
        return None
    nd, dep = (2, math.ceil(n / 20)) if policy == 'loose' else (1, math.ceil(n / 40))
    return [dep if j == depot_index else nd for j in range(n_loc)]


def collect():
    plan = read(RAW / 'main/plugs_plan.json')
    require(read(RAW / 'block3_recovery/plugs_plan.json') == plan, 'recovery plan differs')
    require(len(plan) == 18, 'plan size')
    rows, blocks = [], []
    for b in plan:
        i = b['block_index']
        base = base_for(i)
        folder = base / 'results' / f'block_{i}'
        bs = read(folder / 'block_summary.json')
        require(bs['completed'] is True and bs['environment_consistent'] is True and bs['instance_sha256'] == b['instance_sha256']
                and bs['arm_order'] == b['arms'], f'block {i} summary')
        inst = read(folder / 'instance.json')
        require(inst['sha256'] == b['instance_sha256'], f'block {i} instance hash')
        group = {}
        for arm in ARMS:
            path = folder / arm
            r, m = read(path / 'result.json'), read(path / 'manifest.json')
            ai = read(inst_path := path / 'instance.json')
            require(ai == inst, f'{i}/{arm} arm instance differs')
            ap, rp = base / 'audits' / f'block_{i}_{arm}.json', base / 'audits' / f'block_{i}_{arm}_receipt.json'
            a, rc = read(ap), read(rp)
            spec = m['case']
            require(m['variant'] == r['variant'] == arm and m['excluded_calibration'] is False and spec['case'] == b['case_name'], f'{i}/{arm} identity')
            require(m['instance_sha256'] == r['instance_sha256'] == b['instance_sha256'], f'{i}/{arm} input hash')
            require(m['budget_seconds'] == 1800 and m['cg_cap_seconds'] == 600, f'{i}/{arm} budget')
            env = m['environment']
            require(env['gurobi'] == [12, 0, 3] and 'EPYC 9654' in env['cpu_model'] and str(env['allocated_cpus']) == '1'
                    and len(env['cpu_affinity']) == 1, f'{i}/{arm} environment')
            # audit + receipt
            require(a['passed'] is True and a['optimization_performed'] is False and a['local_test_environment_override'] is False
                    and len(a['workers']) == 1, f'{i}/{arm} audit')
            w = a['workers'][0]
            require(w['passed'] is True and w['local_test_override'] is False and w['variant'] == arm and w['case'] == b['case_name']
                    and w['status'] == r['status'], f'{i}/{arm} worker')
            require(a['verifier_sha256'] == w['verifier_sha256'] == rc['verifier_sha256'] == VERIFIER, f'{i}/{arm} verifier')
            ex = rc['external_execution']
            require(rc['passed'] is True and rc['status'] == 'verified' and ex['returncode'] == 0 and ex['external_timeout'] is False
                    and rc['primary_evidence_unchanged'] is True and rc['excluded_calibration'] is False
                    and rc['snapshot_manifest_sha256'] == SNAPSHOT and rc['block_index'] == i and rc['arm'] == arm, f'{i}/{arm} receipt')
            local = {n: sha(path / n) for n in ('result.json', 'manifest.json', 'instance.json')}
            require(w['evidence_binding_sha256'] == local and rc['primary_result_sha256'] == local['result.json']
                    and rc['audit_output_sha256'] == sha(ap), f'{i}/{arm} hash binding')
            child = next(x for x in bs['results'] if x['arm'] == arm)
            require(child['result_sha256'] == local['result.json'], f'{i}/{arm} block summary binding')
            lp = arm.endswith('_lp')
            inc = w['accepted_feasible_incumbent']
            if inc:
                require(finite(w['feasible_upper_bound']) and w['feasible_upper_bound'] == r['objective'], f'{i}/{arm} incumbent')
            else:
                require(not lp and r['status'] == 'time_limit' and r.get('solution_count') == 0 and r.get('objective') is None,
                        f'{i}/{arm} unsupported no-incumbent outcome')
            if lp:
                require(w['accepted_common_family_lp'] is True and w['full_family_gap'] <= w['common_quality_absolute_gap_limit'] + 1e-12,
                        f'{i}/{arm} LP quality')
            require(w['phase1_infeasibility_evidence'] is False and w['native_infeasible_claim_only'] is False, f'{i}/{arm} infeasibility flag')
            cg = r.get('cg') or {}
            cert = w['phase2']['certificate'] if arm.startswith('cg') else w.get('full_family_certificate')
            row = {
                'block': i, 'case': b['case_name'], 'physical_case': spec['physical_case'], 'policy': spec['plug_policy'], 'arm': arm,
                'arm_position': b['arms'].index(arm), 'worker': rc['worker'], 'host': env['host'],
                'cpu_affinity': env['cpu_affinity'], 'started_utc': m['started_utc'],
                'ended_utc': (datetime.datetime.fromisoformat(m['started_utc'])
                              + datetime.timedelta(seconds=r['total_including_checks_seconds'])).isoformat(),
                'status': r['status'], 'native_status': r.get('native_status'), 'audit_passed': True,
                'accepted_incumbent': inc, 'accepted_common_family_lp': w['accepted_common_family_lp'],
                'objective': r.get('objective'), 'native_bound': r.get('bound'), 'native_bound_scope': r.get('bound_scope'),
                'native_gap': r.get('native_gap'), 'solution_count': r.get('solution_count'),
                'restricted_pool_bound': r.get('restricted_pool_bound'),
                'audit_global_lower_bound': w.get('global_economic_lower_bound'),
                'full_family_gap': w.get('full_family_gap'),
                'phase1_objective': (w.get('phase1') or {}).get('objective'),
                'phase1_infeasibility_evidence': w['phase1_infeasibility_evidence'],
                'phase2_rmp_objective': (w.get('phase2') or {}).get('objective'),
                'cg_status': cg.get('status'), 'cg_seconds': cg.get('elapsed_seconds'), 'cg_columns': cg.get('columns'),
                'cg_rmp_calls': len(cg.get('rmp_calls', [])) if cg else None,
                'solve_end_to_end_seconds': r['solve_end_to_end_seconds'],
                'peak_rss_bytes': r.get('process_peak_rss_at_stop_bytes'),
                'variables': r.get('variables'), 'constraints': r.get('constraints'),
                'occupancy': occupancy_stats(w['primal'], inst) if inc else None,
                'plug_prices': price_stats(cert, inst) if lp else None,
                'result_sha256': local['result.json'], 'audit_sha256': sha(ap), 'receipt_sha256': sha(rp),
            }
            group[arm] = row
            rows.append(row)
        # capacity policy check
        pol = group['cg_lp']['policy']
        n = inst['physical']['n_tasks']
        dep_idx = inst['plug_locations'].index(inst['physical']['depot'])
        exp = expected_caps(pol, n, len(inst['plug_locations']), dep_idx)
        if exp is None:
            require(all(c is None for row in inst['plug_capacities'] for c in row), f'block {i} unlimited caps')
        else:
            require(all(all(c == exp[j] for c in row) for j, row in enumerate(inst['plug_capacities'])), f'block {i} cap policy')
        cl, dl = group['cg_lp'], group['direct_lp']
        rel = abs(cl['objective'] - dl['objective']) / abs(dl['objective'])
        require(rel <= 1e-6, f'block {i} LP disagreement {rel}')
        blocks.append({
            'block': i, 'case': b['case_name'], 'physical_case': cl['physical_case'], 'policy': pol,
            'physical_sha256': inst['physical']['sha256'], 'n_tasks': n,
            'depot_plugs': None if exp is None else exp[dep_idx], 'nondepot_plugs': None if exp is None else next(c for j, c in enumerate(exp) if j != dep_idx),
            'lp_cg': cl['objective'], 'lp_direct': dl['objective'], 'lp_rel_diff': rel,
            'lp_lower_bound_max': max(cl['audit_global_lower_bound'], dl['audit_global_lower_bound']),
            'cg_lp_seconds': cl['solve_end_to_end_seconds'], 'direct_lp_seconds': dl['solve_end_to_end_seconds'],
            'direct_over_cg_time': dl['solve_end_to_end_seconds'] / cl['solve_end_to_end_seconds'],
            'occ_cg': cl['occupancy'], 'occ_direct': dl['occupancy'],
            'price_cg': cl['plug_prices'], 'price_direct': dl['plug_prices'],
            'cg_pool': {k: group['cg_pool_mip'][k] for k in ('status', 'objective', 'accepted_incumbent', 'restricted_pool_bound', 'cg_status', 'solve_end_to_end_seconds', 'phase2_rmp_objective', 'audit_global_lower_bound')},
            'direct_mip': {k: group['direct_mip'][k] for k in ('status', 'objective', 'accepted_incumbent', 'native_bound', 'native_gap', 'solve_end_to_end_seconds')},
        })
    # paired triplets on identical physical input
    by_case, mono_dev = {}, []
    for bl in blocks:
        by_case.setdefault(bl['physical_case'], []).append(bl)
    for case, trip in by_case.items():
        require([t['policy'] for t in trip] == ['unlimited', 'loose', 'tight'], f'{case} policy order')
        require(len({t['physical_sha256'] for t in trip}) == 1, f'{case} physical input differs across policies')
        base_lp = trip[0]['lp_direct']
        for t in trip:
            t['lp_increase_vs_unlimited_pct'] = 100 * (t['lp_direct'] - base_lp) / base_lp
            t['lp_increase_vs_unlimited_abs'] = t['lp_direct'] - base_lp
        z = [t['lp_direct'] for t in trip]
        require(z[0] <= z[1] * (1 + TOL) and z[1] <= z[2] * (1 + TOL), f'{case} LP monotonicity')
        for k in (0, 1):  # record any rounding-level decrease that the 1e-6 relative check tolerates
            if z[k + 1] < z[k]:
                mono_dev.append({'case': case, 'from_block': trip[k]['block'], 'to_block': trip[k + 1]['block'],
                                 'abs_decrease': z[k] - z[k + 1], 'rel_decrease': (z[k] - z[k + 1]) / z[k]})
    # wall-clock overlap between plug arms (manifest started_utc + result total_including_checks_seconds)
    win = [(datetime.datetime.fromisoformat(r['started_utc']), datetime.datetime.fromisoformat(r['ended_utc']), r) for r in rows]
    overlaps = []
    for a in range(len(win)):
        for c in range(a + 1, len(win)):
            (s1, e1, r1), (s2, e2, r2) = win[a], win[c]
            ov = (min(e1, e2) - max(s1, s2)).total_seconds()
            if ov > 0 and r1['block'] != r2['block']:
                overlaps.append({'arm_a': f"{r1['block']}/{r1['arm']}", 'arm_b': f"{r2['block']}/{r2['arm']}",
                                 'overlap_seconds': round(ov, 1), 'cores': [r1['cpu_affinity'], r2['cpu_affinity']]})
    require(len(rows) == 72, 'arm count')
    return {'arms': rows, 'blocks': blocks, 'plug_arm_overlaps': overlaps, 'lp_monotonicity_decreases': mono_dev,
            'hosts': sorted({r['host'] for r in rows}), 'counts': {
        'arms': len(rows), 'audits_passed': sum(r['audit_passed'] for r in rows),
        'accepted_incumbents': sum(r['accepted_incumbent'] for r in rows),
        'no_incumbent_arms': [f"{r['block']}/{r['arm']}" for r in rows if not r['accepted_incumbent']],
        'time_limit_arms': [f"{r['block']}/{r['arm']}" for r in rows if r['status'] == 'time_limit'],
        'cg_cap_exhausted_integer_arms': [f"{r['block']}" for r in rows if r['arm'] == 'cg_pool_mip' and r['cg_status'] == 'cg_budget_exhausted'],
        'phase1_infeasibility_evidence_any': any(r['phase1_infeasibility_evidence'] for r in rows),
        'cg_phase1_objectives_nonzero': [f"{r['block']}/{r['arm']}" for r in rows if r['arm'].startswith('cg') and r['phase1_objective'] != 0],
        'max_lp_rel_diff': max(b['lp_rel_diff'] for b in blocks),
        'cg_lp_faster_blocks': sum(b['direct_over_cg_time'] > 1 for b in blocks)}}


def fmt(v, d=2):
    return '—' if v is None else f'{v:,.{d}f}'


def table(x):
    L = ['| Blk | Input (n/L/step, draw) | Policy (nondepot/depot plugs) | LP value (direct) | CG−direct rel. diff | CG LP s | Direct LP s | Direct/CG | Binding rows CG / direct (depot) | Positive plug prices CG / direct | Peak occ. depot / nondepot (direct) | LP Δ vs unlimited | CG-pool MIP cost (status) | Direct MIP cost (status) |',
         '|---:|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---|---|']
    for b in x['blocks']:
        n, Lc, step, draw = b['case'].split('_')[1:5]
        inp = f"{n[1:]}/{Lc[1:]}/{step[1:].replace('p', '.')} kWh, {draw}"
        pol = b['policy'] if b['depot_plugs'] is None else f"{b['policy']} ({b['nondepot_plugs']}/{b['depot_plugs']})"
        oc, od, pc, pd = b['occ_cg'], b['occ_direct'], b['price_cg'], b['price_direct']
        bind = '—' if b['policy'] == 'unlimited' else f"{oc['binding_rows']} ({oc['binding_rows_depot']}) / {od['binding_rows']} ({od['binding_rows_depot']})"
        pr = '—' if b['policy'] == 'unlimited' else f"{pc['positive_price_rows']} / {pd['positive_price_rows']}"
        peak = f"{od['peak_depot']:.3g} / {od['peak_nondepot']:.3g}"
        cp, dm = b['cg_pool'], b['direct_mip']
        cps = f"{fmt(cp['objective'])} ({cp['status']}{', CG cap hit' if cp['cg_status'] == 'cg_budget_exhausted' else ''})"
        dms = f"{fmt(dm['objective'])} ({dm['status']}; bound {fmt(dm['native_bound'])})"
        L.append(f"| {b['block']} | {inp} | {pol} | {b['lp_direct']:.6f} | {b['lp_rel_diff']:.1e} | {b['cg_lp_seconds']:.1f} | {b['direct_lp_seconds']:.1f} | {b['direct_over_cg_time']:.2f} | {bind} | {pr} | {peak} | {'0.000%' if abs(b['lp_increase_vs_unlimited_pct']) < 1e-9 else format(b['lp_increase_vs_unlimited_pct'], '+.3f') + '%'} | {cps} | {dms} |")
    return '\n'.join(L) + '\n'


def main():
    x = collect()
    x['collector_sha256'] = sha(__file__)
    x['remote_evidence_rehash'] = 'raw/remote_evidence_rehash.json (read-only cluster sha256 of every evidence_sha256 file; 0 mismatches required)'
    rh = read(RAW / 'remote_evidence_rehash.json')
    require(len(rh) == 72 and not any(v['mismatched_or_missing'] for v in rh.values()), 'remote rehash mismatch')
    for r in x['arms']:
        require(rh[f"block_{r['block']}/{r['arm']}"]['result_sha256'] == r['result_sha256'], 'remote/local result.json differ')
    x['counts']['remote_evidence_files_rehashed'] = sum(v['files_checked'] for v in rh.values())
    (HERE / 'plug_results.json').write_text(json.dumps(x, indent=1, allow_nan=False) + '\n')
    cols = ['block', 'case', 'policy', 'arm', 'arm_position', 'status', 'native_status', 'audit_passed', 'accepted_incumbent',
            'accepted_common_family_lp', 'objective', 'native_bound', 'native_gap', 'restricted_pool_bound', 'audit_global_lower_bound',
            'full_family_gap', 'phase1_objective', 'phase2_rmp_objective', 'cg_status', 'cg_seconds', 'cg_columns',
            'solve_end_to_end_seconds', 'peak_rss_bytes', 'solution_count', 'worker']
    with (HERE / 'plug_arms.csv').open('w', newline='') as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows({k: r[k] for k in cols} for r in x['arms'])
    (HERE / 'plug_table.md').write_text(table(x))
    print(json.dumps(x['counts'], indent=1))


if __name__ == '__main__':
    main()
