"""No-solve reporting/recovery boundary checks; all fixtures are synthetic."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile

from cg_reuse_recovery import POLICY, digest, load_recovery_map, execution_ledger, execution_counts
from certify_cg_reuse_selected import selected_workers
from run_cg_reuse import experiment_plan
import summarize_cg_reuse as reporting

ROOT = Path(__file__).resolve().parent
FROZEN = {
    'persistent_rmp.py': 'e44d4503922ad8823c2f992f5991ba58be8a1a1165c7495d2734244e7619760c',
    'run_cg_reuse.py': '9d7cd34bb1319b43e1e54c01dea3881e3a6b6b54f013bba1b234136bb4c5b768',
    'CG_REUSE_PROTOCOL.md': '4af1e6eba7246dfa97bfa0f1d5411869d04e46a064cc0058dba2422f1a74b129',
    'check_cg_reuse.py': 'df06e9954cf92f4d3f34491344b5e9b9a12eb41234c597c67683dcf0e98c3c6e'}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2)+'\n')


def run_checks(output):
    if output.exists(): raise FileExistsError('Fresh output required')
    checks = []
    def check(label, value):
        if not value: raise AssertionError(label)
        checks.append(label)
    def rejects(label, call):
        try: call()
        except (ValueError, FileExistsError): checks.append(label)
        else: raise AssertionError(label)
    a = {'case':'synthetic', 'repeat':0, 'n_tasks':100, 'draw_seed':0,
         'variant':'cold', 'status':'optimal_to_pricing_tolerance', 'identity_passed':True,
         'primary_accepted':True, 'supplementary_accepted':False, 'additional_posthoc_validation':False, 'objective':100.,
         'numerical_lower_bound':99.999999, 'solve_end_to_end_seconds':100.,
         'budget_seconds':1800., 'genuine_optimization_time_limit':False}
    b = {**a, 'variant':'reuse', 'solve_end_to_end_seconds':50.}
    ac = {**a, 'status':'budget_exhausted', 'primary_accepted':False,
          'genuine_optimization_time_limit':True, 'solve_end_to_end_seconds':1800.}
    bc = {**b, 'status':'budget_exhausted', 'primary_accepted':False,
          'genuine_optimization_time_limit':True, 'solve_end_to_end_seconds':1800.}
    check('Exact equal-LP pair ratio', reporting.pair(a,b)['ratio'] == 2)
    check('Numerator censor nonstrict lower bound', reporting.pair(ac,b)['ratio_lower_bound'] == 36 and not reporting.pair(ac,b)['bound_is_strict'])
    check('Denominator censor nonstrict upper bound', reporting.pair(a,bc)['ratio_upper_bound'] == 100/1800)
    check('Zero successful clock rejected', reporting.pair(ac,{**b,'solve_end_to_end_seconds':0})['classification'] == 'invalid_timing')
    check('Two censors ratio unidentified', reporting.pair(ac,bc)['classification'] == 'both_time_censored_ratio_unidentified')
    check('Watchdog has no algorithm-time bound', reporting.pair({**ac,'status':'external_timeout','genuine_optimization_time_limit':False},b)['classification'] == 'external_watchdog_no_algorithm_time_bound')
    check('Compatible unequal objectives no exact ratio', reporting.pair(a,{**b,'objective':100.000002})['classification'] == 'compatible_intervals_not_equal_LP')
    check('Incompatible objectives rejected', reporting.pair(a,{**b,'objective':101.,'numerical_lower_bound':100.999999})['classification'] == 'incompatible_objectives')
    memory_rows=[{**a,'process_peak_rss_at_stop_bytes':80*2**20,
                   'process_peak_rss_after_diagnostics_bytes':120*2**20},
                 {**ac,'process_peak_rss_at_stop_bytes':100*2**20,
                   'process_peak_rss_after_diagnostics_bytes':100*2**20}]
    memory_group=next(g for g in reporting.summaries(memory_rows,[])[0] if g['n_tasks']==100 and g['variant']=='cold')
    check('Stop and post-diagnostic memory remain separate summaries',
          memory_group['all_observed_stop_metrics']['process_peak_rss_at_stop_bytes']['median']==90*2**20
          and memory_group['all_observed_stop_metrics']['process_peak_rss_after_diagnostics_bytes']['median']==110*2**20)
    check('Certified and censored memory populations remain separate',
          memory_group['primary_completed_metrics']['process_peak_rss_after_diagnostics_bytes']['median']==120*2**20
          and memory_group['censored_stop_metrics']['process_peak_rss_after_diagnostics_bytes']['median']==100*2**20)
    with tempfile.TemporaryDirectory(prefix='cg-reuse-reporting-') as temporary:
        tmp = Path(temporary); base = tmp/'input'; base.mkdir()
        block = experiment_plan()[0]
        record = {'case':block['case_name'], 'repeat':block['repeat'], 'method':'barrier'}
        supplement = tmp/'supplement.json'
        save(supplement, {'post_hoc':True,'primary_results_changed':False,'results':[record]})
        missing = reporting.analyze(base,tmp/'missing',supplements=[supplement])
        check('Missing collection retains54 outcomes108 paired views', len(missing['raw_worker_rows']) == 54 and len(missing['paired_rows']) == 108)
        check('Supplement with missing block rejected safely', not any(r['supplementary_accepted'] for r in missing['raw_worker_rows']))
        for dirname in ('duplicate_a','duplicate_b'):
            save(base/dirname/'manifest.json', {'variant':'all','case':{'case':block['case_name']},'repeat':block['repeat']})
        duplicate = reporting.analyze(base,tmp/'duplicated',supplements=[supplement])
        check('Duplicate block never selected favorably', any('Duplicate block' in e for b in duplicate['block_checks'] for e in b['errors']) and len(duplicate['raw_worker_rows']) == 54)
        check('CG native-optimal counts null/direct numeric', all(g['native_optimal'] is None if g['variant'] != 'barrier' else isinstance(g['native_optimal'],int) for g in missing['groups']))
        check('Native-optimal display explicitly direct-only', 'Direct native optimal' in reporting.describe(missing) and '| n/a |' in reporting.describe(missing))
        check('Both memory windows and incomplete-diagnostic caveat are displayed',
              'At algorithm stop | After worker diagnostics' in reporting.describe(missing)
              and 'does not imply completed validation' in reporting.describe(missing))
        # New fixture: two preserved, externally interrupted original blocks.
        base = tmp/'recovery_input'; base.mkdir(); map_path = tmp/'map.json'
        accounting = tmp/'accounting.txt'
        accounting.write_text('242625_13|PREEMPTED|1450|2\n242625_14|PREEMPTED|1450|2\n')
        entries=[]
        for index in (13,14):
            block=experiment_plan()[index]; original=base/f'block_{index}'
            manifest={'variant':'all','case':{'case':block['case_name']},'repeat':block['repeat'],
                      'started_utc':'2026-10-13T04:00:00+00:00','budget_seconds':1800,
                      'worker_watchdog_grace_seconds':600,'environment':{'cpu_model':'synthetic_cpu','gurobi':[12,0,3]}}
            save(original/'manifest.json',manifest)
            save(original/'cold'/'manifest.json',{'started_utc':'2026-10-13T04:01:00+00:00'})
            if index==13:
                save(original/'barrier'/'manifest.json',{'started_utc':'2026-10-13T04:00:00+00:00'})
                save(original/'barrier'/'result.json',{'status':'optimal','objective':100.,'solve_end_to_end_seconds':30.})
            entries.append({'block_index':index,'original_relative_dir':f'block_{index}',
                'recovery_relative_dir':f'recovery/block_{index}','registered_utc':'2026-10-13T05:26:08+00:00',
                'recovery_job_id':f'243560_{index}',
                'preemption_receipt':{'path':'accounting.txt','sha256':digest(accounting),'job_id':f'242625_{index}'},
                'original_artifact_sha256':{str(p.relative_to(original)):digest(p) for p in original.rglob('*') if p.is_file()}})
        data={'schema_version':1,'policy_sha256':digest(POLICY),'policy_registered_utc':'2026-10-13T05:26:08+00:00',
              'original_array_job_id':'242625','entries':entries}
        submission=tmp/'submission.json'
        registration={'utc':data['policy_registered_utc'],'indices':[13,14],
            'policy_sha256':data['policy_sha256'],'scientific_outcomes_used':False,
            'selection_basis':'scheduler_PREEMPTED_without_completed_block',
            'status':'submitted','returncode':0,'job_id':'243560',
            'command':['sbatch','--nodelist=lisbeth','--array=13,14'],
            'accounting_sha256':digest(accounting),
            'original_artifact_sha256':{f"results/block_{e['block_index']}/{relative}":value
                for e in entries for relative,value in e['original_artifact_sha256'].items()}}
        save(submission,registration)
        for entry in entries:
            entry['registration_receipt']={'path':'submission.json','sha256':digest(submission)}
        save(map_path,data)
        selected,provenance=load_recovery_map(map_path,base)
        check('Plain scheduler receipt permits onlytwo registered whole-block recoveries',len(selected)==2 and provenance['registered_recovery_blocks']==2)
        selected_slots,unselected,omitted,_=selected_workers(base,map_path,False)
        check('Original partialbarrier retained onlyas unselected evidence',not selected_slots and len(unselected)==1 and len(omitted)==18)
        report=reporting.analyze(base,tmp/'mapped_missing',recovery_map=map_path)
        check('No fallback to old successful barrier when recovery missing',not any(r['present'] for r in report['raw_worker_rows']) and not report['unexpected_results'])
        check('54logical slots plus60 totalattempt slots andoriginalpartial result retained',len(report['raw_worker_rows'])==54 and len(report['execution_ledger'])==60 and report['execution_counts']['original']['saved_result_outcomes']==1 and report['execution_counts']['recovery']['planned_execution_arm_slots']==6)
        def reject_map(label,changed):
            save(map_path,changed); rejects(label,lambda:load_recovery_map(map_path,base)); save(map_path,data)
        changed=copy.deepcopy(data);del changed['entries'][0]['registration_receipt']
        reject_map('Missing prospective submission receipt rejected',changed)
        def reject_registration(label,changed):
            save(submission,changed);changed_map=copy.deepcopy(data)
            for e in changed_map['entries']:e['registration_receipt']['sha256']=digest(submission)
            reject_map(label,changed_map);save(submission,registration)
        reject_registration('Unsubmitted registration receipt rejected',{**registration,'status':'prepared'})
        reject_registration('Failed submission returncode rejected',{**registration,'returncode':1})
        reject_registration('Missing submitted node rejected',{**registration,'command':['sbatch','--array=13,14']})
        reject_registration('Ambiguous multi-node recovery request rejected',{**registration,'command':['sbatch','--nodelist=lisbeth,other']})
        changed=copy.deepcopy(data);changed['entries'].append(changed['entries'][0])
        reject_map('Duplicate recovery registration rejected',changed)
        changed=copy.deepcopy(data);changed['entries']=changed['entries'][:1]
        reject_map('Omitted externally preempted eligible block rejected',changed)
        accounting.write_text('242625_13|TIMEOUT|1450|2\n242625_14|PREEMPTED|1450|2\n')
        changed=copy.deepcopy(data)
        for e in changed['entries']:e['preemption_receipt']['sha256']=digest(accounting)
        reject_map('Solver/scheduler timeout cannot select recovery',changed)
        accounting.write_text('242625_13|PREEMPTED|1450|2\n242625_14|PREEMPTED|1450|2\n')
        original=base/'block_13'; target=original/'cold'/'manifest.json'; before=target.read_bytes()
        target.write_text('{}\n');rejects('Altered original artifacts rejected',lambda:load_recovery_map(map_path,base));target.write_bytes(before)
        save(original/'block_summary.json',{'completed':True})
        rejects('Completed original block cannot select recovery',lambda:load_recovery_map(map_path,base));(original/'block_summary.json').unlink()
        recovery=base/'recovery/block_13'; manifest=json.loads((original/'manifest.json').read_text())
        manifest['environment']['host']='lisbeth.tech.cornell.edu'
        manifest['started_utc']='2026-10-13T05:27:00+00:00';save(recovery/'manifest.json',manifest)
        check('Short submitted node accepts matching canonical host',load_recovery_map(map_path,base)[1]['entries'][0]['observed_recovery_host']=='lisbeth.tech.cornell.edu')
        wronghost=copy.deepcopy(manifest);wronghost['environment']['host']='other.tech.cornell.edu'
        save(recovery/'manifest.json',wronghost)
        rejects('Undeclared same-CPU recovery block host rejected',lambda:load_recovery_map(map_path,base));save(recovery/'manifest.json',manifest)
        wronghost=copy.deepcopy(manifest);del wronghost['environment']['host'];save(recovery/'manifest.json',wronghost)
        rejects('Missing recovery host rejected',lambda:load_recovery_map(map_path,base));save(recovery/'manifest.json',manifest)
        changedmanifest={**manifest,'started_utc':'2026-10-13T05:25:00+00:00'};save(recovery/'manifest.json',changedmanifest)
        rejects('Recovery beginning before registration rejected',lambda:load_recovery_map(map_path,base));save(recovery/'manifest.json',manifest)
        save(recovery/'manifest.json',{**manifest,'worker_watchdog_grace_seconds':601})
        rejects('Changed recovery budget grace rejected',lambda:load_recovery_map(map_path,base));save(recovery/'manifest.json',manifest)
        worker_manifest={'started_utc':'2026-10-13T05:27:00+00:00','environment':{'host':'lisbeth.tech.cornell.edu'}}
        save(recovery/'cold'/'manifest.json',{**worker_manifest,'environment':{'host':'other.tech.cornell.edu'}})
        rejects('Recovery worker host must equal containing block host',lambda:load_recovery_map(map_path,base))
        save(recovery/'cold'/'manifest.json',worker_manifest)
        save(recovery/'barrier'/'manifest.json',worker_manifest)
        check('Matching recorded recovery worker hosts pass',load_recovery_map(map_path,base)[1]['entries'][0]['worker_hosts_checked']==2)
        save(recovery/'barrier'/'result.json',{'status':'error','objective':None})
        selected_slots,unselected,_,_=selected_workers(base,map_path,False)
        check('Failed recovery selected wholeblock without oldsuccessful fallback',len(selected_slots)==1 and selected_slots[0]['folder']==(recovery/'barrier').resolve() and len(unselected)==1)
        rejects('Final collector refuses incomplete selected blocks',lambda:selected_workers(base,map_path,True))
        save(recovery/'block_summary.json',{'completed':True})
        save(base/'extra_attempt'/'manifest.json',manifest)
        rejects('Unregistered third attempt rejected',lambda:selected_workers(base,map_path,False))
        (base/'extra_attempt'/'manifest.json').unlink()
        second=tmp/'second.txt';second.write_text('243560_13|PREEMPTED|800|2\n')
        changed=copy.deepcopy(data);changed['entries'][0]['recovery_preemption_receipt']={'path':'second.txt','sha256':digest(second),'job_id':'243560_13'}
        save(map_path,changed); selected,_=load_recovery_map(map_path,base)
        item=selected[(experiment_plan()[13]['case_name'],experiment_plan()[13]['repeat'])]
        ledger=execution_ledger(experiment_plan()[13],recovery,'recovery',True,item['recovery_preemption'])
        check('Second interruption stays explicit withoutalgorithm censor',next(r for r in ledger if r['variant']=='cold')['execution_state']=='externally_preempted_without_saved_result' and not any(r['algorithm_time_censor_from_scheduler_preemption'] for r in ledger))
        changed['entries'][0]['recovery_job_id']='243560_99'
        reject_map('Second preemption mustmatch registered recovery job',changed)
    check('Frozen runtime/protocol hashes unchanged',all(digest(ROOT/name)==expected for name,expected in FROZEN.items()))
    output.mkdir(parents=True)
    report={'scope':'Synthetic reporting and recovery checks only; no scientific data or optimization',
        'passed':True,'checks':checks,'count':len(checks),'frozen_runtime_sha256':FROZEN,
        'reporting_sha256':{name:digest(ROOT/name) for name in
            ('check_cg_reuse_reporting.py','cg_reuse_recovery.py','certify_cg_reuse_selected.py','summarize_cg_reuse.py')}}
    save(output/'checks.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=run_checks(a.output);print(json.dumps({'passed':report['passed'],'checks':report['count']}))
