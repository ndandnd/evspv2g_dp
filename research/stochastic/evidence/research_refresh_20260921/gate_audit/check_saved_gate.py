"""Read-only audit of saved wave-15 data; writes only adjacent audit.json.
Run from the research root with .venv/bin/python research_refresh_20260921/gate_audit/check_saved_gate.py.
No MIP, campaign run, or cluster call is made. Re-solves four first-day LP witnesses only.
"""
from pathlib import Path
import sys,json,hashlib,collections
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'gate_wave15'))
import oracle as o
w=o.w
SNAP=ROOT/'snapshots/gate_wave15_validation/campaigns'
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'campaigns':{},'sources':{},'skeleton_checks':[],'paired_checks':[],'bootstrap_checks':[]}
for name in ('oracle','baselines','causal'):
 p=ROOT/'gate_wave15'/f'{name}.py';report['sources'][str(p.relative_to(ROOT))]=sha(p)
report['sources']['holdout_dispatch_v3/dispatch.py']=sha(ROOT/'holdout_dispatch_v3/dispatch.py')
for cam in sorted(SNAP.iterdir()):
 tasks=read(cam/'cases.json'); ids=[read(p) for p in sorted((cam/'cases').glob('*/identity.json'))]
 stats=[read(p) for p in sorted((cam/'cases').glob('*/status.json'))]
 mips=[read(p) for p in sorted((cam/'cases').glob('*/mip_result.json'))]
 row=dict(cases=len(tasks),identities=len(ids),statuses=dict(collections.Counter(s.get('state') for s in stats)),mip_statuses=dict(collections.Counter(s.get('status') for s in mips)),journal_days=0,pinned_records=0,code_hashes=dict(collections.Counter(i.get('code_sha256') for i in ids)),journal_errors=[],dominance_errors=[],pin_max_error=0.)
 for j in (cam/'cases').glob('*/days.jsonl'):
  h='0'*64;events=[]
  for i,line in enumerate(j.read_text().splitlines()):
   z=json.loads(line);saved=z.pop('hash');events.append(z)
   if z['previous']!=h or z['sequence']!=i or saved!=w.digest(z):row['journal_errors'].append(str(j))
   h=saved;row['journal_days']+=1
   if 'adaptive_shortage' in z:
    if z['adaptive_shortage']>z['fixed_shortage']+1e-6 or (z['fixed_cost'] is not None and z['adaptive_cost']>z['fixed_cost']+1e-5):row['dominance_errors'].append(str(j))
   if 'pinned_shortage' in z:
    row['pinned_records']+=1;row['pin_max_error']=max(row['pin_max_error'],abs(z['pinned_shortage']-z['fixed_shortage']),abs(z['pinned_cost']-z['fixed_cost']) if z['fixed_cost'] is not None else 0.)
  st=read(j.with_name('status.json'))
  if st['days']!=len(events) or st['journal_hash']!=h:row['journal_errors'].append(str(j)+' status')
 for i,ident in enumerate(ids):
  if 'provenance' in ident:
   task=ident['task'];source=ROOT/'campaigns'/task['source_campaign']
   if not (source/'cases').exists():source=SNAP/task['source_campaign']
   for name,key in [('pool.json','pool_sha256'),('mip_result.json','mip_sha256')]:assert sha(source/'cases'/f"{task['policy']:04d}"/name)==ident['provenance'][key]
  if 'mip_sha256' in ident:
   task=ident['task'];source=SNAP/task['source_campaign']
   for name,key in [('pool.json','pool_sha256'),('mip_result.json','mip_sha256')]:assert sha(source/'cases'/f"{task['policy']:04d}"/name)==ident[key]
  assert ident['code_sha256'] in report['sources'].values()
 report['campaigns'][cam.name]=row
cfgs=read(ROOT/'campaigns/weather_fair_policy_wave7/cases.json')
report['base_identity']=w.identity(cfgs[0])
for source in [ROOT/'campaigns/weather_fair_policy_wave7', SNAP/'gate_baselines_wave15']:
 for i,cfg in enumerate(read(source/'cases.json')):
  if source.name=='weather_fair_policy_wave7' and cfg['method'] not in ('mean','saa'):continue
  inst,cols,x,nb,s0,prov=o.policy(cfg,source/'cases'/f'{i:04d}')
  residual=0.;skeletons=[]
  for col in cols:
   conn,wd,tr,acts=o.skeleton(inst,col)
   soc=np.r_[inst.G,inst.G+np.cumsum((1-inst.eta)*np.maximum(col.e,0)+np.minimum(col.e,0)-wd)]
   residual=max(residual,float(-soc.min()),float(soc.max()-inst.G),float(abs(soc[-1]-inst.G)),float(abs(col.e.sum()-tr)))
   skeletons.append(dict(connected=conn.tolist(),withdraw=wd.tolist(),task_indices=np.flatnonzero(col.a>.5).tolist()))
  assert residual<1e-6
  report['skeleton_checks'].append(dict(source=source.name,policy=i,trucks=float(sum(x)),nb=nb,s0=s0,max_residual=residual,skeleton_sha256=w.digest(skeletons),eta=inst.eta,deg_cost=inst.deg_cost,charge_cap=None if np.isinf(inst.charge_cap) else inst.charge_cap))
# Four representative fresh first-day LP witnesses; original campaign files untouched.
for i in (10,11,14,17):
 task=dict(source_campaign='weather_fair_policy_wave7',policy=i,cap_factor=.8,year=2022)
 S=o.setup(task);dates,ds=w.weather(S['cfg'],True);got=o.day(S,w.instance(S['cfg'],ds[0]).Delta,validate=True)
 report['paired_checks'].append(dict(policy=i,date=dates[0],**got))
# Resample calendar-day blocks then condition within each replicate. Old summarizer compresses failures out first.
cam=SNAP/'gate_oracle_wave15';cases=read(cam/'cases.json')
for i,t in enumerate(cases):
 if t['year']!=2022 or t['cap_factor']!=.8 or t['arm']!='v2g_fleet':continue
 events=[json.loads(l) for l in (cam/'cases'/f'{i:04d}'/'days.jsonl').read_text().splitlines()]
 diff=np.array([z['fixed_cost']-z['adaptive_cost'] if z['fixed_cost'] is not None and z['adaptive_cost'] is not None else np.nan for z in events])
 def boot(a):
  n=len(a);rng=np.random.default_rng(7291);out=[]
  for _ in range(2000):
   idx=np.concatenate([(s+np.arange(14))%n for s in rng.integers(0,n,int(np.ceil(n/14)))])[:n];out.append(float(np.nanmean(a[idx])))
  return np.quantile(out,[.025,.975]).tolist()
 report['bootstrap_checks'].append(dict(case=i,label=t['label'],joint_days=int(np.isfinite(diff).sum()),saving=float(np.nanmean(diff)),calendar_block_ci=boot(diff),compressed_day_ci=boot(diff[np.isfinite(diff)])))
# Independently reproduce monthly training selection.
rows=read(ROOT/'snapshots/gate_wave15_validation/baseline_rows.json')
report['monthly_selection']={}
for arm in ('solar_bess','v2g','v2g_fleet'):
 eligible=[r for r in rows if r['arm']==arm and r['kind']=='monthly' and r['y2023']['fixed_failures']==0]
 report['monthly_selection'][arm]=min(eligible,key=lambda r:r['y2023']['fixed_mean_cost'])
report['time_limited_baselines']=[{k:r[k] for k in ('case','label','gap','status')} for r in rows if r['status']==9]
# Paired all-day causal comparison: annual mean/SAA minus training-selected month08.
w7=ROOT/'snapshots/fair_policy_validation/campaigns/weather_fair_policy_wave7'
baseline=[json.loads(l) for l in (SNAP/'gate_causal_wave15/cases/0003/days.jsonl').read_text().splitlines()]
report['causal_monthly_comparison']=[]
for i,task in enumerate(read(w7/'evaluations.json')):
 if task['policy'] not in (20,21,24,27) or task['forecast']!='monthly_current_solar':continue
 events=[json.loads(l) for l in (w7/'evaluation'/f'{i:04d}'/'days.jsonl').read_text().splitlines()]
 assert [z['date'] for z in events]==[z['date'] for z in baseline]
 diff=np.array([a['cost']-b['cost'] for a,b in zip(events,baseline)])
 n=len(diff);rng=np.random.default_rng(7291);vals=[]
 for _ in range(2000):
  ix=np.concatenate([(s+np.arange(14))%n for s in rng.integers(0,n,int(np.ceil(n/14)))])[:n];vals.append(float(diff[ix].mean()))
 report['causal_monthly_comparison'].append(dict(policy=task['policy'],days=n,policy_mean=float(np.mean([a['cost'] for a in events])),monthly_mean=float(np.mean([a['cost'] for a in baseline])),policy_minus_monthly=float(diff.mean()),calendar_block_ci=np.quantile(vals,[.025,.975]).tolist()))
Path(__file__).with_name('audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('skeleton_checks','base_identity','monthly_selection')},indent=2))
print('All saved journals/provenance and',len(report['skeleton_checks']),'selected-policy skeleton sets passed.')
