#!/bin/bash
# One input per array task: stage 1 (rebuild input with the cohort's generator), stage 2 (independent validation).
# Requeue-safe: outputs are written once at the end; a rerun overwrites only this task's own files.
set -euo pipefail
export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
ROOT=/home/nc437/opte-independent-validation-20261017; PY=/home/nc437/evsp_env/bin/python
JOBS=${JOBS:-$ROOT/jobs.json}
T=${SLURM_ARRAY_TASK_ID}
# NOHINTS=1: second pass over the CG arms only, every selected route found by search (saved witnesses ignored).
NOHINTS=${NOHINTS:-0}
eval "$($PY - "$JOBS" "$T" "$NOHINTS" <<'PYEOF'
import json, sys, shlex
j = json.load(open(sys.argv[1]))[int(sys.argv[2])]
arms = [a for a in j['arms'] if sys.argv[3] != '1' or ':cg:' in a]
print('COHORT=%s CASE=%s RUNTIME=%s' % (j['cohort'], j['case'], j['runtime']))
print('ARMS=(' + ' '.join('--arm ' + shlex.quote(a) for a in arms) + ')')
PYEOF
)"
OUTDIR=results; EXTRA=()
if [ "$NOHINTS" = "1" ]; then OUTDIR=results_nohints; EXTRA=(--no-hints); fi
mkdir -p $ROOT/records $ROOT/$OUTDIR
if [ ! -s "$ROOT/records/$CASE.json" ]; then
  $PY $ROOT/src/rebuild_input.py --runtime "$RUNTIME" --cohort "$COHORT" --case "$CASE" --out "$ROOT/records/$CASE.json"
fi
$PY $ROOT/src/validate_case.py --record "$ROOT/records/$CASE.json" --vendor "$RUNTIME/frozen/vendor" "${ARMS[@]}" "${EXTRA[@]}" --out "$ROOT/$OUTDIR/$COHORT/$CASE.json"
