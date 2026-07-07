#!/bin/bash
#SBATCH --job-name=evsp_overnight3
#SBATCH --output=overnight3_%j.out
#SBATCH --error=overnight3_%j.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT3_STUDIES="${OVERNIGHT3_STUDIES:-U1,U2,U3,U4,U5,U6}"
export OVERNIGHT3_SHARD="${OVERNIGHT3_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight3.py
