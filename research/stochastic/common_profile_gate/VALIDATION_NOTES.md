# Independent validation and replay checks

The validator reconstructs physical equations and operating costs directly from
the portable input and exported arrays. It does not import the extensive LP
builder or consume its matrices. Common truck actions are one multiplicity-scaled
`J,T` charge array, one discharge array, and one `J,T+1` state array; scenario
dimensions on truck decisions are rejected. The validator checks all truck and
BESS state transitions, boundaries, nonnegativity, capacity and connection/rate
limits, generation/shared-charging caps, energy balance, task coverage, and the
inherited pinned witness. Expected costs include the fixed asset charge once.
Input identity, declared source files, exported primals/duals and native solver
logs are checked against their recorded hashes. Primal feasibility is a separate
claim from numerical solver optimality.

The replay evaluator formulates a separate sparse SciPy LP for daily storage and
generation, with the frozen truck actions as constants. It first minimizes
emergency energy, then fixes that minimum exactly and minimizes operating cost.
Every replay is independently checked and exports all per-slot actions and states.
Journals include hash-linked records and trace hashes and support interruption and
resumption with a fixed input/profile/code identity.

Local focused checks used Python 3.12 and SciPy 1.13.1. Results and exact code hashes
are in `VALIDATION_CHECKS.json`:

- All 365 saved 2022 days for policy 17/Nb=20 and policy 14/Nb=20 were replayed with
  their inherited truck profiles. Both reproduce the saved wave16 operating costs
  to a maximum absolute difference of 1.82e-12, with identical zero shortage and
  maximum physical residual 7.11e-15. The means including fixed assets are
  3677.946854747917 and 3604.1165581171017, respectively. This verifies the new daily
  recourse implementation against 730 saved records; the old campaign was not
  rerun and its files were not modified.
- Solver-exported tiny-case primals validate, and independent replay reproduces
  their 15.02 total cost. A one-day checkpoint resumes to the two-day completion.
- Deliberately weather-indexed truck decisions, a modified truck state and a
  modified terminal BESS state are rejected.
- A positive-emergency replay retains its diagnostic operating cost and reports
  monetary total cost as null.
- A different fitting/evaluation year suppresses nesting assertions, including a
  synthetic empirical reversal where the frozen common profile costs more than
  the inherited profile on evaluation days.

Same-population decomposition is asserted only for a complete evaluation, complete
numerically certified LP phases and shared zero shortage on all days. A 2023-fit
profile evaluated on 2022 produces signed descriptive contrasts instead. Both
types of replay retain full-day storage/generator foresight; neither is a causal
controller comparison. Where any comparator has shortage, reliability statistics
come first and no full-population monetary decomposition is produced. Reported
joint-support means are explicitly conditional and do not replace all-day means.
