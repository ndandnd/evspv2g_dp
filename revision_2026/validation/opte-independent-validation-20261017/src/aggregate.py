"""Combine the per-input validation reports into table-level checks (run locally).

1. Validated values: an objective counts only if its saved vector passed the independent
   replay; a CG bound counts only if the independent Lagrangian certificate from the
   stopping duals reaches it (else the certificate value is used and flagged); Gurobi
   ObjBound values are solver evidence and are checked only for consistency
   (bound <= every validated cost; optimal status => bound within MIPGap of the cost).
2. Rows in each collector's schema are rebuilt from validated values and compared field by field.
3. The original table generators are rerun on the rebuilt rows in a scratch folder and their
   LaTeX output is diffed against the printed row files.
"""
import json, glob, os, re, shutil, subprocess, sys, tempfile, statistics as S
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
O = Path('/Users/nadan/Documents/projects/v2g/output')
G, TR, TS, EQ, R36 = O / 'opte-grid-results-20261016', O / 'opte-transition-results-20261017', O / 'opte-task-scaling-results-20261016', O / 'opte-equal-mip-results-20261016', O / 'opte-3600-results-20261017'
TEMPLATE = O / 'opte-revision-v2-20261016/build/blue_manuscript.template.tex'
REL = 1e-9
rep = {}
RES = Path(os.environ.get('IV_RESULTS', HERE / 'results'))
for p in sorted(glob.glob(str(RES / '*/*.json'))):
    d = json.load(open(p)); rep[d['case']] = d

issues = []          # every discrepancy or unvalidated item, with reason
def note(table, case, msg):
    issues.append({'table': table, 'case': case, 'issue': msg})


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


def final_U(a):
    v = (a.get('vectors') or {}).get('final_-1')
    return v['reported_objective'] if v and v.get('validated') else None


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


bound_checks = []
def check_bounds(case):
    d = rep[case]; U = umin(case)
    for label, a in d['arms'].items():
        if a['kind'] != 'direct' or not a.get('passed'): continue
        B = a.get('reported_bound')
        if B is not None and U is not None and B > U + 1e-6 * max(1, abs(U)):
            note('bounds', case, f'{label} ObjBound {B} exceeds a validated cost {U}')
        if a.get('status') == 'optimal':
            fU = final_U(a)
            ok = fU is not None and B is not None and abs(fU - B) <= max(1e-9, 1e-6 * abs(fU))
            if not ok: note('bounds', case, f'{label} optimal but final cost {fU} vs bound {B}')
            bound_checks.append(ok)
    for label in ('cg1800', 'cg3600'):
        if label in d['arms'] and d['arms'][label].get('passed'):
            lb, cert, ok = cg_lb(case, label)
            if lb is not None and U is not None and lb > U + 1e-6 * max(1, abs(U)):
                note('bounds', case, f'{label} CG bound {lb} exceeds a validated cost {U}')


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


def rows_tasks(src_rows):
    new_rows = []; ok = 0
    for r in src_rows:
        c = r['case']; n = dict(r)
        cg = cg_values(c); a = direct(c); lb_cg = cg_lb(c)[0]
        if cg and not cg['passed']: note('Table 19', c, f"cg arm not validated: {cg['failure']}")
        if a is None: note('Table 19', c, 'direct arm not validated')
        n['pool_U'] = cg['U'] if cg and cg['passed'] else None
        U, start = reading(a, 1800) if a else (None, None)
        if U == 'invalid': note('Table 19', c, 'direct 1,800-s incumbent failed validation'); U = None
        n['d_U1800'] = U; n['d_final_U'] = final_U(a) if a else None; n['d_bound'] = a.get('reported_bound') if a else None
        lbs = [x for x in (lb_cg, n['d_bound']) if x is not None]
        n['LB'] = max(lbs) if lbs else None
        n['gap_pool'] = gap(n['pool_U'], n['LB'], False); n['gap_d1800'] = gap(n['d_U1800'], n['LB'], False); n['gap_dfinal'] = gap(n['d_final_U'], n['LB'], False)
        n['d1800_is_fallback'] = bool(start) if U is not None else False
        ok += compare('Table 19', r, n, [('pool_U', 'v'), ('d_U1800', 'v'), ('d_final_U', 'v'), ('d_bound', 'v'), ('LB', 'v'), ('gap_pool', 'gap'),
                                         ('gap_d1800', 'gap'), ('gap_dfinal', 'gap'), ('d1800_is_fallback', 'b')])
        new_rows.append(n)
    return new_rows, ok


def rows_equal(src_rows):
    new_rows = []; ok = 0
    for r in src_rows:
        c = r['case']; n = dict(r)
        cg = cg_values(c); a = direct(c); lb_cg = cg_lb(c)[0]
        if cg and not cg['passed']: note('Table 20', c, f"cg arm not validated: {cg['failure']}")
        if a is None: note('Table 20', c, 'direct arm not validated')
        n['pool_U'] = cg['U'] if cg and cg['passed'] else None
        U, start = reading(a, 1800) if a else (None, None)
        if U == 'invalid': note('Table 20', c, 'direct 1,800-s incumbent failed validation'); U = None
        n['d_U1800'] = U; n['d_final_U'] = final_U(a) if a else None; n['d_final_B'] = a.get('reported_bound') if a else None
        lbs = [x for x in (lb_cg, n['d_final_B']) if x is not None]
        n['LBstar'] = max(lbs) if lbs else None
        cands = [x for x in (n['pool_U'], n['d_final_U'], n['d_U1800']) if x]
        n['BKS'] = min(cands) if cands else None
        n['_start1800'] = bool(start) if U is not None else None
        ok += compare('Table 20', r, n, [('pool_U', 'v'), ('d_U1800', 'v'), ('d_final_U', 'v'), ('d_final_B', 'v'), ('LBstar', 'v'), ('BKS', 'v')])
        new_rows.append(n)
    return new_rows, ok


def rows_3600(src_rows):
    new_rows = []; ok = 0
    for r in src_rows:
        c = r['case']; n = dict(r)
        if c not in rep: note('3,600 s', c, 'no validation report'); new_rows.append(n); continue
        c36, c18 = cg_values(c, 'cg3600'), cg_values(c)
        d18 = direct(c); d36 = direct(c, 'direct3600') if r['study'] == 'transition' else d18
        lbs = [cg_lb(c, 'cg3600')[0], cg_lb(c)[0], d18 and d18.get('reported_bound'), d36 and d36.get('reported_bound')]
        LB = max(x for x in lbs if x)
        u18, s18 = reading(d18, 1800); u36, s36 = reading(d36, 3600)
        for lab, v in (('cg3600', c36), ('cg1800', c18)):
            if not v or not v['passed']: note('3,600 s', c, f'{lab} not validated')
        n['cg18'] = gap(c18['U'], LB); n['cg36'] = gap(c36['U'], LB); n['d18'] = gap(u18, LB); n['d36'] = gap(u36, LB)
        n['start18'] = True if u18 is None else bool(s18); n['start36'] = True if u36 is None else bool(s36)
        ok += compare('3,600 s', r, n, [('cg18', 'gap'), ('cg36', 'gap'), ('d18', 'gap'), ('d36', 'gap'), ('start18', 'b'), ('start36', 'b')])
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


summary = {'inputs_with_reports': len(rep), 'tables': {}}
for c in rep: check_bounds(c)

# Tables 8, 21 and Figure 3 (grid series)
src = json.load(open(G / 'grid_rows.json'))
new, ok = rows_grid_like('Tables 8/21', src)
texts = rerun(G, 'make_tables.py', 'grid_rows.json', new, ['table8_rows.tex', 'table21_cg_rows.tex', 'table21_direct_rows.tex'])
summary['tables']['Table 8 and Table 21 (grid, 64 inputs)'] = {
    'inputs': len(src), 'rows_matching_collector': ok,
    'table8_tex': diff_lines('Table 8', texts['table8_rows.tex'], open(G / 'table8_rows.tex').read()),
    'table21_cg_tex': diff_lines('Table 21', texts['table21_cg_rows.tex'], open(G / 'table21_cg_rows.tex').read()),
    'table21_direct_tex': diff_lines('Table 21', texts['table21_direct_rows.tex'], open(G / 'table21_direct_rows.tex').read())}
grid_new = new
# Table 22 (transition)
src = json.load(open(TR / 'transition_rows.json'))
new, ok = rows_grid_like('Table 22', src); tr_new = new
texts = rerun(TR, 'make_transition_table.py', 'transition_rows.json', new, ['transition_rows.tex'])
summary['tables']['Table 22 and Figure 3 (transition, 108 inputs)'] = {
    'inputs': len(src), 'rows_matching_collector': ok,
    'table22_tex': diff_lines('Table 22', texts['transition_rows.tex'], open(TR / 'transition_rows.tex').read())}
# Table 19 (task scaling, EPYC 9654 cohort)
src = json.load(open(TS / 'v9654/task_scaling_rows.json'))
new, ok = rows_tasks(src); ts_new = new
texts = rerun(TS, 'make_main_table.py', 'task_scaling_rows.json', new, ['main_table_rows.tex'])
summary['tables']['Table 19 (tasks, 40 inputs)'] = {
    'inputs': len(src), 'rows_matching_collector': ok,
    'table19_tex': diff_lines('Table 19', texts['main_table_rows.tex'], open(TS / 'v9654/main_table_rows.tex').read())}
# Table 20 (equal MIP, 23 inputs)
src = json.load(open(EQ / 'prelim_rows.json'))
new, ok = rows_equal(src); eq_new = new
texts = rerun(EQ, 'make_appendix_table.py', 'prelim_rows.json', new, ['appendix_table_rows.tex'], [(EQ / 'raw', 'raw')])
tpl = open(TEMPLATE).read(); t0 = tpl.index('\\label{tab:equalmip}'); t1 = tpl.index('\\end{tabular}', t0)
printed = '\n'.join(l for l in tpl[t0:t1].split('\n') if ' & ' in l and '/' in l.split(' & ')[0])
gen = '\n'.join(l for l in texts['appendix_table_rows.tex'].split('\n') if ' & ' in l)
summary['tables']['Table 20 (equal MIP, 23 inputs)'] = {'inputs': len(src), 'rows_matching_collector': ok,
    'table20_tex': diff_lines('Table 20', gen, printed),
    'note': 'printed 4,000-task direct entry was edited by hand to <0.01 (TL); the generator prints 0.00'}
# 3,600 s
src = json.load(open(R36 / 'rows_3600.json'))
new, ok = rows_3600(src)
cells = {}
for r in new:
    k = (r['L'], r['n']); cells.setdefault(k, []).append(r)
summary['tables']['3,600-s runs (48 inputs)'] = {'inputs': len(src), 'rows_matching_collector': ok,
    'direct_has_better_than_start_at_3600_by_cell': {f'L{k[0]}_n{k[1]}': f"{sum(not r['start36'] for r in v)}/{len(v)}" for k, v in sorted(cells.items())}}

# Dependence of printed gaps on Gurobi bounds (solver evidence) versus the independently certified CG bound
def lb_dependence(table, rows, ukeys, lbkey, clip):
    src = {'cg_certified': 0, 'gurobi_objbound': 0, 'none': 0}; worst = 0.0; worst_case = None; no_cg = []
    for r in rows:
        c = r['case']
        if c not in rep: continue
        lb_cg, cert, ok = cg_lb(c)
        a = direct(c); B = a.get('reported_bound') if a else None
        LB = r.get(lbkey)
        if LB is None: src['none'] += 1; continue
        if lb_cg is not None and abs(LB - lb_cg) <= 1e-9 * max(1, abs(LB)) and ok: src['cg_certified'] += 1; continue
        src['gurobi_objbound'] += 1
        if lb_cg is None or not ok:
            no_cg.append(c); continue          # CG stopped before convergence: no certified LP bound to compare with
        alt = lb_cg
        for k in ukeys:
            U = r.get(k)
            if U is None or alt is None: continue
            d = gap(U, alt, clip) - gap(U, LB, clip)
            if d > worst: worst, worst_case = d, (c, k)
    return {'lower_bound_source': src, 'max_gap_increase_pp_if_only_certified_cg_bound_used': worst, 'at': worst_case,
            'rows_without_a_converged_cg_bound': no_cg}
summary['lower_bound_dependence'] = {
    'Tables 8/21': lb_dependence('Tables 8/21', grid_new, ('pool_U', 'd_U'), 'LB', True),
    'Table 22': lb_dependence('Table 22', tr_new, ('pool_U', 'd_U'), 'LB', True),
    'Table 19': lb_dependence('Table 19', ts_new, ('pool_U', 'd_U1800'), 'LB', False),
    'Table 20': lb_dependence('Table 20', eq_new, ('pool_U', 'd_U1800'), 'LBstar', True)}

# arm-level counts
arms = {'cg': [0, 0], 'direct_vectors': [0, 0], 'dual_certificates': [0, 0]}
maxres = {'cg': 0.0, 'direct': 0.0}; maxobj = {'cg': 0.0, 'direct': 0.0}; vendor_not_above = [0, 0]
cert_rows = []
for c, d in rep.items():
    for label, a in d['arms'].items():
        if a['kind'] == 'cg':
            arms['cg'][0] += 1; arms['cg'][1] += bool(a.get('passed'))
            if not a.get('passed'): note('arms', c, f"{label}: {a.get('failure')}")
            else:
                maxres['cg'] = max(maxres['cg'], a['max_residual']); maxobj['cg'] = max(maxobj['cg'], a['objective_abs_diff'] / max(1, abs(a['validated_objective'])))
                vendor_not_above[0] += 1; vendor_not_above[1] += a['vendor_master_check']['not_above_reported']
                lb, cert, ok = cg_lb(c, label)
                if a['reported_full_family_bound'] is not None:
                    arms['dual_certificates'][0] += 1; arms['dual_certificates'][1] += ok
                    if not ok: note('CG bound', c, f'{label}: certificate {cert} below reported bound {a["reported_full_family_bound"]}')
                cert_rows.append({'case': c, 'arm': label, 'reported_bound': a['reported_full_family_bound'], 'certificate': cert,
                                  'rc_min': a['dual_certificate'].get('rc_min'), 'battery_reduced_cost': a['dual_certificate'].get('battery_reduced_cost'),
                                  'certified': ok})
        else:
            if not a.get('passed'):
                arms['direct_vectors'][0] += 1; note('arms', c, f"{label}: {a.get('failure')}"); continue
            for k, v in a['vectors'].items():
                arms['direct_vectors'][0] += 1; arms['direct_vectors'][1] += bool(v.get('validated'))
                if not v.get('validated'): note('arms', c, f'{label} {k}: {v.get("failure")}')
                else:
                    maxres['direct'] = max(maxres['direct'], v['max_residual']); maxobj['direct'] = max(maxobj['direct'], v['objective_abs_diff'] / max(1, abs(v['reported_objective'])))
                    vendor_not_above[0] += 1; vendor_not_above[1] += v['vendor_master_check']['not_above_reported']
summary.update(arm_counts={k: {'checked': v[0], 'passed': v[1]} for k, v in arms.items()},
               max_physical_residual=maxres, max_relative_objective_difference=maxobj,
               vendor_master_not_above_reported={'checked': vendor_not_above[0], 'passed': vendor_not_above[1]},
               optimal_status_bound_checks={'checked': len(bound_checks), 'passed': sum(bound_checks)},
               forbidden_modules_loaded=sorted({m for d in rep.values() for m in d.get('forbidden_modules_loaded', [])}),
               code_hash_mismatches=sorted({(c, l, tuple(a.get('code_checks', {}).get('runtime_files_differing', [])), tuple(a.get('code_checks', {}).get('vendor_files_differing', [])))
                                           for c, d in rep.items() for l, a in d['arms'].items()
                                           if a.get('code_checks', {}).get('runtime_files_differing') or a.get('code_checks', {}).get('vendor_files_differing')}),
               issues=issues)
json.dump(summary, open(HERE / 'validation_summary.json', 'w'), indent=1, default=str)
json.dump(cert_rows, open(HERE / 'cg_bound_certificates.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in summary.items() if k != 'issues'}, indent=1, default=str))
print(len(issues), 'issues'); [print(i) for i in issues[:60]]
