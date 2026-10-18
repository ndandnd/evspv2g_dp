"""Read-only cost/bound comparison for all four cold n1000 complete-family MIPs."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def finite(value):return isinstance(value,(int,float)) and math.isfinite(value)


def summarize(root,history,lp_certificate,independent_dir):
    historical=json.loads(Path(history).read_text())
    lp_audit=json.loads(Path(lp_certificate).read_text())
    if not historical['passed'] or len(historical['cases'])!=4:raise ValueError('Historical identity audit must pass all four cases')
    expected={f'diag2_L{L:02d}_n1000_s{s}' for L in (4,15) for s in (0,1)}
    if {r['case'] for r in historical['cases']}!=expected:raise ValueError('Wrong case population')
    rows=[];details=[]
    for prior in historical['cases']:
        folder=Path(root)/prior['case']/'worker'
        result=json.loads((folder/'result.json').read_text());manifest=json.loads((folder/'manifest.json').read_text())
        raw=json.loads((folder/'instance.json').read_text())
        identity=(result['instance_sha256']==manifest['instance_sha256']==raw['sha256']==prior['instance_sha256'])
        if not identity:raise ValueError('Input identity mismatch: '+prior['case'])
        checks=[]
        for name,sha in result['evidence_sha256'].items():
            path=(folder/name).resolve()
            if not path.is_relative_to(folder.resolve()):raise ValueError('Artifact path escape')
            checks.append(path.is_file() and digest(path)==sha)
        if not checks or not all(checks):raise ValueError('Evidence hash mismatch: '+prior['case'])
        u,b=result.get('objective'),result.get('bound')
        valid=bool(result.get('incumbent_validated') and finite(u))
        ordered=bool(finite(b) and (not finite(u) or b<=u+1e-6))
        lp=prior['prior_lp_objective'];old=prior['historical_record']['total']
        L,seed=manifest['case']['points'],manifest['case']['draw_seed']
        second_path=Path(independent_dir)/f'independent_L{L:02d}_s{seed}.json'
        second=json.loads(second_path.read_text())
        if not second['passed'] or len(second['workers'])!=1:raise ValueError('Independent MIP replay failed')
        checked=second['workers'][0]
        if checked['case']!=prior['case'] or checked['result_sha256']!=digest(folder/'result.json') or not checked['passed']:
            raise ValueError('Independent MIP replay binding mismatch')
        cert=next(r for r in lp_audit['results'] if r['case']==prior['case'] and r['method']=='barrier' and r['repeat']==0)
        if not cert['supplementary_certified'] or cert['instance_payload_sha256']!=raw['sha256'] or abs(cert['objective']-lp)>1e-6:
            raise ValueError('Prior common-family LP certificate mismatch')
        for name,sha in cert['evidence_binding_sha256'].items():
            if digest(Path(cert['worker'])/name)!=sha:raise ValueError('Prior LP evidence changed')
        lp_lower=cert['supplementary_lower_bound']
        integrality=(100*max(0.,u-lp)/abs(u) if valid and ordered and result['status']=='optimal' and u>0 else None)
        row={'case':prior['case'],'points':manifest['case']['points'],'draw_seed':manifest['case']['draw_seed'],
          'status':result['status'],'native_status':result.get('native_status'),'incumbent':u,'native_bound':b,
          'native_gap':result.get('gap'),'incumbent_validated':valid,'native_interval_ordered':ordered,
          'native_reconstructed_gap':max(0.0,(u-b)/abs(u)) if valid and ordered and u!=0 else None,
          'prior_lp_objective':lp,'incumbent_vs_lp_gap_pct':100*(u-lp)/abs(u) if valid and u!=0 else None,
          'native_bound_minus_prior_lp':b-lp if finite(b) else None,
          'historical_reported_incumbent':old,'historical_incumbent_vs_lp_gap_pct':prior['reported_historical_incumbent_gap_vs_prior_lp_pct'],
          'historical_reported_pool_bound':prior['historical_record']['solver_bound'],
          'historical_cost_source_precision':'JSON total rounded to 0.1; LP rounded to 0.01; pool bound stored as native float',
          'old_minus_new_cost':old-u if valid else None,
          'new_cost_reduction_from_historical_pct':100*(old-u)/abs(old) if valid else None,
          'historical_cost_excess_over_new_pct':100*(old-u)/abs(u) if valid and u!=0 else None,
          'independent_primal_replay_passed':checked['passed'],
          'prior_lp_posthoc_full_family_verified':True,'prior_lp_primary_strict_flag':cert['primary_strict_certified'],
          'prior_lp_verified_lower_bound':lp_lower,'prior_lp_verification_gap':cert['primal_minus_supplementary_bound'],
          'full_family_integrality_gap_pct':integrality,
          'full_family_integrality_gap_lower_pct':max(0.,100*(1-(lp+1e-6)/(b-1e-6))) if integrality is not None and b>1e-6 else None,
          'full_family_integrality_gap_upper_pct':max(0.,100*(1-(lp_lower-1e-6)/(u+1e-6))) if integrality is not None else None,
          'solve_end_to_end_seconds':result.get('solve_end_to_end_seconds'),'solver_runtime_seconds':result.get('solver_runtime_seconds'),
          'diagnostic_seconds':result.get('diagnostic_seconds'),'graph_nodes':result.get('graph_nodes'),
          'graph_arcs':result.get('graph_arcs'),'variables':result.get('variables'),'nonzeros':result.get('nonzeros'),
          'node_count':result.get('node_count'),'fleet':(result.get('validation') or {}).get('fleet'),
          'stationary_batteries':(result.get('validation') or {}).get('nb'),
          'process_peak_rss_at_stop_bytes':result.get('process_peak_rss_at_stop_bytes'),
          'host':manifest['environment']['host'],'cpu_model':manifest['environment']['cpu_model'],
          'solver_version':'.'.join(map(str,result.get('solver_version',[]))),
          'instance_sha256':result['instance_sha256'],'result_sha256':digest(folder/'result.json')}
        rows.append(row);details.append({'case':prior['case'],'raw_result':result,'manifest':manifest,
          'evidence_hashes_passed':True,'history_record':prior,'result_path':str(folder/'result.json'),
          'independent_mip_audit':checked,'independent_mip_audit_sha256':digest(second_path),
          'lp_certificate':{k:v for k,v in cert.items() if k!='repaired_prices'}})
    return {'complete':True,'case_count':4,'all_incumbents_validated':all(r['incumbent_validated'] for r in rows),
      'all_native_intervals_ordered':all(r['native_interval_ordered'] for r in rows),'rows':rows,'details':details,
      'scope':'Four complete implemented-family MIPs on identical historical inputs. Historical costs are reported rounded incumbents, not independently replayed here. Native MIP bounds are solver evidence; replay verifies primal feasibility. All outcomes retained; timing is a new study, not a historical speedup comparison.',
      'history_audit_sha256':digest(history),'lp_certificate_sha256':digest(lp_certificate),
      'integrality_gap_definition':'For native-optimal cases, 100*(U-L)/U. Numerical interval uses native integer [B,U], verified LP [dual lower bound,L], and outward 1e-6 endpoint allowance. Bounds are numerical evidence, not exact arithmetic.',
      'old_new_loss_definition':'old_minus_new_cost=oldU-U; reduction percentage divides by oldU; excess percentage divides by U. Old loss combines pool restriction and unfinished pool-MIP search.',
      'optimization_performed':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True,type=Path)
    p.add_argument('--history',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--lp-certificate',required=True,type=Path);p.add_argument('--independent-dir',required=True,type=Path)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh summary directory required')
    report=summarize(a.input,a.history,a.lp_certificate,a.independent_dir);a.output.mkdir(parents=True)
    (a.output/'mip1000_comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    with (a.output/'mip1000_comparison.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(report['rows'][0]));writer.writeheader();writer.writerows(report['rows'])
    lines=[report['scope'],'',report['integrality_gap_definition'],report['old_new_loss_definition'],'','case | status | new incumbent | native bound | native gap % | prior LP | integrality gap % | historical reported incumbent | historical pool bound | cost reduction % | seconds']
    for r in report['rows']:
        def fmt(key):return f"{r[key]:.9g}" if finite(r.get(key)) else str(r.get(key))
        vals=[r['case'],r['status'],fmt('incumbent'),fmt('native_bound'),
          f"{100*r['native_gap']:.9g}" if finite(r['native_gap']) else 'None',fmt('prior_lp_objective'),
          fmt('full_family_integrality_gap_pct'),fmt('historical_reported_incumbent'),fmt('historical_reported_pool_bound'),fmt('new_cost_reduction_from_historical_pct'),fmt('solve_end_to_end_seconds')]
        lines.append(' | '.join(vals))
    lines+=['',f"All new incumbents replayed: {report['all_incumbents_validated']}",
      f"All finite native bound/incumbent intervals ordered: {report['all_native_intervals_ordered']}",
      'All four independent MIP replay reports and prior hash-bound full-family LP certificates are bound into this report. Primary LP strict flags are preserved.']
    (a.output/'author_report.txt').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'complete':True,'cases':4,'output':str(a.output)}))


if __name__=='__main__':main()
