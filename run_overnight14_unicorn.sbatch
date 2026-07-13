#!/bin/bash
#SBATCH --job-name=evsp_overnight14
#SBATCH --output=overnight14_%j.out
#SBATCH --error=overnight14_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue
#SBATCH --open-mode=append
# Partition on the command line:
#   sbatch -p scaglione ...                              (no preemption, 4 h wall)
#   sbatch -p default_partition --time=24:00:00 ...      (preemptible; per-base
#     checkpoints + --requeue make preemption a pause, not a loss)

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT14_STUDIES="${OVERNIGHT14_STUDIES:-SMOKE}"
export OVERNIGHT14_SHARD="${OVERNIGHT14_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight14.py
