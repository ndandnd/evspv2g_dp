"""Exact direct representation of the vendor DP-path plus singleton-seed family.

The frozen pilot modules are unchanged. This extension supports lossless data
whose capacities, travel/task energy and times are aligned, but whose per-block
charging rate need not be a multiple of the SoC step. The truck DP then permits
``floor(rho / step)`` levels per block; aggregate BESS retains the ORIGINAL rho.
Every real singleton produced by the frozen vendor initialization is also an
explicit variable, including its continuous off-grid recharge profile. Thus the
comparison family is precisely DP paths UNION those initial singletons, rather
than an unqualified continuous-energy route family.

Public API:
    build_extended_graph(inst) -> frozen arc_flow.Graph
    seed_columns(inst) -> list[Column]
    validate_extended_selected_columns(inst, graph, cols, x, tol=1e-7) -> dict
    solve_extended_arc_flow(inst, relax, time_limit, log_path, threads=1) -> dict

Full/full truck boundaries and periodic aggregate BESS only. Returned validation
``paths`` are DAG paths; ``singleton_paths`` separately records explicit seed
variables. Their masses together equal ``fleet``. All timings include graph,
seed and model construction; post-solve replay is separately identified.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy import sparse

import arc_flow
from column_witness import find_column_path, _replay
from rmp_solver import replay_rmp
from master import Column
from colgen import single_trip_column


def effective_truck_rate(inst):
    step = float(inst.soc_step)
    if not np.isfinite(step) or step <= 0 or not np.isfinite(inst.rho) or inst.rho < 0:
        raise ValueError("Finite nonnegative rho and positive soc_step required")
    if not np.isfinite(inst.eta) or abs(inst.eta) > 1e-12:
        raise ValueError("Extension supports eta=0 only")
    # No epsilon adjustment: this is exactly the frozen DP's floor expression.
    return float(np.floor(inst.rho / step) * step)


def build_extended_graph(inst):
    graph_inst = copy.copy(inst)
    graph_inst.rho = effective_truck_rate(inst)
    return arc_flow.build_graph(graph_inst)


def _singleton_witness(inst, tr, col, tol=1e-7):
    """Physically replay the vendor seed's one-trip skeleton at original rho."""
    if abs(inst.eta) > tol:
        raise ValueError("Singleton witness requires eta=0")
    origin = inst.depot
    departure = tr.start-inst.deadhead_time(origin, tr.sloc)
    returned = tr.end+inst.deadhead_time(tr.eloc, origin)
    if departure < 0 or returned > inst.T:
        raise ValueError(f"Seed for task {tr.idx} exceeds the horizon")
    expected_a = np.zeros(inst.n_trips); expected_a[tr.idx] = 1
    if (col.kind != "truck" or np.max(abs(col.a-expected_a), initial=0) > tol
            or abs(col.fixed_cost-inst.c_v) > tol):
        raise ValueError(f"Unexpected singleton incidence/cost for task {tr.idx}")
    energy = np.asarray(col.e, dtype=float)
    if (energy.shape != (inst.T,) or not np.all(np.isfinite(energy))
            or np.any(abs(energy[:returned]) > tol) or np.any(energy < -tol)
            or np.any(energy > inst.rho+tol)):
        raise ValueError(f"Invalid singleton charging profile for task {tr.idx}")
    states = [[0, origin, float(inst.G), 0]]
    kinds, draws = [], []
    t=0; loc=origin; soc=float(inst.G); served=0; max_bounds=0.0
    def event(end, destination, kind, traction=0.0, draw=0.0):
        nonlocal t, loc, soc, served, max_bounds
        if end <= t:
            raise ValueError("Singleton event must advance time")
        if kind == "task":
            served=1
        soc += draw-traction; t=int(end); loc=int(destination)
        max_bounds=max(max_bounds, max(0.0,-soc,soc-inst.G))
        states.append([t,loc,float(soc),served]);kinds.append(kind);draws.append(float(draw))
    while t < departure:
        event(t+1,origin,"wait")
    if tr.sloc != origin:
        event(tr.start,tr.sloc,"travel",inst.deadhead_energy(origin,tr.sloc))
    if t != tr.start or loc != tr.sloc:
        raise ValueError("Singleton task departure mismatch")
    event(tr.end,tr.eloc,"task",tr.energy)
    if tr.eloc != origin:
        event(returned,origin,"travel",inst.deadhead_energy(tr.eloc,origin))
    if t != returned or loc != origin:
        raise ValueError("Singleton return mismatch")
    while t < inst.T:
        draw=float(energy[t])
        event(t+1,origin,"charge" if draw > tol else "wait",draw=draw)
    traction=tr.energy+inst.deadhead_energy(origin,tr.sloc)+inst.deadhead_energy(tr.eloc,origin)
    residuals={"soc_bounds":float(max_bounds),"full_boundary":abs(soc-inst.G),
               "energy_closure":abs(float(energy.sum())-traction),
               "fixed_cost":abs(col.fixed_cost-inst.c_v)}
    if max(residuals.values()) > tol:
        raise ValueError(f"Vendor singleton for task {tr.idx} is physically invalid: {residuals}")
    offgrid=float(np.max(abs(energy/inst.soc_step-np.rint(energy/inst.soc_step)),initial=0))
    return {"passed":True,"family":"initial_singleton","task_ids":[int(tr.idx)],
            "states":states,"state_schema":["time","location","soc_energy_units","served_task"],
            "kinds":kinds,"energy":draws,"profile":energy.tolist(),
            "task_coverage":expected_a.tolist(),"original_rho":float(inst.rho),
            "effective_dag_rho":effective_truck_rate(inst),"off_grid_profile":bool(offgrid>tol),
            "off_grid_residual":offgrid,"traction_energy":float(traction),
            "column_cost":float(col.cost(inst.eps_pen)),"residuals":residuals,
            "max_residual":float(max(residuals.values()))}


def _seeds_with_witnesses(inst):
    effective_truck_rate(inst)
    seeds=[];witnesses=[]
    for tr in inst.trips:
        col=single_trip_column(inst,tr,ice=False,free_start=False)
        if col is not None:
            seeds.append(col);witnesses.append(_singleton_witness(inst,tr,col))
    return seeds,witnesses


def seed_columns(inst):
    """Exact physical vendor initial singletons, in vendor task iteration order."""
    return _seeds_with_witnesses(inst)[0]


def validate_extended_selected_columns(inst,graph,cols,x,tol=1e-7):
    weights=np.asarray(x,dtype=float)
    if (not np.isfinite(tol) or tol<=0 or weights.shape!=(len(cols),)
            or not np.all(np.isfinite(weights)) or np.any(weights < -tol)):
        return {"passed":False,"reason":"invalid_weights_or_tolerance","witnesses":[]}
    seeds,proofs=_seeds_with_witnesses(inst)
    selected=np.flatnonzero(weights>tol);rows=[];cache={};artificial=0.0
    for index in selected:
        col=cols[int(index)]
        if col.kind=="artificial":
            artificial+=float(weights[index])
        key=(col.kind,np.asarray(col.a).tobytes(),np.asarray(col.e).tobytes(),float(col.fixed_cost))
        if key not in cache:
            profile=np.asarray(col.e,dtype=float)
            offgrid=(profile.shape!=(inst.T,) or not np.all(np.isfinite(profile)) or
                     np.max(abs(profile/graph.step-np.rint(profile/graph.step)),initial=0)>tol)
            if not offgrid:
                witness=find_column_path(inst,graph,col,tol)
                witness={**witness,"family":"dp_path"}
            else:
                witness={"passed":False,"reason":"off_grid_profile_not_an_initial_singleton"}
                for seed,proof in zip(seeds,proofs):
                    if (col.kind=="truck" and np.shape(col.a)==np.shape(seed.a)
                            and np.shape(col.e)==np.shape(seed.e)
                            and np.max(abs(col.a-seed.a),initial=0)<=tol
                            and np.max(abs(col.e-seed.e),initial=0)<=tol
                            and abs(col.fixed_cost-seed.fixed_cost)<=tol):
                        witness={**proof,"reason":"matched_verified_initial_singleton"};break
            cache[key]=witness
        rows.append({"column_index":int(index),"weight":float(weights[index]),
                     "label":col.label,"witness":cache[key]})
    passed=all(row["witness"]["passed"] for row in rows)
    return {"passed":passed,"reason":"all_selected_columns_witnessed" if passed else "selected_column_failure",
            "selected_count":len(rows),"selected_mass":float(weights[selected].sum()),
            "artificial_mass":artificial,"witnesses":rows,"distinct_witnesses":len(cache),
            "max_residual":max((r["witness"].get("max_residual",0.0) for r in rows),default=0.0),
            "tolerance":tol,"scope":"Physical DP-path or verified initial-singleton witnesses; aggregate master and pricing certificates checked separately."}


def _hybrid_matrices(inst,graph,seeds):
    # IMPORTANT: original inst here retains original BESS rho; only the graph
    # was constructed with the floor-limited truck transition rate.
    c,lb,ub,ae,be,au,bu,off=arc_flow._matrices(inst,graph)
    V=len(c);K=len(seeds);N=graph.n_nodes;T=inst.T
    er=[];ec=[];ev=[];ur=[];uc=[];uv=[]
    cc=4*T+1 if np.isfinite(inst.charge_cap) else None
    for j,col in enumerate(seeds):
        for i in np.flatnonzero(col.a):
            er.append(N+int(i));ec.append(j);ev.append(float(col.a[i]))
        for t in np.flatnonzero(col.e):
            ur.append(int(t));uc.append(j);uv.append(float(col.e[t]))
            if cc is not None and col.e[t]>0:
                ur.append(cc+int(t));uc.append(j);uv.append(float(col.e[t]))
    se=sparse.coo_matrix((ev,(er,ec)),shape=(ae.shape[0],K)).tocsr()
    su=sparse.coo_matrix((uv,(ur,uc)),shape=(au.shape[0],K)).tocsr()
    ae=sparse.hstack((ae,se),format="csr");au=sparse.hstack((au,su),format="csr")
    c=np.r_[c,[col.cost(inst.eps_pen) for col in seeds]]
    lb=np.r_[lb,np.zeros(K)];ub=np.r_[ub,np.ones(K)]
    off={**off,"seed_start":V,"seed_count":K}
    return c,lb,ub,ae,be,au,bu,off


def _hybrid_replay(inst,graph,seeds,seed_proofs,vec,off,objective,integer):
    paths=arc_flow.decompose_paths(graph,vec[:graph.n_arcs])
    columns=[];weights=[];dag_schedules=[]
    for path in paths:
        a=np.zeros(inst.n_trips);a[path["tasks"]]=1
        e=np.zeros(inst.T)
        for edge in path["arcs"]:
            e[graph.states[graph.tail[edge],0]]+=graph.energy[edge]
        col=Column("truck",a,e,inst.c_v+getattr(inst,"deg_cost",0.0)*np.maximum(-e,0).sum())
        witness=_replay(inst,graph,col,path["arcs"],1e-6)
        if not witness["passed"]:
            raise ValueError(f"DAG path failed physical replay: {witness}")
        columns.append(col);weights.append(path["weight"])
        dag_schedules.append({"weight":path["weight"],"tasks":path["tasks"],
                              "states":witness["states"],"kinds":witness["kinds"],"energy":witness["energy"]})
    singleton_schedules=[]
    seedweights=vec[off["seed_start"]:off["seed_start"]+len(seeds)]
    for j,(col,proof,w) in enumerate(zip(seeds,seed_proofs,seedweights)):
        if w>1e-7:
            columns.append(col);weights.append(float(w))
            singleton_schedules.append({"seed_index":j,"weight":float(w),"witness":proof})
    R=len(columns);T=inst.T;g=vec[off["g"]:off["g"]+T]
    ch=vec[off["charge"]:off["charge"]+T];dis=vec[off["discharge"]:off["discharge"]+T]
    soc=vec[off["soc"]:off["soc"]+T+1];nb=vec[off["nb"]]
    mastervec=np.r_[weights,g,ch,dis,soc,nb]
    moff=(0,R,R+T,R+2*T,R+3*T,R+4*T+1)
    bounds=[(0,None)]*len(mastervec)
    caps=np.broadcast_to(np.asarray(inst.gen_cap),(T,))
    for t in range(T):
        bounds[R+t]=(0,None if not np.isfinite(caps[t]) else float(caps[t]))
    aggregate=replay_rmp(inst,columns,mastervec,moff,bounds,integer,objective,tol=1e-5)
    dag_fleet=float(sum(p["weight"] for p in paths));seed_fleet=float(seedweights.sum())
    fleet_error=abs(dag_fleet-vec[off["fleet"]])
    if fleet_error>1e-5:
        raise ValueError("DAG fleet flow disagrees with decomposition")
    return {"passed":True,"residuals":{**aggregate["residuals"],"dag_fleet":fleet_error},
            "fleet":dag_fleet+seed_fleet,"dag_fleet":dag_fleet,"singleton_fleet":seed_fleet,
            "nb":float(nb),"replayed_objective":aggregate["replayed_objective"],
            "paths":dag_schedules,"singleton_paths":singleton_schedules,
            "generation":g.tolist(),"battery_charge":ch.tolist(),"battery_discharge":dis.tolist(),
            "battery_soc":soc.tolist(),"aggregate_replay":aggregate}


def solve_extended_arc_flow(inst,relax,time_limit,log_path,threads=1):
    started=time.perf_counter()
    if not np.isfinite(time_limit) or time_limit<=0 or threads!=1:
        raise ValueError("Positive finite end-to-end budget and threads=1 required")
    import gurobipy as gp
    from gurobipy import GRB
    graph=build_extended_graph(inst);seeds,proofs=_seeds_with_witnesses(inst)
    graph_done=time.perf_counter()
    c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(inst,graph,seeds)
    result={"method":"extended_arc_flow_lp" if relax else "extended_arc_flow_mip","relax":bool(relax),
            "family":"all_frozen_DP_paths_union_verified_vendor_initial_singletons",
            "n_tasks":inst.n_trips,"original_rho":float(inst.rho),"bess_rho":float(inst.rho),
            "effective_dag_truck_rho":effective_truck_rate(inst),"soc_step":float(inst.soc_step),
            "seed_count":len(seeds),"off_grid_seed_count":sum(p["off_grid_profile"] for p in proofs),
            "graph_seconds":graph_done-started,"graph_nodes":graph.n_nodes,"graph_arcs":graph.n_arcs,
            "unpruned_states":graph.unpruned_states,"unpruned_arcs":graph.unpruned_arcs,
            "objective":None,"bound":None,"gap":None,"solution_count":0,"validation":None,
            "time_limit_seconds":float(time_limit),"threads":1,"seed":0,"solver_version":list(gp.gurobi.version())}
    if log_path is not None:
        log_path=Path(log_path);log_path.parent.mkdir(parents=True,exist_ok=True)
        result["log_path"]=str(log_path.resolve())
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag",1 if log_path is not None else 0);env.setParam("LogToConsole",0)
        if log_path is not None:
            env.setParam("LogFile",str(log_path))
        env.start()
        with gp.Model("direct_DP_paths_plus_singletons",env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.MIPGap=1e-6
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8;model.Params.IntFeasTol=1e-8
            vtype=np.full(len(c),GRB.CONTINUOUS)
            if not relax:
                vtype[:graph.n_arcs+1]=GRB.INTEGER;vtype[off["nb"]]=GRB.INTEGER
                vtype[off["seed_start"]:]=GRB.INTEGER
            variables=model.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=vtype,name="v")
            model.addMConstr(ae,variables,"=",be,name="eq")
            model.addMConstr(au,variables,"<",bu,name="ub")
            model.update();built=time.perf_counter();remaining=time_limit-(built-started)
            result.update(model_build_seconds=built-graph_done,variables=model.NumVars,constraints=model.NumConstrs,
                          nonzeros=model.NumNZs,integer_variables=model.NumIntVars,binary_variables=model.NumBinVars,
                          solver_budget_seconds=max(remaining,0.0))
            if remaining<=0:
                result.update(status="budget_exhausted_before_optimize",native_status=None,
                              solve_seconds=0.0,total_seconds=time.perf_counter()-started)
                return result
            model.Params.TimeLimit=remaining
            ss=time.perf_counter();model.optimize();finished=time.perf_counter()
            names={GRB.OPTIMAL:"optimal",GRB.INFEASIBLE:"infeasible",GRB.INF_OR_UNBD:"infeasible_or_unbounded",
                   GRB.UNBOUNDED:"unbounded",GRB.TIME_LIMIT:"time_limit",GRB.INTERRUPTED:"interrupted",
                   GRB.NUMERIC:"numeric",GRB.SUBOPTIMAL:"suboptimal"}
            result.update(status=names.get(model.Status,f"status_{model.Status}"),native_status=model.Status,
                          solution_count=model.SolCount,solve_seconds=finished-ss,solver_runtime_seconds=model.Runtime,
                          solve_end_to_end_seconds=finished-started,node_count=float(model.NodeCount),iterations=float(model.IterCount))
            for attr,key in (("ObjBound","bound"),("MIPGap","gap"),("MaxMemUsed","solver_peak_memory_gb")):
                try:
                    value=float(getattr(model,attr));result[key]=value if math.isfinite(value) else None
                except (AttributeError,gp.GurobiError):pass
            if model.SolCount:
                result["objective"]=float(model.ObjVal)
                if relax and model.Status==GRB.OPTIMAL:
                    result["bound"]=float(model.ObjVal);result["gap"]=0.0
                result["validation"]=_hybrid_replay(inst,graph,seeds,proofs,np.asarray(variables.X),off,model.ObjVal,not relax)
            result["validation_seconds"]=time.perf_counter()-finished
            result["total_seconds"]=time.perf_counter()-started
    return result
