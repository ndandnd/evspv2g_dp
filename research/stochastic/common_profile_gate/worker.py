#!/usr/bin/env python3
"""One immutable Slurm attempt: verify release, fit, validate, independently replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', type=int, required=True)
    ap.add_argument('--campaign', type=Path, required=True)
    ap.add_argument('--execution-commit', required=True)
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    manifest_path = here / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest['files'].items():
        if sha(here.parent / name) != expected:
            raise RuntimeError('Release hash mismatch: ' + name)
    case = manifest['cases'][args.case]
    output = args.campaign.resolve() / case['name']
    output.mkdir(parents=True, exist_ok=False)
    record = {'state': 'running', 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'execution_commit': args.execution_commit, 'manifest_sha256': sha(manifest_path),
              'case': case, 'hostname': platform.node(), 'python': sys.version,
              'scheduler': {k: os.environ.get(k) for k in ('SLURM_JOB_ID', 'SLURM_ARRAY_JOB_ID',
                            'SLURM_ARRAY_TASK_ID', 'SLURM_JOB_PARTITION', 'SLURM_CPUS_PER_TASK',
                            'SLURM_MEM_PER_NODE', 'SLURM_RESTART_COUNT')}, 'commands': []}
    save(output / 'execution.json', record)
    started = time.monotonic()
    inp = here / 'inputs' / (case['name'] + '.json')
    evaluation = here / 'inputs' / ('policy%d_nb20_fit2022.json' % case['policy'])
    reference = here.parent / 'evidence' / case['reference']
    def run(arguments):
        command = [sys.executable] + list(map(str, arguments))
        print(json.dumps({'command': command}), flush=True)
        record['commands'].append(command)
        save(output / 'execution.json', record)
        subprocess.run(command, check=True)
    try:
        run([here / 'solver.py', '--input', inp, '--output', output / 'fit',
             '--backend', 'gurobi', '--time-limit', '600', '--method', '2'])
        run([here / 'validate.py', '--input', inp, '--result', output / 'fit/result.json',
             '--source-root', here.parent / 'evidence', '--output', output / 'validation.json'])
        run([here / 'evaluate.py', '--input', evaluation, '--fit-input', inp,
             '--result', output / 'fit/result.json', '--output-dir', output / 'replay2022',
             '--source-root', here.parent / 'evidence', '--reference-case', reference])
        record['state'] = 'complete'
    except Exception as exc:
        record.update(state='failed', error=repr(exc))
        raise
    finally:
        record.update(elapsed_seconds=time.monotonic() - started,
                      finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        save(output / 'execution.json', record)


if __name__ == '__main__':
    main()
