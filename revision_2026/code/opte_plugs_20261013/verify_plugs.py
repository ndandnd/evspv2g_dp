"""Independent no-solve station/time connector verification.

This verifier uses a separately materialized DAG and scalar pricing recurrence,
not the runtime's vectorized recurrence. Physical replay derives occupancy from
actual path events. Certificates include the finite plug-capacity dual constant.
Floating-point checks are not exact-arithmetic or branch-and-price proofs.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent;RUNTIME=ROOT/'runtime';FROZEN=RUNTIME/'frozen'
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(RUNTIME))
import plug_instances as inputs
from plug_problem import PlugProblem,PlugColumn,columns_from_record
import master
import arc_flow
from scipy import sparse
import numpy as np
from extension_models import build_extended_graph,_seeds_with_witnesses,_hybrid_matrices
from verify_lp_scaling import _primal,_direct_certificate,_periodic_bess_price
from direct_mip_1000 import integer_indices
from rmp_solver import replay_rmp
from lp_scaling_models import peak_rss_bytes
from run_pilot import safe

TOL=1e-6
THREADS={'OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS'}
_AUDITS=0;_SINGLE_CLI=False


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def fixed_seeds(problem):
    """Frozen original singleton profiles; independently construct occupancy."""
    originals,proofs=_seeds_with_witnesses(problem.inst);answer=[]
    for col,w in zip(originals,proofs):
        witness={k:w[k] for k in ('family','states','kinds','energy','task_ids')}
        occ=np.zeros(problem.capacities.shape)
        for st,kind,energy in zip(w['states'][:-1],w['kinds'],w['energy']):
            if kind in ('charge','discharge'):
                require(energy!=0,'Seed has zero active exchange')
                occ[problem.station_index[int(st[1])],int(st[0])]+=1
        answer.append(PlugColumn(col.kind,col.a.copy(),col.e.copy(),float(col.fixed_cost),occ,witness,col.label))
    require(len(answer)==problem.inst.n_trips,'Missing original physical singleton')
    return answer


def validate_column(problem,col):
    inst=problem.inst;a=np.asarray(col.a);e=np.asarray(col.e);b=np.asarray(col.occupancy)
    require(a.shape==(inst.n_trips,) and e.shape==(inst.T,) and b.shape==problem.capacities.shape,'Column shapes differ')
    require(all(np.all(np.isfinite(x)) for x in (a,e,b)) and finite(col.fixed_cost),'Nonfinite column')
    require(np.all((a==0)|(a==1)) and a.sum()>=1 and np.all((b==0)|(b==1))
            and np.all(b.sum(axis=0)<=1),'Invalid route coverage/occupancy')
    require(col.kind in ('truck','artificial') and col.fixed_cost>=0,'Invalid column type/cost')
    if col.kind=='artificial':
        require(np.count_nonzero(a)==1 and not np.any(e) and not np.any(b) and col.witness is None,
                'Nonphysical artificial coefficients')


def physical_column(problem,col,seeds=None,tol=TOL):
    """Separate event-by-event replay; never call the new runtime replay."""
    validate_column(problem,col);inst=problem.inst;w=col.witness
    require(col.kind=='truck' and isinstance(w,dict),'Real route needs witness')
    st=np.asarray(w['states'],float);draw=np.asarray(w['energy'],float);kinds=w['kinds'];task_ids=list(w['task_ids'])
    require(st.shape==(len(kinds)+1,4) and draw.shape==(len(kinds),)
            and np.all(np.isfinite(st)) and np.all(np.isfinite(draw)),'Malformed physical witness')
    require(np.max(abs(st[0]-[0,inst.depot,inst.G,0]))<=tol
            and np.max(abs(st[-1]-[inst.T,inst.depot,inst.G,1]))<=tol,'Full/depot/served boundaries differ')
    require(np.max(abs(st[:,[0,1,3]]-np.rint(st[:,[0,1,3]])))<=tol,'Fractional time/location/served state')
    require(np.all((st[:,0]>=0)&(st[:,0]<=inst.T)) and np.all((st[:,1]>=0)&(st[:,1]<len(inst.dist)))
            and np.all((st[:,3]==0)|(st[:,3]==1)),'Out-of-domain event states')
    require(np.all(st[:,2]>=-tol) and np.all(st[:,2]<=inst.G+tol),'State of charge outside capacity')
    if w['family']=='dp_path':
        require(np.max(abs(st[:,2]/inst.soc_step-np.rint(st[:,2]/inst.soc_step)))<=tol,'Off-grid DP route')
        rate=math.floor(inst.rho/inst.soc_step)*inst.soc_step
    elif w['family']=='initial_singleton':
        seeds=fixed_seeds(problem) if seeds is None else seeds
        require(any(s.witness==w and s.fixed_cost==col.fixed_cost and np.array_equal(s.a,col.a)
                    and np.array_equal(s.e,col.e) and np.array_equal(s.occupancy,col.occupancy) for s in seeds),
                'Seed differs from its predeclared original witness')
        rate=inst.rho
    else:raise ValueError('Unknown route family')
    a=np.zeros(inst.n_trips);e=np.zeros(inst.T);b=np.zeros_like(problem.capacities)
    tripmap={tr.idx:tr for tr in inst.trips};task_position=0;max_dynamics=0.
    for before,after,kind,energy in zip(st[:-1],st[1:],kinds,draw):
        t,l,s,served=before;nt,nl,ns,nserved=after;t,l,nt,nl=map(int,(t,l,nt,nl))
        require(nt>t,'Path does not increase time');traction=0.;expected_served=served
        if kind=='wait':require(nt==t+1 and l==nl and energy==0,'Invalid idle event')
        elif kind in ('charge','discharge'):
            require(nt==t+1 and l==nl and l in problem.station_index,'Invalid exchange time/location')
            require((energy>0 if kind=='charge' else energy<0) and abs(energy)<=rate+tol,'Invalid exchange magnitude/sign')
            if w['family']=='dp_path':require(abs(energy/inst.soc_step-round(energy/inst.soc_step))<=tol,'Off-grid exchange')
            b[problem.station_index[l],t]+=1
        elif kind=='travel':
            require(l!=nl and nt-t==inst.deadhead_time(l,nl) and energy==0,'Invalid deadhead event')
            traction=inst.deadhead_energy(l,nl)
        elif kind=='task':
            require(task_position<len(task_ids),'Missing task identity');tid=task_ids[task_position];task_position+=1
            require(type(tid) is int and tid in tripmap,'Unknown task identity');tr=tripmap[tid]
            require((t,nt,l,nl)==(tr.start,tr.end,tr.sloc,tr.eloc) and energy==0,'Task timing/location differs')
            traction=tr.energy;a[tid]+=1;expected_served=1
        else:raise ValueError('Unknown event kind')
        max_dynamics=max(max_dynamics,abs(ns-s-energy+traction));e[t]+=energy
        require(nserved==expected_served,'Served flag differs')
    require(task_position==len(task_ids) and a.sum()>=1 and np.all(a<=1),'Task identities repeated/unused')
    cost=inst.c_v+getattr(inst,'deg_cost',0.)*np.maximum(-e,0).sum()
    residuals={'dynamics':float(max_dynamics),'task_coefficients':float(np.max(abs(a-col.a))),
        'energy_coefficients':float(np.max(abs(e-col.e))),'occupancy_coefficients':float(np.max(abs(b-col.occupancy))),
        'fixed_cost':float(abs(cost-col.fixed_cost))}
    require(max(residuals.values())<=tol,'Independent route replay failed: '+str(residuals))
    return {'passed':True,'residuals':residuals,'occupancy':b.tolist(),'events':len(kinds),'tasks':np.flatnonzero(a).tolist()}


def independent_rmp(problem,cols,phase):
    """Original vendor master plus independently assembled occupancy rows."""
    require(phase in ('economic','feasibility'),'Unknown phase')
    for col in cols:validate_column(problem,col)
    c,au,bu,ae,be,bounds,off,*_=master._build_lp(problem.inst,cols,True,soc_mode='cyclic')
    c=np.asarray(c);lb=np.array([0 if l is None else l for l,u in bounds],float);ub=np.array([np.inf if u is None else u for l,u in bounds],float)
    if phase=='feasibility':
        c=np.zeros_like(c);c[:len(cols)]=[float(x.kind=='artificial') for x in cols]
    else:
        for i,col in enumerate(cols):
            if col.kind=='artificial':c[i]=0.;ub[i]=0.
    values=[];rr=[];cc=[]
    for j,col in enumerate(cols):
        for row,cell in enumerate(problem.finite_cells):
            val=col.occupancy.ravel()[cell]
            if val:rr.append(row);cc.append(j);values.append(val)
    plugs=sparse.coo_matrix((values,(rr,cc)),shape=(len(problem.finite_cells),len(c))).tocsr()
    return c,lb,ub,sparse.csr_matrix(ae),np.asarray(be),sparse.vstack((sparse.csr_matrix(au),plugs),format='csr'),np.r_[bu,problem.capacity_vector],off,len(bu)


def audit_pool_vector(problem,cols,vector,objective,integer=False,phase='economic'):
    c,lb,ub,ae,be,au,bu,off,plug_start=independent_rmp(problem,cols,phase)
    residuals=_primal(c,lb,ub,ae,be,au,bu,vector,objective)
    if integer:
        ii=np.r_[np.arange(len(cols)),off[5]].astype(int)
        residuals['integrality']=float(np.max(abs(vector[ii]-np.rint(vector[ii])),initial=0))
    require(max(residuals.values())<=TOL,'Pool raw primal failed: '+str(residuals))
    seeds=fixed_seeds(problem);proofs=[];occupancy=np.zeros_like(problem.capacities);artificial=0.
    for i,(col,w) in enumerate(zip(cols,vector[:len(cols)])):
        occupancy+=w*col.occupancy
        if col.kind=='artificial':artificial+=w
        elif w>0:
            proof=physical_column(problem,col,seeds);proof.pop('occupancy')
            proofs.append({'column':i,'weight':float(w),'physical':proof})
    violation=float(np.max(np.maximum(occupancy.ravel()[problem.finite_cells]-problem.capacity_vector,0),initial=0))
    require(violation<=TOL,'Station/time occupancy violates capacity')
    aggregate=None
    if phase=='economic':
        require(artificial<=TOL,'Artificial mass in physical economic solution')
        aggregate=replay_rmp(problem.inst,cols,vector,off,list(zip(lb,ub)),integer,objective,tol=TOL)
        require(aggregate['original_model_feasible'],'Nonphysical artificial incumbent')
    return {'passed':True,'raw_residuals':residuals,'artificial_mass':float(artificial),
        'station_order':list(problem.stations),'occupancy':occupancy.tolist(),'max_plug_violation':violation,
        'selected_route_proofs':proofs,'original_vendor_aggregate':aggregate,'phase':phase}


def scalar_graph_price(problem,graph,alpha,mu,nu,pi,cost_factor=1):
    """Explicit-arc scalar recurrence, independent of vectorized pricing."""
    inst=problem.inst;dist=np.full(graph.n_nodes,np.inf);dist[graph.source]=0.
    for edge in range(graph.n_arcs):
        tail=int(graph.tail[edge]);head=int(graph.head[edge]);t,l=map(int,graph.states[tail,:2]);e=float(graph.energy[edge])
        value=float(mu[t]*e+nu[t]*max(e,0)+cost_factor*(inst.eps_pen*abs(e)+getattr(inst,'deg_cost',0.)*max(-e,0)))
        if graph.task[edge]>=0:value-=alpha[int(graph.task[edge])]
        if graph.kind[edge] in (arc_flow.CHARGE,arc_flow.DISCHARGE):value+=pi[problem.station_index[l],t]
        if dist[tail]+value<dist[head]:dist[head]=dist[tail]+value
    return float(cost_factor*inst.c_v+dist[graph.sink])


def family_certificate(problem,graph,seeds,alpha,mu,nu,plug_price,phase='economic'):
    """Numerically repaired full-family dual, with explicit finite K*pi term."""
    require(phase in ('economic','feasibility'),'Unknown certificate phase');inst=problem.inst
    a=np.asarray(alpha,float).copy();m=np.asarray(mu,float).copy();v=np.asarray(nu,float).copy();p=np.asarray(plug_price,float).copy()
    require(a.shape==(inst.n_trips,) and m.shape==v.shape==(inst.T,) and p.shape==problem.capacities.shape,'Price dimensions differ')
    require(all(np.all(np.isfinite(x)) for x in (a,m,v,p)),'Nonfinite saved prices')
    factor=1 if phase=='economic' else 0
    def prices(a,m,v,p):
        gr=scalar_graph_price(problem,graph,a,m,v,p,factor)
        sr=min(float(factor*s.cost(inst.eps_pen)-a@s.a+m@s.e+v@np.maximum(s.e,0)+(p*s.occupancy).sum()) for s in seeds)
        bess=_periodic_bess_price(inst,m,v)['unit_reduced_cost'] if factor else 0.
        penalty=float(problem.capacity_vector@p.ravel()[problem.finite_cells])
        objective=float(a.sum()+m@inst.Delta-penalty)
        require(all(math.isfinite(x) for x in (gr,sr,bess,objective)),'Nonfinite family price')
        return {'graph_min_reduced_cost':gr,'seed_min_reduced_cost':sr,'route_min_reduced_cost':min(gr,sr),
            'unit_bess_reduced_cost':bess,'finite_plug_capacity_dual_penalty':penalty,'dual_objective':objective}
    raw=prices(a,m,v,p);original=[x.copy() for x in (a,m,v,p)]
    if factor:m=np.clip(m,0,inst.c_g)
    else:m=np.zeros(inst.T);a=np.minimum(a,1.)
    v=np.zeros(inst.T);p=np.maximum(p,0);p.ravel()[np.flatnonzero(~np.isfinite(problem.capacities.ravel()))]=0
    projected=prices(a,m,v,p);contraction=1.;epsilon=0.;reserve=1e-9
    if factor:
        require(inst.c_b>reserve and inst.c_v>=0 and inst.eps_pen>=0 and getattr(inst,'deg_cost',0)>=0,'Unsupported negative-cost repair')
        for _ in range(3):
            defect=max(0.,-projected['unit_bess_reduced_cost'])
            if defect==0:break
            scale=(inst.c_b-reserve)/(inst.c_b+defect);a*=scale;m*=scale;p*=scale;contraction*=scale
            projected=prices(a,m,v,p)
    final=projected
    for _ in range(3):
        defect=max(0.,-final['route_min_reduced_cost'])
        if defect==0:break
        shift=defect+max(reserve,1e-12*max(1.,float(np.max(abs(a)))));a-=shift;epsilon+=shift
        final=prices(a,m,v,p)
    passed=bool(np.all(p>=0) and np.all(m>=0) and np.all(m<=factor*inst.c_g)
        and (factor or np.all(a<=1)) and final['route_min_reduced_cost']>=0 and final['unit_bess_reduced_cost']>=0)
    lower=max(0.,final['dual_objective']) if passed else None
    return {'passed':passed,'phase':phase,'raw_price_diagnostics':raw,'final_price_diagnostics':final,
        'full_family_lower_bound':lower,'nonnegative_objective_bound_used':bool(passed and final['dual_objective']<0),
        'phase1_positive_bound_infeasibility_evidence':bool(not factor and passed and lower>TOL),
        'global_economic_bound':lower if factor else None,
        'repairs':{'price_contraction':contraction,'task_price_decrease':epsilon,'task_price_repair_loss':inst.n_trips*epsilon,
            'total_dual_change':raw['dual_objective']-final['dual_objective'],
            'max_price_changes':{k:float(np.max(abs(x-y),initial=0)) for k,x,y in zip(('alpha','mu','nu','plug_price'),original,(a,m,v,p))}},
        'repaired_prices':{'alpha':a.tolist(),'mu':m.tolist(),'nu':v.tolist(),'plug_price':p.tolist()},
        'convergence_sized_task_repair':epsilon<=TOL,
        'scope':'Independent floating-point full graph/real seed/periodic BESS pricing, finite plug dual constant included; Phase-I bound is not an economic bound'}


def independent_direct(problem,graph,seeds):
    c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(problem.inst,graph,seeds)
    rr=[];cc=[];vv=[];rowof={int(cell):i for i,cell in enumerate(problem.finite_cells)}
    for edge in np.flatnonzero((graph.kind==arc_flow.CHARGE)|(graph.kind==arc_flow.DISCHARGE)):
        t,l=map(int,graph.states[graph.tail[edge],:2]);cell=problem.station_index[l]*problem.inst.T+t
        if cell in rowof:rr.append(rowof[cell]);cc.append(int(edge));vv.append(1.)
    for j,col in enumerate(seeds):
        for cell in np.flatnonzero(col.occupancy.ravel()):
            if int(cell) in rowof:rr.append(rowof[int(cell)]);cc.append(off['seed_start']+j);vv.append(1.)
    plugs=sparse.coo_matrix((vv,(rr,cc)),shape=(len(rowof),len(c))).tocsr()
    return c,lb,ub,ae,be,sparse.vstack((au,plugs),format='csr'),np.r_[bu,problem.capacity_vector],off,len(bu)


def graph_column(problem,graph,arcs):
    require(bool(arcs),'Empty path');inst=problem.inst
    nodes=[int(graph.tail[arcs[0]])]+[int(graph.head[j]) for j in arcs]
    states=[[int(graph.states[j,0]),int(graph.states[j,1]),float(graph.states[j,2]*graph.step),int(graph.states[j,3])] for j in nodes]
    a=np.zeros(inst.n_trips);e=np.zeros(inst.T);occ=np.zeros_like(problem.capacities);kinds=[];draws=[];tasks=[]
    for j in arcs:
        t,l=map(int,graph.states[graph.tail[j],:2]);kind=arc_flow.KIND_NAMES[int(graph.kind[j])];energy=float(graph.energy[j])
        kinds.append(kind);draws.append(energy);e[t]+=energy
        if kind in ('charge','discharge'):occ[problem.station_index[l],t]+=1
        if graph.task[j]>=0:tid=int(graph.task[j]);a[tid]+=1;tasks.append(tid)
    return PlugColumn('truck',a,e,float(inst.c_v+getattr(inst,'deg_cost',0.)*np.maximum(-e,0).sum()),occ,
        {'family':'dp_path','states':states,'kinds':kinds,'energy':draws,'task_ids':tasks},'independent_decomposition')


def audit_direct_vector(problem,graph,seeds,vector,objective,integer=False):
    c,lb,ub,ae,be,au,bu,off,plug_start=independent_direct(problem,graph,seeds)
    residuals=_primal(c,lb,ub,ae,be,au,bu,vector,objective)
    if integer:
        ii=integer_indices(graph,off,len(c));residuals['integrality']=float(np.max(abs(vector[ii]-np.rint(vector[ii])),initial=0))
    require(max(residuals.values())<=TOL,'Direct raw primal failed: '+str(residuals))
    routes=arc_flow.decompose_paths(graph,vector[:graph.n_arcs]);cols=[];weights=[]
    reconstructed=np.zeros(graph.n_arcs)
    for path in routes:
        cols.append(graph_column(problem,graph,path['arcs']));weights.append(path['weight']);reconstructed[path['arcs']]+=path['weight']
    residuals['decomposed_arc_flow']=float(np.max(abs(reconstructed-vector[:graph.n_arcs]),initial=0))
    residuals['decomposed_fleet']=abs(float(sum(weights))-float(vector[off['fleet']]))
    require(max(residuals.values())<=TOL,'Direct decomposition differs from raw flow')
    for j,col in enumerate(seeds):
        w=float(vector[off['seed_start']+j])
        if w>0:cols.append(col);weights.append(w)
    T=problem.inst.T
    canonical=np.r_[weights,vector[off['g']:off['g']+T],vector[off['charge']:off['charge']+T],
        vector[off['discharge']:off['discharge']+T],vector[off['soc']:off['soc']+T+1],vector[off['nb']]]
    replay=audit_pool_vector(problem,cols,canonical,objective,integer)
    return {'passed':True,'raw_residuals':residuals,'physical_replay':replay,'decomposed_paths':len(routes)},(c,lb,ub,ae,be,au,bu,off,plug_start)


def checked_path(root,name):
    p=(root/name).resolve();require(p.is_relative_to(root.resolve()) and p.is_file(),'Missing or escaping evidence: '+name);return p


def read_columns(path,problem,real_only=False):
    with gzip.open(path,'rt') as f:cols=columns_from_record(json.load(f))
    require(bool(cols),'Empty pool')
    for col in cols:validate_column(problem,col)
    if real_only:require(all(c.kind=='truck' for c in cols),'Artificial in integer pool')
    return cols


def column_key(col):
    return (col.kind,float(col.fixed_cost),col.a.tobytes(),col.e.tobytes(),col.occupancy.tobytes())


def saved_price_identity(problem,data,ae,au,plug_start,direct=False,graph=None):
    pe=np.asarray(data['native_eq_dual']);pu=np.asarray(data['native_ub_dual']);rc=np.asarray(data['native_reduced_cost'])
    require(pe.shape==(ae.shape[0],) and pu.shape==(au.shape[0],) and rc.shape==(ae.shape[1],),'Native dual shapes differ')
    require(all(np.all(np.isfinite(x)) for x in (pe,pu,rc)),'Nonfinite native dual')
    n,T=problem.inst.n_trips,problem.inst.T;start=graph.n_nodes if direct else 0
    alpha=pe[start:start+n];mu=-pu[:T];nu=np.zeros(T);pi=np.zeros_like(problem.capacities)
    pi.ravel()[problem.finite_cells]=-pu[plug_start:]
    if not direct:
        for name,value in (('alpha',alpha),('mu',mu),('nu',nu),('plug_price',pi)):
            require(np.asarray(data[name]).shape==value.shape and np.max(abs(data[name]-value),initial=0)<=1e-10,'Saved price does not match native row dual: '+name)
    return alpha,mu,nu,pi


def audit_snapshot(folder,problem,graph,seeds,hashes,phase):
    prefix='phase1' if phase=='feasibility' else 'phase2'
    names=[prefix+'_stopping'+suffix for suffix in ('_columns.json.gz','_primal.npz','.json')]
    present=[(folder/name).exists() for name in names]
    if not any(present):return None
    require(all(present) and set(names).issubset(hashes),'Incomplete or unhashed stopping snapshot')
    cols=read_columns(folder/names[0],problem);meta=json.loads((folder/names[2]).read_text())
    require(meta.get('phase')==phase and meta.get('native_status')==2 and meta.get('columns')==len(cols),'Mismatched stopping metadata')
    with np.load(folder/names[1],allow_pickle=False) as saved:data={k:saved[k] for k in saved.files}
    objective=meta['objective'];require(finite(objective),'Nonfinite stopping objective')
    model=independent_rmp(problem,cols,phase);c,lb,ub,ae,be,au,bu,off,plug_start=model
    primal=audit_pool_vector(problem,cols,data['x'],objective,False,phase)
    require(abs(primal['artificial_mass']-meta['artificial_mass'])<=TOL,'Artificial mass metadata differs')
    prices=saved_price_identity(problem,data,ae,au,plug_start)
    native=_direct_certificate(c,lb,ub,ae,be,au,bu,data['x'],data['native_eq_dual'],data['native_ub_dual'],data['native_reduced_cost'],objective)
    certificate=family_certificate(problem,graph,seeds,*prices,phase)
    lower=certificate['full_family_lower_bound'];require(lower is None or lower<=objective+TOL,'Repriced dual exceeds stopping primal')
    return {'phase':phase,'primal':primal,'native_restricted_lp_certificate':native,'certificate':certificate,
        'objective':objective,'full_family_gap':None if lower is None else objective-lower,'columns':len(cols)},cols,data


def native_mip_bound(result,key):
    objective=result.get('objective');bound=result.get(key);gap=result.get('native_gap')
    require(objective is None or finite(objective),'Nonfinite native objective')
    require(bound is None or (finite(bound) and (objective is None or bound<=objective+TOL)),'Native bound ordering fails')
    if objective is not None and bound is not None and gap is not None:
        expected=abs(objective-bound)/abs(objective) if objective else (0 if bound==0 else math.inf)
        require(finite(gap) and abs(gap-expected)<=TOL,'Native gap does not match objective/bound')
    codes={'optimal':2,'time_limit':9,'interrupted':11}
    if result.get('status') in codes:
        require(result.get('native_status')==codes[result['status']],'Native status mismatch')
        return bound
    return None


def metadata(folder,manifest,result,local_test=False):
    import run_plugs as runner
    from plug_problem import verify_snapshot
    verify_snapshot()
    for name in ('master','extension_models','verify_lp_scaling','direct_mip_1000','rmp_solver'):
        require(Path(sys.modules[name].__file__).resolve().is_relative_to(FROZEN.resolve()),'Unfrozen imported dependency: '+name)
    code=manifest.get('code_sha256',{})
    require(set(code)==set(runner.DEPENDENCIES),'Changed runtime dependency set')
    for name,digest in code.items():require(sha(checked_path(ROOT,name))==digest,'Changed runtime source: '+name)
    partial=result.get('status') in ('external_timeout','worker_failed')
    hashes=result.get('partial_evidence_sha256' if partial else 'evidence_sha256',{})
    require({'manifest.json','instance.json'}.issubset(hashes),'Missing evidence/input digests')
    for name,digest in hashes.items():require(sha(checked_path(folder,name))==digest,'Changed evidence: '+name)
    spec=manifest['case'];require(spec in inputs.case_specs()+[inputs.calibration_spec()],'Noncanonical plug input')
    inst,caps=inputs.build_case(spec);raw=json.loads((folder/'instance.json').read_text());reconstructed=inputs.instance_record(inst,caps)
    require(raw==reconstructed and raw['sha256']==manifest['instance_sha256']==result['instance_sha256'],'Physical/capacity input differs')
    runner.input_binding(spec,raw)
    require(manifest.get('study')=='station_time_plugs' and manifest.get('repeat')==0,'Wrong study/repeat')
    require(manifest.get('excluded_calibration')==(spec==inputs.calibration_spec()),'Wrong calibration exclusion')
    arm=manifest.get('variant');require(arm in runner.ARMS and manifest.get('method')==arm==result.get('variant'),'Wrong arm identity')
    require(manifest.get('protocol')==runner.protocol(),'Changed protocol')
    expected={'budget_seconds':1800,'cg_cap_seconds':600,'worker_watchdog_grace_seconds':600,'max_cg_iterations':20000,
        'require_gurobi':'12.0.3','require_cpu_model':'AMD EPYC 9654','require_single_affinity_cpu':True}
    if not local_test:
        for name,value in expected.items():require(manifest.get(name)==value,'Changed required control: '+name)
    else:
        require(spec==inputs.calibration_spec(),'Local override allowed only for excluded calibration')
        require(finite(manifest.get('budget_seconds')) and 0<manifest.get('cg_cap_seconds',0)<manifest['budget_seconds'],'Invalid local deadline')
    env=manifest['environment'];require(bool(env.get('host')),'Missing host')
    if not local_test:
        compact=lambda s:''.join(s.split())
        require(env.get('gurobi')==[12,0,3] and 'AMDEPYC9654' in compact(env.get('cpu_model','')),'Wrong Gurobi/processor')
        require(str(env.get('allocated_cpus'))=='1' and len(env.get('cpu_affinity') or [])==1,'Wrong requested or bound CPU count')
        require(set(env.get('thread_environment',{}))==THREADS and all(env['thread_environment'][k]=='1' for k in THREADS),'Wrong math thread controls')
        require(str(manifest.get('scheduler_memory_per_node_mib'))=='65536','Wrong memory allocation')
    if partial:
        require(result.get('objective') is None and not result.get('incumbent_validated')
            and result.get('algorithm_time_censor_bound_valid') is False,'Infrastructure failure presented as algorithm result')
    if result.get('objective') is not None:
        require(finite(result['objective']) and finite(result.get('solve_end_to_end_seconds')) and result['solve_end_to_end_seconds']>0,'Invalid objective/time')
        require(result.get('budget_seconds')==manifest['budget_seconds'] and result.get('threads')==1 and result.get('seed')==0,'Saved controls differ')
    return PlugProblem(inst,caps),hashes,{'passed':True,'local_test_override':local_test,'cluster_protocol_accepted':not local_test,
        'source_files':len(code),'evidence_files':len(hashes),'instance_sha256':raw['sha256'],'host':env['host'],'partial_evidence_only':partial}


def native_controls(result,arm,local_test=False):
    for name,value in {'threads':1,'seed':0,'solver_method':2 if arm in ('direct_lp','direct_mip') else -1,
        'mip_gap_tolerance':1e-6,'mip_gap_absolute_tolerance':1e-10,'feasibility_tolerance':1e-8,
        'optimality_tolerance':1e-8,'integer_feasibility_tolerance':1e-8,'cold_solve':True,
        'external_incumbent_or_basis_start':False,'crossover_parameter':-1}.items():
        require(result.get(name)==value,'Changed native control: '+name)
    if not local_test:require(result.get('solver_version')==[12,0,3],'Wrong native Gurobi version')


def verify_worker(folder,local_test=False):
    global _AUDITS
    _AUDITS+=1;started=time.perf_counter();folder=Path(folder).resolve()
    out={'worker':str(folder),'passed':False,'accepted_feasible_incumbent':False,'accepted_common_family_lp':False,
        'global_economic_lower_bound':None,'restricted_pool_lower_bound':None,'phase1_infeasibility_evidence':False,
        'verification_tolerance':TOL,'scope':'Independent numerical physical/matrix replay and complete graph/seed/BESS pricing, no LP or MIP optimization',
        'verifier_sha256':sha(Path(__file__)),'local_test_override':local_test}
    try:
        manifest=json.loads((folder/'manifest.json').read_text());result=json.loads((folder/'result.json').read_text())
        out.update(case=manifest['case']['case'],variant=manifest['variant'],repeat=manifest['repeat'],status=result.get('status'),
            result_sha256=sha(folder/'result.json'),manifest_sha256=sha(folder/'manifest.json'),instance_file_sha256=sha(folder/'instance.json'))
        out['evidence_binding_sha256']={name:sha(folder/name) for name in ('result.json','manifest.json','instance.json')}
        problem,hashes,meta=metadata(folder,manifest,result,local_test);out['metadata']=meta
        out['evidence_sha256']={name:sha(folder/name) for name in hashes};out['instance_sha256']=manifest['instance_sha256']
        arm=manifest['variant'];objective=result.get('objective');integer=arm.endswith('mip')
        if meta['partial_evidence_only'] or result.get('status') in ('environment_rejected','error'):
            out.update(passed=True,reason='Metadata-only failed execution; no solution or timing acceptance');return out
        if arm!='cg_lp':native_controls(result,arm,local_test)
        if arm=='cg_pool_mip':
            require(result.get('status_scope')=='Restricted integer pool only' and result.get('global_integer_optimality_claimed') is False
                and result.get('bound') is None and result.get('full_family_bound') is None,'Pool bound incorrectly global')
            out['restricted_pool_lower_bound']=native_mip_bound(result,'restricted_pool_bound')
        elif arm=='direct_mip':out['global_economic_lower_bound']=native_mip_bound(result,'bound')
        graph=build_extended_graph(problem.inst);seeds=fixed_seeds(problem)
        out.update(graph_nodes=graph.n_nodes,graph_arcs=graph.n_arcs,finite_connector_rows=len(problem.finite_cells),seed_count=len(seeds))
        snapshots={}
        if arm.startswith('cg'):
            require({'cg_trace.json','cg_all_columns.json.gz','native_stop.json'}.issubset(hashes),'Missing CG checkpoints')
            require(json.loads((folder/'cg_trace.json').read_text())==result.get('cg'),'CG trace differs')
            expected_cap=manifest['cg_cap_seconds'] if arm=='cg_pool_mip' else manifest['budget_seconds']
            require(result.get('cg_cap_seconds')==expected_cap,'Wrong CG phase budget')
            allcols=read_columns(folder/'cg_all_columns.json.gz',problem)
            for phase in ('feasibility','economic'):
                audited=audit_snapshot(folder,problem,graph,seeds,hashes,phase)
                if audited is None:continue
                report,cols,data=audited;snapshots[phase]=(cols,data);out['phase1' if phase=='feasibility' else 'phase2']=report
                if phase=='feasibility':out['phase1_infeasibility_evidence']=report['certificate']['phase1_positive_bound_infeasibility_evidence']
                else:out['global_economic_lower_bound']=report['certificate']['global_economic_bound']
            if arm=='cg_pool_mip':
                require('pool_columns.json.gz' in hashes,'Integer pool not saved')
                cols=read_columns(folder/'pool_columns.json.gz',problem,True)
                require([column_key(c) for c in cols]==[column_key(c) for c in allcols if c.kind=='truck'],'Integer pool differs from all accepted real columns')
            elif 'economic' in snapshots:cols=snapshots['economic'][0]
            else:cols=[]
            realkeys={column_key(c) for c in allcols if c.kind=='truck'}
            require(all(column_key(c) in realkeys for c in seeds),'An original singleton seed was lost')
            if objective is not None:
                require('pool_primal.npz' in hashes and bool(cols),'Missing physical LP/MIP vector')
                with np.load(folder/'pool_primal.npz',allow_pickle=False) as saved:vector=saved['x']
                if arm=='cg_lp':
                    require('economic' in snapshots and np.array_equal(vector,snapshots['economic'][1]['x']),'LP result not matched to actual stopping columns/vector')
                    require(abs(objective-out['phase2']['objective'])<=TOL,'LP objective differs from stopping solution')
                out['primal']=audit_pool_vector(problem,cols,vector,objective,integer)
                out['accepted_feasible_incumbent']=True
        elif objective is not None:
            require('direct_primal.npz' in hashes,'Missing direct raw vector')
            with np.load(folder/'direct_primal.npz',allow_pickle=False) as saved:data={k:saved[k] for k in saved.files}
            primal,model=audit_direct_vector(problem,graph,seeds,data['x'],objective,integer);out['primal']=primal
            out['accepted_feasible_incumbent']=True
            if arm=='direct_lp' and result.get('native_status')==2:
                c,lb,ub,ae,be,au,bu,off,plug_start=model
                prices=saved_price_identity(problem,data,ae,au,plug_start,True,graph)
                out['native_direct_dual_certificate']=_direct_certificate(c,lb,ub,ae,be,au,bu,data['x'],
                    data['native_eq_dual'],data['native_ub_dual'],data['native_reduced_cost'],objective)
                out['full_family_certificate']=family_certificate(problem,graph,seeds,*prices)
                out['global_economic_lower_bound']=out['full_family_certificate']['global_economic_bound']
        lower=out['global_economic_lower_bound'];upper=objective if out['accepted_feasible_incumbent'] else None
        if upper is not None and lower is not None:
            gap=upper-lower;require(gap>=-TOL,'Global lower bound exceeds independently replayed incumbent')
            out.update(full_family_gap=gap,full_family_relative_gap=gap/max(abs(upper),1e-30))
            if arm.endswith('_lp'):
                threshold=problem.inst.n_trips*TOL+1e-5
                out.update(common_quality_absolute_gap_limit=threshold,accepted_common_family_lp=gap<=threshold)
        if out['phase1_infeasibility_evidence']:
            require(not out['accepted_feasible_incumbent'],'Infeasibility evidence contradicts feasible physical primal')
        out.update(passed=True,feasible_upper_bound=upper,reason='All available raw evidence independently checked',
            native_infeasible_claim_only=result.get('native_status')==3,
            optimum_scope='Integer optimality status for restricted CG pool remains restricted; full-family bounds separate')
    except Exception as exc:
        out.update(passed=False,accepted_feasible_incumbent=False,accepted_common_family_lp=False,
            global_economic_lower_bound=None,restricted_pool_lower_bound=None,phase1_infeasibility_evidence=False,error=repr(exc))
    finally:
        out.update(validation_seconds=time.perf_counter()-started,process_peak_rss_bytes=peak_rss_bytes(),
            verification_process_peak_rss_bytes=peak_rss_bytes(),
            rss_scope='Cumulative verifier-process peak; fresh CLI per worker' if _SINGLE_CLI else 'Cumulative current Python-process peak; may include earlier API calls')
    return safe(out)


def main():
    global _SINGLE_CLI
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();folder=a.input.resolve();destination=a.output.resolve()
    require(not destination.exists() and not destination.is_relative_to(folder),'Fresh external audit output required')
    _SINGLE_CLI=True;report=verify_worker(folder)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(safe({'workers':[report],'passed':report['passed'],'optimization_performed':False,
        'verifier_sha256':sha(Path(__file__)),'local_test_environment_override':False}),indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:report.get(k) for k in ('case','variant','passed','accepted_feasible_incumbent','accepted_common_family_lp','error')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
