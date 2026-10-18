"""Submit only the authorized fixed270-base planning array, with immutable receipt."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

SLURM='/usr/local/slurm/current/bin/'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);a=parser.parse_args()
    root=a.root.resolve();receipt=root/'submission.json'
    if receipt.exists():raise ValueError('Submission receipt already exists; duplicate launch refused')
    snapshot=json.loads((root/'snapshot_manifest.json').read_text())
    for name,want in snapshot['files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=want:raise ValueError('Snapshot mismatch: '+name)
    cases=json.loads((root/'code/planning_population_inputs.json').read_text())['cases']
    if len(cases)!=270:raise ValueError('Expected270 fixed bases')
    states=[]
    for cmd in ([SLURM+'squeue','-u','nc437','-h','-o','%i|%j|%T|%N|%R'],
                [SLURM+'sinfo','-N','-n','lisbeth','-o','%N|%t|%c|%m|%C']):
        observed=subprocess.run(cmd,capture_output=True,text=True,check=True)
        states.append({'command':cmd,'stdout':observed.stdout,'stderr':observed.stderr})
    (root/'pre_submission_queue.json').write_text(json.dumps({'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'reads':states},indent=2)+'\n')
    (root/'logs').mkdir(exist_ok=True);(root/'results').mkdir(exist_ok=True)
    worker=root/'array_worker.sh'
    prefix=[SLURM+'srun','--cpu-bind=threads','--hint=nomultithread','/home/nc437/evsp_env/bin/python',str(root/'code/planning_population.py')]
    body=['#!/bin/bash','set -euo pipefail','export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic',
      'export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1',
      'exec '+shlex.join(prefix)+' --index "${SLURM_ARRAY_TASK_ID}" --launch-base --output '+shlex.quote(str(root/'results'))+'/base_"${SLURM_ARRAY_TASK_ID}"']
    worker.write_text('\n'.join(body)+'\n')
    command=[SLURM+'sbatch','--parsable','--job-name=opte_plan60','--partition=default_partition',
      '--nodelist=lisbeth','--nodes=1','--ntasks=1','--cpus-per-task=1','--hint=nomultithread',
      '--mem=4G','--time=00:12:00','--array=0-269%28','--output='+str(root/'logs/planning-%A_%a.out'),str(worker)]
    report={'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'command':command,'status':'attempting_submission',
      'snapshot_manifest_sha256':hashlib.sha256((root/'snapshot_manifest.json').read_bytes()).hexdigest(),
      'worker_script_sha256':hashlib.sha256(worker.read_bytes()).hexdigest(),'mutates_existing_jobs':False}
    receipt.write_text(json.dumps(report,indent=2)+'\n')
    done=subprocess.run(command,capture_output=True,text=True)
    report.update(returncode=done.returncode,stdout=done.stdout.strip(),stderr=done.stderr.strip(),
      status='submitted' if done.returncode==0 else 'submission_failed')
    receipt.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return done.returncode


if __name__=='__main__':raise SystemExit(main())
