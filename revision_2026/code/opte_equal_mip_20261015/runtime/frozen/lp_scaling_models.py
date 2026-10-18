"""LP-only matched-family adapters. Never enrich columns or solve an integer model.

Direct methods reuse the frozen hybrid graph-plus-singletons matrices. CG reuses
the frozen stabilized algorithm and cold-rebuilt RMP adapter with enrich=0.
This measures that fixed CG implementation, not an optimally warm-started CG.
Final replay/certification and evidence serialization are outside time-to-stop,
reported separately. Intermediate RMP replay remains inside CG's timed budget.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import sys
import time

import numpy as np

import colgen
from master import reduced_cost
from arc_flow import shortest_path_reduced_cost
from extension_models import (build_extended_graph, _seeds_with_witnesses,
    _hybrid_matrices, _hybrid_replay, validate_extended_selected_columns)
from rmp_solver import solve_rmp
from run_pilot import BudgetExpired, safe, write_json

TOL=1e-6


def peak_rss_bytes():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform=="darwin" else value*1024)


def _max(values):
    return float(np.max(values,initial=0.0))


def matrix_certificate(c,lb,ub,ae,be,au,bu,x,pi_eq,pi_ub,rc,objective):
    """Native LP certificate, including every finite variable-bound multiplier.

Direct row duals alone are NOT interpreted as route-master pricing duals: flow
and singleton upper bounds can carry reduced costs. Tiny residuals are reported
explicitly rather than claiming exact-arithmetic certification.
    """
    implied=c-ae.T@pi_eq-au.T@pi_ub
    finite_ub=np.isfinite(ub)
    lower_mult=np.maximum(rc,0.0);upper_mult=np.minimum(rc,0.0)
    dual=float(be@pi_eq+bu@pi_ub+lb@lower_mult+ub[finite_ub]@upper_mult[finite_ub])
    residuals={"equalities":_max(abs(ae@x-be)),"inequalities":_max(au@x-bu),
        "lower_bounds":_max(lb-x),"upper_bounds":_max(x[finite_ub]-ub[finite_ub]),
        "dual_row_sign":_max(pi_ub),"stationarity":_max(abs(rc-implied)),
        "unbounded_variable_dual_sign":_max(-rc[~finite_ub]),
        "objective_reconstruction":abs(float(c@x)-objective),
        "primal_dual_objective_difference":abs(objective-dual)}
    return {"passed":max(residuals.values())<=TOL,"absolute_tolerance":TOL,
            "residuals":residuals,"primal_objective":float(objective),"dual_objective":dual,
            "finite_upper_bound_dual_contribution":float(ub[finite_ub]@upper_mult[finite_ub]),
            "scope":"Native row and bound dual certificate to numerical tolerance"}


def _phase_log(log_path):
    if not log_path or not Path(log_path).exists():
        return {}
    text=Path(log_path).read_text(errors="replace")
    selected=[s.strip() for s in text.splitlines() if re.search(
        r"Barrier solved|Crossover log|Crossover time|Solved in|Presolve time|Concurrent",s)]
    barrier=re.findall(r"Barrier solved model in\s+(\d+) iterations and\s+([\d.]+) seconds",text)
    crossover=re.findall(r"Crossover time:\s*([\d.]+) seconds",text)
    return {"phase_lines":selected,"barrier_log_iterations":int(barrier[-1][0]) if barrier else None,
            "barrier_log_seconds":float(barrier[-1][1]) if barrier else None,
            "crossover_log_seconds":float(crossover[-1]) if crossover else None,
            "phase_time_precision":"Native log values are rounded; full runtime remains unrounded"}


def solve_direct_lp(inst,method,time_limit,log_path,threads=1,crossover=-1,evidence_dir=None):
    """Return diagnostics for explicit dual-simplex or barrier LP; no model reuse."""
    if method not in ("dual","barrier") or threads!=1 or not np.isfinite(time_limit) or time_limit<=0:
        raise ValueError("method dual/barrier, one thread, and positive finite budget required")
    if crossover not in (-1,0,1,2,3,4):
        raise ValueError("Invalid crossover parameter")
    import gurobipy as gp
    from gurobipy import GRB
    started=time.perf_counter()
    graph=build_extended_graph(inst);seeds,proofs=_seeds_with_witnesses(inst)
    graph_done=time.perf_counter()
    c,lb,ub,ae,be,au,bu,off=_hybrid_matrices(inst,graph,seeds)
    matrices_done=time.perf_counter()
    out={"method":"direct_"+method,"family":"DP_paths_union_real_singleton_seeds",
         "budget_seconds":float(time_limit),"threads":1,"seed":0,
         "gurobi_method":1 if method=="dual" else 2,"crossover_parameter":crossover,
         "feasibility_tolerance":1e-8,"optimality_tolerance":1e-8,"barrier_convergence_tolerance":1e-8,
         "solver_version":list(gp.gurobi.version()),"graph_seconds":graph_done-started,
         "matrix_build_seconds":matrices_done-graph_done,"graph_nodes":graph.n_nodes,
         "graph_arcs":graph.n_arcs,"unpruned_states":graph.unpruned_states,
         "unpruned_arcs":graph.unpruned_arcs,"seed_count":len(seeds),
         "off_grid_seed_count":sum(p["off_grid_profile"] for p in proofs),
         "physical_rho":float(inst.rho),"dag_truck_rho":float(np.floor(inst.rho/inst.soc_step)*inst.soc_step),
         "status":None,"native_status":None,"objective":None,"certified":False,
         "validation":None,"native_dual_certificate":None,"barrier_callback_last":None,
         "first_crossover_or_simplex_callback_runtime":None,"crossover_banner_callback_runtime":None,
         "barrier_solved_banner_callback_runtime":None}
    if log_path:
        log_path=Path(log_path);log_path.parent.mkdir(parents=True,exist_ok=True)
    with gp.Env(empty=True) as env:
        env.setParam("LogToConsole",0);env.setParam("OutputFlag",int(log_path is not None))
        if log_path:env.setParam("LogFile",str(log_path))
        env.start()
        with gp.Model("lp_scaling_direct_"+method,env=env) as model:
            model.Params.Threads=1;model.Params.Seed=0;model.Params.Method=out["gurobi_method"]
            model.Params.Crossover=crossover;model.Params.FeasibilityTol=1e-8
            model.Params.OptimalityTol=1e-8;model.Params.BarConvTol=1e-8
            x=model.addMVar(len(c),lb=lb,ub=ub,obj=c,name="v")
            eq=model.addMConstr(ae,x,"=",be,name="eq")
            le=model.addMConstr(au,x,"<",bu,name="ub")
            model.update();built=time.perf_counter();remaining=time_limit-(built-started)
            out.update(model_build_seconds=built-graph_done,gurobi_build_seconds=built-matrices_done,
                       variables=model.NumVars,constraints=model.NumConstrs,nonzeros=model.NumNZs,
                       solver_budget_seconds=max(0.0,remaining))
            if remaining<=0:
                out.update(status="budget_exhausted_before_optimize",solve_end_to_end_seconds=built-started)
                return out
            model.Params.TimeLimit=remaining
            def observe(m,where):
                if where==GRB.Callback.BARRIER:
                    out["barrier_callback_last"]={"runtime":float(m.cbGet(GRB.Callback.RUNTIME)),
                        "iteration":int(m.cbGet(GRB.Callback.BARRIER_ITRCNT)),
                        "primal_objective":float(m.cbGet(GRB.Callback.BARRIER_PRIMOBJ)),
                        "dual_objective":float(m.cbGet(GRB.Callback.BARRIER_DUALOBJ)),
                        "primal_infeasibility":float(m.cbGet(GRB.Callback.BARRIER_PRIMINF)),
                        "dual_infeasibility":float(m.cbGet(GRB.Callback.BARRIER_DUALINF))}
                elif where==GRB.Callback.SIMPLEX and out["first_crossover_or_simplex_callback_runtime"] is None:
                    out["first_crossover_or_simplex_callback_runtime"]=float(m.cbGet(GRB.Callback.RUNTIME))
                elif where==GRB.Callback.MESSAGE:
                    message=m.cbGet(GRB.Callback.MSG_STRING)
                    if "Crossover log" in message:
                        out["crossover_banner_callback_runtime"]=float(m.cbGet(GRB.Callback.RUNTIME))
                    elif "Barrier solved model" in message:
                        out["barrier_solved_banner_callback_runtime"]=float(m.cbGet(GRB.Callback.RUNTIME))
            solver_start=time.perf_counter();model.optimize(observe);stopped=time.perf_counter()
            labels={GRB.OPTIMAL:"optimal",GRB.TIME_LIMIT:"time_limit",GRB.INFEASIBLE:"infeasible",
                    GRB.INF_OR_UNBD:"infeasible_or_unbounded",GRB.UNBOUNDED:"unbounded",
                    GRB.INTERRUPTED:"interrupted",GRB.NUMERIC:"numeric",GRB.SUBOPTIMAL:"suboptimal"}
            out.update(status=labels.get(model.Status,str(model.Status)),native_status=model.Status,
                       solve_end_to_end_seconds=stopped-started,solve_seconds=stopped-solver_start,
                       solver_runtime_seconds=float(model.Runtime),iterations=float(model.IterCount),
                       barrier_iterations=int(model.BarIterCount),solution_count=model.SolCount,
                       process_peak_rss_at_stop_bytes=peak_rss_bytes())
            if out["crossover_banner_callback_runtime"] is not None:
                out["crossover_banner_to_solver_finish_seconds"]=max(0.0,float(model.Runtime)-out["crossover_banner_callback_runtime"])
            for attr,key in (("MaxMemUsed","solver_peak_memory_gb"),("Work","solver_work"),
                             ("ConstrVio","solver_constraint_violation"),("BoundVio","solver_bound_violation"),
                             ("DualVio","solver_dual_violation")):
                try:out[key]=float(getattr(model,attr))
                except (AttributeError,gp.GurobiError):out[key]=None
            if model.SolCount:
                vector=np.asarray(x.X);out["objective"]=float(model.ObjVal)
                if evidence_dir:
                    evidence_dir=Path(evidence_dir);evidence_dir.mkdir(parents=True,exist_ok=True)
                    np.savez_compressed(evidence_dir/"direct_primal.npz",x=vector)
                try:
                    out["validation"]=_hybrid_replay(inst,graph,seeds,proofs,vector,off,model.ObjVal,False)
                except ValueError as exc:
                    out["validation"]={"passed":False,"error":str(exc)}
                if model.Status==GRB.OPTIMAL:
                    ep=np.asarray(eq.Pi);ip=np.asarray(le.Pi);rc=np.asarray(x.RC)
                    out["native_dual_certificate"]=matrix_certificate(c,lb,ub,ae,be,au,bu,vector,ep,ip,rc,model.ObjVal)
                    if evidence_dir:
                        np.savez_compressed(evidence_dir/"direct_dual.npz",pi_eq=ep,pi_ub=ip,reduced_cost=rc)
                    out["certified"]=bool(out["validation"]["passed"] and out["native_dual_certificate"]["passed"])
            out["diagnostic_seconds"]=time.perf_counter()-stopped
    out["phase_log"]=_phase_log(log_path)
    out["total_including_checks_seconds"]=time.perf_counter()-started
    return out


def solve_cg_lp(inst,time_limit,output_dir,threads=1,max_iter=20000):
    """Frozen CG, no enrichment, no MIP; certify the actual returned stopping LP.

Budget/iteration-limit returns never silently claim optimality. A duplicate-only
vendor stop becomes certified only if independent graph AND seed pricing pass.
    """
    if threads!=1 or time_limit<=0 or not np.isfinite(time_limit) or max_iter<1:
        raise ValueError("One thread and positive finite budget/iteration limit required")
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter();deadline=started+time_limit
    original_lp,original_price=colgen.solve_lp,colgen.price_truck_dp
    calls=[];price_calls=[];trace=[];last={};generated=None
    out={"method":"cg","family":"DP_paths_union_real_singleton_seeds","budget_seconds":float(time_limit),
         "threads":1,"seed":0,"pricing_tolerance":TOL,"max_cg_iterations":max_iter,
         "stabilization_beta":0.5,"enrichment_rounds":0,"final_mip":False,"certified":False,
         "rmp_implementation":"Frozen cold rebuild per LP; automatic Gurobi method; no basis reuse",
         "status":None,"objective":None,"certificate":None}
    def remaining():
        value=deadline-time.perf_counter()
        if value<=0:raise BudgetExpired("Common LP budget exhausted")
        return value
    def lp_callback(instance,columns,battery_allowed=True,solver=None,soc_mode="cyclic"):
        if not battery_allowed or soc_mode!="cyclic":raise ValueError("Only V2G/cyclic supported")
        sol,diag=solve_rmp(instance,columns,False,remaining(),output_dir/"logs"/f"rmp_{len(calls):05d}.log")
        compact={k:v for k,v in diag.items() if k!="validation"}
        if diag["validation"]:
            compact["validation_summary"]={k:v for k,v in diag["validation"].items() if k!="selected_columns"}
        calls.append(compact)
        last.update(solution=sol,columns=list(columns),diagnostics=diag,elapsed_after_rmp=time.perf_counter()-started)
        trace.append({"lp_call":len(calls),"elapsed_seconds":last["elapsed_after_rmp"],
                      "rmp_objective":diag.get("objective"),"columns":len(columns),
                      "status":diag["status"],"full_family_bound_certified":False})
        if len(calls)==1 or len(calls)%25==0:
            write_json(output_dir/"progress.json",{"trace":trace,"pricing_calls":len(price_calls)})
        if sol.status!="optimal":raise BudgetExpired(f"Nonoptimal RMP status: {diag['status']}")
        remaining()
        return sol
    def price_callback(*args,**kwargs):
        remaining();before=time.perf_counter();answer=original_price(*args,**kwargs);after=time.perf_counter()
        actual=bool(last and np.array_equal(args[1],last["solution"].alpha)
                    and np.array_equal(args[2],last["solution"].mu)
                    and np.array_equal(kwargs.get("nu"),last["solution"].nu))
        price_calls.append({"seconds":after-before,"completed_elapsed_seconds":after-started,
                            "returned_candidates":len(answer),"at_current_rmp_duals":actual})
        remaining();return answer
    try:
        colgen.solve_lp,colgen.price_truck_dp=lp_callback,price_callback
        generated=colgen.column_generation(inst,scenario="v2g",start="warm",tol=TOL,rc_stop=0,beta=0.5,
            max_iter=max_iter,do_milp=False,verbose=False,enrich=0,lp_solver="gurobi",soc_mode="cyclic")
        stopped=time.perf_counter()
        out.update(status="candidate_stopping_lp" if generated["converged"] else "iteration_limit",
                   cg_claimed_converged=generated["converged"],cg_termination_reason=generated["term_reason"],
                   cg_iterations=generated["iters"],pricing_seconds=generated["pricing_time"],
                   solve_end_to_end_seconds=stopped-started,columns=len(generated["cols"]))
        if stopped>deadline:out["status"]="budget_exhausted"
    except BudgetExpired as exc:
        stopped=time.perf_counter();out.update(status="budget_exhausted",error=str(exc),
            solve_end_to_end_seconds=stopped-started,cg_claimed_converged=False)
    finally:
        colgen.solve_lp,colgen.price_truck_dp=original_lp,original_price
    out["process_peak_rss_at_stop_bytes"]=peak_rss_bytes()
    out["lp_calls"]=calls;out["pricing_calls"]=price_calls;out["rmp_objective_trace"]=trace
    out["rmp_call_count"]=len(calls)
    out["pricing_callback_seconds"]=sum(x["seconds"] for x in price_calls)
    out["rmp_model_build_seconds"]=sum(x.get("model_build_seconds",0) for x in calls)
    out["rmp_solver_runtime_seconds"]=sum(x.get("solver_runtime_seconds",0) for x in calls)
    out["intermediate_replay_seconds"]=sum(x.get("validation_seconds",0) for x in calls)
    out["solver_peak_memory_gb"]=max((x.get("solver_peak_memory_gb",0) or 0 for x in calls),default=0)
    out["memory_scope"]="Maximum Gurobi per-RMP environment allocation, not sum or process RSS"
    if last and last["solution"].status=="optimal":
        sol=generated["lp"] if generated else last["solution"]
        # At max_iter the algorithm may append columns after the last LP;
        # its x vector still belongs to last["columns"], not the larger pool.
        cols=last["columns"]
        out["objective"]=float(sol.obj);out["last_rmp_finished_elapsed_seconds"]=last["elapsed_after_rmp"]
        out["stopping_master_validation"]=last["diagnostics"]["validation"]
        # Actual stopping pool is unchanged after its last LP: enrich=0.
        graph=build_extended_graph(inst);seeds,seed_proofs=_seeds_with_witnesses(inst)
        graph_rc=shortest_path_reduced_cost(inst,graph,sol.alpha,sol.mu,sol.nu)
        seed_rc=min((reduced_cost(s,sol,inst) for s in seeds),default=float("inf"))
        best=min(graph_rc,seed_rc)
        physical=validate_extended_selected_columns(inst,graph,cols,sol.x,tol=TOL)
        aggregate=out["stopping_master_validation"]
        original_feasible=bool(aggregate and aggregate["original_model_feasible"] and physical["passed"]
                               and aggregate["artificial_mass"]<=TOL)
        priced=bool(best>=-TOL)
        out["certified"]=bool(out["status"]=="candidate_stopping_lp" and original_feasible and priced)
        if out["certified"]:out["status"]="optimal_to_pricing_tolerance"
        elif out["status"]=="candidate_stopping_lp":out["status"]="uncertified_vendor_stop"
        out["certificate"]={"source":"actual_CG_stopping_duals_no_enrichment",
            "shared_master_dual_feasibility":"Relies on native optimal Gurobi RMP status at OptimalityTol=1e-8; its aggregate primal is independently replayed. Full graph/seed reduced costs are independently checked here.",
            "graph_min_reduced_cost":graph_rc,"seed_min_reduced_cost":seed_rc,"min_reduced_cost":best,
            "priced_out_independently":priced,"original_model_feasible":original_feasible,
            "pricing_tolerance_corrected_bound":sol.obj-inst.n_trips*TOL if out["certified"] else None,
            "stopping_duals":{"alpha":sol.alpha.tolist(),"mu":sol.mu.tolist(),"nu":sol.nu.tolist()},
            "selected_paths":physical,"seed_count":len(seeds),
            "off_grid_seed_count":sum(p["off_grid_profile"] for p in seed_proofs)}
        out["certificate"]["independent_certificate_elapsed_seconds"]=time.perf_counter()-started
        out.update(graph_nodes=graph.n_nodes,graph_arcs=graph.n_arcs,
                   graph_size_scope="Post-timing independent certification graph; CG itself does not materialize this graph")
        with gzip.open(output_dir/"cg_columns.json.gz","wt") as file:
            json.dump(safe([{"kind":c.kind,"a":c.a,"e":c.e,"fixed_cost":c.fixed_cost,"label":c.label} for c in cols]),file)
        np.savez_compressed(output_dir/"cg_primal.npz",x=sol.x,g=sol.g,charge=sol.charge,
                            discharge=sol.discharge,soc=sol.soc,nb=sol.nb)
    out["diagnostic_seconds"]=time.perf_counter()-stopped
    out["total_including_checks_seconds"]=time.perf_counter()-started
    return out
