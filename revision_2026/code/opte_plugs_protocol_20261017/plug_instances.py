"""Fixed physical inputs paired across three plug policies; no optimization."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
FROZEN=ROOT/'runtime/frozen'
sys.path.insert(0,str(FROZEN));sys.path.insert(0,str(FROZEN/'vendor'))
import numpy as np
import recreate_arxiv as historical
from arc_flow import validate_instance
from lp_scaling_instances import instance_record as physical_record
from instance import Instance,Trip

CELLS=(("n100_L15_d25",100,15,.25),("n100_L15_d12p5",100,15,.125),
       ("n200_L30_d25",200,30,.25))
POLICIES=("unlimited","loose","tight")


def calibration_spec():
    return {"case":"calibration_two_trucks_one_plug","family":"excluded_plug_calibration",
        "excluded_from_main_results":True,"n_tasks":2,"points":1,"soc_step":.5,
        "plug_policy":"one_depot_plug","purpose":"Initial singleton pool infeasible; Phase I must restore feasibility"}


def case_specs():
    return [{"case":f"plugs_{label}_s{j}_{policy}","physical_case":f"plugs_{label}_s{j}",
        "family":"station_time_active_plugs","cell_index":i,"setting":label,
        "n_tasks":n,"points":L,"soc_step":step,"draw_seed":j,"plug_policy":policy,
        "rng_namespace":[20261013,1014,i,j],"energy_rng_namespace":[20261013,1014,i,j,1],
        "energy_support_kwh":[75,125],"energy_mean_kwh":100,
        "depot_plugs":None if policy=="unlimited" else math.ceil(n/(20 if policy=="loose" else 40)),
        "nondepot_plugs":None if policy=="unlimited" else 2 if policy=="loose" else 1}
        for i,(label,n,L,step) in enumerate(CELLS) for j in (0,1) for policy in POLICIES]


def radical_inverse(index,base):
    value=0.;factor=1./base
    while index:
        index,digit=divmod(index,base);value+=digit*factor;factor/=base
    return value


def coordinates(L):
    points=[tuple(x) for x in historical._COORDS[:15]];k=1
    while len(points)<L:
        candidate=(1.5*radical_inverse(k,2)-.75,1.5*radical_inverse(k,3)-.75);k+=1
        if max(abs(x) for x in candidate)<1e-12:continue
        if any(max(abs(a-b) for a,b in zip(candidate,p))<1e-12 for p in points):continue
        points.append(candidate)
    return [(0.,0.)]+points


def distances(coords):
    xy=np.asarray(coords,float);raw=2*np.sum(abs(xy[:,None,:]-xy[None,:,:]),axis=2)
    nearest=np.rint(raw);raw=np.where(abs(raw-nearest)<=1e-12,nearest,raw)
    matrix=np.ceil(raw)
    if np.any(matrix[~np.eye(len(xy),dtype=bool)]<=0):raise AssertionError("Distinct locations required")
    return matrix


def balanced_trips(spec):
    L,n=spec['points'],spec['n_tasks'];rng=np.random.default_rng(np.random.SeedSequence(spec['rng_namespace']))
    pairs=[]
    for _ in range(2):
        order=rng.permutation(np.arange(1,L+1));shift=int(rng.integers(1,L))
        pairs.extend(zip(order.tolist(),np.roll(order,shift).tolist()))
    while len(pairs)<n:
        a=int(rng.integers(1,L+1));b=int(rng.integers(1,L));b+=int(b>=a);pairs.append((a,b))
    rng.shuffle(pairs)
    return [(a,b,int(rng.integers(6,20))) for a,b in pairs]


def balanced_energies(spec):
    step=spec['soc_step'];support=np.arange(round(.75/step),round(1.25/step)+1)*step
    n=spec['n_tasks'];values=np.concatenate((np.tile(support,n//len(support)),np.ones(n%len(support))))
    np.random.default_rng(np.random.SeedSequence(spec['energy_rng_namespace'])).shuffle(values)
    if len(values)!=n or values.sum()!=n:raise AssertionError("Exact balanced100kWh mean required")
    return values


def build_case(spec):
    if spec==calibration_spec():
        inst=Instance(T=8,D=np.ones(8),P=np.array([0,0,0,0,3,3,0,0],float),
            trips=[Trip(j,2,3,1,1,.5) for j in range(2)],dist=np.array([[0,1],[1,0]],float),
            G=2.,rho=1.,eta=0.,energy_per_dist=.5,c_g=5.,c_v=45.,c_b=36.,eps_pen=.025,
            depot=0,soc_step=.5,stations=[0])
        validate_instance(inst)
        return inst,np.ones((1,8))
    if spec not in case_specs():raise ValueError("Use one canonical preregistered input")
    coords=coordinates(spec['points'])
    inst=historical.build_instance(spec['points'],1.,[(6,20)],trip_list=balanced_trips(spec),
        duration=1.,coords_override=coords[1:],stations='all',pv_scale=2.)
    inst.dist=distances(coords);inst.c_g,inst.c_b,inst.rho,inst.c_v=40.,36.,1.75,45.
    inst.soc_step=spec['soc_step']
    for trip,energy in zip(inst.trips,balanced_energies(spec)):trip.energy=float(energy)
    validate_instance(inst)
    for endpoint in ('sloc','eloc'):
        counts=np.bincount([getattr(t,endpoint) for t in inst.trips],minlength=spec['points']+1)
        if min(counts[1:])<2:raise AssertionError("Every location requires actual demand")
    caps=np.full((len(inst.charge_locs),inst.T),np.inf)
    if spec['plug_policy']!='unlimited':
        for row,loc in enumerate(inst.charge_locs):
            caps[row,:]=spec['depot_plugs'] if loc==inst.depot else spec['nondepot_plugs']
    return inst,caps


def instance_record(inst,caps):
    caps=np.asarray(caps,float)
    if caps.shape!=(len(inst.charge_locs),inst.T) or np.any(np.isnan(caps)) or np.any(caps<0):
        raise ValueError("Invalid station/time capacities")
    finite=caps[np.isfinite(caps)]
    if np.any(finite!=np.rint(finite)):raise ValueError("Physical plug counts must be integers")
    body={"physical":physical_record(inst),"plug_locations":list(inst.charge_locs),
        "plug_capacities":[[None if math.isinf(x) else int(x) for x in row] for row in caps],
        "occupancy":"One truck per positive charging OR discharging action in a block; idle trucks can disconnect; stationary BESS excluded",
        "constraint_scope":"station_time_active_truck_connectors"}
    body['sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return body


def input_checks(inst,caps):
    energies=[t.energy for t in inst.trips]
    return {"physical_sha256":physical_record(inst)['sha256'],
        "mean_task_energy_kwh":100*sum(energies)/inst.n_trips,
        "energy_support_kwh":sorted(set(100*x for x in energies)),
        "physical_energy_lattice_kwh":100*math.gcd(*[round(16*x) for x in
            [inst.G,inst.rho]+energies+[inst.deadhead_energy(a,b) for a in range(len(inst.dist)) for b in range(len(inst.dist))]])/16,
        "finite_plug_rows":int(np.isfinite(caps).sum()),
        "minimum_singleton_terminal_slack_blocks":min(inst.T-t.end-inst.deadhead_time(t.eloc,inst.depot)
            -math.ceil((t.energy+inst.deadhead_energy(inst.depot,t.sloc)+inst.deadhead_energy(t.eloc,inst.depot))/inst.rho) for t in inst.trips),
        "task_origins_by_site":np.bincount([t.sloc for t in inst.trips],minlength=len(inst.dist)).tolist(),
        "task_destinations_by_site":np.bincount([t.eloc for t in inst.trips],minlength=len(inst.dist)).tolist(),
        "task_energy_independent_of_od_distance":True,"full_model_feasibility_not_assumed":True}
