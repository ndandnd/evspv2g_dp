#!/bin/bash
#SBATCH --job-name=evsp_overnight9
#SBATCH --output=overnight9_%j.out
#SBATCH --error=overnight9_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue
# no --time: studies are sized to ~5-8 h; the partition default applies.

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT9_STUDIES="${OVERNIGHT9_STUDIES:-ENDUR2,OUTAGE2,SATFIX2,SCHED2,WCITIES}"
export OVERNIGHT9_SHARD="${OVERNIGHT9_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight9.py
