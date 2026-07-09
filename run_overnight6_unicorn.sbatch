#!/bin/bash
#SBATCH --job-name=evsp_overnight6
#SBATCH --output=overnight6_%j.out
#SBATCH --error=overnight6_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue
# no --time: studies are sized to ~5-8 h; the partition default applies.

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT6_STUDIES="${OVERNIGHT6_STUDIES:-CAPS3,SATFIX}"
export OVERNIGHT6_SHARD="${OVERNIGHT6_SHARD:-0/1}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight6.py
