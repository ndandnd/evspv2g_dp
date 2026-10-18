"""Vectorized lossless full/full DAG pricing with exact connector occupancy.

The recurrence has the frozen DP's transitions, but retains one explicit parent
per label so the priced column's station/time occupancy is never reconstructed
from aggregate energy alone. Phase I uses cost_factor=0 for every real cost.
"""
from __future__ import annotations
import numpy as np
from plug_problem import PlugColumn,validate_column_data


def reduced_cost(problem,col,alpha,mu,nu,plug_price,cost_factor=1.):
    return float(cost_factor*col.cost(problem.inst.eps_pen)-col.a@alpha+col.e@mu+
        np.maximum(col.e,0)@nu+np.sum(col.occupancy*plug_price))


def price_route(problem,alpha,mu,nu,plug_price,cost_factor=1.):
    """Return (one physical minimum-cost path or None, true minimum route RC)."""
    inst=problem.inst;T=inst.T;L=len(inst.dist);step=inst.soc_step;S=int(round(inst.G/step))+1
    alpha=np.asarray(alpha,float);mu=np.asarray(mu,float);nu=np.asarray(nu,float);plug_price=np.asarray(plug_price,float)
    if alpha.shape!=(inst.n_trips,) or mu.shape!=(T,) or nu.shape!=(T,) or plug_price.shape!=problem.capacities.shape:
        raise ValueError('Incompatible pricing dual shapes')
    if cost_factor not in (0,1) or not all(np.all(np.isfinite(a)) for a in (alpha,mu,nu,plug_price)):
        raise ValueError('Finite pricing duals and phase cost factor0/1 required')
    rate=min(S-1,int(np.floor(inst.rho/step)));shape=(T+1,L,S,2)
    ids=np.arange(np.prod(shape),dtype=np.int64).reshape(shape)
    dp=np.full(shape,np.inf);parent=np.full(shape,-1,dtype=np.int64)
    kind=np.full(shape,-1,dtype=np.int8);task=np.full(shape,-1,dtype=np.int32);draw=np.zeros(shape)
    origin=(0,inst.depot,S-1,0);terminal=(T,inst.depot,S-1,1);dp[origin]=0.
    def relax(index,candidate,previous,typ,tid=-1,energy=0.):
        target=dp[index];mask=candidate<target
        if not np.any(mask):return
        target[mask]=candidate[mask];parent[index][mask]=previous[mask]
        kind[index][mask]=typ;task[index][mask]=tid;draw[index][mask]=energy
    trips_at={}
    for tr in inst.trips:trips_at.setdefault((tr.start,tr.sloc),[]).append(tr)
    for t in range(T):
        cur=dp[t]
        relax((t+1,slice(None),slice(None),slice(None)),cur,ids[t],0)
        for ih,h in enumerate(problem.stations):
            for d in range(1,rate+1):
                energy=d*step
                charge=energy*(mu[t]+nu[t]+cost_factor*inst.eps_pen)+plug_price[ih,t]
                discharge=energy*(-mu[t]+cost_factor*(inst.eps_pen+getattr(inst,'deg_cost',0.)))+plug_price[ih,t]
                relax((t+1,h,slice(d,None),slice(None)),cur[h,:S-d]+charge,ids[t,h,:S-d],1,energy=energy)
                relax((t+1,h,slice(None,S-d),slice(None)),cur[h,d:]+discharge,ids[t,h,d:],2,energy=-energy)
        for h in range(L):
            if not np.any(np.isfinite(cur[h])):continue
            for nh in range(L):
                if nh==h:continue
                dt=inst.deadhead_time(h,nh);shift=int(round(inst.deadhead_energy(h,nh)/step))
                if t+dt<=T and shift<S:
                    relax((t+dt,nh,slice(None,S-shift),slice(None)),cur[h,shift:],ids[t,h,shift:],3)
            for tr in trips_at.get((t,h),[]):
                shift=int(round(tr.energy/step))
                if shift>=S:continue
                previous=np.where(cur[h,:,0]<=cur[h,:,1],ids[t,h,:,0],ids[t,h,:,1])
                candidate=np.minimum(cur[h,:,0],cur[h,:,1])[shift:]-alpha[tr.idx]
                relax((tr.end,tr.eloc,slice(None,S-shift),1),candidate,previous[shift:],4,tid=tr.idx)
    rc=float(cost_factor*inst.c_v+dp[terminal])
    if not np.isfinite(rc):return None,rc
    end=int(ids[terminal]);start=int(ids[origin]);chain=[]
    while end!=start:
        previous=int(parent.ravel()[end])
        if previous<0 or len(chain)>T:raise ValueError('Broken pricing parent chain')
        chain.append((previous,end,int(kind.ravel()[end]),int(task.ravel()[end]),float(draw.ravel()[end])))
        end=previous
    chain.reverse();a=np.zeros(inst.n_trips);e=np.zeros(T);z=np.zeros_like(problem.capacities)
    states=[];kinds=[];energies=[];tasks=[]
    def state(index):
        t,h,s,k=np.unravel_index(index,shape);return [int(t),int(h),float(s*step),int(k)]
    states.append(state(start))
    for u,v,typ,tid,energy in chain:
        t,h,_,_=state(u);states.append(state(v));kinds.append(('wait','charge','discharge','travel','task')[typ]);energies.append(energy)
        e[t]+=energy
        if typ in (1,2):z[problem.station_index[h],t]=1
        if tid>=0:a[tid]+=1;tasks.append(tid)
    col=PlugColumn('truck',a,e,float(inst.c_v+getattr(inst,'deg_cost',0.)*np.maximum(-e,0).sum()),z,
        {'family':'dp_path','states':states,'kinds':kinds,'energy':energies,'task_ids':tasks},f'plug_path[{int(a.sum())}]')
    validate_column_data(problem,[col])
    reconstructed=reduced_cost(problem,col,alpha,mu,nu,plug_price,cost_factor)
    if abs(reconstructed-rc)>1e-7*max(1.,abs(rc)):raise ValueError('Pricing recurrence/reconstruction objective differs')
    return col,rc
