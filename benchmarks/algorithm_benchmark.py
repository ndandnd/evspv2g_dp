"""Paired, checkpointed CG ablation and separate frozen-pool MIP stage."""
from pathlib import Path
import argparse,ast,copy,csv,fcntl,json,os,signal,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from scipy.optimize import linprog,OptimizeResult
from scipy.sparse import coo_matrix,csr_matrix,hstack,vstack
from instance import Instance
from master import Column
from colgen import initial_columns,SCENARIOS
from column_validation import replay_column
from pricing_truck import price_truck_dp
from pricing_contract import clear_pricing_cache
from stochastic_master import StochasticTemplate,PersistentStochasticLP,default_instance
from profile_robustness import base_curves
from durable import Journal,digest,sha,atomic,pack,unpack,key
STOP=False

def stop(*_):
 global STOP
 STOP=True
for sig in (signal.SIGUSR1,signal.SIGTERM,signal.SIGINT):signal.signal(sig,stop)

def load_weather(cfg):
 with (ROOT/'data/solar_days_2023.csv').open() as f:
  rows=[r for r in csv.reader(f) if r and not r[0].startswith('#') and r[0]!='date']
 dates=[r[0] for r in rows];ghi=np.array([[float(v) for v in r[1:25]] for r in rows])
 D,P=base_curves();delta=D[None,:]-P.sum()*cfg['pv']/ghi.sum(axis=1).mean()*ghi
 ix=np.random.default_rng(cfg['seed']).permutation(len(rows))[:cfg['samples']]
 return [dates[i] for i in ix],delta[ix]

def baseline_builders():
 scope=dict(np=np,Instance=Instance,Column=Column,COVERING=False,instance=default_instance,
            coo_matrix=coo_matrix,csr_matrix=csr_matrix,hstack=hstack,vstack=vstack,SCENARIOS=SCENARIOS)
 for filename,names in [('master.py',{'_layout','_build_lp'}),('worker.py',{'expected_model','model','phase_model'})]:
  p=Path(__file__).parent/'baseline'/filename;tree=ast.parse(p.read_text())
  selected=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names],type_ignores=[])
  exec(compile(selected,str(p),'exec'),scope)
 return scope

def cold_lp(m,backend,time_limit=120.):
 c,au,bu,ae,be,lb,ub,_=m
 if backend=='highs':return linprog(c,A_ub=au,b_ub=bu,A_eq=ae,b_eq=be,bounds=list(zip(lb,ub)),method='highs',options={'time_limit':time_limit})
 import gurobipy as gp
 with gp.Model() as gm:
  gm.Params.OutputFlag=0;gm.Params.Threads=1;gm.Params.Method=1;gm.Params.TimeLimit=time_limit;gm.Params.OptimalityTol=1e-8;gm.Params.FeasibilityTol=1e-8
  x=gm.addMVar(len(c),lb=lb,ub=ub,obj=c)
  u=gm.addMConstr(au,x,'<',bu);e=gm.addMConstr(ae,x,'=',be);gm.optimize()
  if gm.Status!=gp.GRB.OPTIMAL:raise RuntimeError('Cold Gurobi LP status '+str(gm.Status))
  return OptimizeResult(success=True,status=0,message='Gurobi optimal',fun=gm.ObjVal,x=x.X,
                        eqlin=OptimizeResult(marginals=e.Pi),ineqlin=OptimizeResult(marginals=u.Pi))

def validate_lp(m,r):
 c,au,bu,ae,be,lb,ub,_=m
 if np.shape(r.x)!=np.shape(c) or not np.isfinite(r.x).all() or not np.isfinite(r.fun):raise RuntimeError('Nonfinite/malformed LP vector or objective')
 residual=max(np.max(au@r.x-bu),np.max(abs(ae@r.x-be)),np.max(lb-r.x),np.max(r.x-ub))
 if residual>1e-6 or abs(c@r.x-r.fun)>1e-5:raise RuntimeError('LP residual/objective validation')
 return float(residual)

def verify(campaign):
 manifest=json.loads((ROOT/'algorithm_release.json').read_text())
 for p,h in manifest['files'].items():
  if sha(ROOT/p)!=h:raise RuntimeError('Changed execution/input: '+p)
 if sha(campaign/'cases.json')!=manifest['cases_sha256'] or sha(campaign/'PROTOCOL.md')!=manifest['protocol_sha256']:
  raise RuntimeError('Changed campaign configuration')
 return manifest

def run_cg(cfg,variant,out,manifest,campaign):
 start=time.perf_counter();clear_pricing_cache()
 out.mkdir(parents=True,exist_ok=True)
 ident=dict(config=cfg,variant=variant,release_sha256=digest(manifest),execution_commit=manifest['execution_commit'],
            information='common truck profiles/assets; full-day continuous recourse',
            initialization='validated cold seeds plus coverage/energy Phase I',master_sense='equal trip coverage',
            tolerance=1e-6,max_iterations=2000,variant_wall_budget_seconds=1800,checkpoint_every=25)
 journal=Journal(out,ident)
 if (out/'pool.json').exists():
  p=json.loads((out/'pool.json').read_text());assert p['identity_sha256']==digest(ident)
  assert p['columns']==[pack(c) for c in journal.cols if c.kind=='truck']
  latest=json.loads((out/'iterations.jsonl').read_text().splitlines()[-1])
  if p['certified']:
   assert latest['phase']=='economic' and latest['best_reduced_cost'] is None and abs(latest['objective']-p['lp_objective'])<1e-8
  journal.checkpoint(p['iterations']-1,'certified' if p['certified'] else p['termination'],phase='economic',
                     pool_sha256=sha(out/'pool.json'),elapsed_seconds=p['elapsed_seconds'],timing_totals=p['timing_totals'],
                     phase1_certificate_sha256=sha(out/'phase1_certificate.json'))
  return
 dates,ds=load_weather(cfg);instances=[default_instance(cfg,d) for d in ds];inst=instances[0];caps=SCENARIOS[cfg['arm']]
 cp=json.loads((out/'checkpoint.json').read_text()) if (out/'checkpoint.json').exists() else {}
 phase=cp.get('phase','phase1');iteration=cp.get('iteration',-1)+1
 prior=float(cp.get('elapsed_seconds',0));last=start
 counters=cp.get('timing_totals',dict(assembly=0.,lp_solve_and_native_build=0.,pricing=0.,replay=0.,warm_import=0.))
 records=(out/'iterations.jsonl').read_text().splitlines() if (out/'iterations.jsonl').exists() else []
 if records:
  latest=json.loads(records[-1])
  if latest['elapsed_seconds']>prior:prior=latest['elapsed_seconds'];counters=latest['timing_totals']
 warm_state=out/'warm_progress.json'
 if warm_state.exists():
  latest=json.loads(warm_state.read_text())
  if latest.get('elapsed_seconds',0)>prior:prior=latest['elapsed_seconds'];counters=latest['timing_totals']
 existing_iterations=[json.loads(x)['iteration'] for x in journal.path.read_text().splitlines()] if journal.path.exists() else []
 iteration=max(iteration,max(existing_iterations,default=-1)+1)
 def elapsed():return prior+time.perf_counter()-start
 def checkpoint(state,it,**extra):
  proof=out/'phase1_certificate.json'
  if phase=='economic' and proof.exists():extra['phase1_certificate_sha256']=sha(proof)
  return journal.checkpoint(it,state,phase=phase,elapsed_seconds=elapsed(),timing_totals=counters,**extra)
 # Complete interrupted seed initialization idempotently, using the same column
 # identities. No positive checkpoint implies that every seed was flushed.
 seen={key(c) for c in journal.cols}
 for c in initial_columns(inst,'cold',caps,'cyclic'):
  if key(c) in seen:continue
  if not replay_column(inst,c,allow_discharge=caps['allow_discharge']):raise RuntimeError('Seed replay')
  journal.add(c,-1);seen.add(key(c))
 t=time.perf_counter();template=StochasticTemplate(instances,battery_allowed=caps['battery'],method='saa') if variant!='legacy_highs' else None
 old=baseline_builders() if variant=='legacy_highs' else None;counters['assembly']+=time.perf_counter()-t
 # -2 journal records distinguish warm additions, preserving the accepted cap
 # even after a crash between append and progress checkpoint.
 if variant=='persistent_cached_warm' and not (out/'warm_import.json').exists():
  wt=time.perf_counter();spec=cfg['warm_source'];source=campaign/spec['path'];assert sha(source)==spec['sha256']
  progress=out/'warm_progress.json'
  stats=json.loads(progress.read_text()) if progress.exists() else dict(scanned=0,accepted=0,duplicates=0,rejected=0,stop='exhausted',seconds=0.)
  stats['accepted']=sum(json.loads(x)['iteration']==-2 for x in journal.path.read_text().splitlines())
  spent=stats['seconds'];warm_base=max(0.,counters['warm_import']-spent);pool=json.loads(source.read_text())['columns']
  for index in range(stats['scanned'],len(pool)):
   if stats['accepted']>=128:stats['stop']='column_limit';break
   if stats['scanned']>=512:stats['stop']='scan_limit';break
   if spent+time.perf_counter()-wt>=30:stats['stop']='time_limit';break
   c=unpack(pool[index]);stats['scanned']=index+1
   if key(c) in seen:stats['duplicates']+=1
   else:
    expected=inst.c_v+inst.deg_cost*np.maximum(-c.e,0).sum()
    if c.kind!='truck' or abs(c.fixed_cost-expected)>1e-8 or not replay_column(inst,c,allow_discharge=caps['allow_discharge']):stats['rejected']+=1
    else:journal.add(c,-2);seen.add(key(c));stats['accepted']+=1
   stats['seconds']=spent+time.perf_counter()-wt;counters['warm_import']=warm_base+stats['seconds']
   stats['elapsed_seconds']=elapsed();stats['timing_totals']=dict(counters);atomic(progress,stats)
   if STOP:checkpoint('paused_warm_import',iteration-1);raise SystemExit(75)
  stats['seconds']=spent+time.perf_counter()-wt;counters['warm_import']=warm_base+stats['seconds']
  stats['elapsed_seconds']=elapsed();stats['timing_totals']=dict(counters);atomic(out/'warm_import.json',stats)
  checkpoint('warm_import_complete',iteration-1)
 phaseinst=copy.deepcopy(inst);phaseinst.c_v=phaseinst.eps_pen=phaseinst.deg_cost=0.
 persistent=variant.startswith('persistent');cached=variant in ('persistent_cached','persistent_cached_warm')
 session=None;session_phase=None;certified=False;r=None;last_solved_phase=None;lp_residual=0.;reason='iteration_limit'
 try:
  for it in range(iteration,2000):
   if STOP:checkpoint('paused',it-1);raise SystemExit(75)
   if elapsed()>=1800:reason='wall_budget';break
   if phase=='economic':
    proof=json.loads((out/'phase1_certificate.json').read_text());assert proof['classification']=='LP_FEASIBLE_NOT_INTEGER_PROOF' and proof['identity_sha256']==digest(ident)
    if cp.get('phase')=='economic':assert cp['phase1_certificate_sha256']==sha(out/'phase1_certificate.json')
   cols=journal.cols;t=time.perf_counter()
   if persistent:
    if session_phase!=phase:
     if session:session.close()
     session=PersistentStochasticLP(template,phase_cap=inst.gen_cap if phase=='phase1' else None,forbid_artificials=phase=='economic')
     session_phase=phase
    session.sync(cols);built=time.perf_counter();r=session.solve(time_limit=min(120.,max(.01,1800-elapsed())));solved=time.perf_counter()
    if not r.success:raise RuntimeError('Persistent LP failure: '+r.message)
    lp_residual=max(lp_residual,float(r.max_primal_violation))
    # Native adapter validates against its accumulated sparse columns; do not
    # rebuild the extensive form inside this timed persistent iteration.
    meta=template.meta
   else:
    if old:
     m=old['phase_model'](cfg,ds,cols,inst.gen_cap) if phase=='phase1' else list(old['model'](cfg,ds,cols))
     if phase=='economic':
      for k,c in enumerate(cols):
       if c.kind=='artificial':m[6][k]=0.
    else:m=template.build(cols,phase_cap=inst.gen_cap if phase=='phase1' else None,forbid_artificials=phase=='economic')
    built=time.perf_counter();r=cold_lp(m,'gurobi' if variant=='sparse_gurobi' else 'highs',min(120.,max(.01,1800-elapsed())));solved=time.perf_counter();meta=m[-1]
    if not r.success:raise RuntimeError('LP failure: '+r.message)
    lp_residual=max(lp_residual,validate_lp(m,r))
   counters['assembly']+=built-t;counters['lp_solve_and_native_build']+=solved-built;last_solved_phase=phase
   if not np.isfinite(r.eqlin.marginals).all() or not np.isfinite(r.ineqlin.marginals).all():raise RuntimeError('Nonfinite LP duals')
   alpha=r.eqlin.marginals[:inst.n_trips]
   mu=sum((-r.ineqlin.marginals[md['balance']:md['balance']+inst.T] for md in meta),np.zeros(inst.T));nu=np.zeros(inst.T)
   for md in meta:
    if md['cap'] is not None:nu-=r.ineqlin.marginals[md['cap']:md['cap']+inst.T]
   t=time.perf_counter();priced=price_truck_dp(phaseinst if phase=='phase1' else inst,alpha,mu,nu=nu,allow_discharge=caps['allow_discharge'],soc_mode='cyclic',tol=1e-6,use_cache=cached)
   counters['pricing']+=time.perf_counter()-t
   event=dict(iteration=it,phase=phase,objective=float(r.fun),columns=len(cols),best_reduced_cost=float(priced[0][1]) if priced else None,elapsed_seconds=elapsed(),timing_totals=dict(counters))
   with (out/'iterations.jsonl').open('a') as f:f.write(json.dumps(event)+'\n');f.flush();os.fsync(f.fileno())
   if not priced:
    if phase=='phase1':
     low=float(r.fun-inst.n_trips*1e-6)
     classification='LP_FEASIBLE_NOT_INTEGER_PROOF' if r.fun<1e-7 else 'LP_INFEASIBLE_CERTIFICATE' if low>1e-6 else 'NUMERICALLY_UNRESOLVED'
     atomic(out/'phase1_certificate.json',dict(classification=classification,objective=float(r.fun),lower_bound=low,identity_sha256=digest(ident)))
     if classification!='LP_FEASIBLE_NOT_INTEGER_PROOF':raise RuntimeError('Phase I '+classification)
     phase='economic';checkpoint('phase_transition',it);continue
    certified=True;reason='priced_out';break
   col,rc=priced[0];direct=(0. if phase=='phase1' else col.cost(inst.eps_pen))-col.a@alpha+col.e@mu+np.maximum(col.e,0)@nu
   if abs(direct-rc)>1e-7:raise RuntimeError('Reconstructed RC mismatch')
   if phase=='phase1':col.fixed_cost=inst.c_v
   t=time.perf_counter()
   if not replay_column(inst,col,allow_discharge=caps['allow_discharge']):raise RuntimeError('Column physical replay')
   counters['replay']+=time.perf_counter()-t
   if key(col) in seen:raise RuntimeError('Improving duplicate; no pricing certificate')
   journal.add(col,it);seen.add(key(col))
   if (it+1)%25==0 or time.perf_counter()-last>=60:
    q=checkpoint('checkpointed',it);atomic(out/f'milestone-{it:06d}.json',q);last=time.perf_counter()
  else:it=1999
  if phase!='economic' or r is None or last_solved_phase!='economic':checkpoint('budget_before_feasible_economic_lp',it);raise RuntimeError('No economic LP before budget')
  # A budget stop may have appended a final column. The saved objective/bound is
  # explicitly from the last solved RMP; no full-family bound unless priced out.
  real=[c for c in journal.cols if c.kind=='truck']
  for c in real:
   if not replay_column(inst,c,allow_discharge=caps['allow_discharge']):raise RuntimeError('Frozen pool replay')
  pool=dict(identity_sha256=digest(ident),columns=[pack(c) for c in real],training_dates=dates,certified=certified,
            lp_objective=float(r.fun),full_lp_lower_bound=float(r.fun-inst.n_trips*1e-6) if certified else None,
            scope='discretized common-profile LP' if certified else 'finite pool only; last-solved RMP objective',
            termination=reason,elapsed_seconds=elapsed(),timing_totals=counters,iterations=it+1,last_solved_columns=event['columns'],last_solved_phase=last_solved_phase,
            physical_replay='all real profiles independently replayed',max_cold_lp_residual=lp_residual)
  atomic(out/'pool.json',pool);checkpoint('certified' if certified else reason,it,pool_sha256=sha(out/'pool.json'))
 finally:
  if session:session.close()

def run_mip(cfg,out,manifest):
 import gurobipy as gp
 if (out/'mip_result.json').exists():
  saved=json.loads((out/'mip_result.json').read_text())
  assert saved['pool_sha256']==sha(out/'pool.json') and saved['execution_commit']==manifest['execution_commit']
  if saved['solution_count']<=0:raise RuntimeError('Prior MIP has no incumbent; use a new identified attempt')
  assert saved['incumbent_sha256']==sha(out/'incumbent.sol')
  return
 if (out/'gurobi_mip.log').exists():raise RuntimeError('Interrupted prior MIP; preserve search artifacts and use a new attempt path')
 p=json.loads((out/'pool.json').read_text());status=json.loads((out/'cg_status.json').read_text());assert status['pool_sha256']==sha(out/'pool.json')
 cols=[unpack(c) for c in p['columns']];_,ds=load_weather(cfg);t=StochasticTemplate([default_instance(cfg,d) for d in ds],battery_allowed=SCENARIOS[cfg['arm']]['battery'])
 m=t.build(cols);c,au,bu,ae,be,lb,ub,_=m
 with gp.Model('algorithm_pool_mip') as gm:
  gm.Params.LogFile=str(out/'gurobi_mip.log');gm.Params.Threads=1;gm.Params.TimeLimit=120;gm.Params.MIPGap=1e-6;gm.Params.Seed=cfg['seed']
  types=np.array(['C']*len(c));types[:len(cols)+1]='I'
  x=gm.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=types);gm.addMConstr(au,x,'<',bu);gm.addMConstr(ae,x,'=',be);gm.optimize()
  result=dict(status=int(gm.Status),runtime=float(gm.Runtime),solution_count=int(gm.SolCount),pool_sha256=sha(out/'pool.json'),scope='finite saved real-column pool MIP',cg_full_lp_lower_bound=p['full_lp_lower_bound'],execution_commit=manifest['execution_commit'])
  if gm.SolCount:
   z=x.X;res=OptimizeResult(x=z,fun=gm.ObjVal);residual=validate_lp(m,res);integ=float(np.max(abs(z[:len(cols)+1]-np.rint(z[:len(cols)+1]))))
   if integ>1e-5:raise RuntimeError('MIP integrality violation')
   result.update(objective=float(gm.ObjVal),bound=float(gm.ObjBound),gap=float(gm.MIPGap),shared=z[:len(cols)+2].tolist(),max_residual=residual,integer_error=integ)
   gm.write(str(out/'incumbent.sol'));result['incumbent_sha256']=sha(out/'incumbent.sol')
  atomic(out/'mip_result.json',result)
  if not gm.SolCount:raise RuntimeError('No finite-pool MIP incumbent')

def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['cg','mip']);p.add_argument('--campaign',type=Path,required=True);p.add_argument('--case',type=int,required=True);a=p.parse_args()
 manifest=verify(a.campaign);cfg=json.loads((a.campaign/'cases.json').read_text())[a.case]
 case=a.campaign/'cases'/f'{a.case:04d}';case.mkdir(parents=True,exist_ok=True)
 lock=open(case/(a.mode+'.lock'),'w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 atomic(case/(a.mode+'_attempt_'+str(time.time_ns())+'.json'),dict(job=os.environ.get('SLURM_JOB_ID'),restart=os.environ.get('SLURM_RESTART_COUNT'),host=os.uname().nodename,python=sys.version,numpy=np.__version__,release_sha256=digest(manifest)))
 try:
  for variant in cfg['variant_order']:
   out=case/variant
   if a.mode=='cg':run_cg(cfg,variant,out,manifest,a.campaign)
   else:run_mip(cfg,out,manifest)
  atomic(case/(a.mode+'_status.json'),dict(state='complete',variants=cfg['variant_order'],release_sha256=digest(manifest)))
 except Exception as exc:
  atomic(case/(a.mode+'_error.json'),dict(error=repr(exc),at=time.time()));raise
if __name__=='__main__':main()
