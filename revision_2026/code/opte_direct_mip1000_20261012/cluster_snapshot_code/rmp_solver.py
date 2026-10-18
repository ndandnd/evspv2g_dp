"""Bounded Gurobi adapter for the frozen pilot restricted master.

``solve_rmp(inst, cols, integer, time_limit, log_path, threads=1,
            mip_gap=1e-6)`` returns ``(RMPSolution, diagnostics)``.

The vendor's ``master._build_lp`` supplies the coefficients and offsets. This
adapter supports exact task coverage, periodic aggregate BESS, and the pilot's
full-recharge truck columns. It does not generate or change columns. A caller
must verify the physical feasibility of each truck column separately; the
independent replay here checks the master and aggregate energy/storage balance.

The allowance starts at function entry and includes construction. Nonoptimal
LPs never return usable duals or a finite ``RMPSolution.obj``; their native
status and any available incumbent remain in diagnostics. Artificial columns
are permitted during CG, but a solution using them is never marked feasible
for the original model.
"""
from __future__ import annotations

from pathlib import Path
import math
import time

import numpy as np
from scipy import sparse

import master
from master import RMPSolution


def _validate_scope(inst, cols):
    if master.COVERING:
        raise ValueError("Pilot requires exact task coverage, not covering")
    if abs(inst.eta) > 1e-12:
        raise ValueError("Pilot RMP adapter supports eta=0 only")
    for attr in ("fuel_budget", "max_trucks"):
        if np.isfinite(getattr(inst, attr, float("inf"))):
            raise ValueError(f"Unsupported pilot extension: {attr}")
    if getattr(inst, "nb_fixed", -1.0) is not None and inst.nb_fixed >= 0:
        raise ValueError("Unsupported pilot extension: nb_fixed")
    for r, col in enumerate(cols):
        if col.kind not in ("truck", "artificial"):
            raise ValueError(f"Unexpected column kind {col.kind!r} at {r}")
        a = np.asarray(col.a); e = np.asarray(col.e)
        if a.shape != (inst.n_trips,) or e.shape != (inst.T,):
            raise ValueError(f"Column {r} has incompatible dimensions")
        if not np.all(np.isfinite(a)) or not np.all(np.isfinite(e)):
            raise ValueError(f"Column {r} is nonfinite")
        if np.any(abs(a - np.round(a)) > 1e-9) or np.any((a < 0) | (a > 1)) or a.sum() < 1:
            raise ValueError(f"Column {r} must cover a nonempty task subset exactly once")
        if not np.isfinite(col.fixed_cost) or col.fixed_cost < 0:
            raise ValueError(f"Column {r} has invalid fixed cost")


def replay_rmp(inst, cols, vec, offsets, bounds, integer, objective, tol=1e-5):
    """Reconstruct master constraints directly from column/physical data."""
    oX, oG, oC, oD, oS, oNb = offsets
    T, n, R = inst.T, inst.n_trips, len(cols)
    x = vec[oX:oX+R]; g=vec[oG:oG+T]; ch=vec[oC:oC+T]; dis=vec[oD:oD+T]
    soc=vec[oS:oS+T+1]; nb=float(vec[oNb])
    cov = np.zeros(n); grid = np.zeros(T); truck_charge = np.zeros(T)
    col_cost=0.0; artificial=0.0; trucks=0.0
    for weight, col in zip(x, cols):
        cov += weight * col.a; grid += weight * col.e
        truck_charge += weight * np.maximum(col.e, 0.0)
        col_cost += weight * (float(col.fixed_cost) + inst.eps_pen*float(np.abs(col.e).sum()))
        if col.kind == "artificial":
            artificial += weight
        else:
            trucks += weight
    caps = np.broadcast_to(np.asarray(inst.gen_cap, dtype=float), (T,))
    lb = np.asarray([0.0 if lo is None else lo for lo, hi in bounds])
    ub = np.asarray([np.inf if hi is None else hi for lo, hi in bounds])
    residuals = {
        "task_coverage": float(np.max(abs(cov-1.0), initial=0.0)),
        "energy_balance": float(np.max(np.maximum(inst.Delta+grid+ch-dis-g, 0.0), initial=0.0)),
        "battery_dynamics": float(np.max(abs(np.diff(soc)-(1-inst.eta)*ch+dis), initial=0.0)),
        "battery_periodic": abs(float(soc[-1]-soc[0])),
        "battery_capacity": float(np.max(np.maximum(soc-inst.G*nb, 0.0), initial=0.0)),
        "battery_charge_rate": float(np.max(np.maximum(ch-inst.rho*nb, 0.0), initial=0.0)),
        "battery_discharge_rate": float(np.max(np.maximum(dis-inst.rho*nb, 0.0), initial=0.0)),
        "generation_cap": float(np.max(np.maximum(g-caps, 0.0), initial=0.0)),
        "aggregate_charging_cap": float(np.max(np.maximum(truck_charge+ch-inst.charge_cap, 0.0), initial=0.0)),
        "lower_bounds": float(np.max(np.maximum(lb-vec, 0.0), initial=0.0)),
        "upper_bounds": float(np.max(np.maximum(vec-ub, 0.0), initial=0.0)),
        "column_integrality": float(np.max(abs(x-np.round(x)), initial=0.0)) if integer else 0.0,
        "battery_count_integrality": abs(nb-round(nb)) if integer else 0.0,
    }
    objective_replay = (col_cost+inst.c_g*float(g.sum())+inst.c_b*nb
                        +inst.eps_pen*float(ch.sum()+dis.sum())
                        +getattr(inst,"deg_cost",0.0)*float(dis.sum()))
    residuals["objective"] = abs(objective_replay-objective)
    passed = all(value <= (tol*max(1,abs(objective)) if key=="objective" else tol)
                 for key,value in residuals.items())
    if not passed:
        raise ValueError(f"Independent RMP replay failed: {residuals}")
    return {"passed": True, "scope":"aggregate_master_replay",
            "original_model_feasible": bool(artificial <= tol),
            "artificial_mass": float(artificial), "truck_count": float(trucks),
            "battery_count": nb, "residuals":residuals,
            "replayed_objective":float(objective_replay),
            "selected_columns":[{"index":int(r), "weight":float(w), "kind":cols[r].kind}
                                for r,w in enumerate(x) if w>tol]}


def _empty_solution(inst, R, integer, status):
    return RMPSolution(status, np.inf, np.zeros(R), np.zeros(inst.T),
                       np.full(inst.n_trips,np.nan), np.full(inst.T,np.nan), bool(integer),
                       nb=0.0, charge=np.zeros(inst.T), discharge=np.zeros(inst.T),
                       nu=np.full(inst.T,np.nan))


def solve_rmp(inst, cols, integer, time_limit, log_path, threads=1, mip_gap=1e-6):
    started=time.perf_counter()
    if not np.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("A positive finite end-to-end allowance is required")
    if threads != 1:
        raise ValueError("Matched pilot requires threads=1")
    if mip_gap is None or not np.isfinite(mip_gap) or mip_gap < 0:
        raise ValueError("mip_gap must be finite and nonnegative")
    _validate_scope(inst,cols)
    import gurobipy as gp
    from gurobipy import GRB
    c,au,bu,ae,be,bounds,off,n,T,R,cc_start=master._build_lp(inst,cols,True,soc_mode="cyclic")
    ae=sparse.csr_matrix(ae);au=sparse.csr_matrix(au)
    lb=np.asarray([0.0 if lo is None else lo for lo,hi in bounds],dtype=float)
    ub=np.asarray([np.inf if hi is None else hi for lo,hi in bounds],dtype=float)
    diag={"method":"restricted_master_mip" if integer else "restricted_master_lp",
          "integer":bool(integer),"columns":R,"time_limit_seconds":float(time_limit),
          "objective":None,"bound":None,"gap":None,"solution_count":0,
          "threads":1,"seed":0,"mip_gap_tolerance":float(mip_gap),
          "validation":None,"usable_optimal_lp":False,"solver_version":list(gp.gurobi.version())}
    if log_path is not None:
        log_path=Path(log_path);log_path.parent.mkdir(parents=True,exist_ok=True)
        diag["log_path"]=str(log_path.resolve())
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag",1 if log_path is not None else 0)
        env.setParam("LogToConsole",0)
        if log_path is not None:
            env.setParam("LogFile",str(log_path))
        env.start()
        with gp.Model("bounded_pilot_rmp",env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.MIPGap=mip_gap
            model.Params.FeasibilityTol=1e-8;model.Params.OptimalityTol=1e-8;model.Params.IntFeasTol=1e-8
            vt=np.full(len(c),GRB.CONTINUOUS)
            if integer:
                vt[off[0]:off[0]+R]=GRB.INTEGER;vt[off[5]]=GRB.INTEGER
            variables=model.addMVar(len(c),lb=lb,ub=ub,obj=c,vtype=vt,name="v")
            eq=model.addMConstr(ae,variables,"=",be,name="eq")
            le=model.addMConstr(au,variables,"<",bu,name="ub")
            model.update();built=time.perf_counter()
            remaining=time_limit-(built-started)
            diag.update(model_build_seconds=built-started,solver_budget_seconds=max(remaining,0.0),
                        variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,
                        integer_variables=model.NumIntVars,binary_variables=model.NumBinVars)
            if remaining<=0:
                diag.update(status="budget_exhausted_before_optimize",native_status=None,
                            solve_seconds=0.0,total_seconds=time.perf_counter()-started)
                return _empty_solution(inst,R,integer,diag["status"]),diag
            model.Params.TimeLimit=remaining
            solve_start=time.perf_counter();model.optimize();solved=time.perf_counter()
            names={GRB.OPTIMAL:"optimal",GRB.INFEASIBLE:"infeasible",GRB.INF_OR_UNBD:"infeasible_or_unbounded",
                   GRB.UNBOUNDED:"unbounded",GRB.TIME_LIMIT:"time_limit",GRB.INTERRUPTED:"interrupted",
                   GRB.NUMERIC:"numeric",GRB.SUBOPTIMAL:"suboptimal"}
            status=names.get(model.Status,f"status_{model.Status}")
            diag.update(status=status,native_status=model.Status,solution_count=model.SolCount,
                        solve_seconds=solved-solve_start,solver_runtime_seconds=model.Runtime,
                        solve_end_to_end_seconds=solved-started,node_count=float(model.NodeCount),
                        iterations=float(model.IterCount))
            for attr,key in (("ObjBound","bound"),("MIPGap","gap"),("MaxMemUsed","solver_peak_memory_gb")):
                try:
                    value=float(getattr(model,attr));diag[key]=value if math.isfinite(value) else None
                except (AttributeError,gp.GurobiError):
                    pass
            solution=_empty_solution(inst,R,integer,status)
            if model.SolCount:
                vec=np.asarray(variables.X);diag["objective"]=float(model.ObjVal)
                diag["validation"]=replay_rmp(inst,cols,vec,off,bounds,integer,model.ObjVal)
                # LP primal results at a limit are diagnostic only; CG requires an optimal LP.
                if integer or model.Status==GRB.OPTIMAL:
                    oX,oG,oC,oD,oS,oNb=off
                    alpha=np.full(n,np.nan);mu=np.full(T,np.nan);nu=np.full(T,np.nan)
                    if not integer:
                        ep=np.asarray(eq.Pi);ip=np.asarray(le.Pi)
                        alpha=ep[:n];mu=-ip[:T]
                        nu=-ip[cc_start:cc_start+T] if cc_start is not None else np.zeros(T)
                        diag["usable_optimal_lp"]=True;diag["bound"]=float(model.ObjVal);diag["gap"]=0.0
                    solution=RMPSolution("optimal" if model.Status==GRB.OPTIMAL else "feasible",
                        float(model.ObjVal),vec[oX:oX+R],vec[oG:oG+T],alpha,mu,bool(integer),
                        float(vec[oNb]),vec[oC:oC+T],vec[oD:oD+T],nu)
                    solution.soc=vec[oS:oS+T+1]
            solution.native_status=model.Status;solution.solver_bound=diag["bound"]
            solution.solver_gap=diag["gap"]
            diag["validation_seconds"]=time.perf_counter()-solved
            diag["total_seconds"]=time.perf_counter()-started
    return solution,diag
