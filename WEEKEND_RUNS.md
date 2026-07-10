# Weekend run plan (48h unattended, finalize before submitting)

Two tiers on the unicorn/G2 cluster:

- **`-p scaglione`** (group priority): never preempted, but ~4 h wall limit.
  Reserve for runs whose single cells are long (a preemption mid-cell wastes
  the most work here).
- **`-p default_partition --requeue --time=48:00:00`**: preemptible, but every
  overnight study checkpoints per row (atomic write) and skips done cells on
  restart, so preemption is a pause, not a loss. `--requeue` puts the job back
  in queue automatically; `--open-mode=append` (in the sbatch files) keeps logs
  across restarts. This tier carries the bulk.

Everything below assumes `cd ~/evspv2g_dp && git pull` first.

## Tier 1 -- scaglione (uninterruptible, one job per line)

```bash
# DIAG: integer diagnostics on the 100-1000-task maps (completes Table 5).
# Long cells (LP up to ~1 h + MILP up to 30 min): 4 shards fit the 4 h wall.
for i in 0 1 2 3; do OVERNIGHT12_STUDIES=DIAG OVERNIGHT12_SHARD=$i/4 sbatch -p scaglione -N1 run_overnight12_unicorn.sbatch; done

# PERIODIC: steady-state boundary robustness (32 cells, ~15x pricing cost each)
OVERNIGHT13_STUDIES=PERIODIC OVERNIGHT13_SHARD=0/2 sbatch -p scaglione -N1 run_overnight13_unicorn.sbatch
OVERNIGHT13_STUDIES=PERIODIC OVERNIGHT13_SHARD=1/2 sbatch -p scaglione -N1 run_overnight13_unicorn.sbatch
```

## Tier 2 -- default_partition (preemptible bulk; requeue-safe)

```bash
DP="-p default_partition --requeue --time=48:00:00 -N1"

# FOURARM: the V2G x BESS factorial (324 bases x 4 arms grid, tl 900) -- the
# run that identifies the treatment effects; highest priority of the weekend.
for i in 0 1 2 3 4 5; do OVERNIGHT13_STUDIES=FOURARM OVERNIGHT13_SHARD=$i/6 sbatch $DP run_overnight13_unicorn.sbatch; done

# FOURCAPS: the feasibility cliff with all four arms (does charge-only+BESS survive?)
OVERNIGHT13_STUDIES=FOURCAPS OVERNIGHT13_SHARD=0/2 sbatch $DP run_overnight13_unicorn.sbatch
OVERNIGHT13_STUDIES=FOURCAPS OVERNIGHT13_SHARD=1/2 sbatch $DP run_overnight13_unicorn.sbatch

# W2: weather year on the repaired deterministic base (BREAKS2), 3 arms x 5 pv
for i in 0 1 2 3 4 5 6 7; do OVERNIGHT13_STUDIES=W2 OVERNIGHT13_SHARD=$i/8 sbatch $DP run_overnight13_unicorn.sbatch; done

# EXPORT2 + REGIME2: repaired-window export table and regime ladder (small)
OVERNIGHT13_STUDIES=EXPORT2,REGIME2 OVERNIGHT13_SHARD=0/1 sbatch $DP run_overnight13_unicorn.sbatch

# SPINE25: the one-factor spine at delta = 25 kWh (exact-lattice headline runs)
for i in 0 1 2; do OVERNIGHT13_STUDIES=SPINE25 OVERNIGHT13_SHARD=$i/3 sbatch $DP run_overnight13_unicorn.sbatch; done

# ETA125: loss sweep at delta = 12.5 kWh (minimal rate-quantization confound)
OVERNIGHT13_STUDIES=ETA125 OVERNIGHT13_SHARD=0/2 sbatch $DP run_overnight13_unicorn.sbatch
OVERNIGHT13_STUDIES=ETA125 OVERNIGHT13_SHARD=1/2 sbatch $DP run_overnight13_unicorn.sbatch

# HOLDOUT22: committed schedules designed on 2023, tested on 2022 (out-of-sample)
for i in 0 1 2; do OVERNIGHT13_STUDIES=HOLDOUT22 OVERNIGHT13_SHARD=$i/3 sbatch $DP run_overnight13_unicorn.sbatch; done

# Completions from the previous round
OVERNIGHT12_STUDIES=PACK3 OVERNIGHT12_SHARD=0/2 sbatch $DP run_overnight12_unicorn.sbatch
OVERNIGHT12_STUDIES=PACK3 OVERNIGHT12_SHARD=1/2 sbatch $DP run_overnight12_unicorn.sbatch
OVERNIGHT12_STUDIES=SUN  OVERNIGHT12_SHARD=0/2 sbatch $DP run_overnight12_unicorn.sbatch   # resumes; s1of2 done
OVERNIGHT11_STUDIES=MODESX3 sbatch $DP run_overnight11_unicorn.sbatch                      # resumes at ~800/1872
```

## The trio (MODESX2 / CAPS2 / CAPS3): diagnose BEFORE resubmitting

They completed in ~1 second five times. First print what they actually said:

```bash
cat overnight5_822328.out overnight5_822329.out overnight6_822330.out
```

The runners now FAIL LOUD on unknown study names, so a name mismatch can no
longer no-op silently. After reading the output (and `git pull`):

```bash
OVERNIGHT5_STUDIES=MODESX2 sbatch $DP run_overnight5_unicorn.sbatch
OVERNIGHT5_STUDIES=CAPS2   sbatch $DP run_overnight5_unicorn.sbatch
OVERNIGHT6_STUDIES=CAPS3   sbatch $DP run_overnight6_unicorn.sbatch
```

## Rules that keep the weekend safe

1. **Never two jobs on the same checkpoint file** (same study AND same shard
   i/K). Different shards of one study are different files and are fine.
2. Preempted/requeued jobs resume from their checkpoint automatically; a job
   that hits `--time` can simply be resubmitted with the identical command.
3. The correctness fixes in this round (honest MILP statuses, CG termination
   flags, Phase-I artificial seeds, BREAKS2 windows, periodic pricing mode)
   are all in `git`; the cluster MUST `git pull` before submitting anything.
4. `squeue --me` truth check: our jobs are named `evsp_overnight*`; `sacct`
   entries with other names/nodes are other clusters' recycled job IDs.

## What lands where (for the rebuild after the weekend)

| Study | Feeds |
|---|---|
| FOURARM | collapse/value story recomputed with 4 arms; new gamma* (conditional); fig 5/7 successors |
| FOURCAPS | feasibility-cliff figure with 4 arms (the "prerequisite" claim test) |
| W2/EXPORT2/REGIME2 | weather fig, export table, regime fig on repaired instances |
| SPINE25 | headline one-factor numbers at the exact lattice |
| ETA125 | loss sweep without rate quantization |
| PERIODIC | boundary-robustness table vs full-recharge (Table 3 companion) |
| HOLDOUT22 | out-of-sample commitment figure (2023-design vs 2022-test) |
| DIAG | integer columns for Table 5 |
| PACK3 / MODESX3 / SUN / trio | pack fig 200-task curve; modes 6-seed; solar-shortfall fig; caps error bars |
