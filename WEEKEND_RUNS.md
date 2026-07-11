# Weekend run plan — FINAL v2 (48h+, unattended)

`cd ~/evspv2g_dp && git pull` first. GATE needs networkx
(`pip install --user networkx` once if the env lacks it).

Since v1: outcome classes replace the feasible/infeasible conflation
(`feasible` / `lp_certified_infeasible` / `no_real_incumbent` /
`no_incumbent`), LP artificial mass recorded (the certificate lives at the LP
level), full diagnostics per row (cg_s, milp_s, pricing_s, iters, cols),
PERIODIC now at 25 kWh like its controls, the independent oracle validates the
periodic boundary properly (GATE samples cyclic/free/periodic, charge-only,
and priced-station cases; passes at 1e-14), SPINE25's infinite-cap resume keys
canonicalized, CHARGECAPS added (the charging-cap panel with utilization),
PACK4 replaces the legacy-schema PACK3, HOLDOUT22 at 25 kWh with stage-1
provenance. SUN2 and the old SUN/DIAG/PACK3/MODESX/CAPS resumes are OFF the
queue.

Known open item (documented, not weekend-blocking): the max_trucks dual is
absent from reduced-cost pricing, so frozen-asset stage-2 runs (OUT3, SUN)
carry valid incumbents but no LP price-out certificate. Nothing this weekend
uses max_trucks. Fix lands before any SUN2/OUT4 rerun.

## Step 0 — blocking gate (scaglione; read the output before releasing bulk)

```bash
JG=$(sbatch --parsable -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=GATE,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch)
echo "gate job $JG -- overnight13_${JG}.out must say GATE PASS"
```

## Step 1 — core (release after GATE PASS)

```bash
DP="-p default_partition --requeue --time=48:00:00 -N1"

# P1 the factorial (decides the economics)
for i in $(seq 0 11); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=FOURARM,OVERNIGHT13_SHARD=$i/12 run_overnight13_unicorn.sbatch; done
# P2 generation-cap frontier, four arms, Phase-I-certified outcomes
for i in $(seq 0 5); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=FOURCAPS,OVERNIGHT13_SHARD=$i/6 run_overnight13_unicorn.sbatch; done
# P2b charging-cap panel, four arms, utilization recorded
for i in $(seq 0 5); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=CHARGECAPS,OVERNIGHT13_SHARD=$i/6 run_overnight13_unicorn.sbatch; done
# P3 lattice/theorem alignment (Corollary-1 falsification test)
for i in $(seq 0 3); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=ALIGN,OVERNIGHT13_SHARD=$i/4 run_overnight13_unicorn.sbatch; done
# P4 scalability diagnostics + solver audit (scaglione: one hard cell per job)
for i in $(seq 0 23); do sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=DIAG2,OVERNIGHT13_SHARD=$i/24 run_overnight13_unicorn.sbatch; done
for i in $(seq 0 7);  do sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=AUDIT,OVERNIGHT13_SHARD=$i/8 run_overnight13_unicorn.sbatch; done
# P5 boundary convention (scaglione; periodic pricing is ~15x per cell)
for i in $(seq 0 7);  do sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=PERIODIC,OVERNIGHT13_SHARD=$i/8 run_overnight13_unicorn.sbatch; done
# P6 treatment-effect error bars (promoted ahead of weather breadth)
for i in $(seq 0 11); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=FOURARMX,OVERNIGHT13_SHARD=$i/12 run_overnight13_unicorn.sbatch; done
```

## Step 2 — breadth (submit after Step 1, at LOWER priority so core drains first)

```bash
DPN="$DP --nice=200"
for i in $(seq 0 9); do sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=W2,OVERNIGHT13_SHARD=$i/10 run_overnight13_unicorn.sbatch; done
sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=EXPORT2,REGIME2,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch
for i in $(seq 0 3); do sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=SPINE25,OVERNIGHT13_SHARD=$i/4 run_overnight13_unicorn.sbatch; done
sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=ETA125,OVERNIGHT13_SHARD=0/2 run_overnight13_unicorn.sbatch
sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=ETA125,OVERNIGHT13_SHARD=1/2 run_overnight13_unicorn.sbatch
for i in $(seq 0 1); do sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=PACK4,OVERNIGHT13_SHARD=$i/2 run_overnight13_unicorn.sbatch; done
# optional tail, single-pass shards (each completes stage 1 + its evals in one go)
for i in $(seq 0 31); do sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=HOLDOUT22,OVERNIGHT13_SHARD=$i/32 run_overnight13_unicorn.sbatch; done
```

## Dropped / deferred, with reasons

- **SUN2**: deferred — needs the max_trucks pricing dual, stage-1 persistence,
  and sunk-cost accounting first. Breadth, not core.
- **PACK3 resume**: replaced by PACK4 (fresh schema; the 38 legacy rows lack
  provenance).
- **Old SUN / DIAG resumes, MODESX2/3, CAPS2/3**: superseded.
- **REGIME2 stays**, with the standing convention that ICE/EV flat-price rows
  are made comparable in ANALYSIS (the gallery adds the measured 3.3x ICE
  traction fuel post hoc, as the regime figure has always documented); the
  solver objective is not the cross-regime comparator and never was.

## Claims discipline

- AUDIT supports exactly: "CBC and Gurobi agree on eight representative
  matched column pools" (CBC bounds are not recorded). Family-level
  open-source claims come from which solver actually produced each family.
- DIAG2 is a 50 kWh coarse-lattice scalability study by design (the
  multi-station family's energies divide no lattice); do not quote its gaps
  as continuous-model gaps.
- Paper rows require: `cg_converged = true`, outcome `feasible` (artificial-
  free) for any feasibility claim, and `lp_certified_infeasible` for any
  infeasibility claim. `no_real_incumbent` / `no_incumbent` rows are
  diagnostics only.
