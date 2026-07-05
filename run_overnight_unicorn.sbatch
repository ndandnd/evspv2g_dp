#!/bin/bash
#SBATCH --job-name=evsp_overnight
#SBATCH --output=overnight_%j.out
#SBATCH --error=overnight_%j.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE
export OVERNIGHT_STUDIES="${OVERNIGHT_STUDIES:-S3,S4,S2,S1}"
export OVERNIGHT_N_SWEEP="${OVERNIGHT_N_SWEEP:-500}"

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"
python3 overnight.py
