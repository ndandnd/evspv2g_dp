# CG speed ablation: measured results (1,000-task inputs)

Written 2026-10-18 02:05 EDT from results rsynced at 02:02 EDT. All 12 arms (6 per input) have completed.
Design and arm definitions: `experiments/opte_cg_speed_ablation_20261017/FORENSIC.md` §11. Raw copies:
`raw/results/` (without the C arms' column/primal dumps), `raw/logs/`, `raw/preempted/`. Collector output
(run locally as `collect_ablation.py raw/results <prefix>`): `ablation_summary_final_20261018T0602Z.{md,json}`.
`ablation_summary_partial_20261018T0538Z.*` is an earlier run without arm A on L04; it is superseded.

Labels: **measured** = read from a completed result.json. **inferred** = calculated under a stated assumption.

## 1. Arms

| Arm | Code / master | Where |
|---|---|---|
| A0 | original 14835da, exact Table 4 call: SciPy/HiGHS master rebuilt densely each iteration, 25 enrichment rounds | Xeon Silver 4214, scaglione-compute-01, 4 CPUs |
| A | as A0 | EPYC 9654, samitha-compute-01, 1 core |
| B | as A, no enrichment | EPYC 9654 |
| E | original code with its own Gurobi backend, model rebuilt each iteration (term-by-term `quicksum` build), 25 enrichment rounds | EPYC 9654 |
| C | frozen new code, Gurobi master rebuilt each iteration from the dense `_build_lp` (Table 18 "rebuild"), no enrichment | EPYC 9654 |
| D | frozen new code, one persistent Gurobi master with basis reuse (Table 20 CG phase), no enrichment | EPYC 9654 |

Arm A on L04 (job 365528_0) was preempted at 22:04 after 1,075 RMP solves, requeued and restarted from scratch at
22:47 EDT; it finished at 02:00 EDT. The numbers below are from the complete second attempt.

## 2. Per-arm results [measured]

Master s = build / engine / in-loop validation. Per solve = master s / RMP solves. Pricing per call covers greedy,
loop and enrichment calls.

**diag2_L04_n1000_s0** (4 locations)

| Arm | CPU | CG s | iters | cols | LP | master s (build / engine / valid.) | pricing s | s per master solve | ms per pricing call |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| A0 | Silver 4214 | 16,401.8 | 1,729 | 3,793 | 48,050.4250 | 16,369.0 (130.9 / 16,236.0 / –) | 32.0 | 9.46 | 17.8 |
| A | EPYC 9654 | 11,602.6 | 1,729 | 3,793 | 48,050.4250 | 11,583.7 (72.0 / 11,511.1 / –) | 18.1 | 6.70 | 10.1 |
| B | EPYC 9654 | 11,349.1 | 1,729 | 3,768 | 48,050.4250 | 11,330.0 (82.2 / 11,245.4 / –) | 18.5 | 6.55 | 10.4 |
| E | EPYC 9654 | 4,062.7 | 1,762 | 3,826 | 48,050.4250 | 4,042.7 (1,047.6 / 2,983.0 / –) | 19.3 | 2.29 | 10.5 |
| C | EPYC 9654 | 3,428.3 | 1,733 | 3,772 | 48,050.4250 | 3,392.2 (265.7 / 3,074.4 / 51.6) | 19.6 | 1.96 | 11.0 |
| D | EPYC 9654 | 1,032.8 | 1,849 | 3,888 | 48,050.4250 | 1,010.4 (60.0 / 888.9 / 58.9) | 20.0 | 0.55 | 10.6 |

**diag2_L15_n1000_s0** (15 locations)

| Arm | CPU | CG s | iters | cols | LP | master s (build / engine / valid.) | pricing s | s per master solve | ms per pricing call |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|
| A0 | Silver 4214 | 13,056.5 | 1,704 | 3,768 | 54,681.6875 | 12,932.0 (129.5 / 12,800.2 / –) | 123.7 | 7.58 | 69.9 |
| A | EPYC 9654 | 9,122.5 | 1,704 | 3,768 | 54,681.6875 | 9,050.9 (85.1 / 8,963.3 / –) | 70.9 | 5.31 | 40.1 |
| B | EPYC 9654 | 9,082.0 | 1,704 | 3,743 | 54,681.6875 | 9,010.2 (88.0 / 8,919.2 / –) | 71.2 | 5.29 | 40.8 |
| E | EPYC 9654 | 3,635.6 | 1,728 | 3,792 | 54,681.6875 | 3,562.4 (986.9 / 2,563.3 / –) | 72.5 | 2.06 | 40.4 |
| C | EPYC 9654 | 3,114.5 | 1,716 | 3,755 | 54,681.6875 | 3,026.7 (268.2 / 2,706.5 / 51.4) | 71.2 | 1.76 | 40.5 |
| D | EPYC 9654 | 886.0 | 1,767 | 3,806 | 54,681.6875 | 810.5 (58.2 / 694.2 / 55.8) | 73.4 | 0.46 | 40.6 |

All arms converged (original code: `priced_out`; C: `optimal_to_pricing_tolerance`; D: `candidate_priced_out`
with the final DP call empty). None reached the 21,600-s cap.

## 3. Same LP, same input [measured]

- LP values: every arm is within 1.5e-9 of 48,050.425 (L04) and 54,681.6875 (L15); the largest relative deviation
  is 2.7e-14. All round to the Table 4 records (48,050.43 and 54,681.69).
- Input: every arm reports the same instance sha256 per input (`5cfb5f26…` for L04, `d28f88d8…` for L15), in
  original-code and new-code arms alike.
- A0 and A reproduce the Table 4 iteration and column counts exactly (1,729 / 3,793 and 1,704 / 3,768). B has the
  same iterations and 25 fewer columns (no enrichment). D reproduces the Table 20 counts exactly (1,849 / 3,888 and
  1,767 / 3,806). E, C and D take 0.2–7% more iterations than A; the different LP engines return different duals
  in degenerate masters. Per-solve ratios are therefore slightly larger than total-time ratios.

## 4. Where the time goes [measured]

- Master LP time is 99.0–99.8% of CG time in A0, A and B, 97–99.5% in E and C, and 91.5–97.8% in D. Pricing is
  0.16–2.3%, except D on L15 (8.3%).
- The 25 enrichment rounds took 0.30 s (A, L04), 0.45 s (A0, L04), 0.96 s (A, L15) and 1.74 s (A0, L15) of pricing.
  They add no master solves (A and B both make 1,730 and 1,705 master solves).
- Mean seconds per master solve by number of columns in the master:

| Columns | A0 L04 | A L04 | E L04 | C L04 | D L04 | A0 L15 | A L15 | E L15 | C L15 | D L15 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2,000–2,499 | 0.32 | 0.21 | 0.44 | 0.20 | 0.07 | 0.30 | 0.21 | 0.42 | 0.19 | 0.07 |
| 2,500–2,999 | 2.20 | 1.51 | 1.21 | 0.85 | 0.28 | 1.63 | 1.17 | 1.12 | 0.79 | 0.25 |
| 3,000–3,499 | 11.02 | 7.54 | 3.08 | 2.95 | 0.76 | 9.41 | 6.84 | 2.88 | 2.75 | 0.70 |
| 3,500–3,999 | 35.74 | 25.89 | 5.62 | 5.13 | 1.18 | 29.80 | 20.29 | 5.12 | 4.56 | 0.99 |

  The gap opens as the master grows. Near 3,500–4,000 columns a SciPy/HiGHS solve takes 20–36 s, a rebuilt
  Gurobi solve 4.6–5.6 s and a warm-started persistent Gurobi solve 1.0–1.2 s.

## 5. Measured factors

Ratios of CG wall time; per master solve and engine-only in brackets. [measured]

| Factor | Ratio | L04 | L15 |
|---|---|---:|---:|
| Processor: original code, Silver 4214 node vs EPYC 9654 | A0/A | **1.41** (per solve 1.41; per pricing call 1.76) | **1.43** (1.43; 1.74) |
| Solver: SciPy/HiGHS dense rebuild vs Gurobi rebuild from the same dense build | A/C | **3.38** (3.42; engine 3.74) | **2.93** (3.01; engine 3.31) |
| Solver inside the original code (its own Gurobi path) | A/E | 2.86 (2.92; engine 3.86) | 2.51 (2.58; engine 3.50) |
| Rebuild each iteration vs one persistent master with basis reuse | C/D | **3.32** (3.58; 3.47 without validation) | **3.52** (3.85; 3.69 without validation) |
| Enrichment: 25 rounds vs none | A/B | 1.022 | 1.004 |
| Original vs new code, same CPU | A/D | 11.2 | 10.3 |
| Original code on original node vs new code on EPYC 9654 | A0/D | 15.9 = 1.41 × 3.38 × 3.32 | 14.7 = 1.43 × 2.93 × 3.52 |

Notes:
- Solver: C is the clean comparison; it swaps only the LP engine under the same dense build. E's Gurobi path
  builds the model term by term with `quicksum`, which costs about 1,000 s (26–28% of E's master time), so A/E is
  smaller than A/C. On engine time alone, HiGHS to Gurobi is 3.3–3.9× in both comparisons.
- Enrichment: A and B solve the same sequence of master LPs (same iterations, same number of solves, same LP).
  Enrichment itself took 0.30 s (L04) and 0.96 s (L15). The rest of the 253-s (L04) and 40-s (L15) gap is in
  master time over that identical LP sequence, i.e. timing variation between runs, not enrichment work
  [inferred]. On L04, A ran in a restarted attempt next to fewer of the other arms than B.

## 6. Link to the printed tables [measured]

| | L04 | L15 |
|---|---:|---:|
| Table 4 run / A0 rerun (same code, same node) | 1.023 | 1.008 |
| D on EPYC 9654 / Table 20 run on EPYC 9555 | 0.69 | 1.28 |
| Table 4 / Table 20 (printed) | 11.3 | 19.0 |

- The original code on the original node today reproduces the Table 4 CG times within 2.3%, and the iterations,
  columns and LP exactly.
- D follows exactly the Table 20 CG path (same iteration and column counts; 1.27 million simplex iterations on L04
  in both), but its time differs from Table 20 by 0.69× and 1.28×, in opposite directions on the two inputs. This is
  node or load variation between the EPYC 9654 and EPYC 9555 runs. It was not investigated.
- Table 4 / Table 20 = (Table 4 / A0) × (A0 / A) × (A / C) × (C / D) × (D / Table 20). The first and last terms are
  reproduction and node variation. The middle three are the processor, solver and reuse factors of §5.

## 7. FORENSIC.md estimates superseded

| Factor | FORENSIC.md §1/§8 [inferred] | Measured here |
|---|---|---|
| Processor and load | 2.2–2.5× (pricing per call, vs the EPYC 9555 run) | 1.41–1.43× vs EPYC 9654 (total and per master solve); pricing per call 1.74–1.76× |
| Rebuild vs reuse | 1.8–2.9× per solve | 3.3–3.5× total; 3.6–3.8× per solve |
| SciPy/HiGHS vs Gurobi | remainder, 2.2–3.8× | 2.9–3.4× (A/C); 2.5–2.9× via the original code's own Gurobi path (A/E) |
| Enrichment | no effect | 0.30–0.96 s; no change to the iterations; total-time ratio 1.004–1.022 |


## 8. Caveats

- Load was not controlled. scaglione-compute-01 (24 cores) ran the two A0 jobs (4 CPUs each) next to another
  user's 2-CPU job and a changing set of 3-CPU jobs. samitha-compute-01 (2 × 96-core EPYC 9654) ran all ten EPYC
  arms at once (one bound core each, thread variables 1), next to other users' 2–32-CPU jobs (`sacct -a -N`).
- One run per arm and input (sample 1 of each location count). There are no repeats, so run-to-run spread is not
  measured. The A vs B gap (up to 2.2% on an identical LP sequence) and D vs Table 20 (0.69–1.28) give a rough idea.
- C and D include 51–59 s of in-loop replay validation in CG time (6% of D's total); A0, A, B and E have none.
- The processor factor is Silver 4214 vs EPYC 9654. Table 20 ran on an EPYC 9555; the ablation does not measure
  Silver 4214 vs EPYC 9555 directly.

## 9. Summary

Rerunning both codes on the two 1,000-task inputs, with the same LP value in every run, splits the 15–16-fold
speedup between the original code on the node of the original runs (Intel Xeon Silver 4214) and the new code on one AMD EPYC 9654
node into a factor of about 1.4 from the processor, 2.9–3.4 from solving the rebuilt restricted master with Gurobi
instead of SciPy/HiGHS, and 3.3–3.5 from keeping one Gurobi master and reusing its basis, while the 25 enrichment
rounds took less than 2 s and did not change the iterations.

Note: the three factors multiply to A0/D = 15.9 (L04) and 14.7 (L15), not to the printed Table 4 / Table 20 ratios
(11.3 and 19.0). Those also include the node difference between the EPYC 9654 rerun and the EPYC 9555 Table 20 run
(0.69× and 1.28×) and the 1–2% reproduction gap (§6).
