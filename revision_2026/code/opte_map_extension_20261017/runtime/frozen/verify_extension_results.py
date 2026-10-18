"""Independent physical/path-master audit of the six saved extension comparisons.

Runs only after the batch is marked completed. It never imports extension_models,
arc_flow, column_witness, or rmp_solver. Saved DAG paths and singleton witnesses
are replayed against original physical inputs; a separate scalar DP checks the
stopping dual. Vendor HiGHS LP and native Gurobi MIP use only reconstructed direct
integer-solution columns. These verification solves are not benchmark runs.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from instance import Instance, Trip
from master import Column, solve_lp, solve_milp
from colgen import single_trip_column

TOL = 1e-6
CASES = ("diag2_L04_n100_s0", "diag2_L15_n100_s0")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def instance_from_record(raw):
    delta = np.asarray(raw["Delta"])
    require(raw["eta"] == 0 and raw["truck_boundary"] == "full/full"
            and raw["stationary_boundary"] == "periodic", "Unsupported model scope")
    require(raw["generation_cap"] == raw["charging_cap"] == "unbounded", "Unsupported cap")
    return Instance(T=raw["T"], D=np.maximum(delta, 0), P=np.maximum(-delta, 0),
                    trips=[Trip(**tr) for tr in raw["trips"]], dist=np.asarray(raw["dist"]),
                    G=raw["G"], rho=raw["rho"], eta=0, energy_per_dist=raw["energy_per_dist"],
                    c_g=raw["c_g"], c_v=raw["c_v"], c_b=raw["c_b"], eps_pen=raw["eps_pen"],
                    depot=raw["depot"], soc_step=raw["soc_step"], deg_cost=raw["deg_cost"],
                    stations=raw["charge_locations"])


def replay_path(inst, path, singleton=False):
    """Return a physically reconstructed column without using a graph builder."""
    states, kinds, energies = path["states"], path["kinds"], path["energy"]
    tasks = path.get("tasks", path.get("task_ids"))
    factor = 1.0 if singleton else inst.soc_step
    require(len(states) == len(kinds) + 1 == len(energies) + 1, "Path length mismatch")
    require(tasks and len(set(tasks)) == len(tasks), "Empty or repeated task")
    require(np.max(abs(np.asarray(states[0]) - [0, inst.depot, inst.G/factor, 0])) < TOL,
            "Start boundary mismatch")
    require(np.max(abs(np.asarray(states[-1]) - [inst.T, inst.depot, inst.G/factor, 1])) < TOL,
            "Terminal boundary mismatch")
    by_id = {tr.idx: tr for tr in inst.trips}
    coverage, profile = np.zeros(inst.n_trips), np.zeros(inst.T)
    pos = 0; served = 0
    for a, b, kind, e in zip(states[:-1], states[1:], kinds, energies):
        t, loc, s, flag = a; nt, nloc, ns, nflag = b
        require(t == int(t) and nt == int(nt) and nt > t, "Nonpositive/nonintegral event time")
        t, nt, loc, nloc = int(t), int(nt), int(loc), int(nloc)
        require(0 <= t < nt <= inst.T and flag == served, "Time/served flag mismatch")
        require(-TOL <= s*factor <= inst.G+TOL and -TOL <= ns*factor <= inst.G+TOL,
                "Battery bound violation")
        if not singleton:
            require(abs(s-round(s)) < TOL and abs(ns-round(ns)) < TOL, "Off-grid DAG state")
        change = (ns-s)*factor
        if kind == "task":
            tr = by_id[tasks[pos]]; pos += 1
            require((t, nt, loc, nloc) == (tr.start, tr.end, tr.sloc, tr.eloc), "Task mismatch")
            require(abs(change+tr.energy) < TOL and abs(e) < TOL, "Task energy mismatch")
            coverage[tr.idx] += 1; served = 1
        elif kind == "travel":
            require(loc != nloc and nt-t == inst.dist[loc, nloc] and abs(e) < TOL, "Travel mismatch")
            require(abs(change+inst.dist[loc,nloc]*inst.energy_per_dist) < TOL, "Travel energy mismatch")
        elif kind == "wait":
            require(nt == t+1 and loc == nloc and abs(change) < TOL and abs(e) < TOL, "Wait mismatch")
        elif kind in ("charge", "discharge"):
            require(nt == t+1 and loc == nloc and loc in inst.charge_locs, "Charging location/time mismatch")
            require(abs(change-e) < TOL and abs(e) <= inst.rho+TOL, "Physical charging mismatch")
            require(e > 0 if kind == "charge" else e < 0, "Energy sign mismatch")
            if not singleton:
                require(abs(e/inst.soc_step-round(e/inst.soc_step)) < TOL, "Off-grid DP draw")
                require(abs(e) <= np.floor(inst.rho/inst.soc_step)*inst.soc_step+TOL, "DP rate mismatch")
        else:
            raise AssertionError(f"Unknown transition {kind}")
        require(nflag == served, "Served flag transition mismatch")
        profile[t] += e
    require(pos == len(tasks) and served == 1, "Task list mismatch")
    fixed = inst.c_v + inst.deg_cost*np.maximum(-profile,0).sum()
    col = Column("truck", coverage, profile, fixed, "independently_replayed")
    if singleton:
        require(len(tasks) == 1, "Singleton must serve one task")
        original = single_trip_column(inst, by_id[tasks[0]], ice=False, free_start=False)
        require(original is not None and np.max(abs(original.e-profile)) < TOL
                and np.max(abs(original.a-coverage)) < TOL and abs(original.fixed_cost-fixed) < TOL,
                "Off-grid witness is not an original singleton")
    return col, len(kinds)


def replay_direct(inst, saved, integer):
    val = saved["validation"]
    columns, weights = [], []; transitions = 0
    for path in val["paths"]:
        col, count = replay_path(inst, path)
        columns.append(col); weights.append(path["weight"]); transitions += count
    for entry in val.get("singleton_paths",[]):
        col, count = replay_path(inst, entry["witness"], singleton=True)
        columns.append(col); weights.append(entry["weight"]); transitions += count
    weights = np.asarray(weights)
    require(np.all(weights > 0), "Invalid route weight")
    if integer:
        require(np.max(abs(weights-np.round(weights))) < TOL, "Noninteger route multiplicity")
    cov = sum((w*c.a for w,c in zip(weights,columns)),np.zeros(inst.n_trips))
    grid = sum((w*c.e for w,c in zip(weights,columns)),np.zeros(inst.T))
    g = np.asarray(val["generation"]); ch = np.asarray(val["battery_charge"])
    dis = np.asarray(val["battery_discharge"]); soc = np.asarray(val["battery_soc"]); nb = val["nb"]
    objective = (sum(w*c.cost(inst.eps_pen) for w,c in zip(weights,columns))
                 +inst.c_g*g.sum()+inst.c_b*nb+inst.eps_pen*(ch.sum()+dis.sum())+inst.deg_cost*dis.sum())
    residuals = {
        "coverage": float(np.max(abs(cov-1))),
        "balance": float(np.maximum(inst.Delta+grid+ch-dis-g,0).max()),
        "bess_dynamics": float(abs(np.diff(soc)-ch+dis).max()),
        "bess_periodic": float(abs(soc[-1]-soc[0])),
        "bess_capacity": float(np.maximum(soc-inst.G*nb,0).max()),
        "bess_charge_rate": float(np.maximum(ch-inst.rho*nb,0).max()),
        "bess_discharge_rate": float(np.maximum(dis-inst.rho*nb,0).max()),
        "nonnegative": float(max(0,-g.min(),-ch.min(),-dis.min(),-soc.min(),-nb)),
        "bess_integer": float(abs(nb-round(nb))) if integer else 0.,
        "fleet": float(abs(weights.sum()-val["fleet"])),
        "objective": float(abs(objective-saved["objective"])),
    }
    require(max(residuals.values()) < TOL, f"Physical direct replay failed: {residuals}")
    return {"passed":True,"paths":len(columns),"transitions":transitions,"residuals":residuals,
            "replayed_objective":float(objective),"battery_count":float(nb)}, columns


def scalar_pricing(inst, alpha, mu, nu):
    """Unpruned forward DP independently enumerating the declared transition set."""
    T,L,S = inst.T,len(inst.dist),int(round(inst.G/inst.soc_step))+1
    q = int(np.floor(inst.rho/inst.soc_step))
    labels = np.full((T+1,L,S,2),np.inf); labels[0,inst.depot,S-1,0] = 0
    tasks = {}
    for tr in inst.trips: tasks.setdefault((tr.start,tr.sloc),[]).append(tr)
    for t in range(T):
        for loc in range(L):
            for s in range(S):
                for served in (0,1):
                    base = labels[t,loc,s,served]
                    if not np.isfinite(base): continue
                    def relax(nt,nloc,ns,nserved,cost=0.):
                        if base+cost < labels[nt,nloc,ns,nserved]: labels[nt,nloc,ns,nserved]=base+cost
                    relax(t+1,loc,s,served)
                    if loc in inst.charge_locs:
                        for d in range(1,min(q,S-1-s)+1):
                            e=d*inst.soc_step;relax(t+1,loc,s+d,served,(mu[t]+nu[t]+inst.eps_pen)*e)
                        for d in range(1,min(q,s)+1):
                            e=d*inst.soc_step;relax(t+1,loc,s-d,served,(-mu[t]+inst.eps_pen+inst.deg_cost)*e)
                    for other in range(L):
                        if other==loc: continue
                        duration=int(round(inst.dist[loc,other]));draw=int(round(inst.deadhead_energy(loc,other)/inst.soc_step))
                        if t+duration<=T and s>=draw: relax(t+duration,other,s-draw,served)
                    for tr in tasks.get((t,loc),[]):
                        draw=int(round(tr.energy/inst.soc_step))
                        if s>=draw: relax(tr.end,tr.eloc,s-draw,1,-alpha[tr.idx])
    graph_rc = float(inst.c_v+labels[T,inst.depot,S-1,1])
    seed_rc = min(c.cost(inst.eps_pen)-c.a@alpha+c.e@mu+np.maximum(c.e,0)@nu
                  for tr in inst.trips if (c:=single_trip_column(inst,tr)) is not None)
    return {"graph_min_reduced_cost":graph_rc,"seed_min_reduced_cost":float(seed_rc),
            "min_reduced_cost":min(graph_rc,float(seed_rc))}


def audit_case(folder):
    start=time.perf_counter()
    raw=json.loads((folder/"instance.json").read_text());inst=instance_from_record(raw)
    unhashed={k:v for k,v in raw.items() if k!="sha256"}
    require(hashlib.sha256(json.dumps(unhashed,sort_keys=True).encode()).hexdigest()==raw["sha256"],
            "Saved instance content hash mismatch")
    random_family="spec" in raw and raw["spec"]["family"]=="random_diag2"
    require(inst.soc_step==.5 and inst.G==7 and inst.c_v==45 and inst.c_b==36,
            "Historical economic/capacity/grid settings mismatch")
    require((inst.rho==1.75 and inst.c_g==40 and inst.charge_locs==list(range(len(inst.dist))))
            if random_family else (inst.rho==.5 and inst.c_g==5 and inst.charge_locs==[0]),
            "Historical rate/generation/station settings mismatch")
    data={name:json.loads((folder/f"{name}.json").read_text()) for name in ("arc_lp","arc_mip","cg")}
    lp,a,cg=data["arc_lp"],data["arc_mip"],data["cg"];cert=cg["certification"];r=cg["restricted_mip"]
    require(lp["status"]=="optimal" and a["status"] in ("optimal","time_limit")
            and r["status"] in ("optimal","time_limit") and a["solution_count"]>0 and r["solution_count"]>0,
            "Optimal LP plus validated integer incumbents/bounds required")
    lp_replay,_=replay_direct(inst,lp,False);mip_replay,cols=replay_direct(inst,a,True)
    require(a["bound"]<=a["objective"]+TOL and r["bound"]<=r["objective"]+TOL,"Invalid MIP bound ordering")
    require(a["time_limit_seconds"]==cg["budget_seconds"]==1800
            and a["threads"]==cg["threads"]==r["threads"]==1
            and a["seed"]==cg["seed"]==r["seed"]==0,
            "Model-family or matched-budget metadata mismatch")
    if random_family:
        require(a["bess_rho"]==1.75 and a["effective_dag_truck_rho"]==1.5
                and a["seed_count"]==a["off_grid_seed_count"]==100,"Random hybrid family mismatch")
    a_exact=abs(a["objective"]-a["bound"])<TOL
    r_exact=abs(r["objective"]-r["bound"])<TOL
    require(max(abs(lp["objective"]-x) for x in (cg["cg_lp_objective"],cert["stopping_lp_objective"],cert["final_pool_lp"]["objective"]))<TOL,"LP values differ")
    require(cert["certificate_source"]=="actual_pre_enrichment_CG_stopping_duals","Wrong dual source")
    dual={k:np.asarray(v) for k,v in cert["stopping_duals"].items()}
    pricing=scalar_pricing(inst,dual["alpha"],dual["mu"],dual["nu"])
    require(pricing["min_reduced_cost"]>=-1e-6,"Full-family pricing not certified")
    require(max(abs(pricing[k]-cert[k]) for k in pricing if k in cert)<TOL,"Saved reduced-cost mismatch")
    with gzip.open(folder/"cg_columns.json.gz","rt") as stream: saved_columns=json.load(stream)
    cg_transitions=0
    for key in ("selected_lp_paths","selected_mip_paths"):
        check=cert[key];require(check["passed"] and abs(check["artificial_mass"])<TOL,"Invalid selected CG witness")
        coverage=np.zeros(inst.n_trips)
        for entry in check["witnesses"]:
            proof=entry["witness"];singleton=proof.get("family")=="initial_singleton"
            col,count=replay_path(inst,proof,singleton);cg_transitions+=count
            original=saved_columns[entry["column_index"]]
            require(original["kind"]=="truck" and np.max(abs(col.a-np.asarray(original["a"])))<TOL
                    and np.max(abs(col.e-np.asarray(original["e"])))<TOL
                    and abs(col.fixed_cost-original["fixed_cost"])<TOL,"Stored CG column differs from replay")
            coverage+=entry["weight"]*col.a
            if key=="selected_mip_paths":
                require(abs(entry["weight"]-round(entry["weight"]))<TOL,"Noninteger selected CG multiplicity")
        require(np.max(abs(coverage-1))<TOL,"Selected CG witness coverage mismatch")
    # These solves begin only after the entire timed batch is complete.
    check_start=time.perf_counter()
    path_lp=solve_lp(inst,cols,solver="highs",soc_mode="cyclic")
    path_mip=solve_milp(inst,cols,time_limit=60,solver="gurobi",soc_mode="cyclic",mip_gap=1e-9)
    require(path_lp.status=="optimal" and path_mip.status in ("optimal","feasible"),"Reconstructed vendor master has no verified result")
    require(lp["objective"]-TOL<=path_lp.obj<=a["objective"]+TOL,"Selected-path LP outside valid bounds")
    require(a["bound"]-TOL<=path_mip.obj<=a["objective"]+TOL,"Vendor path MIP outside valid direct bounds")
    if a_exact:
        require(abs(path_mip.obj-a["objective"])<TOL,"Vendor path MIP does not reproduce certified direct optimum")
        require(abs(getattr(path_mip,"solver_bound",np.nan)-a["objective"])<TOL,"Vendor path MIP bound differs")
    decomposition=({"integrality":a["objective"]-lp["objective"],
                    "route_restriction":r["objective"]-a["objective"],"unfinished_search":0.}
                   if a_exact and r_exact else None)
    return {"case":folder.name,"passed":True,
            "family":"random_hybrid" if random_family else "structured_aligned",
            "input_sha256":{p.name:digest(p) for p in [folder/"instance.json",folder/"arc_lp.json",folder/"arc_mip.json",folder/"cg.json",folder/"cg_columns.json.gz"]},
            "arc_lp_physical_replay":lp_replay,"arc_mip_physical_replay":mip_replay,
            "cg_selected_witness_transitions_replayed":cg_transitions,"independent_scalar_pricing":pricing,
            "common_lp":lp["objective"],"direct_integer_incumbent":a["objective"],"restricted_integer_incumbent":r["objective"],
            "direct_integer_bound":a["bound"],"restricted_integer_bound":r["bound"],
            "direct_optimum_certified_at_absolute_tolerance":a_exact,
            "restricted_optimum_certified_at_absolute_tolerance":r_exact,
            "absolute_gap_decomposition_if_both_bounds_tight":decomposition,
            "absolute_gap_component_intervals":{
                "integrality":[max(0,a["bound"]-lp["objective"]),max(0,a["objective"]-lp["objective"])],
                "route_restriction":[max(0,r["bound"]-a["objective"]),max(0,r["objective"]-a["bound"])],
                "unfinished_restricted_search":[0,max(0,r["objective"]-r["bound"])]},
            "vendor_selected_path_lp":{"status":path_lp.status,"objective":path_lp.obj,"comparison":"full LP <= selected-path LP <= direct integer optimum"},
            "vendor_selected_path_mip":{"status":path_mip.status,"objective":path_mip.obj,"bound":getattr(path_mip,"solver_bound",None)},
            "verification_solver_seconds":time.perf_counter()-check_start,"total_verification_seconds":time.perf_counter()-start}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",type=Path,default=ROOT/"results/random_extension_20261012")
    args=parser.parse_args();root=args.results.resolve()
    progress=json.loads((root/"progress.json").read_text())
    require(progress.get("status")=="completed" and progress.get("cases")==2,
            "All timed cases must finish before independent solver verification")
    import gurobipy as gp
    gp.setParam("OutputFlag",0);gp.setParam("Threads",1);gp.setParam("Seed",0)
    manifest=json.loads((root/"run_manifest.json").read_text())
    changed=[name for name,h in manifest["code_sha256"].items() if digest(ROOT/name)!=h]
    benchmark_dependencies={"arc_flow.py","column_witness.py","extension_instances.py",
                            "extension_models.py","run_extension.py","run_pilot.py","rmp_solver.py"}
    require(benchmark_dependencies.issubset(manifest["code_sha256"]),"Incomplete benchmark source manifest")
    benchmark_changed=sorted(benchmark_dependencies.intersection(changed))
    require(not benchmark_changed,f"Benchmark source changed since batch manifest: {benchmark_changed}")
    for name,row in manifest["vendor_manifest"]["files"].items():
        require(digest(ROOT/"vendor"/name)==row["sha256"],f"Vendor source drift: {name}")
    rows=[audit_case(root/case) for case in CASES]
    report={"passed":True,"purpose":"Independent post-batch audit; verification solves excluded from benchmark timing",
            "family":"Same finite DP-path plus verified initial-singleton union, original continuous BESS rate",
            "scope":"Physical replay of both direct LP/MIP and selected CG columns; independent full-DP/seed dual pricing; vendor path-master LP/MIP cross-check",
            "limitations":"Solver-tolerance certificates for two selected draws, not Table 4 two-draw medians, generic scalability, or continuous-truck-energy integer equivalence",
            "checker_sha256":digest(__file__),"run_manifest_sha256":digest(root/"run_manifest.json"),
            "benchmark_code_hashes_match":True,"checked_benchmark_dependencies":sorted(benchmark_dependencies),
            "unrelated_diagnostic_files_changed_since_manifest":sorted(set(changed)-benchmark_dependencies),
            "vendor_hashes_match":True,"absolute_tolerance":TOL,"cases":rows}
    target=root/"independent_audit.json";target.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"passed":True,"output":str(target),"cases":[r["case"] for r in rows]}))
    structured_root=ROOT/"results/structured_extension_20261012"
    structured_manifest=json.loads((structured_root/"run_manifest.json").read_text())
    structured_dependencies={"arc_flow.py","column_witness.py","run_pilot.py","rmp_solver.py"}
    require(structured_dependencies.issubset(structured_manifest["code_sha256"]),"Incomplete structured manifest")
    for name in structured_dependencies:
        require(digest(ROOT/name)==structured_manifest["code_sha256"][name],f"Structured benchmark drift: {name}")
    for name,row in structured_manifest["vendor_manifest"]["files"].items():
        require(digest(ROOT/"vendor"/name)==row["sha256"],f"Structured vendor drift: {name}")
    structured_rows=[audit_case(structured_root/f"n{n:03d}_e{energy}")
                     for n in (150,210) for energy in (150,200)]
    structured_report={**report,"family":"Aligned full DP-path family; original singleton seeds are graph paths",
                       "limitations":"Four structured extension inputs, not a general scalability or integrality result",
                       "run_manifest_sha256":digest(structured_root/"run_manifest.json"),
                       "checked_benchmark_dependencies":sorted(structured_dependencies),
                       "unrelated_diagnostic_files_changed_since_manifest":sorted(
                           name for name,h in structured_manifest["code_sha256"].items()
                           if name not in structured_dependencies and digest(ROOT/name)!=h),
                       "cases":structured_rows}
    target=structured_root/"independent_audit.json"
    target.write_text(json.dumps(structured_report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"passed":True,"output":str(target),"cases":[r["case"] for r in structured_rows]}))


if __name__=="__main__":
    main()
