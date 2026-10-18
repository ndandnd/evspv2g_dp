"""Run one prespecified case/repeat block in fresh, sequential method processes.

Example calibration (excluded from main statistics by its separate directory):
python run_lp_scaling.py --case-name diag2_L15_n100_s0 --repeat 0 \
  --output results/lp_calibration_20261012/L15_r0 --budget 1800

--plan prints all 36 blocks without running anything. Root orchestrates any
cluster submission. This script never submits jobs or changes prior evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"vendor"))
import numpy as np
import scipy
from lp_scaling_instances import case_specs,build_case,instance_record,source_manifest
from lp_scaling_models import solve_direct_lp,solve_cg_lp,peak_rss_bytes
from run_pilot import safe,write_json,verify_vendor

METHODS=("dual","barrier","cg")
DEPENDENCIES=("run_lp_scaling.py","lp_scaling_instances.py","lp_scaling_models.py",
              "extension_instances.py","extension_models.py","arc_flow.py","column_witness.py",
              "rmp_solver.py","run_pilot.py")


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_child_bounded(command,env,wall_limit):
    """POSIX worker watchdog; kill/reap the process group on external expiry."""
    began=time.perf_counter()
    process=subprocess.Popen(command,env=env,start_new_session=True)
    try:
        returncode=process.wait(timeout=wall_limit)
        return {"returncode":returncode,"external_timeout":False,
                "external_wall_seconds":time.perf_counter()-began}
    except subprocess.TimeoutExpired:
        # A process group includes any solver descendants as well as the worker.
        # The grace already allows final diagnostics; do not let a stuck process
        # keep the allocation alive or prevent the next balanced-order arm.
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()
        return {"returncode":process.returncode,"external_timeout":True,
                "external_wall_seconds":time.perf_counter()-began,
                "watchdog_limit_seconds":wall_limit,"process_group_killed":True}


def method_order(case_index,repeat):
    offset=(case_index+repeat)%3
    return list(METHODS[offset:]+METHODS[:offset])


def experiment_plan():
    return [{"block_index":3*i+r,"case_name":s["case"],"repeat":r,
             "methods":method_order(i,r)} for i,s in enumerate(case_specs()) for r in range(3)]


def environment_record():
    import gurobipy as gp
    cpu=platform.processor()
    if Path("/proc/cpuinfo").is_file():
        cpu=next((line.split(":",1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                  if line.startswith("model name")),cpu)
    elif sys.platform=="darwin":
        try:cpu=subprocess.check_output(["sysctl","-n","machdep.cpu.brand_string"],text=True).strip()
        except (OSError,subprocess.CalledProcessError):pass
    return {"host":platform.node(),"cpu_model":cpu,"platform":platform.platform(),
            "machine":platform.machine(),"python":sys.version,"executable":sys.executable,
            "numpy":np.__version__,"scipy":scipy.__version__,"gurobi":list(gp.gurobi.version()),
            "pid":os.getpid(),"allocated_cpus":os.environ.get("SLURM_CPUS_PER_TASK"),
            "cpu_affinity":sorted(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else None,
            "thread_environment":{k:os.environ.get(k) for k in
                ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS",
                 "VECLIB_MAXIMUM_THREADS")}}


def manifest(spec,args,raw):
    return {"started_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"case":spec,"repeat":args.repeat,
            "method":args.method,"budget_seconds":args.budget,"crossover_parameter":args.crossover,
            "max_cg_iterations":args.max_cg_iterations,"instance_sha256":raw["sha256"],
            "worker_watchdog_grace_seconds":args.watchdog_grace,
            "environment":environment_record(),"vendor_manifest":verify_vendor(),
            "source_manifest":source_manifest(),"code_sha256":{p:sha(ROOT/p) for p in DEPENDENCIES},
            "protocol":{"threads":1,"seed":0,"feasibility_tolerance":1e-8,
                "optimality_tolerance":1e-8,"barrier_convergence_tolerance":1e-8,"pricing_tolerance":1e-6,
                "enrichment":0,"final_mip":False,"CG_RMP_basis_reuse":False,
                "timing_scope":"Instance generation/imports/initial serialization excluded; graph or seed construction, model construction, optimization and intermediate CG replay included. Final independent replay/certification and result serialization excluded and reported separately.",
                "memory_scope":"Fresh process high-water RSS at algorithm stop, before final diagnostics; Gurobi allocation also recorded",
                "same_cpu_within_block":True,"repeat_method_order":"Latin rotation across all three positions",
                "worker_watchdog":"Parent kills complete worker process group after arm budget plus diagnostic grace. External timeout is not an optimization-time lower bound because the worker may have finished optimizing and be in diagnostics.",
                "cross_study_timing":"Do not pool local calibration or earlier Gurobi12.0.1 timings with cluster12.0.3 timings"}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case-name");p.add_argument("--repeat",type=int,choices=range(3),default=0)
    p.add_argument("--output",type=Path);p.add_argument("--budget",type=float,default=1800)
    p.add_argument("--method",choices=("all",)+METHODS,default="all")
    p.add_argument("--crossover",type=int,default=-1,choices=(-1,0,1,2,3,4))
    p.add_argument("--max-cg-iterations",type=int,default=20000)
    p.add_argument("--watchdog-grace",type=float,default=600)
    p.add_argument("--expected-instance-sha256");p.add_argument("--plan",action="store_true")
    a=p.parse_args()
    if a.plan:print(json.dumps(experiment_plan(),indent=2));return 0
    if not a.case_name or a.output is None:p.error("--case-name and --output are required")
    if not np.isfinite(a.budget) or a.budget<=0 or not np.isfinite(a.watchdog_grace) or a.watchdog_grace<0:
        p.error("Positive finite budget and nonnegative finite watchdog grace required")
    specs=case_specs();spec=next((s for s in specs if s["case"]==a.case_name),None)
    if spec is None:p.error("Unknown prespecified case")
    if a.output.exists():raise ValueError("Fresh output directory required; existing evidence is immutable")
    inst=build_case(spec);raw=instance_record(inst)
    if a.expected_instance_sha256 and raw["sha256"]!=a.expected_instance_sha256:
        raise ValueError("Worker instance differs from block input")
    a.output.mkdir(parents=True)
    write_json(a.output/"instance.json",raw);write_json(a.output/"manifest.json",manifest(spec,a,raw))
    if a.method=="all":
        order=method_order(specs.index(spec),a.repeat);results=[]
        env=os.environ.copy()
        for name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS"):
            env[name]="1"
        for method in order:
            command=[sys.executable,str(Path(__file__).resolve()),"--case-name",a.case_name,"--repeat",str(a.repeat),
                     "--output",str(a.output/method),"--budget",str(a.budget),"--method",method,
                     "--crossover",str(a.crossover),"--max-cg-iterations",str(a.max_cg_iterations),
                     "--watchdog-grace",str(a.watchdog_grace),
                     "--expected-instance-sha256",raw["sha256"]]
            write_json(a.output/"progress.json",{"method_order":order,"active_method":method,"completed":results})
            print(f"START {a.case_name} repeat={a.repeat} method={method}",flush=True)
            execution=run_child_bounded(command,env,a.budget+a.watchdog_grace)
            result_path=a.output/method/"result.json"
            if execution["external_timeout"]:
                if not (a.output/method).exists():(a.output/method).mkdir(parents=True)
                partial={str(f.relative_to(a.output/method)):sha(f) for f in (a.output/method).rglob("*")
                         if f.is_file() and not f.name.endswith(".tmp") and f.name!="result.json"}
                write_json(result_path,{"status":"external_timeout","certified":False,"objective":None,
                    "solve_end_to_end_seconds":None,"method":method,"instance_sha256":raw["sha256"],
                    "external_watchdog":execution,"budget_seconds":a.budget,
                    "algorithm_time_censor_bound_valid":False,
                    "reason":"Worker exceeded optimization budget plus diagnostic grace; whole process group killed. Optimization completion is unknown, so this is not an LP-time lower bound.",
                    "partial_evidence_sha256":partial})
            child=json.loads(result_path.read_text()) if result_path.exists() else {}
            results.append({"method":method,"returncode":execution["returncode"],"status":child.get("status"),
                            "external_execution":execution,
                            "certified":child.get("certified",False),"objective":child.get("objective"),
                            "seconds":child.get("solve_end_to_end_seconds")})
            if (a.output/method/"manifest.json").exists():
                child_manifest=json.loads((a.output/method/"manifest.json").read_text())
                if child_manifest["environment"]["host"]!=platform.node():raise ValueError("Cross-host block")
        write_json(a.output/"block_summary.json",{"method_order":order,"results":results,
                   "instance_sha256":raw["sha256"],"completed":True})
        return int(any(r["returncode"]!=0 for r in results))
    try:
        result=(solve_cg_lp(inst,a.budget,a.output,max_iter=a.max_cg_iterations) if a.method=="cg"
                else solve_direct_lp(inst,a.method,a.budget,a.output/"logs"/"direct.log",
                                     crossover=a.crossover,evidence_dir=a.output))
        exit_code=0
    except Exception as exc:
        result={"status":"error","certified":False,"error":repr(exc),"traceback":traceback.format_exc()};exit_code=1
    result["process_peak_rss_after_diagnostics_bytes"]=peak_rss_bytes()
    result["instance_sha256"]=raw["sha256"]
    result["evidence_sha256"]={str(f.relative_to(a.output)):sha(f) for f in a.output.rglob("*")
                                if f.is_file() and f.name!="progress.json"}
    write_json(a.output/"result.json",result)
    print(json.dumps({"case":a.case_name,"repeat":a.repeat,"method":a.method,
                      **{k:result.get(k) for k in ("status","certified","objective","solve_end_to_end_seconds")}}),flush=True)
    return exit_code


if __name__=="__main__":raise SystemExit(main())
