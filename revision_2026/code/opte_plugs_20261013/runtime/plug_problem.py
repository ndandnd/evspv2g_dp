"""Exact truck connector rows for DP paths plus fixed physical singleton seeds.

The station order is exactly inst.charge_locs. One strictly positive charge OR
discharge action occupies one connector for its whole block, independent of its
energy magnitude. Waiting/travel/tasks and stationary BESS dispatch occupy none.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
RUNTIME=Path(__file__).resolve().parent
sys.path.insert(0,str(RUNTIME/'frozen'));sys.path.insert(0,str(RUNTIME/'frozen/vendor'))
import numpy as np
from scipy import sparse
import master
import arc_flow
from extension_models import build_extended_graph,_seeds_with_witnesses,_hybrid_matrices
from rmp_solver import _validate_scope,replay_rmp


def verify_snapshot():
    record=json.loads((RUNTIME/'frozen_snapshot.json').read_text())
    for name,item in record['files'].items():
        if hashlib.sha256((RUNTIME/name).read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Frozen dependency changed: '+name)
    return record


@dataclass
class PlugProblem:
    inst: object
    capacities: np.ndarray

    def __post_init__(self):
        _validate_scope(self.inst,[])
        if np.isfinite(self.inst.charge_cap) or np.any(np.isfinite(np.broadcast_to(self.inst.gen_cap,(self.inst.T,)))):
            raise ValueError('Plug study requires uncapped aggregate charging and generation')
        self.stations=tuple(int(h) for h in self.inst.charge_locs)
        if len(set(self.stations))!=len(self.stations) or self.inst.depot not in self.stations:
            raise ValueError('Unique charging sites including depot required')
        self.capacities=np.array(self.capacities,dtype=float,copy=True)
        if self.capacities.shape!=(len(self.stations),self.inst.T):raise ValueError('Expected station-by-time connector capacities')
        finite=np.isfinite(self.capacities)
        if np.any(np.isnan(self.capacities)) or np.any(self.capacities<0) or np.any(abs(self.capacities[finite]-np.rint(self.capacities[finite]))>0):
            raise ValueError('Connector capacities must be nonnegative integers or positive infinity')
        self.finite_cells=np.flatnonzero(finite.ravel())
        self.capacity_vector=self.capacities.ravel()[self.finite_cells]
        self.station_index={h:i for i,h in enumerate(self.stations)}
        # Strict lossless lattice checks without materializing a graph.
        import copy
        physical=copy.copy(self.inst);physical.rho=np.floor(self.inst.rho/self.inst.soc_step)*self.inst.soc_step
        arc_flow.validate_instance(physical)
        self.capacities.setflags(write=False)


@dataclass
class PlugColumn:
    kind: str
    a: np.ndarray
    e: np.ndarray
    fixed_cost: float
    occupancy: np.ndarray
    witness: dict | None
    label: str=''

    def cost(self,eps_pen):return float(self.fixed_cost+eps_pen*np.abs(self.e).sum())


def column_key(col):
    digest=hashlib.sha256(col.kind.encode()+float(col.fixed_cost).hex().encode())
    for values in (col.a,col.e,col.occupancy):
        array=np.ascontiguousarray(values,dtype=np.float64)
        digest.update(str(array.shape).encode());digest.update(array.tobytes())
    return digest.hexdigest()


def columns_record(cols):
    return [{'kind':c.kind,'a':c.a.tolist(),'e':c.e.tolist(),'fixed_cost':c.fixed_cost,
        'occupancy':c.occupancy.tolist(),'witness':c.witness,'label':c.label} for c in cols]


def columns_from_record(records):
    return [PlugColumn(r['kind'],np.asarray(r['a'],float),np.asarray(r['e'],float),float(r['fixed_cost']),
        np.asarray(r['occupancy'],float),r['witness'],r.get('label','')) for r in records]


def witness_occupancy(problem,witness):
    z=np.zeros_like(problem.capacities)
    for state,kind,draw in zip(witness['states'][:-1],witness['kinds'],witness['energy']):
        if kind in ('charge','discharge'):
            if draw==0:raise ValueError('Zero action cannot consume a connector')
            t,h=int(state[0]),int(state[1]);z[problem.station_index[h],t]+=1
        elif draw!=0:raise ValueError('Nonenergy action has a grid draw')
    return z


def seed_columns(problem):
    cols,proofs=_seeds_with_witnesses(problem.inst);answer=[]
    for col,proof in zip(cols,proofs):
        witness={'family':'initial_singleton','states':proof['states'],'kinds':proof['kinds'],
            'energy':proof['energy'],'task_ids':proof['task_ids']}
        answer.append(PlugColumn(col.kind,np.array(col.a),np.array(col.e),float(col.fixed_cost),
            witness_occupancy(problem,witness),witness,col.label))
    if len(answer)!=problem.inst.n_trips:raise ValueError('Every task needs its original physical singleton')
    return answer


def artificial_columns(problem):
    cols=[]
    for i in range(problem.inst.n_trips):
        a=np.zeros(problem.inst.n_trips);a[i]=1
        cols.append(PlugColumn('artificial',a,np.zeros(problem.inst.T),0.,np.zeros_like(problem.capacities),None,f'artificial[{i}]'))
    return cols


def validate_column_data(problem,cols):
    _validate_scope(problem.inst,cols)
    for col in cols:
        if col.occupancy.shape!=problem.capacities.shape or not np.all(np.isfinite(col.occupancy)):
            raise ValueError('Incompatible occupancy shape or values')
        if np.any((col.occupancy!=0)&(col.occupancy!=1)) or np.any(col.occupancy.sum(axis=0)>1):
            raise ValueError('Route occupancy must be binary and use at most one station per block')
        if col.kind=='artificial' and (np.any(col.e) or np.any(col.occupancy)):
            raise ValueError('Task-coverage artificials must have no physical coefficients')


@dataclass
class Matrices:
    c: np.ndarray
    lb: np.ndarray
    ub: np.ndarray
    ae: object
    be: np.ndarray
    au: object
    bu: np.ndarray
    offsets: object
    plug_start: int


def rmp_matrices(problem,cols,phase='economic'):
    if phase not in ('feasibility','economic'):raise ValueError('Unknown phase')
    validate_column_data(problem,cols)
    inst=problem.inst
    c,au,bu,ae,be,bounds,off,n,T,R,cc=master._build_lp(inst,cols,True,soc_mode='cyclic')
    start=len(bu);lb=np.asarray([0. if lo is None else lo for lo,hi in bounds]);ub=np.asarray([np.inf if hi is None else hi for lo,hi in bounds])
    if phase=='feasibility':
        c=np.zeros(len(c))
        for j,col in enumerate(cols):c[j]=float(col.kind=='artificial')
    else:
        for j,col in enumerate(cols):
            if col.kind=='artificial':c[j]=0.;ub[j]=0.
    rows=[];columns=[]
    for j,col in enumerate(cols):
        active=np.flatnonzero(col.occupancy.ravel()[problem.finite_cells])
        rows.extend(active.tolist());columns.extend([j]*len(active))
    occupancy=sparse.coo_matrix((np.ones(len(rows)),(rows,columns)),shape=(len(problem.finite_cells),len(c))).tocsr()
    return Matrices(np.asarray(c),lb,ub,sparse.csr_matrix(ae),np.asarray(be),
        sparse.vstack((sparse.csr_matrix(au),occupancy),format='csr'),np.r_[bu,problem.capacity_vector],off,start)


def direct_matrices(problem,graph,seeds):
    c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(problem.inst,graph,seeds)
    cell_to_row={int(cell):j for j,cell in enumerate(problem.finite_cells)}
    rr=[];cc=[]
    active=np.flatnonzero((graph.kind==arc_flow.CHARGE)|(graph.kind==arc_flow.DISCHARGE))
    for a in active:
        t,h=map(int,graph.states[graph.tail[a],:2]);cell=problem.station_index[h]*problem.inst.T+t
        if cell in cell_to_row:rr.append(cell_to_row[cell]);cc.append(int(a))
    for j,col in enumerate(seeds):
        for cell in np.flatnonzero(col.occupancy.ravel()):
            if int(cell) in cell_to_row:rr.append(cell_to_row[int(cell)]);cc.append(off['seed_start']+j)
    plug=sparse.coo_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(problem.finite_cells),len(c))).tocsr()
    return Matrices(c,lb,ub,ae,be,sparse.vstack((au,plug),format='csr'),np.r_[bu,problem.capacity_vector],off,len(bu))


def replay_column(problem,col,tol=1e-7):
    """Reconstruct physical transitions and exact occupancy from saved route."""
    validate_column_data(problem,[col]);inst=problem.inst
    if col.kind!='truck' or col.witness is None:raise ValueError('Physical replay requires a real saved witness')
    w=col.witness;states=np.asarray(w['states'],float);kinds=w['kinds'];draws=np.asarray(w['energy'],float)
    if states.shape!=(len(kinds)+1,4) or len(draws)!=len(kinds):raise ValueError('Malformed witness')
    if np.max(abs(states[0]-[0,inst.depot,inst.G,0]))>tol or np.max(abs(states[-1]-[inst.T,inst.depot,inst.G,1]))>tol:
        raise ValueError('Wrong full/depot/served boundary')
    if not np.all(np.isfinite(states)) or not np.all(np.isfinite(draws)):
        raise ValueError('Nonfinite witness')
    if np.any(abs(states[:,[0,1,3]]-np.rint(states[:,[0,1,3]]))>tol) or np.any((states[:,2]<-tol)|(states[:,2]>inst.G+tol)):
        raise ValueError('Witness time/location/SoC bounds')
    if np.any((states[:,0]<0)|(states[:,0]>inst.T)) or np.any((states[:,1]<0)|(states[:,1]>=len(inst.dist))) or np.any((states[:,3]!=0)&(states[:,3]!=1)):
        raise ValueError('Out-of-domain witness state')
    if w['family']=='dp_path':
        if np.max(abs(states[:,2]/inst.soc_step-np.rint(states[:,2]/inst.soc_step)))>tol:raise ValueError('Off-grid DP witness')
    elif w['family']=='initial_singleton':
        matches=[s for s in seed_columns(problem) if column_key(s)==column_key(col) and s.witness==w]
        if not matches:raise ValueError('Seed witness differs from its fixed original physical profile')
    else:raise ValueError('Unknown route family')
    a=np.zeros(inst.n_trips);e=np.zeros(inst.T);z=np.zeros_like(problem.capacities);tasks=iter(w['task_ids']);trips={x.idx:x for x in inst.trips}
    for st,en,kind,draw in zip(states[:-1],states[1:],kinds,draws):
        t,h,s,k=st;nt,nh,ns,nk=en;t=int(t);h=int(h);nt=int(nt);nh=int(nh)
        if nt<=t:raise ValueError('Nonpositive witness duration')
        traction=0.;expected_k=k
        if kind=='wait':ok=nt==t+1 and h==nh and draw==0
        elif kind in ('charge','discharge'):
            ok=nt==t+1 and h==nh and h in problem.station_index and (draw>0 if kind=='charge' else draw<0)
            rate=inst.rho if w['family']=='initial_singleton' else np.floor(inst.rho/inst.soc_step)*inst.soc_step
            ok=ok and abs(draw)<=rate+tol;z[problem.station_index[h],t]+=1
        elif kind=='travel':
            ok=h!=nh and nt-t==inst.deadhead_time(h,nh) and draw==0;traction=inst.deadhead_energy(h,nh)
        elif kind=='task':
            tid=next(tasks);tr=trips[tid];ok=(t,nt,h,nh)==(tr.start,tr.end,tr.sloc,tr.eloc) and draw==0
            traction=tr.energy;expected_k=1;a[tid]+=1
        else:raise ValueError('Unknown event kind')
        if not ok or abs(ns-s-draw+traction)>tol or nk!=expected_k:raise ValueError('Invalid physical event')
        e[t]+=draw
    if next(tasks,None) is not None:raise ValueError('Unused task identities')
    fixed=inst.c_v+getattr(inst,'deg_cost',0.)*np.maximum(-e,0).sum()
    residuals={'task_profile':float(np.max(abs(a-col.a))),'energy_profile':float(np.max(abs(e-col.e))),
        'occupancy_profile':float(np.max(abs(z-col.occupancy))),'fixed_cost':abs(float(fixed-col.fixed_cost))}
    if np.any(a>1) or max(residuals.values())>tol:raise ValueError('Witness and column coefficients differ')
    return {'passed':True,'residuals':residuals,'occupancy':z.tolist(),'tasks':np.flatnonzero(a).tolist()}


def replay_pool(problem,cols,vec,mat,objective,integer,tol=1e-6):
    inst=problem.inst;weights=np.asarray(vec[:len(cols)]);selected=np.flatnonzero(weights>tol)
    if any(cols[j].kind!='truck' for j in selected):raise ValueError('Artificial selected in physical solution')
    proofs=[{'index':int(j),'weight':float(weights[j]),'replay':replay_column(problem,cols[j],tol)} for j in selected]
    occupancy=sum((weights[j]*cols[j].occupancy for j in selected),np.zeros_like(problem.capacities))
    violation=float(np.max(np.maximum(occupancy.ravel()[problem.finite_cells]-problem.capacity_vector,0),initial=0))
    bounds=list(zip(mat.lb,mat.ub));aggregate=replay_rmp(inst,cols,vec,mat.offsets,bounds,integer,objective,tol=tol)
    if violation>tol or not aggregate['original_model_feasible']:raise ValueError('Connector or original master feasibility failed')
    return {'passed':True,'aggregate':aggregate,'selected_route_proofs':proofs,'occupancy':occupancy.tolist(),
        'max_connector_violation':violation,'station_order':list(problem.stations)}
