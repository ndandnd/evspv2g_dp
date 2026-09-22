# Validated algorithm priority benchmark

All 56 feasible CG/MIP variants passed independent validation. Two additional 120-trip/no-BESS repetitions retain separately validated Phase-I infeasibility certificates. Implementation: [draft PR #2](https://github.com/ndandnd/evspv2g_dp/pull/2), execution `37a5e788d7a2079acb30fa6e45cddc30373c12e7`.

## Paired engineering comparisons

Each row reports the range across matched allocation cases, not a confidence interval. Speedup greater than one favors the candidate; positive MIP cost change is worse. Two order-reversed timing repetitions use the same seed and are not independent scenario samples. CG plus native MIP time excludes separate launcher/model-setup overhead.

| Change | Matched pairs | CG speedup range | MIP cost change range | CG + native MIP speedup range |
|---|---:|---:|---:|---:|
| legacy_highs → sparse_highs | 10 | 1.115–1.277× | 0.000–0.000% | 1.067–1.272× |
| sparse_gurobi → persistent_gurobi | 10 | 1.045–2.153× | -1.079–1.619% | 0.647–1.419× |
| persistent_gurobi → persistent_cached | 10 | 0.981–1.143× | 0.000–0.000% | 0.991–1.139× |
| persistent_cached → persistent_cached_warm | 6 | 1.269–2.625× | -1.594–0.001% | 1.216–1.358× |

## Every feasible workload

Values below are means of two timing repetitions; cost and gap ranges retain both results. Full rows, component timings and paired comparisons are editable in [all_variant_results.csv](all_variant_results.csv) and [paired_comparisons.csv](paired_comparisons.csv).

### 20 trips / solar_bess

| Variant | Mean CG seconds | Mean iterations | Mean columns | MIP objective range | MIP gap range | Mean native MIP seconds |
|---|---:|---:|---:|---:|---:|---:|
| legacy_highs | 18.80 | 40.0 | 58.0 | 4641.087–4641.087 | 0.0000–0.0000% | 0.37 |
| sparse_highs | 15.03 | 40.0 | 58.0 | 4641.087–4641.087 | 0.0000–0.0000% | 0.36 |
| sparse_gurobi | 13.61 | 42.0 | 60.0 | 4632.971–4632.971 | 0.0000–0.0000% | 0.28 |
| persistent_gurobi | 10.04 | 47.0 | 65.0 | 4707.999–4707.999 | 0.0000–0.0000% | 1.04 |
| persistent_cached | 9.91 | 47.0 | 65.0 | 4707.999–4707.999 | 0.0000–0.0000% | 1.00 |
| persistent_cached_warm | 7.77 | 3.0 | 149.0 | 4632.970–4632.970 | 0.0000–0.0000% | 0.31 |

### 20 trips / v2g

| Variant | Mean CG seconds | Mean iterations | Mean columns | MIP objective range | MIP gap range | Mean native MIP seconds |
|---|---:|---:|---:|---:|---:|---:|
| legacy_highs | 22.56 | 44.0 | 62.0 | 4587.657–4587.657 | 0.0000–0.0000% | 0.36 |
| sparse_highs | 18.25 | 44.0 | 62.0 | 4587.657–4587.657 | 0.0000–0.0000% | 0.36 |
| sparse_gurobi | 15.30 | 42.0 | 60.0 | 4637.588–4637.588 | 0.0000–0.0000% | 0.61 |
| persistent_gurobi | 11.51 | 45.0 | 63.0 | 4587.539–4587.539 | 0.0000–0.0000% | 0.30 |
| persistent_cached | 10.83 | 45.0 | 63.0 | 4587.539–4587.539 | 0.0000–0.0000% | 0.28 |
| persistent_cached_warm | 7.91 | 4.0 | 150.0 | 4587.551–4587.551 | 0.0000–0.0000% | 0.75 |

### 20 trips / v2g_fleet

| Variant | Mean CG seconds | Mean iterations | Mean columns | MIP objective range | MIP gap range | Mean native MIP seconds |
|---|---:|---:|---:|---:|---:|---:|
| legacy_highs | 158.40 | 304.0 | 322.0 | 6129.375–6129.375 | 3.2165–3.2238% | 120.01 |
| sparse_highs | 130.76 | 304.0 | 322.0 | 6129.375–6129.375 | 3.2166–3.2166% | 120.01 |
| sparse_gurobi | 105.48 | 308.0 | 326.0 | 6064.704–6064.704 | 2.1231–2.1235% | 120.01 |
| persistent_gurobi | 49.30 | 292.0 | 310.0 | 6132.205–6132.205 | 3.2530–3.2537% | 120.01 |
| persistent_cached | 48.71 | 292.0 | 310.0 | 6132.205–6132.205 | 3.2530–3.2538% | 120.01 |
| persistent_cached_warm | 18.59 | 83.0 | 229.0 | 6132.242–6132.242 | 1.8036–1.8323% | 120.01 |

### 120 trips / solar_bess

| Variant | Mean CG seconds | Mean iterations | Mean columns | MIP objective range | MIP gap range | Mean native MIP seconds |
|---|---:|---:|---:|---:|---:|---:|
| legacy_highs | 120.30 | 213.0 | 331.0 | 15753.197–15753.197 | 0.0000–0.0000% | 77.88 |
| sparse_highs | 104.82 | 213.0 | 331.0 | 15753.197–15753.197 | 0.0000–0.0000% | 76.72 |
| sparse_gurobi | 88.01 | 208.0 | 326.0 | 15806.654–15806.654 | 0.0000–0.0000% | 33.75 |
| persistent_gurobi | 83.64 | 211.0 | 329.0 | 15809.672–15809.672 | 0.0000–0.0000% | 103.24 |
| persistent_cached | 84.58 | 211.0 | 329.0 | 15809.672–15809.672 | 0.0000–0.0000% | 103.69 |

### 120 trips / v2g

| Variant | Mean CG seconds | Mean iterations | Mean columns | MIP objective range | MIP gap range | Mean native MIP seconds |
|---|---:|---:|---:|---:|---:|---:|
| legacy_highs | 147.67 | 233.0 | 351.0 | 15598.644–15598.644 | 1.4082–1.4548% | 120.00 |
| sparse_highs | 128.97 | 233.0 | 351.0 | 15598.644–15598.644 | 1.4083–1.4124% | 120.00 |
| sparse_gurobi | 106.21 | 237.0 | 355.0 | 15517.665–15517.665 | 0.6867–0.7059% | 120.00 |
| persistent_gurobi | 94.91 | 233.0 | 351.0 | 15573.631–15573.631 | 1.4264–1.4264% | 120.00 |
| persistent_cached | 91.95 | 233.0 | 351.0 | 15573.631–15573.631 | 1.4264–1.4533% | 120.00 |

## Validation and limitations

All 56 feasible CG runs priced out; all 56 native incumbents and rounded fixed-policy LPs passed. MIP status counts (2=optimal within requested tolerance, 9=time limit): {'2': 34, '9': 22}. Maximum finite-pool gap 3.254%. Total measured CG time 3447.61s, native MIP time 3442.70s; scoped scheduler allocation including canary/native tests and infeasibility attempts 2.119 CPU-hours. Raw job/step memory, nodes and allocation are in accounting.psv (original research artifact `snapshots/algorithm_efficiency_validation/accounting.psv`; not included in this export). CG case11 received two allocated CPUs despite one requested; comparisons remain paired within allocations, but cross-node timing effects cannot be eliminated.

The initial audit incorrectly required a new cold LP's optimal dual to price out immediately. Degenerate restricted masters can return another optimal dual that violates absent-column inequalities. For 10 pools the corrected independent audit added 18 routes to disposable validation models and repriced to completion; every objective remained within 1e-4 of its saved value. Added profiles, reduced costs and objective traces are retained in case validation JSONs. No frozen pool, worker, training policy or native MIP was changed. This validates the objective independently; it does not reproduce the original terminal dual vector.

Source/configuration/protocol and journal hashes, all physical profiles, exact original/sparse matrices, cold LPs, exact uncached pricing, native incumbent vectors and rounded-policy feasibility were checked. Final MIP bounds concern saved finite pools; CG lower bounds concern the admitted discretized common-profile LP. Optimal finite-pool MIPs are not full-route integer optimality proofs. Numerical tolerances remain explicit.

The larger workload is 120 trips, correcting the frozen protocol label of 60 without changing inputs. Cases8/9 have verified positive Phase-I lower bound 38.42297580364211; they are scientifically infeasible under this common-profile model and cap, not crash recoveries. Their dependent MIPs were cancelled. No arbitrary adaptive-route infeasibility claim is made.

This is an algorithm benchmark on 2023 training samples. It establishes no new out-of-sample policy savings. The original 2024/2025 holdout and EVSP–DR are untouched. Warm sources were preexisting validated pools and import costs are included, but generating those source pools is not charged again; a from-scratch comparison must account for that investment. Two repetitions do not support population speedup intervals.


## Implementation decision and next bounded gate

| Priority | Decision from this panel | Follow-up |
|---|---|---|
| Correctness contracts and true Phase I | Retain. All feasible variants and the two infeasibility cases validate within their stated scope. | Keep independent replay and exact current-dual termination mandatory. |
| Sparse scenario template | Strongest low-risk performance result: 1.115–1.277× faster CG, identical integer objectives in all ten pairs. | Preferred assembly path in the candidate; merge remains separate. |
| Persistent Gurobi LP | Keep selectable. CG speedup 1.045–2.153×, but CG plus native MIP speedup ranges 0.647–1.419× and cost changes −1.079% to +1.619%. | Evaluate pool enrichment and total solve quality before universal adoption. |
| Prepared pricing cache | Keep bounded and optional. Same pool quality; CG speedup 0.981–1.143×. | No standalone large speedup claim; optimize only if profiling justifies it. |
| Bounded warm import | Useful when compatible pools already exist: 1.269–2.625× CG speedup over persistent+cache in six small-workload pairs. | Account for source-pool generation in from-scratch studies; no large-workload evidence yet. |

Warm import recovered the small solar+BESS pool deficit, but the no-BESS warm result still costs 6132.242 versus 6064.704 for cold Gurobi (about 1.11% higher) at equal 120-second MIP limits. Faster CG and a smaller reported MIP gap do not imply a better incumbent across different pools. The next justified diagnostic is a frozen-pool, longer-MIP-budget comparison to separate pool quality from truncated integer search, followed only if needed by bounded pool enrichment/diving. Predeclare total budgets and keep native searches in new non-requeued Scaglione attempt paths. This follow-up is proposed, not launched. Full branch-and-price or RL remains unjustified by this engineering panel alone.
