"""Prespecified DIAG2 LP scaling inputs; no optimization or mutable legacy imports.

The existing hashed random generator is reused unchanged. Different n values use
the historical seed formula (which includes n), so these are independent draws,
not nested task sets. This changes task count and map size, not arbitrary route
complexity, horizon, battery discretization, energy cost, or physical rate.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from extension_instances import rand_trips, source_manifest as legacy_manifest
import recreate_arxiv as historical
from run_pilot import safe, verify_vendor


def case_specs():
    return [{"case":f"diag2_L{L:02d}_n{n}_s{sd}","family":"random_diag2_lp_scaling",
             "n_tasks":n,"points":L,"draw_seed":sd,"task_energy_kwh":100,
             "rand_trips_seed_argument":200+sd,
             "rng_seed":20000+1000*(200+sd)+10*L+n}
            for n in (100,400,1000) for L in (4,15) for sd in (0,1)]


def build_case(spec):
    canonical=next((x for x in case_specs() if x["case"]==spec.get("case")),None)
    if canonical!=spec:
        raise ValueError("Use an unmodified lp_scaling_instances.case_specs entry")
    verify_vendor()
    fleet=rand_trips(spec["points"],spec["n_tasks"],spec["rand_trips_seed_argument"])
    pool=list(historical._COORDS)+[(0.75,0.75),(-0.75,0.75),(0.75,-0.75)]
    inst=historical.build_instance(spec["points"],1.0,[(6,20)],trip_list=fleet,
                                  duration=1.0,coords_override=pool[:spec["points"]],
                                  stations="all",pv_scale=2.0)
    inst.c_g,inst.c_b,inst.rho,inst.c_v=40.0,36.0,1.75,45.0
    expected={"T":48,"G":7.0,"soc_step":0.5,"eta":0.0,"energy_per_dist":0.5,
              "eps_pen":0.025,"deg_cost":0.0,"n_trips":spec["n_tasks"]}
    for name,value in expected.items():
        if getattr(inst,name)!=value:
            raise AssertionError(f"Unexpected frozen input parameter {name}")
    return inst


def instance_record(inst):
    body=safe({"T":inst.T,"n_tasks":inst.n_trips,"model_energy_unit_kwh":100,
        **{k:getattr(inst,k) for k in ("G","rho","soc_step","eta","energy_per_dist",
                                      "c_g","c_v","c_b","eps_pen","deg_cost","depot")},
        "charge_locations":list(inst.charge_locs),"generation_cap":"unbounded",
        "charging_cap":"unbounded","truck_boundary":"full/full","stationary_boundary":"periodic",
        "dist":inst.dist,"Delta":inst.Delta,"trips":[vars(tr) for tr in inst.trips]})
    body["sha256"]=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
    return body


def source_manifest():
    return {"legacy_generator":deepcopy(legacy_manifest()),
            "scaling_axes":{"n":[100,400,1000],"task_locations":[4,15],"draw_seed":[0,1]},
            "draws_are_nested":False,"physical_rate":1.75,"dp_truck_rate":1.5,
            "soc_step":0.5,"family":"all DP paths plus real original singleton seeds",
            "historical_results_are_not_new_results":True}
