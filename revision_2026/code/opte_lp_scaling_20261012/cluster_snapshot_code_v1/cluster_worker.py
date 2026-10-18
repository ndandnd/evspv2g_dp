"""Execute a frozen OPTE study block inside a Slurm one-CPU allocation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--study', choices=['lp', 'calibration', 'planning'], required=True)
    p.add_argument('--output-root', type=Path, required=True)
    p.add_argument('--index', type=int)
    a = p.parse_args()
    if int(os.environ.get('SLURM_CPUS_PER_TASK', '0')) != 1:
        raise RuntimeError('A one-CPU allocation is required')
    affinity = sorted(os.sched_getaffinity(0))
    if len(affinity) != 1:
        raise RuntimeError(f'One bound CPU required; observed affinity {affinity}')
    index = a.index if a.index is not None else int(os.environ['SLURM_ARRAY_TASK_ID'])
    if a.study in ('lp', 'calibration'):
        from run_lp_scaling import experiment_plan
        block = (dict(case_name='diag2_L15_n100_s0', repeat=0) if a.study == 'calibration'
                 else experiment_plan()[index])
        command = [sys.executable, str(ROOT / 'run_lp_scaling.py'),
                   '--case-name', block['case_name'], '--repeat', str(block['repeat']),
                   '--output', str(a.output_root / f"{block['case_name']}_r{block['repeat']}"),
                   '--budget', '1800']
    else:
        from planning_direct import planning_specs, SCENARIO_ORDER
        cases = [(s['case'], c) for s in planning_specs() for c in SCENARIO_ORDER]
        case, config = cases[index]
        command = [sys.executable, str(ROOT / 'planning_direct.py'), '--input', case,
                   '--config', config, '--output', str(a.output_root / f'{case}_{config}'),
                   '--budget', '1800']
    print(json.dumps({'study': a.study, 'index': index, 'job': os.environ.get('SLURM_JOB_ID'),
                      'array_job': os.environ.get('SLURM_ARRAY_JOB_ID'),
                      'affinity': affinity, 'command': command}), flush=True)
    return subprocess.run(command, check=False).returncode

if __name__ == '__main__': raise SystemExit(main())
