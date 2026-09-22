#!/bin/bash
#SBATCH --job-name=v2g17_common
#SBATCH --account=scaglione
#SBATCH --partition=scaglione
#SBATCH --no-requeue
#SBATCH --exclude=scaglione-compute-01
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=01:00:00
#SBATCH --array=0-3%2
#SBATCH --nice=1000

set -eo pipefail
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
RELEASE_ROOT=$1
CAMPAIGN_ROOT=$2
EXECUTION_COMMIT=$3
PYTHON_BIN=${PYTHON_BIN:?Set PYTHON_BIN to the cluster's scientific environment}
"$PYTHON_BIN" -u "$RELEASE_ROOT/research/stochastic/common_profile_gate/worker.py" \
    --case "$SLURM_ARRAY_TASK_ID" --campaign "$CAMPAIGN_ROOT" \
    --execution-commit "$EXECUTION_COMMIT"
