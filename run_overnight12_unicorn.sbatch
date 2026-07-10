#!/bin/bash
#SBATCH --job-name=evsp_overnight12
#SBATCH --output=overnight12_%j.out
#SBATCH --error=overnight12_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue
# no --time: DIAG ~5-6 h per shard at 0/2,1/2; SPINE ~4-6 h per shard.

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT12_STUDIES="${OVERNIGHT12_STUDIES:-DIAG,SPINE}"
export OVERNIGHT12_SHARD="${OVERNIGHT12_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight12.py
