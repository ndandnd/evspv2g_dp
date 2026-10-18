"""Fixed beyond-1000 stage-one inputs; no optimization or old-source edits.

Physical units: 1 model energy unit = 100 kWh, 1 time block = 30 minutes.
Historical random task draws are reused; maps are nested, task sets are not.
"""
from __future__ import annotations
from copy import copy
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
FROZEN = ROOT / "frozen"
sys.path.insert(0, str(FROZEN))
sys.path.insert(0, str(FROZEN / "vendor"))
import numpy as np
import recreate_arxiv as historical
from extension_instances import rand_trips
from lp_scaling_instances import instance_record
from run_pilot import verify_vendor
from arc_flow import validate_instance

CELLS = ((1000,15,.5,"baseline"), (2000,15,.5,"task_density"),
         (4000,15,.5,"task_density"), (1000,30,.5,"map_density"),
         (1000,50,.5,"map_density"), (1000,15,.25,"energy_grid"))


def case_specs():
    return [{"case":f"scale_n{n}_L{L:02d}_d{int(step*100)}_s{sd}",
             "family":"beyond1000_stage1", "cell_index":i, "axis":axis,
             "n_tasks":n, "points":L, "soc_step":step, "draw_seed":sd,
             "task_energy_kwh":100, "rand_trips_seed_argument":200+sd,
             "rng_seed":20000+1000*(200+sd)+10*L+n}
            for i,(n,L,step,axis) in enumerate(CELLS) for sd in (0,1)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_snapshot():
    manifest=json.loads((ROOT/"frozen_manifest.json").read_text())
    for name,record in manifest["files"].items():
        if sha(ROOT/name)!=record["sha256"]:
            raise ValueError("Immutable snapshot changed: "+name)
    verify_vendor()
    return manifest


def radical_inverse(index,base):
    value=0.; factor=1./base
    while index:
        index,digit=divmod(index,base); value+=digit*factor; factor/=base
    return value


def coordinates(L):
    """Historical first15, then a deterministic bounded-extent Halton prefix."""
    if L<15: raise ValueError("This geometry requires at least15 task locations")
    points=[tuple(x) for x in historical._COORDS[:15]]; k=1
    while len(points)<L:
        candidate=(1.5*radical_inverse(k,2)-.75,1.5*radical_inverse(k,3)-.75); k+=1
        if max(abs(x) for x in candidate)<1e-12: continue
        if any(max(abs(a-b) for a,b in zip(candidate,p))<1e-12 for p in points): continue
        points.append(candidate)
    return [(0.,0.)]+points


def distances(coords):
    xy=np.asarray(coords,dtype=float)
    raw=2*np.sum(abs(xy[:,None,:]-xy[None,:,:]),axis=2)
    # Avoid a spurious extra block for representational noise near an integer.
    nearest=np.rint(raw); raw=np.where(abs(raw-nearest)<=1e-12,nearest,raw)
    result=np.ceil(raw)
    if not np.all(result[np.eye(len(xy),dtype=bool)]==0): raise AssertionError("Diagonal")
    if np.any(result[~np.eye(len(xy),dtype=bool)]<=0): raise AssertionError("Distinct points")
    return result


def build_case(spec):
    canonical=next((s for s in case_specs() if s["case"]==spec.get("case")),None)
    if spec!=canonical: raise ValueError("Use an unmodified stage-one case_specs entry")
    verify_snapshot()
    L=spec["points"]; coords=coordinates(L)
    trips=rand_trips(L,spec["n_tasks"],spec["rand_trips_seed_argument"])
    inst=historical.build_instance(L,1.,[(6,20)],trip_list=trips,duration=1.,
        coords_override=coords[1:],stations="all",pv_scale=2.)
    before=inst.dist[:16,:16].copy(); inst.dist=distances(coords)
    if not np.array_equal(before,inst.dist[:16,:16]):
        raise AssertionError("Historical depot+first15 distances changed")
    inst.c_g,inst.c_b,inst.rho,inst.c_v=40.,36.,1.75,45.
    inst.soc_step=spec["soc_step"]
    coarse=copy(inst); coarse.rho=math.floor(inst.rho/inst.soc_step)*inst.soc_step
    validate_instance(coarse)
    used={t.sloc for t in inst.trips}|{t.eloc for t in inst.trips}
    if used!=set(range(1,L+1)): raise AssertionError("Every declared task location must be active")
    if L==15 and spec["n_tasks"]==1000:
        fixture=json.loads((ROOT/"fixtures"/f'baseline_s{spec["draw_seed"]}.json').read_text())
        current=instance_record(inst)
        if inst.soc_step==.5:
            if current!=fixture: raise AssertionError("Historical serialized baseline changed")
        else:
            a={k:v for k,v in current.items() if k not in ("sha256","soc_step")}
            b={k:v for k,v in fixture.items() if k not in ("sha256","soc_step")}
            if a!=b: raise AssertionError("Fine grid changed data other than energy step")
    return inst


def geometry_record(inst,spec):
    L=spec["points"]; dist=inst.dist; nonzero=dist[~np.eye(L+1,dtype=bool)]
    return {"coordinates":coordinates(L), "rule":"historical first15 then Halton bases2,3 scaled to[-.75,.75]^2; k starts1; skip depot/duplicates",
        "distance_rule":"ceil(2*Manhattan), snap to nearest integer only within1e-12; same matrix for time and traction",
        "maps_are_nested_prefixes":True,"tasks_are_nested":False,
        "task_duration_blocks":2,"task_energy":1.,"task_energy_and_duration_independent_of_od_distance":True,
        "travel_blocks_min":float(nonzero.min()),"travel_blocks_max":float(nonzero.max()),
        "travel_blocks_mean":float(nonzero.mean()),"depot_blocks_max":float(dist[0].max()),
        "fixed_net_energy_total":float(inst.Delta.sum()),"fixed_net_energy_absolute_total":float(abs(inst.Delta).sum()),
        "task_traction_total":float(sum(t.energy for t in inst.trips)),
        "tasks_per_task_location":inst.n_trips/L,
        "active_task_locations":len({t.sloc for t in inst.trips}|{t.eloc for t in inst.trips}),
        "minimum_singleton_terminal_recharge_slack_blocks":min(
            inst.T-t.end-inst.deadhead_time(t.eloc,inst.depot)-math.ceil(
                (t.energy+inst.deadhead_energy(inst.depot,t.sloc)+inst.deadhead_energy(t.eloc,inst.depot))/inst.rho)
            for t in inst.trips),
        "physical_rho":inst.rho,"effective_truck_rho":math.floor(inst.rho/inst.soc_step)*inst.soc_step,
        "bess_rho":inst.rho,"soc_step":inst.soc_step,
        "interpretation":"Changing task count changes demand density; changing map size changes spatial density/rounded travel distributions; changing grid changes allowable truck rate. Methods are matched within each input."}


def estimate_graph(inst):
    """Exact unpruned counts, not a claim of a measured peak-memory bound."""
    T=inst.T; L=len(inst.dist); S=round(inst.G/inst.soc_step)+1
    r=math.floor(inst.rho/inst.soc_step); H=len(inst.charge_locs)
    wait=2*T*L*S
    energy=4*T*H*sum(min(r,s) for s in range(S))
    travel=sum(2*max(0,T-int(inst.dist[a,b])+1)*max(0,S-round(inst.dist[a,b]*inst.energy_per_dist/inst.soc_step))
               for a in range(L) for b in range(L) if a!=b)
    tasks=sum(2*max(0,S-round(t.energy/inst.soc_step)) for t in inst.trips)
    arcs=wait+energy+travel+tasks; states=2*(T+1)*L*S
    # Broad reservation heuristic only: earlier ~300k-variable solves peaked
    # near512MiB; assume4KiB per unpruned arc plus1GiB base. Native MIP tree
    # storage and numerical factors may exceed this, so scheduler OOM is retained.
    reservation=1024**3+4096*arcs
    return {"unpruned_states":states,"unpruned_arcs":arcs,
        "arc_breakdown":{"wait":wait,"charge_and_discharge":energy,"travel":travel,"task":tasks},
        "integer_soc_levels":S,"truck_rate_grid_steps":r,"seed_column_count":inst.n_trips,
        "full_model_variable_upper_bound":arcs+inst.n_trips+195,
        "heuristic_reservation_bytes":reservation,
        "heuristic_scope":"4KiB per unpruned arc plus1GiB; conservative planning extrapolation, not a proven memory bound; no graph/model/optimizer allocated",
        "pricing_route_correction_width":inst.n_trips*1e-6}


def load_matched_input(case_name,path):
    spec=next((s for s in case_specs() if s["case"]==case_name),None)
    if spec is None: raise ValueError("Unknown stage-one case")
    raw=json.loads(Path(path).read_text()); inst=build_case(spec)
    if raw!=instance_record(inst): raise ValueError("Saved input differs from exact stage-one builder")
    return spec,inst,raw
