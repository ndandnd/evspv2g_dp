"""Addendum, 18 Oct 2026: table-level checks for the four 160- and 200-location inputs (8 runs), run locally.

Same rules as aggregate.py; the functions below are copied from it unchanged (only the inputs differ):
validated objectives only, CG bound counts only if the Lagrangian certificate from the stopping duals
reaches it, LB* = max(certified CG bound, Gurobi bound > 0), gap = 100 (U - LB*) / U.
Rows in the collector schema (output/opte-map-extension-20261017/grid_rows.json) are rebuilt from validated
values and compared field by field; that folder's make_tables.py (byte-identical to the grid study's) is rerun
on the rebuilt rows and its LaTeX is diffed with table8_rows.tex. Writes validation_summary_mapx.json and
cg_bound_certificates_mapx.json; does not touch the files of the main 548-run validation.
"""
import json, glob, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
X = Path('/Users/nadan/Documents/projects/v2g/output/opte-map-extension-20261017')
MANUSCRIPT = Path('/Users/nadan/Documents/projects/v2g/output/opte-revision-v2-20261016/build/blue_manuscript.tex')
REL = 1e-9
rep = {}
for p in sorted(glob.glob(str(HERE / 'results/mapx/*.json'))):
    d = json.load(open(p)); rep[d['case']] = d
nh = {}
for p in sorted(glob.glob(str(HERE / 'results_nohints/mapx/*.json'))):
    d = json.load(open(p)); nh[d['case']] = d
issues = []
def note(table, case, msg):
    issues.append({'table': table, 'case': case, 'issue': msg})


# ---- copied unchanged from aggregate.py ------------------------------------------------------------
def cg_values(case, label='cg1800'):
    d = rep.get(case); a = (d or {}).get('arms', {}).get(label)
    if a is None: return None
    out = {'passed': a.get('passed'), 'U': a.get('validated_objective') if a.get('passed') else None,
           'rep_lb': a.get('reported_full_family_bound'), 'failure': a.get('failure')}
    dc = a.get('dual_certificate') or {}
    out['dual'] = dc
    return out


def umin(case):
    d = rep[case]; us = []
    for a in d['arms'].values():
        if not a.get('passed'): continue
        if a['kind'] == 'cg' and a.get('validated_objective') is not None: us.append(a['validated_objective'])
        if a['kind'] == 'direct':
            us += [v['reported_objective'] for v in a.get('vectors', {}).values() if v.get('validated')]
    return min(us) if us else None


def cg_lb(case, label='cg1800'):
    """(bound used, certificate value, certified?)"""
    v = cg_values(case, label)
    if v is None or not v['dual'].get('available'): return (v or {}).get('rep_lb'), None, False
    d = rep[case]; U = umin(case)
    cert = v['dual']['bound_before_battery_term'] + (U / d['c_b']) * min(0.0, v['dual']['battery_reduced_cost'])
    r = v['rep_lb']
    if r is None: return None, cert, False
    ok = cert >= r - 1e-7 * max(1.0, abs(r))
    return (r if ok else cert), cert, ok


def direct(case, label='direct'):
    d = rep.get(case); a = (d or {}).get('arms', {}).get(label)
    if a is None or not a.get('passed'): return None
    return a


def reading(a, T):
    r = (a.get('readings') or {}).get(str(int(T)))
    if not r or r.get('objective') is None: return None, None
    if not r.get('validated'): return 'invalid', None
    return r['objective'], bool(r.get('is_one_truck_per_task_schedule'))


def gap(U, LB, clip=True):
    if U is None or LB is None or U == 'invalid': return None
    g = 100 * (U - LB) / U
    return max(0.0, g) if clip else g


def close(a, b, kind):
    if a is None or b is None: return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool): return a == b
    if kind == 'gap': return abs(a - b) <= 1e-6
    return abs(a - b) <= REL * max(1.0, abs(a), abs(b))


def compare(table, old, new, fields):
    diffs = []
    for f, kind in fields:
        if not close(old.get(f), new.get(f), kind):
            diffs.append((f, old.get(f), new.get(f)))
    if diffs: note(table, old['case'], f'field differences {diffs}')
    return not diffs


def rows_grid_like(table, src_rows):
    new_rows = []; ok = 0
    for r in src_rows:
        c = r['case']; n = dict(r)
        if c not in rep: note(table, c, 'no validation report'); new_rows.append(n); continue
        cg = cg_values(c); a = direct(c)
        lb_cg = cg_lb(c)[0]
        n['pool_U'] = cg['U'] if cg and cg['passed'] else None
        if cg and not cg['passed']: note(table, c, f"cg arm not validated: {cg['failure']}")
        if a is None: note(table, c, 'direct arm not validated');
        U, start = reading(a, 1800) if a else (None, None)
        if U == 'invalid': note(table, c, 'direct 1,800-s incumbent failed validation'); U = None
        n['d_U'] = U; n['d_initial'] = bool(start) if U is not None else False
        n['d_bound'] = a.get('reported_bound') if a else None
        lbs = [x for x in (lb_cg, n['d_bound']) if x is not None and x > 0]
        n['LB'] = max(lbs) if lbs else None
        n['gap_cg'] = gap(n['pool_U'], n['LB']); n['gap_d'] = gap(n['d_U'], n['LB'])
        if r.get('d_opt_by_T') and not (a and a.get('status') == 'optimal'): note(table, c, 'optimal-by-1800 claim without optimal status')
        ok += compare(table, r, n, [('pool_U', 'v'), ('d_U', 'v'), ('d_bound', 'v'), ('LB', 'v'), ('gap_cg', 'gap'), ('gap_d', 'gap'), ('d_initial', 'b')])
        new_rows.append(n)
    return new_rows, ok


def rerun(script_dir, script, rows_name, rows, outputs, extra_links=()):
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(script_dir / script, tmp)
        json.dump(rows, open(f'{tmp}/{rows_name}', 'w'), indent=1)
        for src, dst in extra_links: os.symlink(src, f'{tmp}/{dst}')
        r = subprocess.run([sys.executable, script], cwd=tmp, capture_output=True, text=True)
        if r.returncode:
            note(script, '-', 'generator failed on rebuilt rows: ' + r.stderr.strip().split('\n')[-1])
            return {o: '' for o in outputs}
        return {o: open(f'{tmp}/{o}').read() for o in outputs}


def diff_lines(table, new_text, old_text):
    a, b = old_text.strip().split('\n'), new_text.strip().split('\n')
    bad = [(x, y) for x, y in zip(a, b) if x.strip() != y.strip()]
    if len(a) != len(b): bad.append((f'{len(a)} lines', f'{len(b)} lines'))
    for x, y in bad: note(table, '-', f'printed row differs from row rebuilt from validated values: printed [{x}] rebuilt [{y}]')
    return {'rows': len(a), 'rows_identical': len(a) - len(bad), 'differing': len(bad)}
# ------------------------------------------------------------------------------------------------------


src = json.load(open(X / 'grid_rows.json'))
CASES = [r['case'] for r in src]
for c in CASES:
    if c not in rep: note('mapx', c, 'no validation report')
new, ok = rows_grid_like('Map extension (Section 8.2)', src)
texts = rerun(X, 'make_tables.py', 'grid_rows.json', new, ['table8_rows.tex'])
tex = diff_lines('Map extension rows', texts['table8_rows.tex'], open(X / 'table8_rows.tex').read())

# Bound consistency (as check_bounds in aggregate.py): no Gurobi or CG bound above a validated cost
for c in CASES:
    d = rep.get(c)
    if not d: continue
    U = umin(c)
    for label, a in d['arms'].items():
        if a['kind'] == 'direct' and a.get('passed') and a.get('reported_bound') is not None and a['reported_bound'] > U + 1e-6 * max(1, abs(U)):
            note('bounds', c, f'{label} ObjBound above a validated cost')
    lb, cert, okc = cg_lb(c)
    if lb is not None and lb > U + 1e-6 * max(1, abs(U)): note('bounds', c, 'CG bound above a validated cost')

per_run = []; certs = []
for r_old, r_new in zip(src, new):
    c = r_old['case']; d = rep.get(c)
    if d is None: continue
    g = d['graph']
    for label, a in d['arms'].items():
        row = {'case': c, 'arm': label, 'kind': a['kind'], 'passed': a.get('passed'), 'failure': a.get('failure'),
               'instance_sha256': d['instance_sha256'], 'input_checks': a.get('input_checks'),
               'runtime_files_differing': (a.get('code_checks') or {}).get('runtime_files_differing'),
               'vendor_files_differing': (a.get('code_checks') or {}).get('vendor_files_differing'),
               'rebuilt_graph': [g['nodes'], g['arcs']], 'runner_graph': a.get('runner_graph'),
               'graph_match': list(a.get('runner_graph') or []) == [g['nodes'], g['arcs']]}
        if a['kind'] == 'cg' and a.get('passed'):
            lb, cert, okc = cg_lb(c)
            dc = a['dual_certificate']
            row.update(selected_routes=a['selected_routes'], route_realization=a['route_realization'],
                       transitions_replayed=a['transitions_replayed'], max_residual=a['max_residual'],
                       reported_objective=a['reported_objective'], recomputed_objective=a['recomputed_objective'],
                       objective_abs_diff=a['objective_abs_diff'], battery_count=a['battery_count'],
                       vendor_master_not_above=a['vendor_master_check']['not_above_reported'],
                       vendor_master_objective=a['vendor_master_check']['objective'],
                       cg_priced_out=a['cg_priced_out'], final_pricing_call_empty=a['final_pricing_call_empty'],
                       reported_cg_bound=a['reported_full_family_bound'], certificate=cert, certified=okc,
                       certificate_minus_reported=None if cert is None else cert - a['reported_full_family_bound'],
                       rc_min=dc['rc_min'], rc_min_graph=dc['rc_min_graph'], rc_min_singletons=dc['rc_min_singletons'],
                       battery_reduced_cost=dc['battery_reduced_cost'], mu_clipped_max=dc['mu_clipped_max'],
                       gap_restricted_mip_recomputed=r_new['gap_cg'], gap_restricted_mip_collector=r_old['gap_cg'])
            n_ = nh.get(c, {}).get('arms', {}).get(label)
            row['nohints'] = None if n_ is None else {
                'passed': n_.get('passed'), 'failure': n_.get('failure'), 'route_realization': n_.get('route_realization'),
                'same_objective': n_.get('recomputed_objective') == a['recomputed_objective'],
                'same_certificate': (n_.get('dual_certificate') or {}).get('rc_min') == dc['rc_min'],
                'max_residual': n_.get('max_residual'), 'forbidden_modules_loaded': nh[c].get('forbidden_modules_loaded')}
            if row['nohints'] is None: note('nohints', c, 'no witness-free report')
            elif not row['nohints']['passed']: note('nohints', c, f"witness-free pass failed: {row['nohints']['failure']}")
            certs.append({'case': c, 'arm': label, 'reported_bound': a['reported_full_family_bound'], 'certificate': cert,
                          'rc_min': dc['rc_min'], 'battery_reduced_cost': dc['battery_reduced_cost'], 'certified': okc})
            if not okc: note('CG bound', c, f'certificate {cert} below reported bound {a["reported_full_family_bound"]}')
        elif a['kind'] == 'direct' and a.get('passed'):
            vs = a['vectors']; rd = a['readings']['1800']
            row.update(unpruned_rebuilt=[g['unpruned_states'], g['unpruned_arcs']], status=a['status'], reported_bound=a['reported_bound'],
                       vectors={k: {'validated': v['validated'], 'failure': v.get('failure'), 'max_residual': v.get('max_residual'),
                                    'reported_objective': v['reported_objective'], 'recomputed_objective': v.get('recomputed_objective'),
                                    'objective_abs_diff': v.get('objective_abs_diff'), 'routes': v.get('routes'),
                                    'dag_routes': v.get('dag_routes'), 'singleton_routes': v.get('singleton_routes'),
                                    'one_truck_per_task_singletons': v.get('one_truck_per_task_singletons'),
                                    'vendor_master_not_above': (v.get('vendor_master_check') or {}).get('not_above_reported')}
                                for k, v in vs.items()},
                       reading_1800=rd, gap_direct_recomputed=r_new['gap_d'], gap_direct_collector=r_old['gap_d'])
            for k, v in vs.items():
                if not v['validated']: note('direct', c, f'{k}: {v.get("failure")}')
        if not a.get('passed'): note('arms', c, f'{label}: {a.get("failure")}')
        per_run.append(row)

def ms_bracket():
    t = MANUSCRIPT.read_text(); i = t.find('At 160 and 200 locations')
    return t[i:t.find('\n', i)] if i >= 0 else None
gc = [r['gap_cg'] for r in new if r.get('gap_cg') is not None]; gd = [r['gap_d'] for r in new if r.get('gap_d') is not None]
summary = {
    'scope': '4 inputs (160 and 200 locations, two samples each), 8 runs: 4 CG + route-MIP, 4 direct MIP (1,800-s limit)',
    'inputs_with_reports': len([c for c in CASES if c in rep]), 'inputs_with_nohints_reports': len([c for c in CASES if c in nh]),
    'runs_passed': {'cg': sum(1 for r in per_run if r['kind'] == 'cg' and r['passed']),
                    'direct': sum(1 for r in per_run if r['kind'] == 'direct' and r['passed'])},
    'direct_vectors_validated': [sum(v['validated'] for r in per_run if r['kind'] == 'direct' for v in r.get('vectors', {}).values()),
                                 sum(len(r.get('vectors', {})) for r in per_run if r['kind'] == 'direct')],
    'cg_certificates_reaching_reported_bound': [sum(x['certified'] for x in certs), len(certs)],
    'rows_matching_collector': [ok, len(src)], 'printed_rows_reproduced': tex,
    'restricted_mip_gap_range_recomputed': [min(gc), max(gc)] if gc else None,
    'direct_gap_range_recomputed': [min(gd), max(gd)] if gd else None,
    'manuscript_sentence_l1187': ms_bracket(),
    'forbidden_modules_loaded': sorted({m for d in list(rep.values()) + list(nh.values()) for m in d.get('forbidden_modules_loaded', [])}),
    'validator_sha256': sorted({d.get('validator_sha256') for d in list(rep.values()) + list(nh.values())}),
    'per_run': per_run, 'issues': issues}
json.dump(summary, open(HERE / 'validation_summary_mapx.json', 'w'), indent=1, default=str)
json.dump(certs, open(HERE / 'cg_bound_certificates_mapx.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in summary.items() if k not in ('per_run', 'issues')}, indent=1, default=str))
for r in per_run:
    if r['kind'] == 'cg' and r['passed']:
        print(f"{r['case']} {r['arm']}: graph {r['graph_match']} routes {r['selected_routes']} {r['route_realization']} resid {r['max_residual']:.2e} "
              f"U {r['recomputed_objective']:.4f} vs {r['reported_objective']:.4f} (diff {r['objective_abs_diff']:.1e}) cert {r['certificate']:.6f} "
              f"vs {r['reported_cg_bound']:.6f} rc_min {r['rc_min']:.2e} gap {r['gap_restricted_mip_recomputed']:.4f} (collector {r['gap_restricted_mip_collector']:.4f}) "
              f"nohints {None if r['nohints'] is None else (r['nohints']['passed'], r['nohints']['route_realization'])}")
    elif r['kind'] == 'direct' and r['passed']:
        v = r['vectors']; rd = r['reading_1800']
        print(f"{r['case']} {r['arm']}: graph {r['graph_match']} unpruned {r['unpruned_rebuilt']} bound {r['reported_bound']} "
              f"vectors {[(k, x['validated'], x['max_residual'], x['recomputed_objective'], x['objective_abs_diff'], x['one_truck_per_task_singletons']) for k, x in v.items()]} "
              f"reading1800 t={rd.get('elapsed_seconds')} first={rd.get('is_first_incumbent')} start={rd.get('is_one_truck_per_task_schedule')} "
              f"gap {r['gap_direct_recomputed']:.4f} (collector {r['gap_direct_collector']:.4f})")
    else:
        print(r['case'], r['arm'], 'FAILED', r['failure'])
print(len(issues), 'issues'); [print(i) for i in issues]
