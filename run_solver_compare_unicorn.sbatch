#!/bin/bash
#SBATCH --job-name=evsp_solver_compare
#SBATCH --output=solver_compare_%j.out
#SBATCH --error=solver_compare_%j.err
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export EVSP_LADDER="${EVSP_LADDER:-16:600,18:1000}"
export EVSP_MILP_TIME_LIMIT="${EVSP_MILP_TIME_LIMIT:-28800}"
export EVSP_MIP_GAP="${EVSP_MIP_GAP:-0.01}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 solver_compare.py
