"""Independent prescribed-profile reachability and exact column identities."""
from __future__ import annotations
import numpy as np
from pricing_contract import grid_index, validate_storage


def column_key(col):
    """Cost and signed energy are part of a column, even with equal coverage."""
    a=np.asarray(col.a,dtype=float);e=np.asarray(col.e,dtype=float)
    if not np.isfinite(a).all() or not np.isfinite(e).all() or not np.isfinite(col.fixed_cost):
        raise ValueError('Nonfinite column')
    return (col.kind,tuple(a),tuple(e),float(col.fixed_cost))


def replay_column(inst,col,*,allow_charge=True,allow_discharge=True,ice=False,soc_mode='cyclic'):
    """Independent reachability for a prescribed profile on the pricing grid.

    Only scalar grid/storage validation is shared with pricing. This routine
    constructs reachability states from raw instance data without pricing labels,
    cached transitions, duals, or a claimed predecessor path. Activity is measured
    by integer SoC increments, never by an absolute energy threshold.
    """
    a=np.asarray(col.a,dtype=float);e=np.asarray(col.e,dtype=float)
    if a.shape!=(inst.n_trips,) or e.shape!=(inst.T,):return False
    if not np.isfinite(a).all() or not np.isfinite(e).all() or not np.isfinite(col.fixed_cost):return False
    # Incidence is integer input data, not a rounded continuous solver vector.
    if np.any((a!=0)&(a!=1)):return False
    incidence=a.astype(int).tolist()
    if col.kind=='artificial':return bool(sum(incidence)==1 and not np.any(e))
    if col.kind!='truck' or not any(incidence):return False
    try:
        T,step,nlevels,up,down=validate_storage(inst,None)
        top=nlevels-1
        # Nonzero grid energy cannot stand in for an idle slot, even when the
        # chosen units make it smaller than a conventional feasibility tolerance.
        ds=[]
        for v in e:
            delta=(1-inst.eta)*v if v>0 else v
            shift=grid_index(abs(delta),step,'profile SoC increment')
            if v!=0 and shift==0:return False
            ds.append(shift if v>=0 else -shift)
        ds=np.asarray(ds,dtype=int)
        if np.any(ds>up) or np.any(ds < -down):return False
        if ice and np.any(ds):return False
        if not allow_charge and np.any(ds>0):return False
        if not allow_discharge and np.any(ds<0):return False
        if not np.isfinite(inst.energy_per_dist) or inst.energy_per_dist<0:return False
        dist=np.asarray(inst.dist,dtype=float)
        if dist.ndim!=2 or dist.shape[0]!=dist.shape[1] or not dist.shape[0]:return False
        nloc=dist.shape[0]
        if inst.depot!=int(inst.depot) or not 0<=inst.depot<nloc:return False
        times=np.zeros((nloc,nloc),dtype=int);energy=np.zeros((nloc,nloc),dtype=int)
        for origin in range(nloc):
            for dest in range(nloc):
                dt=grid_index(dist[origin,dest],1.,'deadhead time')
                if (origin==dest and dt!=0) or (origin!=dest and dt<1):return False
                times[origin,dest]=dt
                energy[origin,dest]=0 if ice else grid_index(
                    inst.deadhead_energy(origin,dest),step,'deadhead energy')
        trip_energy={}
        indices=[]
        for tr in inst.trips:
            fields=(tr.idx,tr.start,tr.end,tr.sloc,tr.eloc)
            if any(not np.isfinite(v) or v!=int(v) for v in fields):return False
            if not (0<=tr.idx<inst.n_trips and 0<=tr.start<tr.end<=T
                    and 0<=tr.sloc<nloc and 0<=tr.eloc<nloc):return False
            indices.append(tr.idx)
            if not np.isfinite(tr.energy) or tr.energy<0:return False
            trip_energy[tr.idx]=0 if ice else grid_index(tr.energy,step,'trip energy')
        if sorted(indices)!=list(range(inst.n_trips)):return False
        if soc_mode=='periodic':starts=range(nlevels)
        elif soc_mode.startswith('pin'):
            start=grid_index(float(soc_mode[3:]),step,'pinned SoC')
            if start>top:return False
            starts=[start]
        elif soc_mode in ('cyclic','free'):starts=[top]
        else:raise ValueError('Unknown truck boundary: '+soc_mode)
        stations=set(inst.charge_locs)
        if any(not np.isfinite(h) or h!=int(h) or not 0<=h<nloc for h in stations):return False
    except (ValueError,TypeError,OverflowError):return False
    selected=sorted([tr for tr in inst.trips if incidence[tr.idx]],key=lambda tr:(tr.start,tr.idx))
    if any(x.end>y.start for x,y in zip(selected,selected[1:])):return False
    active=ds!=0
    for start in starts:
        states=[set() for _ in range(T+1)];states[0].add((inst.depot,start,0))
        for t in range(T):
            for loc,level,k in states[t]:
                if k<len(selected) and selected[k].start<t:continue
                if active[t]:
                    if loc in stations and 0<=level+ds[t]<=top:
                        states[t+1].add((loc,level+ds[t],k))
                    continue
                states[t+1].add((loc,level,k))
                for dest in range(nloc):
                    if dest==loc:continue
                    dt,shift=times[loc,dest],energy[loc,dest]
                    if t+dt<=T and level>=shift and not np.any(active[t:t+dt]):
                        states[t+dt].add((dest,level-shift,k))
                if k<len(selected):
                    tr=selected[k];shift=trip_energy[tr.idx]
                    if tr.start==t and tr.sloc==loc and level>=shift and not np.any(active[t:tr.end]):
                        states[tr.end].add((tr.eloc,level-shift,k+1))
        if any(loc==inst.depot and k==len(selected) and (soc_mode=='free' or level==start)
               for loc,level,k in states[-1]):return True
    return False
