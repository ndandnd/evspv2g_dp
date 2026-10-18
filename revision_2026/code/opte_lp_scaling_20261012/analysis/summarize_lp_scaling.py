"""Audit and describe the prespecified LP scaling study without optimization.

Every planned outcome is retained, including missing workers and resource limits.
Ratios are direct elapsed / CG elapsed: greater than one favors CG. Exact ratios
require both certified arms and matching LP values. Genuine optimization-time
limits produce one-sided ratio bounds, never fabricated capped observations.
External watchdog expiry may occur in diagnostics and gives no LP-time bound.

Use --verify for independent compressed-primal/dual/path replay. Without it,
successful-pair statistics are explicitly provisional saved-certificate checks.
Derived outputs are written only below --output; experiment inputs are unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"vendor"))
from lp_scaling_instances import case_specs
from run_lp_scaling import experiment_plan
from run_pilot import safe,write_json

TOL=1e-6
METHODS=("dual","barrier","cg")


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def distribution(values):
    values=[float(v) for v in values if finite(v)]
    return {"count":len(values),"median":statistics.median(values) if values else None,
            "minimum":min(values) if values else None,"maximum":max(values) if values else None}


def count_values(rows,key):
    answer={}
    for row in rows:
        value=str(row.get(key));answer[value]=answer.get(value,0)+1
    return answer


def hash_record(raw):
    return hashlib.sha256(json.dumps({k:v for k,v in raw.items() if k!="sha256"},sort_keys=True).encode()).hexdigest()


def saved_certificate_check(method,result,n):
    errors=[]
    if not result.get("certified"):
        return False,["Run does not claim a certified solution"]
    if not finite(result.get("objective")):
        errors.append("Certified result has no finite objective")
    if method=="cg":
        cert=result.get("certificate") or {};master=result.get("stopping_master_validation") or {}
        paths=cert.get("selected_paths") or {}
        if result.get("status")!="optimal_to_pricing_tolerance":errors.append("Unexpected certified CG status")
        if result.get("enrichment_rounds")!=0 or result.get("final_mip") is not False:
            errors.append("CG included enrichment or a final MIP")
        if cert.get("source")!="actual_CG_stopping_duals_no_enrichment":errors.append("Wrong stopping dual source")
        if not cert.get("priced_out_independently") or not cert.get("original_model_feasible"):
            errors.append("CG missing full-family feasibility/pricing check")
        for key in ("min_reduced_cost","graph_min_reduced_cost","seed_min_reduced_cost"):
            if not finite(cert.get(key)) or cert[key]<-TOL:errors.append(f"Failed {key}")
        if not master.get("passed") or not master.get("original_model_feasible") or not paths.get("passed"):
            errors.append("CG missing passing aggregate/path replay")
        if abs(master.get("artificial_mass",math.inf))>TOL or abs(paths.get("artificial_mass",math.inf))>TOL:
            errors.append("Selected artificial mass")
        if finite(result.get("objective")) and (not finite(cert.get("pricing_tolerance_corrected_bound"))
                or abs(cert["pricing_tolerance_corrected_bound"]-(result["objective"]-n*TOL))>TOL):
            errors.append("Wrong pricing-tolerance bound correction")
    else:
        native=result.get("native_dual_certificate") or {};physical=result.get("validation") or {}
        if result.get("status")!="optimal" or result.get("native_status")!=2:errors.append("Direct LP not native optimal")
        if result.get("gurobi_method")!={"dual":1,"barrier":2}[method]:errors.append("Wrong explicit LP method")
        if not native.get("passed") or not physical.get("passed"):errors.append("Missing native dual or physical replay")
        if max(native.get("residuals",{"missing":math.inf}).values())>TOL:errors.append("Native LP certificate residual")
    return not errors,errors


def genuine_time_limit(method,result):
    """True only when evidence establishes no valid algorithm stop by its budget."""
    if result.get("certified") or result.get("status")=="external_timeout":return False
    elapsed=result.get("solve_end_to_end_seconds");budget=result.get("budget_seconds")
    if not finite(elapsed) or not finite(budget) or min(elapsed,budget)<=0 or elapsed<budget-0.01:return False
    if method!="cg":return (result.get("status")=="time_limit" and result.get("native_status")==9
                            or result.get("status")=="budget_exhausted_before_optimize")
    if result.get("status")!="budget_exhausted":return False
    error=result.get("error","")
    return ("Common LP budget exhausted" in error or "Nonoptimal RMP status: time_limit" in error
            or result.get("cg_claimed_converged") is True)


def audit_worker(folder,method,block,verify=False):
    row={"case":block["case_name"],"repeat":block["repeat"],"method":method,
         "method_position":block["methods"].index(method)+1,"status":"missing",
         "present":False,"saved_certificate_passed":False,"independent_replay":"not_requested",
         "accepted_certificate":False,"identity_passed":False,"genuine_optimization_time_limit":False}
    evidence={"folder":str(folder) if folder else None,"errors":[],"replay":None}
    if folder is None or not (folder/"result.json").is_file():return row,evidence,None
    row["present"]=True
    result=json.loads((folder/"result.json").read_text());row["status"]=result.get("status","missing_status")
    for key in ("objective","solve_end_to_end_seconds","budget_seconds","diagnostic_seconds",
                "solver_runtime_seconds","graph_seconds","model_build_seconds","rmp_model_build_seconds",
                "rmp_solver_runtime_seconds","pricing_callback_seconds","intermediate_replay_seconds",
                "graph_nodes","graph_arcs","variables","constraints","nonzeros","columns",
                "solver_peak_memory_gb","process_peak_rss_at_stop_bytes","barrier_iterations",
                "crossover_banner_to_solver_finish_seconds"):
        row[key]=result.get(key)
    row["genuine_optimization_time_limit"]=genuine_time_limit(method,result)
    errors=evidence["errors"]
    if not (folder/"manifest.json").is_file() or not (folder/"instance.json").is_file():
        errors.append("Missing worker manifest or instance; outcome retained but provenance incomplete")
        return row,evidence,None
    manifest=json.loads((folder/"manifest.json").read_text());raw=json.loads((folder/"instance.json").read_text())
    evidence["result_sha256"]=digest(folder/"result.json")
    evidence["manifest_sha256"]=digest(folder/"manifest.json")
    row.update(n_tasks=manifest["case"]["n_tasks"],task_locations=manifest["case"]["points"],
               draw_seed=manifest["case"]["draw_seed"],instance_sha256=raw.get("sha256"),
               host=manifest["environment"].get("host"),cpu_model=manifest["environment"].get("cpu_model"),
               gurobi=".".join(map(str,manifest["environment"].get("gurobi",[]))))
    if manifest["method"]!=method or manifest["case"]["case"]!=block["case_name"] or manifest["repeat"]!=block["repeat"]:
        errors.append("Worker identity differs from planned block")
    canonical=next(s for s in case_specs() if s["case"]==block["case_name"])
    if manifest["case"]!=canonical or raw.get("n_tasks")!=canonical["n_tasks"] or len(raw.get("dist",[]))!=canonical["points"]+1:
        errors.append("Instance/specification differs from prespecified task count/map")
    if raw.get("sha256")!=hash_record(raw):errors.append("Instance payload hash mismatch")
    if manifest.get("instance_sha256")!=raw.get("sha256") or result.get("instance_sha256")!=raw.get("sha256"):
        errors.append("Manifest/result instance mismatch")
    protocol=manifest.get("protocol",{})
    for key,value in (("threads",1),("seed",0),("enrichment",0),("final_mip",False),
                      ("pricing_tolerance",TOL),("feasibility_tolerance",1e-8),("optimality_tolerance",1e-8)):
        if protocol.get(key)!=value:errors.append(f"Protocol mismatch: {key}")
    if manifest.get("budget_seconds")!=1800:errors.append("Not the prespecified main-study 1800-second budget")
    for name,value in manifest["environment"].get("thread_environment",{}).items():
        if value!="1":errors.append(f"Worker math-thread environment is not one: {name}")
    hashes=result.get("evidence_sha256",result.get("partial_evidence_sha256",{}))
    for relative,expected in hashes.items():
        path=(folder/relative).resolve()
        if folder.resolve() not in path.parents or not path.is_file() or digest(path)!=expected:
            errors.append(f"Saved evidence hash mismatch: {relative}")
    for relative,expected in manifest.get("code_sha256",{}).items():
        path=ROOT/relative
        if not path.is_file() or digest(path)!=expected:errors.append(f"Current frozen dependency hash mismatch: {relative}")
    for relative,record in manifest["vendor_manifest"]["files"].items():
        if digest(ROOT/"vendor"/relative)!=record["sha256"]:errors.append(f"Vendor hash mismatch: {relative}")
    valid,certificate_errors=saved_certificate_check(method,result,row["n_tasks"])
    row["saved_certificate_passed"]=valid;evidence["saved_certificate_errors"]=certificate_errors
    if verify and result.get("certified"):
        from verify_lp_scaling import verify_worker
        try:
            replay=verify_worker(folder);evidence["replay"]=replay
            fully_verified=bool(replay.get("passed") and replay.get("independently_certified"))
            row["independent_replay"]="passed" if fully_verified else "failed"
            if not fully_verified:errors.append("Independent compressed-output replay/certificate failed")
        except Exception as exc:
            evidence["replay"]={"passed":False,"error":repr(exc)};row["independent_replay"]="failed"
            errors.append("Independent compressed-output replay raised an exception")
    row["identity_passed"]=not errors
    row["accepted_certificate"]=bool(valid and not errors and (not verify or row["independent_replay"]=="passed"))
    evidence["identity_passed"]=row["identity_passed"]
    return row,evidence,manifest


def pair_result(direct,cg):
    pair={k:direct.get(k) for k in ("case","repeat","n_tasks","task_locations","draw_seed")}
    pair.update(direct_method=direct["method"],direct_status=direct["status"],cg_status=cg["status"],
                ratio_direct_over_cg=None,ratio_lower_bound=None,ratio_upper_bound=None,
                objective_difference_cg_minus_direct=None,objective_match_verified=False,
                classification="unavailable_or_uncertified")
    if not direct["identity_passed"] or not cg["identity_passed"]:
        pair["classification"]="provenance_incomplete_or_failed";return pair
    ds=direct["accepted_certificate"];cs=cg["accepted_certificate"]
    td=direct.get("solve_end_to_end_seconds");tc=cg.get("solve_end_to_end_seconds")
    if ds and cs:
        difference=cg["objective"]-direct["objective"]
        pair["objective_difference_cg_minus_direct"]=difference
        if abs(difference)>TOL:
            pair["classification"]=("certificate_tolerance_compatible_but_not_equal_LP" if
                -TOL<=difference<=direct["n_tasks"]*TOL+TOL else "incompatible_LP_objectives")
            return pair
        if not finite(td) or not finite(tc) or min(td,tc)<=0:
            pair["classification"]="invalid_timing";return pair
        pair.update(classification="paired_certified_equal_LP",ratio_direct_over_cg=td/tc,
                    ratio_lower_bound=td/tc,ratio_upper_bound=td/tc,
                    direct_seconds=td,cg_seconds=tc,objective_match_verified=True)
    elif cs and direct["genuine_optimization_time_limit"]:
        budget=direct.get("budget_seconds")
        if not all(finite(v) and v>0 for v in (td,tc,budget)):
            pair["classification"]="invalid_timing";return pair
        cutoff=min(td,budget)
        pair.update(classification="direct_time_censored",ratio_lower_bound=cutoff/tc,
                    direct_seconds=None,cg_seconds=tc,bound_is_strict=False,censor_cutoff_seconds=cutoff)
    elif ds and cg["genuine_optimization_time_limit"]:
        budget=cg.get("budget_seconds")
        if not all(finite(v) and v>0 for v in (td,tc,budget)):
            pair["classification"]="invalid_timing";return pair
        cutoff=min(tc,budget)
        pair.update(classification="cg_time_censored",ratio_lower_bound=0.0,
                    ratio_upper_bound=td/cutoff,direct_seconds=td,cg_seconds=None,
                    bound_is_strict=False,censor_cutoff_seconds=cutoff)
    elif direct["genuine_optimization_time_limit"] and cg["genuine_optimization_time_limit"]:
        pair["classification"]="both_time_censored_ratio_unidentified"
    elif direct["status"]=="external_timeout" or cg["status"]=="external_timeout":
        pair["classification"]="external_watchdog_no_optimization_time_bound"
    return pair


def summaries(rows,pairs):
    method_groups=[];paired_groups=[];per_draw=[];association=[]
    for L in (4,15):
        for n in (100,400,1000):
            subset=[r for r in rows if r.get("n_tasks")==n and r.get("task_locations")==L]
            for method in METHODS:
                chosen=[r for r in subset if r["method"]==method]
                successes=[r for r in chosen if r["accepted_certificate"]]
                method_groups.append({"n_tasks":n,"task_locations":L,"method":method,"planned_runs":6,
                    "status_counts":count_values(chosen,"status"),"accepted_runs":len(successes),
                    "certified_seconds_completed_only":distribution([r.get("solve_end_to_end_seconds") for r in successes]),
                    "process_peak_rss_bytes_completed_only":distribution([r.get("process_peak_rss_at_stop_bytes") for r in successes]),
                    "graph_arcs":distribution([r.get("graph_arcs") for r in chosen]),
                    "genuine_time_limits":sum(r["genuine_optimization_time_limit"] for r in chosen)})
            for method in ("dual","barrier"):
                chosen=[p for p in pairs if p.get("n_tasks")==n and p.get("task_locations")==L and p["direct_method"]==method]
                exact=[p for p in chosen if p["classification"]=="paired_certified_equal_LP"]
                ratios=[p["ratio_direct_over_cg"] for p in exact]
                paired_groups.append({"n_tasks":n,"task_locations":L,"direct_method":method,
                    "planned_pairs":6,"outcome_counts":count_values(chosen,"classification"),
                    "paired_speedup_completed_only":distribution(ratios),
                    "CG_faster_count":sum(r>1 for r in ratios),"direct_faster_count":sum(r<1 for r in ratios),
                    "exact_tie_count":sum(r==1 for r in ratios),
                    "censored_bounds":[{k:p[k] for k in ("case","repeat","classification","ratio_lower_bound","ratio_upper_bound")}
                                       for p in chosen if "censored" in p["classification"]]})
                for sd in (0,1):
                    q=[p for p in exact if p["draw_seed"]==sd]
                    per_draw.append({"n_tasks":n,"task_locations":L,"draw_seed":sd,"direct_method":method,
                        "planned_repeats":3,"certified_paired_repeats":len(q),
                        "paired_repeat_ratio":distribution([p["ratio_direct_over_cg"] for p in q]),
                        "direct_repeat_seconds":distribution([p["direct_seconds"] for p in q]),
                        "cg_repeat_seconds":distribution([p["cg_seconds"] for p in q])})
        for method in ("dual","barrier"):
            groups=[g for g in paired_groups if g["task_locations"]==L and g["direct_method"]==method]
            complete=all(g["paired_speedup_completed_only"]["count"]==6 for g in groups)
            medians=[g["paired_speedup_completed_only"]["median"] for g in groups]
            trend="not_classified_with_missing_censored_or_rejected_pairs"
            if complete:
                trend=("descriptive_unchanged" if len(set(medians))==1 else
                       "descriptive_monotone_increase" if all(a<=b for a,b in zip(medians,medians[1:]))
                       else "descriptive_monotone_decrease" if all(a>=b for a,b in zip(medians,medians[1:]))
                       else "descriptive_nonmonotone")
            association.append({"task_locations":L,"direct_method":method,"n_values":[100,400,1000],
                "median_direct_over_CG_ratios":medians,"classification":trend,
                "interpretation":"Descriptive association for these fixed nonnested draws; three repeats are timing replicates, not new independent instances. No population significance or causal scaling conclusion is claimed."})
    return method_groups,paired_groups,per_draw,association


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--verify",action="store_true")
    args=parser.parse_args();started=time.perf_counter();base=args.input.resolve()
    specs={s["case"]:s for s in case_specs()};plan=experiment_plan();blocks={};duplicate_blocks=[]
    for path in base.rglob("manifest.json"):
        data=json.loads(path.read_text())
        if data.get("method")!="all" or data.get("case",{}).get("case") not in specs:continue
        key=(data["case"]["case"],data.get("repeat"))
        if key in blocks:duplicate_blocks.append({"key":key,"folders":[str(blocks[key]),str(path.parent)]})
        blocks[key]=path.parent
    rows=[];evidence=[];manifests={};block_checks=[]
    for block in plan:
        key=(block["case_name"],block["repeat"]);folder=blocks.get(key);current=[];current_manifests=[]
        for method in METHODS:
            row,proof,manifest=audit_worker(folder/method if folder else None,method,block,args.verify)
            spec=specs[block["case_name"]]
            row.update(n_tasks=spec["n_tasks"],task_locations=spec["points"],draw_seed=spec["draw_seed"])
            rows.append(row);current.append(row);evidence.append(proof)
            if manifest:manifests[(key,method)]=manifest;current_manifests.append(manifest)
        errors=[]
        if len(current_manifests)==3:
            for field in ("instance_sha256","code_sha256","budget_seconds","max_cg_iterations","crossover_parameter"):
                if any(m[field]!=current_manifests[0][field] for m in current_manifests[1:]):errors.append(f"Block mismatch: {field}")
            for field in ("host","cpu_model","cpu_affinity","gurobi","numpy","scipy","python"):
                if any(m["environment"].get(field)!=current_manifests[0]["environment"].get(field) for m in current_manifests[1:]):
                    errors.append(f"Block environment mismatch: {field}")
        if folder and (folder/"block_summary.json").exists():
            saved=json.loads((folder/"block_summary.json").read_text())
            if saved.get("method_order")!=block["methods"]:errors.append("Saved method order differs from prespecified rotation")
        elif folder:errors.append("Block not yet marked completed")
        if errors:
            for row in current:row["identity_passed"]=False;row["accepted_certificate"]=False
        block_checks.append({"case":key[0],"repeat":key[1],"present":folder is not None,
                             "workers_with_manifests":len(current_manifests),"errors":errors})
    global_errors=[]
    if duplicate_blocks:global_errors.append("Duplicate case/repeat blocks; cannot silently select a rerun")
    for case in specs:
        hashes={r.get("instance_sha256") for r in rows if r["case"]==case and r.get("instance_sha256")}
        if len(hashes)>1:global_errors.append(f"Input drift across methods/repeats: {case}")
    if manifests:
        first=next(iter(manifests.values()))
        for field in ("code_sha256","budget_seconds","max_cg_iterations","crossover_parameter"):
            if any(m[field]!=first[field] for m in manifests.values()):global_errors.append(f"Across-study protocol drift: {field}")
        for field in ("cpu_model","gurobi","numpy","scipy"):
            values={json.dumps(m["environment"].get(field),sort_keys=True) for m in manifests.values()}
            if len(values)>1:global_errors.append(f"Heterogeneous study {field}; report separate strata instead of pooled times")
    if global_errors:
        for row in rows:row["identity_passed"]=False;row["accepted_certificate"]=False
    bykey={(r["case"],r["repeat"],r["method"]):r for r in rows}
    pairs=[pair_result(bykey[(b["case_name"],b["repeat"],method)],bykey[(b["case_name"],b["repeat"],"cg")])
           for b in plan for method in ("dual","barrier")]
    method_groups,paired_groups,per_draw,association=summaries(rows,pairs)
    report={"study":"prespecified DIAG2 LP-only scaling","planned_blocks":36,"planned_runs":108,
        "observed_runs":sum(r["present"] for r in rows),"all_outcomes_present":all(r["present"] for r in rows),
        "independent_replay_requested":args.verify,"statistics_provisional_without_replay":not args.verify,
        "global_errors":global_errors,"duplicate_blocks":duplicate_blocks,"block_checks":block_checks,
        "all_present_provenance_passed":all(r["identity_passed"] for r in rows if r["present"]),
        "status_counts":count_values(rows,"status"),"pair_classifications":count_values(pairs,"classification"),
        "lp_absolute_match_tolerance":TOL,"raw_worker_rows":rows,"paired_rows":pairs,
        "method_summaries":method_groups,"paired_summaries":paired_groups,"per_draw_repeat_summaries":per_draw,
        "scaling_associations":association,"worker_evidence":evidence,
        "analysis_seconds":time.perf_counter()-started,"analyzer_sha256":digest(__file__),
        "interpretation_rules":[
            "All 108 planned outcomes remain visible; missing/error/limit runs are never silently dropped.",
            "CG ratios compare with both predeclared direct methods. No hindsight selection of the faster direct solver.",
            "Exact paired ratios require both certified results and objective agreement within 1e-6. Compatible but looser pricing-tolerance results are flagged separately.",
            "Time-limit comparisons use one-sided bounds. A censored run is never replaced by its budget in a median speedup.",
            "Censored ratio bounds concern time to the prespecified method certificates; paired objective equality cannot be checked for a censored arm and is labeled unverified.",
            "External watchdog expiry includes diagnostics; it establishes no optimization-time lower bound.",
            "Completed-only medians/ranges are descriptive and must be read alongside counts and censored outcomes.",
            "Two task draws per (n,L) are independent inputs; three repeats only measure timing variation. Draws at different n are not nested.",
            "Fresh child processes and matched block allocation are checked; local calibration and historical timings must be kept outside this input directory.",
            "CG is the fixed cold-RMP implementation with no basis reuse; results do not characterize every possible CG implementation.",
            "Final independent diagnostics are excluded from time-to-stop and reported separately for every method." ]}
    args.output.mkdir(parents=True,exist_ok=True)
    write_csv(args.output/"lp_scaling_workers.csv",rows);write_csv(args.output/"lp_scaling_pairs.csv",pairs)
    write_json(args.output/"lp_scaling_analysis.json",report)
    print(json.dumps({k:report[k] for k in ("observed_runs","all_outcomes_present","global_errors","status_counts","pair_classifications")},indent=2))
    return int(bool(global_errors) or any(r["present"] and not r["identity_passed"] for r in rows))


if __name__=="__main__":raise SystemExit(main())
