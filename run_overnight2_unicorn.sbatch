#!/bin/bash
#SBATCH --job-name=evsp_overnight2
#SBATCH --output=overnight2_%j.out
#SBATCH --error=overnight2_%j.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT2_STUDIES="${OVERNIGHT2_STUDIES:-S5,S6,S7,S8}"
export OVERNIGHT2_SHARD="${OVERNIGHT2_SHARD:-0/1}"
export OVERNIGHT2_N_FLEETS="${OVERNIGHT2_N_FLEETS:-240}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight2.py
