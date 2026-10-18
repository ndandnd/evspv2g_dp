"""Independent fresh task inputs for the fixed LP hypothesis panel; no optimization."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from shared_scaling_helpers import (coordinates, distances, instance_record,
    estimate_graph, verify_snapshot, sha)
import numpy as np
import recreate_arxiv as historical
from arc_flow import validate_instance

MEMORY_CAP_BYTES = 64 * 1024**3
CELLS = (("energy25", 100, 15, .25), ("energy12p5", 100, 15, .125),
         ("energy6p25", 100, 15, .0625), ("map30", 200, 30, .25),
         ("map50", 200, 50, .25), ("map75", 200, 75, .25))


def _specs(draws, phase):
    return [{"case":f"panel_{label}_draw{sd}", "family":"cg_hypothesis_panel",
             "phase":phase, "cell_index":i, "setting":label, "n_tasks":n,
             "points":L, "soc_step":step, "draw_seed":sd,
             "task_energy_support_kwh":[75,125], "task_energy_mean_kwh":100,
             "task_energy_rule":"complete evenly spaced support cycles then100kWh remainder; independently shuffled",
             "rng_namespace":[20261013, 913, i, sd],
             "energy_rng_namespace":[20261013, 913, i, sd, 1],
             "geometry":"fixed historical-prefix/Halton map; confirmation changes task draws only"}
            for i,(label,n,L,step) in enumerate(CELLS) for sd in draws]


def case_specs():
    return _specs((0,1), "unselected_panel")


def confirmation_specs():
    """This runner accepts only the twelve unselected-panel inputs."""
    return []  # Confirmation uses a separate prospective release and RNG namespace914.


def balanced_trips(spec):
    L,n = spec["points"],spec["n_tasks"]
    if n < 2*L:
        raise ValueError("Every site requires two origins and two destinations")
    rng=np.random.default_rng(np.random.SeedSequence(spec["rng_namespace"]))
    pairs=[]
    # Two randomly permuted cycles ensure genuine demand at every site.
    # They are coverage safeguards, not known vehicle routes or warm starts.
    for _ in range(2):
        order=rng.permutation(np.arange(1,L+1)); shift=int(rng.integers(1,L))
        pairs.extend(zip(order.tolist(),np.roll(order,shift).tolist()))
    while len(pairs)<n:
        a=int(rng.integers(1,L+1)); b=int(rng.integers(1,L))
        if b>=a:b+=1
        pairs.append((a,b))
    rng.shuffle(pairs)
    return [(a,b,int(rng.integers(6,20))) for a,b in pairs]


def balanced_energies(spec):
    """Genuinely required energy lattice; exact100kWh sample mean in every case."""
    step=spec["soc_step"]
    support=np.arange(round(.75/step),round(1.25/step)+1,dtype=int)*step
    n=spec["n_tasks"]
    energies=np.concatenate((np.tile(support,n//len(support)),np.ones(n%len(support))))
    rng=np.random.default_rng(np.random.SeedSequence(spec["energy_rng_namespace"]))
    rng.shuffle(energies)
    if len(energies)!=n or float(energies.sum())!=float(n):
        raise AssertionError("Unbalanced task energies")
    return energies


def build_case(spec):
    canonical=next((s for s in case_specs()+confirmation_specs()
                    if s["case"]==spec.get("case")),None)
    if spec!=canonical:raise ValueError("Use a frozen declared regime input")
    verify_snapshot()
    coords=coordinates(spec["points"])
    inst=historical.build_instance(spec["points"],1.,[(6,20)],
        trip_list=balanced_trips(spec),duration=1.,coords_override=coords[1:],
        stations="all",pv_scale=2.)
    inst.dist=distances(coords)
    inst.c_g,inst.c_b,inst.rho,inst.c_v=40.,36.,1.75,45.
    inst.soc_step=spec["soc_step"]
    for trip,energy in zip(inst.trips,balanced_energies(spec)):
        trip.energy=float(energy)
    validate_instance(inst)  # All three energy grids divide the physical rate.
    origins=np.bincount([t.sloc for t in inst.trips],minlength=spec["points"]+1)
    ends=np.bincount([t.eloc for t in inst.trips],minlength=spec["points"]+1)
    if min(origins[1:])<2 or min(ends[1:])<2:raise AssertionError("Inactive site")
    if any(t.sloc==t.eloc for t in inst.trips):raise AssertionError("Self task")
    return inst


def geometry_record(inst,spec):
    d=inst.dist; L=spec["points"]
    origins=np.bincount([t.sloc for t in inst.trips],minlength=L+1)
    ends=np.bincount([t.eloc for t in inst.trips],minlength=L+1)
    return {"coordinates":coordinates(L),
        "geometry_rule":"unchanged historical first15 plus bounded Halton prefix; positive ceil(2*Manhattan) travel times",
        "coordinates_unique":len(set(map(tuple,coordinates(L))))==L+1,
        "active_task_locations":L, "task_origins_by_site":origins.tolist(),
        "task_destinations_by_site":ends.tolist(),
        "minimum_origins_per_task_location":int(min(origins[1:])),
        "minimum_destinations_per_task_location":int(min(ends[1:])),
        "travel_blocks_min":float(d[~np.eye(L+1,dtype=bool)].min()),
        "travel_blocks_max":float(d.max()), "physical_rho":inst.rho,
        "dag_truck_rho":inst.rho, "bess_rho":inst.rho,
        "soc_step":inst.soc_step,"rate_grid_aligned":True,
        "task_duration_blocks":2,
        "task_energy_values_kwh":sorted(set(100*t.energy for t in inst.trips)),
        "task_energy_counts":{str(100*v):sum(t.energy==v for t in inst.trips)
                              for v in sorted(set(t.energy for t in inst.trips))},
        "task_energy_mean_kwh":100*sum(t.energy for t in inst.trips)/inst.n_trips,
        "coarsest_common_physical_energy_lattice_kwh":math.gcd(
            *[round(16*x) for x in ([inst.G,inst.rho]+[t.energy for t in inst.trips]
                +[inst.deadhead_energy(a,b) for a in range(L+1) for b in range(L+1)])])/16*100,
        "task_energy_and_duration_independent_of_od_distance":True,
        "minimum_singleton_terminal_recharge_slack_blocks":min(
            inst.T-t.end-inst.deadhead_time(t.eloc,inst.depot)-math.ceil(
                (t.energy+inst.deadhead_energy(inst.depot,t.sloc)+inst.deadhead_energy(t.eloc,inst.depot))/inst.rho)
            for t in inst.trips),
        "no_idle_horizon_or_unused_locations":True,
        "confirmation_scope":"fresh task seeds on the same fixed geometry"}


def resource_decision(inst):
    estimate=estimate_graph(inst)
    eligible=estimate["heuristic_reservation_bytes"]<=MEMORY_CAP_BYTES
    return {"eligible_before_solve":eligible,
        "status":"eligible" if eligible else "excluded_preflight_memory_estimate",
        "memory_cap_bytes":MEMORY_CAP_BYTES,
        "criterion":"1GiB + 4KiB per exact unpruned arc <=64GiB; planning heuristic, not a proof of peak memory",
        "graph_estimate":estimate}
