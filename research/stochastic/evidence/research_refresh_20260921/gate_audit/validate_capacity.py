#!/usr/bin/env python3
"""Validate a downloaded capacity-wave16 campaign without solving or modifying it.

Example:
 .venv/bin/python research_refresh_20260921/gate_audit/validate_capacity.py \
   --campaign snapshots/capacity_gate_wave16/campaigns/capacity_gate_wave16 \
   --output snapshots/capacity_gate_wave16/validation

The source/input closure is checked against --root (default: this research root).
Exit 0 means valid complete OR explicitly incomplete; exit 2 means invalid evidence.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
import numpy as np

ROOT_DEFAULT = Path(__file__).resolve().parents[2]
SHA_FIELDS = ('previous', 'hash', 'seconds')
OUTCOMES = ('fixed_shortage', 'fixed_cost', 'fixed_operating', 'adaptive_shortage',
            'adaptive_cost', 'adaptive_operating', 'adaptive_generation',
            'adaptive_truck_charge', 'adaptive_truck_discharge',
            'adaptive_bess_charge', 'adaptive_bess_discharge')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def close(a, b, tol):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (bool, str)) or isinstance(b, (bool, str)):
        return a == b
    return np.isfinite(a) and np.isfinite(b) and abs(a - b) <= tol


def summary(events):
    both = [e for e in events if e['fixed_cost'] is not None and e['adaptive_cost'] is not None]
    ans = {'days': len(events), 'jointly_feasible_days': len(both)}
    for side in ('fixed', 'adaptive'):
        shortage = [e[side + '_shortage'] for e in events]
        costs = [e[side + '_cost'] for e in events]
        ans[side + '_failures'] = sum(v > 1e-6 for v in shortage)
        ans[side + '_mean_shortage'] = float(np.mean(shortage))
        ans[side + '_mean_cost_all'] = float(np.mean(costs)) if all(v is not None for v in costs) else None
        ans[side + '_mean_cost_joint'] = float(np.mean([e[side + '_cost'] for e in both])) if both else None
    ans['mean_saving_joint'] = float(np.mean([e['fixed_cost'] - e['adaptive_cost'] for e in both])) if both else None
    return ans


def paired_stats(events, resamples, block, seed):
    n = len(events)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, (resamples, int(np.ceil(n / block))))
    ix = ((starts[:, :, None] + np.arange(block)) % n).reshape(resamples, -1)[:, :n]
    fs = np.array([e['fixed_shortage'] for e in events])
    ads = np.array([e['adaptive_shortage'] for e in events])
    diff = np.array([e['fixed_cost'] - e['adaptive_cost'] if e['fixed_cost'] is not None and e['adaptive_cost'] is not None else np.nan for e in events])
    valid = np.isfinite(diff)
    draws = diff[ix]
    den = np.isfinite(draws).sum(axis=1)
    conditional = np.divide(np.nansum(draws, axis=1), den, out=np.full(resamples, np.nan), where=den > 0)
    def ci(v):
        finite = v[np.isfinite(v)]
        return np.quantile(finite, [.025, .975]).tolist() if len(finite) else None
    s = summary(events)
    return dict(**s, saving_pct_joint=(100 * s['mean_saving_joint'] / s['fixed_mean_cost_joint']) if valid.any() and s['fixed_mean_cost_joint'] else None,
                saving_ci_calendar_blocks=ci(conditional), bootstrap_replicates_without_joint_days=int((den == 0).sum()),
                mean_shortage_reduction=float((fs - ads).mean()), shortage_reduction_ci=ci((fs - ads)[ix].mean(axis=1)),
                failed_day_rate_reduction=float(((fs > 1e-6).astype(float) - (ads > 1e-6)).mean()),
                failed_day_rate_reduction_ci=ci(((fs > 1e-6).astype(float) - (ads > 1e-6))[ix].mean(axis=1)))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--campaign', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--root', type=Path, default=ROOT_DEFAULT)
    p.add_argument('--wave15', type=Path, default=None)
    p.add_argument('--tol', type=float, default=1e-5)
    p.add_argument('--bootstrap', type=int, default=2000)
    p.add_argument('--block', type=int, default=14)
    p.add_argument('--seed', type=int, default=7291)
    a = p.parse_args()
    if a.output.resolve() == a.campaign.resolve():
        p.error('--output must differ from the read-only campaign directory')
    root, camp = a.root.resolve(), a.campaign.resolve()
    old = a.wave15 or root / 'snapshots/gate_wave15_validation/campaigns/gate_oracle_wave15'
    errors, warnings = [], []
    def check(ok, message):
        if not ok:
            errors.append(message)
        return bool(ok)
    result = dict(campaign=str(camp), state='incomplete', errors=errors, warnings=warnings,
                  bootstrap=dict(replicates=a.bootstrap, block_calendar_days=a.block, seed=a.seed,
                                 scope='Descriptive paired circular blocks; retain all dates, condition costs inside each replicate'),
                  scope='Fixed reconstructed routes and assets within pairs; both full-day foresight; empty-cyclic BESS; 2022 development; no investment or causal optimum')
    tasks, manifest, dates = [], {}, []
    try:
        tasks, manifest = read(camp / 'cases.json'), read(camp / 'manifest.json')
        check(sha(camp / 'cases.json') == manifest['cases_sha256'], 'case-list hash mismatch')
        for name, expected in manifest['files'].items():
            path = root / name
            if name.startswith('campaigns/capacity_gate_wave16/'):
                path = camp / Path(name).name
            check(path.exists() and sha(path) == expected, 'source/input hash mismatch or missing: ' + name)
        with open(root / 'releases/method_union_v8/reference/data/ghi_2022_socal.csv') as f:
            dates = [row[0] for row in csv.reader(f) if row and row[0] != 'date' and not row[0].startswith('#')]
        check(len(dates) == 365 and len(set(dates)) == 365, '2022 source dates are not 365 unique days')
        expected_grid = {(i, n) for i in (10, 11, 14, 17) for n in (0, 1, 2, 5, 10, 20)}
        check(len(tasks) == 24 and {(t['policy'], t['bess_units']) for t in tasks} == expected_grid, 'case grid is not the registered 24 pairs')
        check(all(t['source_campaign'] == 'weather_fair_policy_wave7' and t['cap_factor'] == .8 for t in tasks), 'case source/cap differs from registered design')
    except Exception as ex:
        errors.append('cannot validate registration/input closure: ' + repr(ex))
    result['manifest_sha256'] = sha(camp / 'manifest.json') if (camp / 'manifest.json').exists() else None
    events_by_case, rows = {}, []
    result['cases'] = rows
    for i, task in enumerate(tasks):
        out = camp / 'cases' / f'{i:04d}'
        row = dict(case=i, policy=task['policy'], bess_units=task['bess_units'], state='missing', days=0)
        rows.append(row)
        if not out.exists():
            continue
        if not (out / 'identity.json').exists():
            if (out / 'days.jsonl').exists() and (out / 'days.jsonl').stat().st_size:
                errors.append(f'case {i}: journal exists without its run identity')
                row['state'] = 'invalid'
            else:
                row['state'] = 'incomplete'
                warnings.append(f'case {i}: directory exists but initialization is not yet recorded')
            continue
        try:
            ident = read(out / 'identity.json')
            check(ident['task'] == task, f'case {i}: task identity mismatch')
            check(ident['manifest_sha256'] == result['manifest_sha256'], f'case {i}: manifest identity mismatch')
            source = root / 'campaigns' / task['source_campaign'] / 'cases' / f"{task['policy']:04d}"
            for name, field in (('pool.json', 'pool_sha256'), ('mip_result.json', 'mip_sha256')):
                check(sha(source / name) == ident['source'][field], f'case {i}: source {field} mismatch')
            physics = ident['physics']
            check(physics['eta'] == 0 and physics['G'] == 7 and physics['rho'] == 1.75 and close(physics['cap'], 11.2, a.tol), f'case {i}: physics outside registered scope')
            pool, mip = read(source / 'pool.json'), read(source / 'mip_result.json')
            weights = np.rint(np.array(mip['shared'][:-2]))
            selected = [(col, float(x)) for col, x in zip(pool['columns'], weights) if x > 0]
            check(len(selected) == len(ident['skeletons']), f'case {i}: selected skeleton count mismatch')
            coverage = None
            for k, (sk, (col, x)) in enumerate(zip(ident['skeletons'], selected)):
                e, wd, conn = np.array(sk['profile']), np.array(sk['withdraw']), np.array(sk['connected'], dtype=bool)
                check(sk['profile'] == col['e'] and sk['incidence'] == col['a'] and sk['multiplicity'] == x, f'case {i} truck {k}: source column mismatch')
                check(e.shape == wd.shape == conn.shape == (48,), f'case {i} truck {k}: wrong temporal dimensions')
                check(bool(np.all(conn[np.abs(e) > 1e-9])) and np.all(wd >= -a.tol) and np.max(np.abs(e)) <= physics['rho'] + a.tol, f'case {i} truck {k}: profile outside connection/rate/traction bounds')
                soc = physics['G'] + np.cumsum(e - wd)
                check(soc.min() >= -a.tol and soc.max() <= physics['G'] + a.tol and close(soc[-1], physics['G'], a.tol), f'case {i} truck {k}: pinned SoC replay failed')
                coverage = np.array(sk['incidence']) * x if coverage is None else coverage + np.array(sk['incidence']) * x
            check(coverage is not None and np.max(np.abs(coverage - 1)) < a.tol, f'case {i}: task coverage failed')
            events, previous = [], '0' * 64
            if (out / 'days.jsonl').exists():
                for line in (out / 'days.jsonl').read_text().splitlines():
                    e = json.loads(line)
                    h = e.pop('hash')
                    check(e['previous'] == previous and e['sequence'] == len(events) and digest(e) == h, f'case {i} day {len(events)}: broken journal')
                    e['hash'] = h
                    events.append(e)
                    previous = h
            check([e['date'] for e in events] == dates[:len(events)] and len(events) <= len(dates), f'case {i}: dates mismatch')
            events_by_case[i] = events
            row.update(days=len(events), state='incomplete', identity_sha256=digest(ident), journal_hash=previous)
            for d, e in enumerate(events):
                check(all(key in e for key in OUTCOMES), f'case {i} day {d}: missing outcome')
                for side in ('fixed', 'adaptive'):
                    short = e[side + '_shortage']
                    check(np.isfinite(short) and short >= -a.tol and (e[side + '_cost'] is None) == (short > 1e-6), f'case {i} day {d}: inconsistent shortage/cost semantics')
                check(e['adaptive_shortage'] <= e['fixed_shortage'] + a.tol, f'case {i} day {d}: adaptive shortage exceeds fixed')
                if e['fixed_cost'] is not None:
                    check(e['adaptive_cost'] is not None and e['adaptive_cost'] <= e['fixed_cost'] + a.tol, f'case {i} day {d}: adaptive cost exceeds fixed')
                if d < 3 or d % 90 == 0:
                    check('pinned_shortage' in e and close(e.get('pinned_shortage'), e['fixed_shortage'], a.tol), f'case {i} day {d}: missing/bad pinned shortage')
                    if e['fixed_cost'] is not None:
                        check(close(e.get('pinned_cost'), e['fixed_cost'], a.tol), f'case {i} day {d}: pinned cost mismatch')
            st = read(out / 'status.json') if (out / 'status.json').exists() else None
            if st:
                count = st['days']
                check(st['identity_sha256'] == digest(ident), f'case {i}: status identity mismatch')
                check(0 <= count <= len(events), f'case {i}: status ahead of journal')
                if 0 <= count <= len(events):
                    check(st['journal_hash'] == (events[count - 1]['hash'] if count else '0' * 64), f'case {i}: status digest mismatch')
                row['reported_state'] = st['state']
                if st['state'] == 'complete':
                    check(len(events) == len(dates) == st['days'] == 365, f'case {i}: incomplete day count labeled complete')
                    for key, val in summary(events).items():
                        check(key in st and close(st.get(key), val, a.tol), f'case {i}: summary mismatch {key}')
                    if len(events) == 365:
                        row.update(state='complete', statistics=paired_stats(events, a.bootstrap, a.block, a.seed))
            else:
                warnings.append(f'case {i}: no status file yet')
        except Exception as ex:
            errors.append(f'case {i}: unreadable/invalid evidence: {ex!r}')
            row['state'] = 'invalid'
    # Reproduce the Nb=0 reference for every available date, not just a mean.
    zero_compared, nesting_compared = 0, 0
    try:
        old_tasks = read(old / 'cases.json')
        for i, task in enumerate(tasks):
            if task['bess_units'] != 0 or not events_by_case.get(i):
                continue
            matches = [j for j, t in enumerate(old_tasks) if t['policy'] == task['policy'] and t.get('year', 2022) == 2022 and t['cap_factor'] == .8]
            if not check(len(matches) == 1, f'case {i}: wave15 reference ambiguous/missing'):
                continue
            reference = [json.loads(line) for line in (old / 'cases' / f'{matches[0]:04d}' / 'days.jsonl').read_text().splitlines()]
            for d, e in enumerate(events_by_case[i]):
                ref = reference[d]
                check(e['date'] == ref['date'] and e['sequence'] == ref['sequence'], f'case {i} day {d}: wave15 date/sequence mismatch')
                for field in set(ref).difference(SHA_FIELDS + ('date', 'sequence')):
                    check(field in e and close(e.get(field), ref[field], a.tol), f'case {i} day {d}: Nb0 != wave15 in {field}')
                zero_compared += 1
    except Exception as ex:
        errors.append('cannot compare wave15 reference: ' + repr(ex))
    groups = defaultdict(list)
    for i, task in enumerate(tasks):
        groups[task['policy']].append((task['bess_units'], i))
    for policy, members in groups.items():
        members.sort()
        for (na, ia), (nb, ib) in zip(members, members[1:]):
            for d, (ea, eb) in enumerate(zip(events_by_case.get(ia, []), events_by_case.get(ib, []))):
                check(ea['date'] == eb['date'], f'policy {policy} capacities {na}/{nb}: unpaired dates')
                for side in ('fixed', 'adaptive'):
                    ua, ub = ea[side + '_shortage'], eb[side + '_shortage']
                    check(ub <= ua + a.tol, f'policy {policy} day {d} {side}: shortage worsens Nb{na}->{nb}')
                    if abs(ub - ua) <= 1e-6:
                        check(eb[side + '_operating'] <= ea[side + '_operating'] + a.tol, f'policy {policy} day {d} {side}: operating cost worsens at tied shortage Nb{na}->{nb}')
                nesting_compared += 1
    complete = sum(r['state'] == 'complete' for r in rows)
    result.update(complete_cases=complete, total_cases=len(tasks), observed_days=sum(r['days'] for r in rows),
                  nb0_reference_days_compared=zero_compared, adjacent_capacity_day_pairs_compared=nesting_compared)
    result['state'] = 'invalid' if errors else ('validated_complete' if complete == len(tasks) == 24 else 'incomplete')
    lines = ['# Capacity gate wave 16 validation', '', f"Status: **{result['state']}**. {complete}/{len(tasks)} cases complete; {result['observed_days']} daily records inspected.", '', result['scope'] + '.', '']
    if errors:
        lines += ['Scientific conclusions are withheld because validation failed.', ''] + ['- ' + e for e in errors[:40]]
        if len(errors) > 40:
            lines += [f'- {len(errors)-40} additional errors are in validation.json.']
    elif result['state'] == 'incomplete':
        lines += ['The campaign is incomplete. Partial journals passed the checks applicable to available records; there is no completed scientific result yet.', '', 'Pending cases: ' + ', '.join(str(r['case']) for r in rows if r['state'] != 'complete') + '.']
    else:
        lines += [f"All source/identity/journal/summary checks passed. Nb=0 matches wave 15 on {zero_compared} days; minimum-shortage and tied-shortage operating-cost nesting passed for {nesting_compared} adjacent-capacity day pairs.", '',
                  '| Policy | Nb | Fixed/adaptive failures | Joint days | Saving/day [95% calendar-block interval] | Saving % | Fixed/adaptive all-day costs |',
                  '|---|---:|---:|---:|---|---:|---|']
        def fmt(v):
            return '—' if v is None else f'{v:,.2f}'
        for row in rows:
            s = row['statistics']; ci = s['saving_ci_calendar_blocks']
            interval = '—' if ci is None else f'[{ci[0]:.2f}, {ci[1]:.2f}]'
            lines.append(f"| {row['policy']} | {row['bess_units']} | {s['fixed_failures']}/{s['adaptive_failures']} | {s['jointly_feasible_days']} | {fmt(s['mean_saving_joint'])} {interval} | {fmt(s['saving_pct_joint'])} | {fmt(s['fixed_mean_cost_all'])} / {fmt(s['adaptive_mean_cost_all'])} |")
        lines += ['', 'Costs are conditional on the stated joint support unless all-day costs are shown. Intervals resample calendar dates before conditioning, using 14-day circular blocks and 2,000 replicates by default. Policies share the same development weather; seeds are not independent test populations. This does not establish causal gains, an optimal investment frontier or original-route recovery. The gap between fixed and adaptive optima need not be monotone in capacity.']
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'validation.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (a.output / 'RESULTS.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({k: result[k] for k in ('state', 'complete_cases', 'total_cases', 'observed_days', 'nb0_reference_days_compared', 'adjacent_capacity_day_pairs_compared')}, indent=2))
    if errors:
        print('\n'.join(errors[:10]), file=sys.stderr)
    return 2 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
