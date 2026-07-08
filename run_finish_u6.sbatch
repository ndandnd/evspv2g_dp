#!/bin/bash
#SBATCH --job-name=evsp_finish_u6
#SBATCH --output=finish_u6_%j.out
#SBATCH --error=finish_u6_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue
# no --time: ~6.5 h of chained work (7 U6 runs + 18 LATTICE LP runs).
# ckpt() now tolerates truncated checkpoint files and save() writes atomically,
# so a mid-write kill can no longer corrupt a shard or crash this chain.
# (S3 deg=13 break-even rows are already complete -- removed from the chain.)

set -euo pipefail

cd "$HOME/evspv2g_dp"
mkdir -p logs results

export GRB_LICENSE_FILE=/share/apps/software/gurobi/gurobi.lic
unset LM_LICENSE_FILE

source /share/apps/software/anaconda3/etc/profile.d/conda.sh
conda activate /home/nc437/evsp_env

python3 -c "import gurobipy; print('gurobi', gurobipy.gurobi.version())"

OVERNIGHT3_STUDIES=U6 OVERNIGHT3_SHARD=3/6 python3 overnight3.py
OVERNIGHT3_STUDIES=U6 OVERNIGHT3_SHARD=5/6 python3 overnight3.py
OVERNIGHT4_STUDIES=LATTICE OVERNIGHT4_SHARD=0/1 python3 overnight4.py
