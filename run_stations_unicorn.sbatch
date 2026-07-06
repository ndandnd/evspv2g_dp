#!/bin/bash
#SBATCH --job-name=evsp_stations
#SBATCH --output=stations_%j.out
#SBATCH --error=stations_%j.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export STATIONS_STUDIES="${STATIONS_STUDIES:-SA,SB}"
export STATIONS_SHARD="${STATIONS_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 stations_study.py
