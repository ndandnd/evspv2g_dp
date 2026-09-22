# Bounded reserves reduce the cost of reliability

All72 new cases completed and passed validation. With five batteries and an empty daily starting state, a50% reserve target eliminates observed failures for all six fixed schedules at a15.5–17.4% matched cost premium. The earlier maximum-reserve controller costs29.1–33.7% more than baseline. A25% target costs7.9–9.0% more and has zero failures for five schedules and one failure for the sixth.

## Five units with an empty cyclic start

Every count is out of365 development days. Source fit N means the original schedule was fitted without BESS; B means fitted with BESS. Comparisons hold each schedule fixed.

| Source fit and seed | Baseline failures | 10% target | 25% target | 50% target | Maximum reserve |
|---|---:|---:|---:|---:|---:|
| N, seed 11 | 5 | 1 | 0 | 0 | 0 |
| N, seed 29 | 8 | 2 | 1 | 0 | 0 |
| N, seed 47 | 9 | 2 | 0 | 0 | 0 |
| B, seed 11 | 11 | 8 | 0 | 0 | 0 |
| B, seed 29 | 11 | 9 | 0 | 0 | 0 |
| B, seed 47 | 13 | 10 | 0 | 0 | 0 |

| Reserve target | Extra cost versus baseline on jointly feasible dates |
|---|---:|
| 10% | 2.5–3.0% |
| 25% | 7.9–9.0% |
| 50% | 15.5–17.4% |
| Maximum | 29.1–33.7% |

All120 treatment rows and144 paired comparisons, with cost supports and95% intervals, are retained in [all_treatments.csv](all_treatments.csv), [all_comparisons.csv](all_comparisons.csv) and [validated_results.json](validated_results.json). Counts are related sensitivity outcomes over the same weather year; they are not independent replications or a zero-risk guarantee.

## Boundaries and adverse outcomes

Across both capacities and both starting fractions,10% reserves produce zero observed failures in14/24 configurations,25% in20/24, and50% in24/24. Cost depends strongly on installed capacity and starting energy: a fraction of20units is not the same physical reserve as that fraction of5units. These are not new optimal investment choices.

The adverse case must remain visible: source27, five units, half-full cyclic start, increases from2 to3 failed days under10% reserves, with about2.35% higher cost on jointly feasible dates. Increasing a local reserve floor does not guarantee improved realized multi-step reliability. At20units with a half-full start, some10%/25% configurations also retain failures.

## Validation and next gate

All26,280 new trajectories, journal/configuration identities, costs and216 independent oracle LPs passed;48 reused endpoint journals match their previous validation hashes. Max physical residual1.42e-14. Actual allocation including smoke was4.268CPU-hours; the last job ended18:11:54UTC and validation completed2026-09-13T18:20:30.462572+00:00. The ten-minute monitor is paused after this completed batch.

This is2022 development weather with forecasts from2023 and assumed current-slot solar observation. Before independent evaluation or BESS investment claims, test observation lag and continuous multi-day energy, preserving the same transport duties. No new campaign was launched during monitoring; original2024/2025 results and EVSP–DR remain separate.
