# Weekend run plan — FINAL (48h+, unattended; longer is better)

Everything assumes `cd ~/evspv2g_dp && git pull` first, and that the conda env
has networkx (`pip install --user networkx` once if the GATE job complains).

Two tiers:
- **`-p scaglione`**: no preemption, ~4h wall. Gets the GATE and the runs whose
  single cells are long (DIAG2, AUDIT, PERIODIC).
- **`-p default_partition --requeue --time=48:00:00`**: preemptible bulk; every
  study checkpoints per row and resumes, so preemption is a pause.

Corrections baked in since the draft plan (all smoke-tested):
honest MILP statuses preserved everywhere (time-limit incumbents are kept and
labeled `feasible`), universal Phase-I artificial coverage (the initial RMP can
never be infeasible before pricing — this **invalidated the old feasibility
cliff**: a first corrected solve shows charge-only IS feasible at the 1.0x cap
at ~6.5x the full-stack cost), delta = 25 kWh on all headline studies (exact
lattice for the lossless family), REGIME2 rebuilt (162 real cells), SPINE25 and
ETA125 de-confounded (all four arms), provenance (commit, solvers, step,
boundary) recorded per row, independent oracle fixed to the correct terminal
condition and gated.

## Step 0 — the blocking gate (run first, read output before releasing bulk)

```bash
JG=$(sbatch --parsable -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=GATE,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch)
echo "gate job $JG -- check overnight13_${JG}.out says GATE PASS before proceeding"
```

If the gate FAILS, stop and send me the output. If it passes:

## Step 1 — the core (priorities 1–5; release immediately after the gate)

```bash
DP="-p default_partition --requeue --time=48:00:00 -N1"

# P1: the factorial that decides the paper's economics (12 shards)
for i in $(seq 0 11); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=FOURARM,OVERNIGHT13_SHARD=$i/12 run_overnight13_unicorn.sbatch; done

# P2: the corrected cap frontier (does charge-only+BESS survive? is anything infeasible at all?)
for i in $(seq 0 5); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=FOURCAPS,OVERNIGHT13_SHARD=$i/6 run_overnight13_unicorn.sbatch; done

# P3: lattice/theorem alignment (Corollary-1 test: LP(25) must equal LP(12.5) lossless)
for i in $(seq 0 3); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=ALIGN,OVERNIGHT13_SHARD=$i/4 run_overnight13_unicorn.sbatch; done

# P4: corrected scalability diagnostics + solver audit (scaglione: long single cells)
for i in $(seq 0 11); do sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=DIAG2,OVERNIGHT13_SHARD=$i/12 run_overnight13_unicorn.sbatch; done
sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=AUDIT,OVERNIGHT13_SHARD=0/2 run_overnight13_unicorn.sbatch
sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=AUDIT,OVERNIGHT13_SHARD=1/2 run_overnight13_unicorn.sbatch

# P5: boundary-convention comparison (scaglione)
sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=PERIODIC,OVERNIGHT13_SHARD=0/2 run_overnight13_unicorn.sbatch
sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=PERIODIC,OVERNIGHT13_SHARD=1/2 run_overnight13_unicorn.sbatch
```

## Step 2 — the breadth tail (submit right after Step 1; preemption ordering
## naturally lets the core drain first, and these soak the remaining 48h+)

```bash
for i in $(seq 0 9);  do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=W2,OVERNIGHT13_SHARD=$i/10 run_overnight13_unicorn.sbatch; done
sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=EXPORT2,REGIME2,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch
for i in $(seq 0 3);  do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=SPINE25,OVERNIGHT13_SHARD=$i/4 run_overnight13_unicorn.sbatch; done
sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=ETA125,OVERNIGHT13_SHARD=0/2 run_overnight13_unicorn.sbatch
sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=ETA125,OVERNIGHT13_SHARD=1/2 run_overnight13_unicorn.sbatch
for i in $(seq 0 2);  do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=HOLDOUT22,OVERNIGHT13_SHARD=$i/3 run_overnight13_unicorn.sbatch; done
for i in $(seq 0 3);  do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=SUN2,OVERNIGHT13_SHARD=$i/4 run_overnight13_unicorn.sbatch; done
for i in $(seq 0 11); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=FOURARMX,OVERNIGHT13_SHARD=$i/12 run_overnight13_unicorn.sbatch; done
# finish PACK3 (resumes at 38/48 under the corrected status wrapper)
sbatch $DP --export=ALL,OVERNIGHT12_STUDIES=PACK3,OVERNIGHT12_SHARD=0/2 run_overnight12_unicorn.sbatch
sbatch $DP --export=ALL,OVERNIGHT12_STUDIES=PACK3,OVERNIGHT12_SHARD=1/2 run_overnight12_unicorn.sbatch
```

## Deliberately dropped

- **MODESX2 / MODESX3 / CAPS2 / CAPS3**: superseded. The caps figure's error
  bars now come from FOURCAPS (which also fixes the initialization artifact and
  the missing arm); the modes 240–400 extension is deferred — the corrected
  factorial carries the workload story. This also ends the five-submission
  mystery chase.
- **Old SUN/DIAG resumes**: replaced by SUN2/DIAG2 with corrected recorders and
  fresh checkpoint schemas; do not resume the old shards.

## Solver policy (decided; revisit if you disagree)

Cluster runs use Gurobi for the final integer master, recorded per row; the
AUDIT study solves eight matched cells with BOTH CBC and Gurobi so the paper
can state the open-source reproducibility claim family-by-family, honestly.

## Safety rules

1. Never two jobs on the same (study, shard) key.
2. A job that hits --time can be resubmitted with the identical command.
3. `squeue --me` shows our jobs as `evsp_overnight13`; foreign names under
   recycled IDs in sacct are other clusters' jobs.
4. Results enter the paper only from rows with `cg_converged = true`, an
   artificial-free incumbent for feasibility claims, and recorded statuses.
