"""Read-only timing/model/memory diagnostics from saved LP workers.

This is a mechanism audit, not certified performance inference. Every saved
outcome is counted, strict flags are preserved, and missing runs stay explicit.
No optimizer is imported or called. Run against the final study again with a
new output directory to reproduce the same diagnostics after completion.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics

METHODS=("cg","dual","barrier")


def numeric(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
def sha(data):return hashlib.sha256(data).hexdigest()
def summary(values):
    values=[value for value in values if numeric(value)]
    return {"count":len(values),"median":statistics.median(values) if values else None,
            "minimum":min(values) if values else None,"maximum":max(values) if values else None}


def read_worker(path):
    rb=path.read_bytes();mb=(path.parent/"manifest.json").read_bytes()
    result=json.loads(rb);manifest=json.loads(mb);method=manifest["method"]
    if method not in METHODS:raise ValueError(f"Unexpected worker method: {method}")
    row={"case":manifest["case"]["case"],"repeat":manifest["repeat"],"method":method,
         "n_tasks":manifest["case"]["n_tasks"],"task_locations":manifest["case"]["points"],"draw_seed":manifest["case"]["draw_seed"],
         "result_path":str(path.resolve()),"result_sha256":sha(rb),"manifest_sha256":sha(mb),
         "status":result.get("status"),"original_certified_flag":result.get("certified"),
         "instance_sha256":result.get("instance_sha256"),"host":manifest["environment"].get("host"),
         "process_rss_mib":result["process_peak_rss_at_stop_bytes"]/2**20 if numeric(result.get("process_peak_rss_at_stop_bytes")) else None,
         "solver_peak_memory_gb":result.get("solver_peak_memory_gb"),
         "stop_seconds":result.get("solve_end_to_end_seconds"),"post_stop_diagnostic_seconds":result.get("diagnostic_seconds")}
    if method=="cg":
        calls=result.get("lp_calls",[]);last=calls[-1] if calls else {}
        for field in ("variables","constraints","nonzeros"):
            row[f"final_model_{field}"]=last.get(field)
            row[f"max_model_{field}"]=max((c[field] for c in calls if numeric(c.get(field))),default=None)
        row.update(iterations=result.get("cg_iterations"),rmp_calls=result.get("rmp_call_count"),
                   pricing_calls=len(result.get("pricing_calls",[])),route_columns=result.get("columns"),
                   build_seconds=result.get("rmp_model_build_seconds"),solver_seconds=result.get("rmp_solver_runtime_seconds"),
                   pricing_seconds=result.get("pricing_callback_seconds"),intermediate_replay_seconds=result.get("intermediate_replay_seconds"),
                   graph_seconds=0.,graph_memory_scope="No materialized graph before stop; reported graph size belongs to post-stop diagnostics")
        component_names=("build_seconds","solver_seconds","pricing_seconds","intermediate_replay_seconds")
        if calls:
            for stored,field in (("build_seconds","model_build_seconds"),("solver_seconds","solver_runtime_seconds"),("intermediate_replay_seconds","validation_seconds")):
                if abs(sum(c.get(field,0) for c in calls)-row[stored])>1e-8:raise ValueError(f"Inconsistent CG component: {stored}")
    else:
        for field in ("variables","constraints","nonzeros"):row[f"final_model_{field}"]=result.get(field)
        row.update(graph_nodes=result.get("graph_nodes"),graph_arcs=result.get("graph_arcs"),
                   build_seconds=result.get("model_build_seconds"),graph_seconds=result.get("graph_seconds"),
                   solver_seconds=result.get("solver_runtime_seconds"),matrix_build_seconds=result.get("matrix_build_seconds"),
                   gurobi_build_seconds=result.get("gurobi_build_seconds"),iterations=result.get("iterations"),
                   barrier_iterations=result.get("barrier_iterations"),crossover_to_finish_seconds=result.get("crossover_banner_to_solver_finish_seconds"),
                   graph_memory_scope="Materialized graph and direct model included before stop")
        component_names=("graph_seconds","build_seconds","solver_seconds")
    if numeric(row["stop_seconds"]) and row["stop_seconds"]>0 and all(numeric(row.get(name)) for name in component_names):
        row["other_seconds"]=row["stop_seconds"]-sum(row[name] for name in component_names)
        if row["other_seconds"] < -1e-5:raise ValueError("Timing components overlap or exceed their recorded end-to-end total")
        for name in component_names+("other_seconds",):row[name+"_percent"]=100*row[name]/row["stop_seconds"]
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True,type=Path);parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args();paths=sorted(p for p in args.input.glob("*/*/result.json") if p.parent.name in METHODS)
    rows=[read_worker(path) for path in paths]
    keys=[(row["case"],row["repeat"],row["method"]) for row in rows]
    if len(set(keys))!=len(keys):raise ValueError("Duplicate saved outcomes")
    expected={(f"diag2_L{L:02d}_n{n}_s{draw}",repeat,method) for L in (4,15) for n in (100,400,1000)
              for draw in (0,1) for repeat in range(3) for method in METHODS}
    if not set(keys)<=expected:raise ValueError("Saved outcomes are outside the fixed study plan")
    metrics=("stop_seconds","build_seconds","solver_seconds","pricing_seconds","intermediate_replay_seconds","other_seconds",
             "build_seconds_percent","solver_seconds_percent","pricing_seconds_percent","intermediate_replay_seconds_percent","other_seconds_percent",
             "post_stop_diagnostic_seconds","rmp_calls","pricing_calls","iterations","route_columns","final_model_variables","final_model_constraints",
             "final_model_nonzeros","max_model_variables","max_model_nonzeros","graph_nodes","graph_arcs","graph_seconds","matrix_build_seconds",
             "gurobi_build_seconds","barrier_iterations","crossover_to_finish_seconds","process_rss_mib","solver_peak_memory_gb")
    groups=[]
    for L in (4,15):
        for n in (100,400,1000):
            group={"task_locations":L,"n_tasks":n,"methods":{}}
            for method in METHODS:
                chosen=[row for row in rows if (row["task_locations"],row["n_tasks"],row["method"])==(L,n,method)]
                group["methods"][method]={"planned":6,"saved":len(chosen),"missing":6-len(chosen),
                    "original_certified_flags_true":sum(row["original_certified_flag"] is True for row in chosen),
                    "status_counts":dict(collections.Counter(row["status"] for row in chosen)),
                    "metrics":{field:summary([row.get(field) for row in chosen]) for field in metrics}}
            groups.append(group)
    report={"scope":"Descriptive implementation diagnostics; not final certified performance comparisons",
        "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"source":str(args.input.resolve()),
        "snapshot_saved_workers":len(rows),"snapshot_missing_workers":108-len(rows),
        "completed_cg_workers":sum(row["method"]=="cg" for row in rows),
        "helper_sha256":sha(Path(__file__).read_bytes()),"groups":groups,"workers":rows,
        "interpretation":[
            "All saved outcomes are included in diagnostic summaries irrespective of strict certificate flag; flags and missing counts are shown. Use the separate primary analysis for certified timing claims.",
            "CG build time sums dense master assembly, sparse conversion, fresh Gurobi environment/model creation and setup per RMP; it is not solver optimization time.",
            "CG solver time sums native Runtime over every cold RMP solve. No basis or persistent model is reused in this frozen implementation.",
            "Pricing callback time includes every DP invocation before stopping. Intermediate replay is the aggregate feasibility replay after every RMP; both remain inside the recorded end-to-end budget.",
            "Other time is the remainder after disjoint measured components; it includes initialization, column handling, callback/log bookkeeping and residual overhead. It is not an estimated extra solver phase.",
            "Medians of components or percentages need not sum exactly to the median total or 100 percent because each statistic is taken across runs separately.",
            "Final independent diagnostics are after the recorded stop and reported separately. CG graph size refers to its post-stop diagnostic graph; the CG optimization itself does not materialize that graph.",
            "Process peak RSS is the fresh-worker high-water mark by algorithm stop, including imports and instance setup, but excluding later diagnostics. Solver peak memory is the native decimal-GB allocation, not RSS; CG reports its maximum single RMP environment, not the sum across iterations.",
            "Smaller RMPs can reduce memory without reducing total time when hundreds of cold LP solves, model rebuilds and pricing calls accumulate.",
            "Persistent models, basis reuse, alternative pricing strategies or batching may reduce particular costs, but their benefit and induced dual/iteration behavior have not been measured. No guaranteed speedup is inferred.",
            "Do not extrapolate to missing 1000-task CG runs or conflate timing repeats with independent task draws."]}
    if args.output.exists() and any(args.output.iterdir()):raise FileExistsError("Use a fresh output directory")
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"lp_timing_diagnostics.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with (args.output/"lp_timing_diagnostics.csv").open("w",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    def show(value):return "--" if value is None else f"{value:.3g}"
    lines=["AUTHOR DIAGNOSTICS — SAVED OUTCOME CHECKPOINT, NOT FINAL PERFORMANCE INFERENCE",report["created_utc"],
           f"Saved outcomes: {len(rows)}/108; CG outcomes: {report['completed_cg_workers']}/36. All strict flags are preserved.","",
           "CG time breakdown: each entry is median seconds (median fraction of recorded stop time). Numerical summaries use all saved runs; missing is explicit.",
           "L  n     saved  total     build          solver         pricing        replay         other"]
    for group in groups:
        cg=group["methods"]["cg"];m=cg["metrics"]
        pieces=[f"{show(m[key]['median'])} ({show(m[key+'_percent']['median'])}%)" for key in ("build_seconds","solver_seconds","pricing_seconds","intermediate_replay_seconds","other_seconds")]
        lines.append(f"{group['task_locations']:<2} {group['n_tasks']:<5} {cg['saved']}/6    {show(m['stop_seconds']['median']):<8} "+" | ".join(pieces))
    lines.extend(["","Model size / process peak RSS: median [minimum, maximum], saved count shown. CG model is its final RMP; direct is the entire graph-plus-seed LP."])
    for group in groups:
        lines.append(f"L={group['task_locations']}, n={group['n_tasks']}")
        for method in METHODS:
            data=group["methods"][method];m=data["metrics"]
            def cell(field):
                v=m[field];return f"{show(v['median'])} [{show(v['minimum'])}, {show(v['maximum'])}]"
            lines.append(f"  {method}: {data['saved']}/6 saved; {data['original_certified_flags_true']} strict true; variables {cell('final_model_variables')}; constraints {cell('final_model_constraints')}; nonzeros {cell('final_model_nonzeros')}; RSS MiB {cell('process_rss_mib')}; solver GB {cell('solver_peak_memory_gb')}")
    lines.extend(["","Interpretation and recommended author framing:"]+["- "+line for line in report["interpretation"]])
    (args.output/"author_timing_diagnostics.txt").write_text("\n".join(lines)+"\n")
    print(json.dumps({key:report[key] for key in ("snapshot_saved_workers","snapshot_missing_workers","completed_cg_workers")},indent=2))


if __name__=="__main__":main()
