#!/bin/bash
#SBATCH --job-name=evsp_finish_u6
#SBATCH --output=finish_u6_%j.out
#SBATCH --error=finish_u6_%j.err
#SBATCH --time=09:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --requeue

# One node, chained: (1) the ~7 U6 runs the 24h wall killed on shards 3 and 5
# (per-row checkpoints skip everything already done), (2) the S3 enablement
# break-even rows for the new deg=$0.13/kWh level (checkpointed on (deg,prem,pv)),
# (3) the LATTICE ladder. Do NOT also submit separate shard-3/5 overnight3 jobs --
# two jobs writing the same shard checkpoint file race each other.

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
OVERNIGHT_STUDIES=S3 python3 overnight.py
OVERNIGHT4_STUDIES=LATTICE OVERNIGHT4_SHARD=0/1 python3 overnight4.py
