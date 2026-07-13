# OVERNIGHT-14 — common-pool repair round (8–9 h)

`cd ~/evspv2g_dp && git pull` first.

Why: the overnight13 four-arm integer comparisons solved each arm over its own
generated pool. The exact LP values respect every dominance relation; the
incumbents do not (14 nesting violations in FOURARM, 42 adjacent-cap
monotonicity violations in FOURCAPS — pool-and-time-limit artifacts, not
economics). overnight14 re-solves the integer comparisons over arm-admissible
UNION pools (C_CO = solar ∪ solar_bess; C_V2G = C_CO ∪ v2g_fleet ∪ v2g; caps
studies also union across all six levels), restrictive→flexible and
tight→loose with inherited MIP starts, so nesting and monotonicity hold by
construction. Per-row verifications: union-pool LP == own priced-out LP,
start acceptance, dominance; pool hashes and start provenance recorded.

## Step 0 — blocking gates (scaglione; read output before releasing bulk)

```bash
JG=$(sbatch --parsable -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=GATE,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch)
JS=$(sbatch --parsable -p scaglione -N1 --export=ALL,OVERNIGHT14_STUDIES=SMOKE,OVERNIGHT14_SHARD=0/1 run_overnight14_unicorn.sbatch)
echo "gates: overnight13_${JG}.out must say GATE PASS; overnight14_${JS}.out must say SMOKE PASS"
```

## Step 1 — core (release after BOTH gates pass)

```bash
DP="-p default_partition --requeue --time=24:00:00 -N1"

# P1 the repaired factorial (the paper's principal treatment comparison)
for i in $(seq 0 11); do sbatch $DP --export=ALL,OVERNIGHT14_STUDIES=COMMON4,OVERNIGHT14_SHARD=$i/12 run_overnight14_unicorn.sbatch; done
# P2 repaired generation-cap frontier (one base per shard; unions across caps)
for i in $(seq 0 8); do sbatch $DP --export=ALL,OVERNIGHT14_STUDIES=COMMONCAPS,OVERNIGHT14_SHARD=$i/9 run_overnight14_unicorn.sbatch; done
# P3 charging-cap panel, common pools, utilization recorded (replaces legacy Fig 8b)
for i in $(seq 0 8); do sbatch $DP --export=ALL,OVERNIGHT14_STUDIES=CHARGECAPS2,OVERNIGHT14_SHARD=$i/9 run_overnight14_unicorn.sbatch; done
# P4 integer diagnostics ladder (completes Table 5's promised column)
for i in $(seq 0 23); do sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=DIAG2,OVERNIGHT13_SHARD=$i/24 run_overnight13_unicorn.sbatch; done
# P5 lattice/Corollary-1 falsification test
for i in $(seq 0 3); do sbatch $DP --export=ALL,OVERNIGHT13_STUDIES=ALIGN,OVERNIGHT13_SHARD=$i/4 run_overnight13_unicorn.sbatch; done
# P6 CBC/Gurobi audit on eight matched pools (narrow claim)
for i in $(seq 0 7); do sbatch -p scaglione -N1 --export=ALL,OVERNIGHT13_STUDIES=AUDIT,OVERNIGHT13_SHARD=$i/8 run_overnight13_unicorn.sbatch; done
```

## Step 2 — spare capacity only

```bash
# PACK4 at finer sharding (6 cells/shard; 2 shards would risk 12 h worst case)
for i in $(seq 0 7); do sbatch $DP --nice=200 --export=ALL,OVERNIGHT13_STUDIES=PACK4,OVERNIGHT13_SHARD=$i/8 run_overnight13_unicorn.sbatch; done
```

## Explicitly NOT queued this round

- **FOURARMX unchanged**: its pv 1.5–2.5 window is NOT a common γ region
  (γ = 2.6–5.9 / 0.86–1.98 / 0.43–0.99 at 20/60/120 tasks). If a numerical
  break-even stays a headline, the replacement is a γ-matched design with the
  charger premium inside the optimization.
- **EXPORT2 tightening**: 27 of the 56 high-gap rows are already optimal on
  their restricted pools, so longer MIP time closes nothing; the table gets
  LP values or bound intervals and a combined-system-displacement relabel
  instead (EXPORT4 four-arm only if marginal export stays central).
- **SUN2**: still needs the max_trucks pricing dual + stage-1 persistence.

## Claims discipline (additions)

- Paired treatment claims from COMMON4/COMMONCAPS use the certified interval
  [L_A − U_B, U_A − L_B] (LP bound of one arm vs incumbent of the other) and
  say whether the sign is certified.
- Rows with `lp_check_ok = false` or `start_accepted = false` are quarantined
  as solver anomalies, not results.

# Weekend run plan — FINAL v2 (48h+, unattended)

`cd ~/evspv2g_dp && git pull` first. GATE needs networkx
(`pip install --user networkx` once if the env lacks it).

Since v1: outcome classes replace the feasible/infeasible conflation
(`feasible` / `lp_certified_infeasible` / `no_real_incumbent` /
`no_incumbent`), LP artificial mass recorded, full diagnostics per row (cg_s,
milp_s, pricing_s, iters, cols), PERIODIC now at 25 kWh like its controls,
SPINE25's infinite-cap resume keys canonicalized, CHARGECAPS added (the
charging-cap panel with utilization), PACK4 replaces the legacy-schema PACK3,
HOLDOUT22 at 25 kWh with stage-1 provenance. SUN2 and the old
SUN/DIAG/PACK3/MODESX/CAPS resumes are OFF the queue.

Since v2 (pre-launch review round):
- **True Phase-I certificate.** Positive artificial mass in the converged
  economic LP is NOT an infeasibility certificate (the finite 1e6 penalty only
  bounds optimal mass by ~U/1e6, so a feasible near-cliff cell can park
  fractional mass legitimately). `_solve13` now treats positive mass as a
  TRIGGER: `_phase1_certify` minimizes artificial mass with all real costs
  zeroed, priced to optimality. Priced-out positive Phase-I mass =>
  `lp_certified_infeasible`; Phase-I mass zero => the economic CG resumes with
  the Phase-I columns injected (`ph1_resume`); budget exhausted =>
  `positive_artificial_unresolved`, and the MILP still runs (an artificial-free
  incumbent proves feasibility by exhibit). Validated: BREAKS benchmark
  certifies at exactly mass 12 (the 12 dead tasks); repaired BREAKS2 drives to
  mass 0; the m=1.0 reference cell reproduces solar 6,871.3 / v2g 1,044.7
  artificial-free.
- **GATE hardened** (it was a strong smoke test, not yet an oracle): the
  Bellman-Ford comparator now keeps min-weight parallel transitions
  (DiGraph.add_edge overwrote; parallel trip/relocation arcs could mask
  disagreements), duals are heterogeneous (identity seeds gave near-uniform
  duals), both 50 and 25 kWh are sampled, synthetic station prices replay
  through the master reduced-cost formula (previously rc_master := rc_dp was
  tautological), free mode covers synthetic nu and charge-only, and a fixed
  periodic tail runs at 25 kWh (the PERIODIC study's lattice). Local smoke
  shards pass at 2.8e-14.
- **max_trucks dual: consequence corrected (less severe than v2 said).** The
  dual on sum x_r <= M is <= 0 in the min LP, so omitting it UNDERSTATES every
  truck reduced cost uniformly: a reported price-out remains a valid LP
  certificate; the real failure mode is phantom negative columns (churn /
  stalling to max_iter, visible in cg_converged). Old SUN/OUT rows are still
  not publication-grade -- they lack the new statuses -- but not because their
  convergence was unsound. The dual still gets added before SUN2/OUT4, for
  efficiency and cleanliness. Nothing this weekend uses max_trucks.

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
# NOTE: one study per job. sbatch --export splits on commas, so
# "OVERNIGHT13_STUDIES=EXPORT2,REGIME2" would be parsed as the assignment
# EXPORT2 plus a bare env-var name REGIME2 -- REGIME2 would silently never run.
sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=EXPORT2,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch
sbatch $DPN --export=ALL,OVERNIGHT13_STUDIES=REGIME2,OVERNIGHT13_SHARD=0/1 run_overnight13_unicorn.sbatch
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
  infeasibility claim -- which now means the TRUE Phase-I certificate
  (`ph1_converged = true` with `ph1_mass > 0`), never the finite-penalty
  economic LP alone. `no_real_incumbent` / `no_incumbent` /
  `positive_artificial_unresolved` rows are diagnostics only.
- Rows with positive `lp_artificial_mass` after a `ph1_resume` carry a
  penalized `lp_obj` (a lower bound on the true economic LP value); quote their
  MILP incumbents, not their LP objective.
