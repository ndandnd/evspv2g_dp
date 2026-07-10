#!/bin/bash
#SBATCH --job-name=evsp_overnight13
#SBATCH --output=overnight13_%j.out
#SBATCH --error=overnight13_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue
#SBATCH --open-mode=append
# Partition on the command line:
#   sbatch -p scaglione ...                              (no preemption, 4 h wall)
#   sbatch -p default_partition --time=24:00:00 ...      (preemptible; per-row
#     checkpoints + --requeue make preemption a pause, not a loss)

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT13_STUDIES="${OVERNIGHT13_STUDIES:-FOURARM}"
export OVERNIGHT13_SHARD="${OVERNIGHT13_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight13.py
