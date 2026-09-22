# Independent result audit

Audit status: **valid**. The four synced attempt02 cases pass independent local reinspection. This covers 16 fitting LP phases, 1,460 replay days and 2,920 daily old/common physical-state checks.

| Case | Old mean | Common mean | Adaptive mean | Old − common | Common − adaptive | Nesting asserted |
|---|---:|---:|---:|---:|---:|---|
| policy14_nb20_fit2022 | 3604.11655812 | 3602.96404824 | 3602.38561068 | 1.15250987 | 0.57843757 | Yes |
| policy14_nb20_fit2023 | 3604.11655812 | 3602.97022974 | 3602.38561068 | 1.14632838 | 0.58461906 | No |
| policy17_nb20_fit2022 | 3677.94685475 | 3602.96404824 | 3602.38561068 | 74.98280650 | 0.57843757 | Yes |
| policy17_nb20_fit2023 | 3677.94685475 | 3602.97020029 | 3602.38561068 | 74.97665445 | 0.58458962 | No |

All comparators have zero shortage on all 365 evaluation days in every case. Costs include the fixed asset charge. Fits using 2022 support the retrospective finite-population decomposition. Fits using 2023 are frozen-profile evaluations on a different weather population: their contrasts are descriptive, and the audit confirms that cross-population nesting is not asserted. Storage and generation retain full-day foresight.

The audit rehashes the registered release manifest, original fitting/evaluation inputs, declared source evidence, result files, all solver primal/dual/matrix artifacts, native logs, journals and daily traces. It verifies that the exported named arrays equal the indexed raw primal vectors and that the frozen common truck actions/states match the fitting solution and are exactly identical across all evaluation days. Physics and costs are reconstructed directly from arrays; no extensive model builder is imported and no solver is rerun.

All 16 native phases have OPTIMAL status. The largest absolute difference between a recomputed primal objective and its native LP bound is 9.64e-11; maximum KKT stationarity error is 2.1e-13. The largest daily physical residual is 7.11e-15, and maximum saved daily cost recomputation error is 3.64e-12.

Some reconstructed dual objectives remain null because unbounded variables have tiny negative reduced costs. These are preserved rather than rounded to manufacture a lower bound. Native LP bounds and floating-point KKT evidence are retained; they are numerical certificates, not exact rational proofs.

Weighted summaries recomputed across local/cluster NumPy environments differ by at most 2.27e-12. Numeric comparisons use the stated tolerances; source hashes, structural fields and frozen-profile arrays require exact equality.

`INDEPENDENT_RESULT_AUDIT.json` contains the complete method, source/code hashes, per-phase numerical checks and per-case replay evidence. No source, solver, campaign, or scheduler state was changed during this audit.
