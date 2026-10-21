"""Common-profile SAA CG. Independent research extension; no adaptive truck routes."""
from pathlib import Path
import os, sys, json, csv, hashlib, time, signal, argparse, fcntl
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, vstack, hstack, csr_matrix
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'reference'))
from recreate_arxiv import build_instance, BREAKS2
from profile_robustness import base_curves
from master import Column, _build_lp
from colgen import initial_columns, SCENARIOS
from pricing_strict import price_truck_dp
STOP=False

def signal_stop(*_):
    global STOP
    STOP=True
for sig in (signal.SIGUSR1,signal.SIGTERM,signal.SIGINT): signal.signal(sig,signal_stop)
def digest(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp')
    with open(tmp,'w') as f: json.dump(obj,f,sort_keys=True,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def pack(c):return dict(kind=c.kind,a=c.a.tolist(),e=c.e.tolist(),fixed_cost=c.fixed_cost,label=c.label)
def unpack(c):return Column(c['kind'],np.array(c['a']),np.array(c['e']),c['fixed_cost'],c['label'])
def key(c):return digest(dict(kind=c.kind,a=c.a.tolist(),e=c.e.tolist(),fixed_cost=c.fixed_cost))
def load_weather(name):
    with open(ROOT/'reference/data'/name) as f:
        rows=[r for r in csv.reader(f) if r and not r[0].startswith('#') and r[0]!='date']
    return [r[0] for r in rows],np.array([[float(v) for v in r[1:25]] for r in rows])
def weather(cfg,test=False):
    dates,g=load_weather('solar_days_2023.csv');D,P=base_curves();scale=P.sum()*cfg['pv']/g.sum(axis=1).mean()
    if test: dates,g=load_weather('ghi_2022_socal.csv')
    data=D[None,:]-scale*g
    if test:return dates,data
    if cfg.get('scenario_indices') is not None:
        ix=cfg['scenario_indices'];return [dates[i] for i in ix],data[ix]
    if cfg['method']=='mean':return ['2023_mean'],data.mean(axis=0)[None,:]
    idx=np.random.default_rng(cfg['seed']).permutation(len(data))[:cfg['samples']]
    return [dates[i] for i in idx],data[idx]
def instance(cfg,delta):
    inst=build_instance(cfg['points'],2.,BREAKS2,delta_hourly=delta)
    inst.rho=1.75;inst.soc_step=.25;inst.c_g=40.
    if "cap_factor" in cfg:
        D,_=base_curves();inst.gen_cap=float(cfg["cap_factor"]*np.max(D)/2)
    return inst

def expected_model(cfg,deltas,cols,fixed=None):
    S=len(deltas);R=len(cols);inst=instance(cfg,deltas[0]);T=inst.T;n=inst.n_trips
    weights=np.asarray(cfg.get('weights',np.full(S,1/S)),dtype=float)
    if len(weights)!=S:weights=np.full(S,1/S) # single-day evaluation uses probability1
    assert np.all(weights>0) and abs(weights.sum()-1)<1e-10
    shared=R+2;nv=shared+S*4*T;c=np.zeros(nv);lb=np.zeros(nv);ub=np.full(nv,np.inf)
    AU=[];AE=[];BU=[];BE=[];meta=[];ue=ee=0
    for s,d in enumerate(deltas):
        ins=instance(cfg,d)
        cc,au,bu,ae,be,bounds,off,_,_,_,cap=_build_lp(ins,cols,SCENARIOS[cfg['arm']]['battery'],'cyclic')
        ox,og,oc,od,osoc,onb=off;m=np.empty(len(cc),int);m[:R]=np.arange(R);m[onb]=R;m[osoc]=R+1
        m[og:osoc]=np.arange(shared+s*4*T,shared+s*4*T+3*T)
        m[osoc+1:osoc+T+1]=np.arange(shared+s*4*T+3*T,shared+(s+1)*4*T)
        if s==0:c[:R]=cc[:R];c[R]=cc[onb]
        cc[:R]=0;cc[onb]=0;np.add.at(c,m,cc*weights[s])
        # Keep one common coverage block; all other equalities are scenario recourse.
        if s:ae=ae[n:];be=be[n:]
        for a,coll in [(au,AU),(ae,AE)]:
            rr,cl=np.nonzero(a);coll.append(coo_matrix((a[rr,cl],(rr,m[cl])),shape=(len(a),nv)).tocsr())
        meta.append(dict(balance=ue,cap=None if cap is None else ue+cap));ue+=len(bu);ee+=len(be)
        BU.extend(bu);BE.extend(be)
        for k,(l,u) in enumerate(bounds):
            lb[m[k]]=max(lb[m[k]],l or 0)
            if u is not None:ub[m[k]]=min(ub[m[k]],u)
    if fixed is not None:lb[:shared]=fixed;ub[:shared]=fixed
    return c,vstack(AU,format='csr'),np.array(BU),vstack(AE,format='csr'),np.array(BE),lb,ub,meta

def model(cfg,deltas,cols,fixed=None):
    m=expected_model(cfg,deltas,cols,fixed)
    if cfg.get('method')!='minimax':return m
    c,au,bu,ae,be,lb,ub,meta=m;R=len(cols);T=instance(cfg,deltas[0]).T;shared=R+2;nv=len(c);S=len(deltas)
    inst=instance(cfg,deltas[0]);rr=[];cc=[];vv=[]
    for j in range(S):
        offset=shared+j*4*T
        for t in range(T):
            for k,v in [(offset+t,inst.c_g),(offset+T+t,inst.eps_pen),(offset+2*T+t,inst.eps_pen+getattr(inst,'deg_cost',0.))]:rr.append(j);cc.append(k);vv.append(v)
        rr.append(j);cc.append(nv);vv.append(-1.)
    epi=coo_matrix((vv,(rr,cc)),shape=(S,nv+1)).tocsr()
    obj=np.r_[c,1.];obj[shared:nv]=0.
    return obj,vstack([hstack([au,csr_matrix((au.shape[0],1))]),epi],format='csr'),np.r_[bu,np.zeros(S)],hstack([ae,csr_matrix((ae.shape[0],1))],format='csr'),be,np.r_[lb,0.],np.r_[ub,np.inf],meta

def lp(m):
    c,au,bu,ae,be,lb,ub,_=m
    return linprog(c,A_ub=au,b_ub=bu,A_eq=ae,b_eq=be,bounds=list(zip(lb,ub)),method='highs')

def identity(cfg):
    manifest=json.loads((Path(__file__).parent/'release.json').read_text())
    for p,h in manifest['files'].items():
        if sha(ROOT/p)!=h:raise RuntimeError('Execution/input hash mismatch: '+p)
    return dict(config=cfg,config_sha256=digest(cfg),release_sha256=digest(manifest),reference_commit=manifest['reference_commit'],execution_commit=manifest['execution_commit'],physics=dict(G=7,rho=1.75,soc_step=.25,eta=0,c_g=40,c_v=45,c_b=36,eps_pen=.025,truck_boundary='full-full',battery_boundary='shared_s0_cyclic'),initialization=cfg.get('initialization','cold reference seeds'),master_sense='equal coverage / '+('minimize first-stage plus maximum finite-scenario recourse' if cfg.get('method')=='minimax' else 'minimize probability-weighted expected cost'),information='common truck energy profiles, Nb and initial SoC; full-day continuous BESS/fossil recourse')

class Journal:
    def __init__(self,out,ident):
        self.out=out;self.ident=ident;self.path=out/'accepted.columns.jsonl';self.cols=[];self.hash='0'*64
        if (out/'identity.json').exists():
            if json.loads((out/'identity.json').read_text())!=ident:raise RuntimeError('Incompatible run identity')
        else:
            if self.path.exists():raise RuntimeError('Journal without identity')
            atomic(out/'identity.json',ident)
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                r=json.loads(line);h=r.pop('hash')
                if r['previous']!=self.hash or digest(r)!=h or r['sequence']!=len(self.cols):raise RuntimeError('Corrupt journal; manual recovery required')
                self.cols.append(unpack(r['column']));self.hash=h
        cp=out/'checkpoint.json'
        if cp.exists():
            q=json.loads(cp.read_text())
            if q['identity_sha256']!=digest(ident) or q['count']>len(self.cols):raise RuntimeError('Checkpoint mismatch')
            lines=self.path.read_text().splitlines()
            prefix='0'*64 if not q['count'] else json.loads(lines[q['count']-1])['hash']
            if prefix!=q['journal_hash']:raise RuntimeError('Checkpoint prefix mismatch')
    def add(self,c,iteration):
        r=dict(sequence=len(self.cols),previous=self.hash,iteration=iteration,column=pack(c));r['hash']=digest(r)
        with open(self.path,'a') as f:f.write(json.dumps(r,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
        self.cols.append(c);self.hash=r['hash']
    def checkpoint(self,iteration,state,**extra):
        q=dict(identity_sha256=digest(self.ident),count=len(self.cols),journal_hash=self.hash,iteration=iteration,state=state,wall_time=time.time(),**extra)
        atomic(self.out/'checkpoint.json',q);atomic(self.out/'cg_status.json',q)
        return q

def phase_model(cfg,ds,cols,cap):
    m=list(model(cfg,ds,cols));c,au,bu,ae,be,lb,ub,meta=m;S=len(ds);T=instance(cfg,ds[0]).T;R=len(cols)
    # Per-slot generation bound; grid balance deficits are separate nonnegative artificials.
    for s in range(S):ub[R+2+s*4*T:R+2+s*4*T+T]=cap
    rows=np.concatenate([np.arange(md['balance'],md['balance']+T) for md in meta]);extra=S*T
    elast=coo_matrix((-np.ones(extra),(rows,np.arange(extra))),shape=(au.shape[0],extra)).tocsr()
    obj=np.zeros(len(c));obj[:R]=[1. if col.kind=='artificial' else 0. for col in cols]
    return (np.r_[obj,np.full(extra,1/S)],hstack([au,elast],format='csr'),bu,hstack([ae,csr_matrix((ae.shape[0],extra))],format='csr'),be,np.r_[lb,np.zeros(extra)],np.r_[ub,np.full(extra,np.inf)],meta)

def cg(cfg,out,args):
    import copy
    ident=identity(cfg);journal=Journal(out,ident);dates,ds=weather(cfg);inst=instance(cfg,ds[0]);caps=SCENARIOS[cfg['arm']]
    cp=out/'checkpoint.json';saved=json.loads(cp.read_text()) if cp.exists() else {};phase=saved.get('phase','phase1');begin=saved.get('iteration',-1)+1
    if saved.get('state')=='infeasible_lp':return
    if (out/'pool.json').exists():
        p=json.loads((out/'pool.json').read_text());assert p['identity_sha256']==digest(ident)
        if saved.get('pool_sha256'):assert saved['pool_sha256']==sha(out/'pool.json')
        journal.checkpoint(saved.get('iteration',-1),'certified' if p['certified'] else 'iteration_limit',phase='economic',pool_sha256=sha(out/'pool.json'),full_lp_lower_bound=p['full_lp_lower_bound']);return
    if not journal.cols:
        for c in initial_columns(inst,'cold',caps,'cyclic'):journal.add(c,-1)
    begin=max(begin,max(json.loads(l)['iteration'] for l in journal.path.read_text().splitlines())+1)
    seen={key(c) for c in journal.cols};last=time.monotonic();cert=False;res=None
    phaseinst=copy.deepcopy(inst);phaseinst.c_v=0.;phaseinst.eps_pen=0.;phaseinst.deg_cost=0.
    journal.checkpoint(begin-1,'running',phase=phase)
    for it in range(begin,args.max_iter):
        if STOP:journal.checkpoint(it-1,'paused',phase=phase);raise SystemExit(75)
        if phase=='economic':
            proof=json.loads((out/'phase1_certificate.json').read_text());assert proof['identity_sha256']==digest(ident) and proof['classification']=='LP_FEASIBLE_NOT_INTEGER_PROOF'
        cols=journal.cols;t=time.monotonic()
        if phase=='phase1':m=phase_model(cfg,ds,cols,float(inst.gen_cap))
        else:
            m=list(model(cfg,ds,cols))
            for k,c in enumerate(cols):
                if c.kind=='artificial':m[6][k]=0.
        res=lp(m)
        if not res.success:raise RuntimeError('RMP solver failure: '+res.message)
        lpsec=time.monotonic()-t;alpha=res.eqlin.marginals[:inst.n_trips];mu=sum((-res.ineqlin.marginals[md['balance']:md['balance']+inst.T] for md in m[-1]),np.zeros(inst.T));nu=np.zeros(inst.T)
        for md in m[-1]:
            if md['cap'] is not None:nu-=res.ineqlin.marginals[md['cap']:md['cap']+inst.T]
        t=time.monotonic();priced=price_truck_dp(phaseinst if phase=='phase1' else inst,alpha,mu,nu=nu,allow_discharge=caps['allow_discharge'],soc_mode='cyclic',tol=args.tol);dpsec=time.monotonic()-t
        best=float(priced[0][1]) if priced else 0.;event=dict(iteration=it,phase=phase,objective=float(res.fun),best_reduced_cost=best,columns=len(cols),lp_seconds=lpsec,pricing_seconds=dpsec)
        with open(out/'iterations.jsonl','a') as f:f.write(json.dumps(event)+'\n');f.flush();os.fsync(f.fileno())
        print(json.dumps(event),flush=True)
        if not priced:
            if phase=='phase1':
                lower=float(res.fun-inst.n_trips*args.tol)
                classification='LP_INFEASIBLE_CERTIFICATE' if lower>1e-6 else 'LP_FEASIBLE_NOT_INTEGER_PROOF' if res.fun<1e-7 else 'NUMERICALLY_UNRESOLVED'
                proof=dict(identity_sha256=digest(ident),objective=float(res.fun),full_phase1_lower_bound=lower,classification=classification,tolerance=args.tol,iteration=it)
                atomic(out/'phase1_certificate.json',proof)
                if classification=='LP_INFEASIBLE_CERTIFICATE':journal.checkpoint(it,'infeasible_lp',phase='phase1',certificate_sha256=sha(out/'phase1_certificate.json'));return
                if classification=='NUMERICALLY_UNRESOLVED':raise RuntimeError('Phase-I numerical ambiguity')
                phase='economic';journal.checkpoint(it,'phase_transition',phase=phase,certificate_sha256=sha(out/'phase1_certificate.json'));continue
            cert=True;break
        col,rc=priced[0];cost=0. if phase=='phase1' else col.cost(inst.eps_pen);direct=cost-col.a@alpha+col.e@mu+np.maximum(col.e,0)@nu
        if abs(direct-rc)>1e-5:raise RuntimeError('Reconstructed reduced cost mismatch')
        if phase=='phase1':col.fixed_cost=inst.c_v
        if not replay(inst,col,caps['allow_discharge']):raise RuntimeError('Independent physical replay failed')
        if key(col) in seen:raise RuntimeError('Improving duplicate')
        journal.add(col,it);seen.add(key(col))
        if (it+1)%25==0 or time.monotonic()-last>=60 or STOP:
            q=journal.checkpoint(it,'checkpointed',phase=phase,last_iteration=event);atomic(out/('milestone-%06d.json'%it),q);last=time.monotonic()
    else:it=args.max_iter-1
    if phase!='economic' or res is None:raise RuntimeError('Phase-I incomplete; no feasible policy claim')
    real=[c for c in journal.cols if c.kind=='truck']
    for c in real:
        if not replay(inst,c,caps['allow_discharge']):raise RuntimeError('Frozen pool replay failed')
    p=dict(identity_sha256=digest(ident),columns=[pack(c) for c in real],training_dates=dates,certified=cert,lp_objective=float(res.fun),full_lp_lower_bound=float(res.fun-inst.n_trips*args.tol) if cert else None,tolerance=args.tol,scope='full discretized common-profile capped LP' if cert else 'restricted pool only',physical_replay='all truck profiles passed independent time/location/SoC reachability',phase1_certificate_sha256=sha(out/'phase1_certificate.json'))
    atomic(out/'pool.json',p);journal.checkpoint(it,'certified' if cert else 'iteration_limit',phase='economic',pool_sha256=sha(out/'pool.json'),full_lp_lower_bound=p['full_lp_lower_bound'])

def replay(inst,col,allow_discharge=True):
    """Independent feasibility reachability with a prescribed grid profile and trip set.
    No pricing duals or source-DP reconstruction; permits only the selected trips.
    """
    selected=sorted([tr for tr in inst.trips if col.a[tr.idx]>.5],key=lambda tr:tr.start)
    if not selected or np.max(np.abs(col.a-np.rint(col.a)))>1e-9:return False
    step=inst.soc_step;top=int(round(inst.G/step));T=inst.T;profile=col.e
    if np.any(np.abs(profile)>inst.rho+1e-8) or (not allow_discharge and np.any(profile < -1e-8)):return False
    levels=profile/step
    if np.max(np.abs(levels-np.rint(levels)))>1e-8:return False
    grid=np.rint(levels).astype(int);states=[set() for _ in range(T+1)];states[0].add((inst.depot,top,0))
    stations=getattr(inst,'charge_locs',None) or [inst.depot]
    for t in range(T):
        for loc,charge,k in states[t]:
            if k<len(selected) and selected[k].start<t:continue
            if grid[t]:
                if loc in stations and 0<=charge+grid[t]<=top:states[t+1].add((loc,charge+grid[t],k))
                continue
            states[t+1].add((loc,charge,k))
            for dest in range(inst.dist.shape[0]):
                dt=inst.deadhead_time(loc,dest);energy=inst.deadhead_energy(loc,dest)/step
                if loc!=dest and dt>0 and t+dt<=T and not np.any(grid[t:t+dt]) and abs(energy-round(energy))<1e-8 and charge>=round(energy):
                    states[t+dt].add((dest,charge-int(round(energy)),k))
            if k<len(selected):
                tr=selected[k];energy=tr.energy/step
                if tr.start==t and tr.sloc==loc and tr.end<=T and not np.any(grid[t:tr.end]) and abs(energy-round(energy))<1e-8 and charge>=round(energy):
                    states[tr.end].add((tr.eloc,charge-int(round(energy)),k+1))
    return (inst.depot,top,len(selected)) in states[T]

def read_pool(cfg,out):
    ident=identity(cfg)
    if json.loads((out/'identity.json').read_text())!=ident:raise RuntimeError('Identity mismatch')
    status=json.loads((out/'cg_status.json').read_text());p=out/'pool.json'
    if sha(p)!=status['pool_sha256']:raise RuntimeError('Pool hash mismatch')
    pool=json.loads(p.read_text());return pool,[unpack(c) for c in pool['columns']]

def mip(cfg,out,args):
    import gurobipy as gp
    if json.loads((out/'cg_status.json').read_text())['state']=='infeasible_lp':
        ident=identity(cfg);assert json.loads((out/'identity.json').read_text())==ident
        cp=json.loads((out/'cg_status.json').read_text());proof=json.loads((out/'phase1_certificate.json').read_text());assert cp['certificate_sha256']==sha(out/'phase1_certificate.json') and proof['identity_sha256']==digest(ident) and proof['classification']=='LP_INFEASIBLE_CERTIFICATE'
        atomic(out/'mip_result.json',dict(status='skipped_full_lp_infeasible',scope='Phase-I full discretized LP infeasibility; no MIP search'));return
    pool,cols=read_pool(cfg,out)
    if (out/'mip_result.json').exists():raise RuntimeError('MIP result exists; never overwrite/restart as continuation')
    _,ds=weather(cfg);m=model(cfg,ds,cols);c,au,bu,ae,be,lb,ub,_=m
    gm=gp.Model('evspv2g_common_profile_saa');gm.Params.LogFile=str(out/'gurobi.log');gm.Params.Threads=1;gm.Params.TimeLimit=args.mip_seconds;gm.Params.MIPGap=1e-4;gm.Params.Seed=cfg['seed']
    types=np.array(['C']*len(c));types[:len(cols)+1]='I'
    x=gm.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=types);gm.addMConstr(au,x,'<',bu);gm.addMConstr(ae,x,'=',be);gm.optimize()
    result=dict(status=int(gm.Status),runtime=float(gm.Runtime),solution_count=int(gm.SolCount),pool_sha256=sha(out/'pool.json'),scope='finite-pool integer model only; branch-and-bound state not resumable',full_lp_lower_bound=pool['full_lp_lower_bound'],physical_replay=pool['physical_replay'])
    if gm.SolCount:
        z=x.X;residual=max(float(np.max(np.abs(ae@z-be))),float(np.max(np.maximum(au@z-bu,0))),float(np.max(np.maximum(lb-z,0))),float(np.max(np.maximum(z-ub,0))))
        integer_error=float(np.max(np.abs(z[:len(cols)+1]-np.rint(z[:len(cols)+1]))))
        if residual>1e-5 or integer_error>1e-5:raise RuntimeError('MIP incumbent residual/integrality failure')
        result.update(objective=float(gm.ObjVal),pool_bound=float(gm.ObjBound),pool_gap=float(gm.MIPGap),shared=z[:len(cols)+2].tolist(),max_residual=residual,integer_error=integer_error)
        gm.write(str(out/'incumbent.sol'))
    atomic(out/'mip_result.json',result)
    if not gm.SolCount:raise RuntimeError('No MIP incumbent; evaluation gated')

def evaluate(cfg,out,args):
    r=json.loads((out/'mip_result.json').read_text())
    if r.get('status')=='skipped_full_lp_infeasible':
        identity(cfg);atomic(out/'evaluation_status.json',dict(state='skipped_no_training_policy',days=0));return
    pool,cols=read_pool(cfg,out)
    if r['pool_sha256']!=sha(out/'pool.json'):raise RuntimeError('MIP pool provenance mismatch')
    fixed=np.array(r['shared']);fixed[:-1]=np.rint(fixed[:-1]);dates,ds=weather(cfg,True)
    if cfg.get('parent_indices') is not None and not (out/'parent_training_evaluation.json').exists():
        parent=dict(cfg,method='saa',scenario_indices=cfg['parent_indices']);parent.pop('weights',None);pdates,pds=weather(parent);pr=[]
        for date,delta in zip(pdates,pds):
            sol=lp(model(parent,[delta],cols,fixed))
            if not sol.success and sol.status!=2:raise RuntimeError('Parent training evaluation solver failure')
            pr.append(dict(date=date,cost=float(sol.fun) if sol.success else None,status=int(sol.status)))
        if cfg.get('method')!='reduced' and any(v['cost'] is None for v in pr):raise RuntimeError('Fitted policy fails parent training recourse; investigate rounding/solver consistency')
        atomic(out/'parent_training_evaluation.json',dict(days=pr,scope='unreduced parent sample evaluation; no policy repair or test-data selection'))
    path=out/'evaluation.jsonl';old=[] if not path.exists() else [json.loads(l) for l in path.read_text().splitlines()]
    if [x['date'] for x in old]!=dates[:len(old)]:raise RuntimeError('Evaluation prefix mismatch')
    for j in range(len(old),len(ds)):
        res=lp(model(cfg,ds[j:j+1],cols,fixed));event=dict(date=dates[j],cost=float(res.fun) if res.success else None,status=int(res.status))
        if not res.success and res.status!=2:raise RuntimeError('Evaluation numerical/solver failure '+res.message)
        with open(path,'a') as f:f.write(json.dumps(event)+'\n');f.flush();os.fsync(f.fileno())
        old.append(event)
        if (j+1)%25==0 or STOP:atomic(out/'evaluation_status.json',dict(state='paused' if STOP else 'running',days=len(old),mip_sha256=sha(out/'mip_result.json')))
        if STOP:raise SystemExit(75)
    good=[e['cost'] for e in old if e['cost'] is not None]
    atomic(out/'evaluation_status.json',dict(state='complete',days=len(old),violations=len(old)-len(good),mean_conditional_on_feasible=float(np.mean(good)) if good else None,quantiles=np.quantile(good,[.05,.5,.95,.99]).tolist() if good else None,mip_sha256=sha(out/'mip_result.json'),evaluation_scope='2022 development evaluation, independent of 2023 training; reused by submitted manuscript, not fresh scientific holdout; full-day recourse'))

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['cg','mip','evaluate']);p.add_argument('--campaign',type=Path,required=True);p.add_argument('--case',type=int,required=True);p.add_argument('--checkpoint-every',type=int,default=25);p.add_argument('--max-iter',type=int,default=5000);p.add_argument('--tol',type=float,default=1e-6);p.add_argument('--mip-seconds',type=float,default=900);a=p.parse_args()
    cfg=json.loads((a.campaign/'cases.json').read_text())[a.case];out=a.campaign/'cases'/('%04d'%a.case);out.mkdir(parents=True,exist_ok=True)
    if a.max_iter!=5000 or a.tol!=1e-6 or a.checkpoint_every!=25 or a.mip_seconds!=900:raise RuntimeError('Non-release numerical settings require a new release')
    atomic(out/(a.mode+'_environment_'+str(time.time_ns())+'.json'),dict(python=sys.version,numpy=np.__version__,host=os.uname().nodename,slurm_job=os.environ.get('SLURM_JOB_ID'),slurm_restart=os.environ.get('SLURM_RESTART_COUNT'),settings=vars(a)|{'campaign':str(a.campaign)}))
    lock=open(out/(a.mode+'.lock'),'w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:globals()[a.mode](cfg,out,a)
    except Exception as e:
        atomic(out/(a.mode+'_error.json'),dict(error=repr(e),time=time.time()));raise
if __name__=='__main__':main()
