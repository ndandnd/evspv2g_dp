#!/bin/bash
# Pull the per-input reports (small JSON) and Slurm records from the cluster, split per arm, aggregate.
set -euo pipefail
H=/Users/nadan/Documents/projects/v2g/output/opte-independent-validation-20261017
cd "$H"
rsync -a unicorn:opte-independent-validation-20261017/results/ results/
rsync -a unicorn:opte-independent-validation-20261017/jobs.json unicorn:opte-independent-validation-20261017/submit_receipt.json unicorn:opte-independent-validation-20261017/worker.sh slurm/
ssh unicorn 'bash -lc "sacct -u nc437 -S 2026-10-17T18:00 -n -P -X -o JobID,JobName,State,Elapsed,MaxRSS,NodeList,ExitCode | grep ivalid"' > slurm/sacct.txt || true
python3 - <<'PY'
import json, glob, os
for p in sorted(glob.glob('results/*/*.json')):
    d = json.load(open(p)); coh = p.split('/')[1]
    os.makedirs(f'results_by_arm/{coh}', exist_ok=True)
    for label, arm in d['arms'].items():
        rec = {k: v for k, v in d.items() if k != 'arms'}; rec['arm_label'] = label; rec['arm'] = arm
        json.dump(rec, open(f"results_by_arm/{coh}/{d['case']}__{label}.json", 'w'), indent=1)
PY
python3 src/aggregate.py > aggregate_stdout.txt
