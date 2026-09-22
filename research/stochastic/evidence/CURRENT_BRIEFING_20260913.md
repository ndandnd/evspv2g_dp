# Current EVSP V2G results and next experiments

Latest update at18:20UTC: the [bounded-reserve batch is now validated](snapshots/bounded_reserve_validation/BRIEFING.md). All72newcases/26,280trajectories passed. Atfiveunits/emptycyclicstart,50%reserves match maximumreserve's observedzero-failure result at15.5–17.4% versus29.1–33.7% extra cost. A25%target costs7.9–9.0% extra, withonefailed day inoneofsixschedules. Fullseedresults andanadversecase are retained in the newbrief. The existingpaperdocument/data package remains the earlier frozen version; monitoring ispausedaftercompletion.

No V2G result changed during the preceding idle monitoring checks. This task then launched and completed 48 new reserve-controller cases on [site identifier omitted]. All 17,520 daily trajectories and 144 independent oracle LPs passed validation. We now have enough for a useful data section, editable tables and preliminary figures.

| Evidence | Result | Meaning for the paper |
|---|---|---|
| Earlier matched deterministic/SAA comparison | V2G+BESS SAA24 saved 7.0–7.3% against the same-pool annual-mean plan; all 365 development days feasible across three seeds. | Stochastic planning is already showing a useful effect under the stated controller. This is development evidence, not a new result from monitoring. |
| Earlier controlled BESS experiment | 90 cases / 32,850 trajectories. All 24 mean-shortage interaction estimates favor a larger storage benefit under variable solar, but all 95% intervals include zero. | We cannot yet claim uncertain weather increases the economic return on BESS. Installed capacity and dispatch quality need to be separated. |
| New reserve-controller experiment | 48 cases / 17,520 trajectories. All 24 reserve configurations have zero observed shortages. With five units and empty cyclic start, the baseline has 5–13 failures per schedule and reserve priority has zero. | How storage is operated matters. This is 2022 development weather with forecasts fitted on 2023, not a fresh holdout. |
| New cost finding | At five units and empty start, reserve priority costs 29.1–33.7% more on jointly feasible dates; at twenty units it costs 163.0–181.7% more. | Maximizing reserves is too expensive as a default. The next scientific experiment is an affordable reserve target. |
| Earlier algorithm improvement | The 120-trip union pool improved the best prior pool cost by about 2.25%, with a 0.272–0.275% gap to the separately valid full-route LP bound in the discretized model. | Keep validated CG plus MIP while testing the operational question. A full branch-and-price rewrite is not currently justified by these results. |

The six source schedules and their repeated daily evaluations are related cases, not thousands of independent weather days. Cost comparisons disclose jointly feasible dates; failed days remain in shortage statistics. Zero observed failures is not a guarantee of zero future risk.

## Data section started

The six-page editable document (original research artifact `paper_data_20260913/EVSP_V2G_Data_and_Experiments.docx`; not included in this export) begins with weather, synthetic trips, model parameters and decisions before/after observation. It includes seven editable tables and two figures. The dataset package (original research artifact `EVSP_V2G_Data_Package_20260913.zip`; not included in this export) adds full CSV tables, three figures in PNG/SVG/PDF, raw-query provenance, protocols, hashes and extraction/plot scripts.

The data contain four weather years, 35,064 hourly observations, 70,128 derived half-hour energy rows, three synthetic instances with 20/60/120 tasks, six validated fixed bus profiles and all new daily outcomes. Existing weather is a gridded BestMatch proxy at fixed UTC−7, not measured military-site PV or a homogeneous ERA5 record. The next operational study must examine its hourly observation timing, continuous day-to-day energy and physical/cost calibration.

## Public code is now being tested selectively

Parmentier's actual MIT energy-resource source compiled and ran on [site identifier omitted]: five right-identity checks and 121 feasible associativity checks passed. Its self-dominance predicate returned false in five cases; we documented that semantics/tolerance issue before any transfer. Full CG/branch-and-price is unreproduced because CPLEX/Concert was not found in the standard software locations inspected. No external solver has been integrated into our implementation.

Baldua's source remains inspected only; use its continuous scenario/partition structure when testing decomposition against a tiny extensive form. Léa's inspected repository supplies benchmark inputs and published results rather than solver source. A trip-data adapter is useful for a later traction-energy benchmark. See [actual code use and decision gates](public_code_checks/RESULTS.md).

## Next priorities

1. **Affordable reserves:** compare fixed reserve targets at the same capacity, forecast and initial energy; produce a cost/shortage frontier.
2. **Operational information and flexibility:** test delayed solar observations and continuous multi-day storage, then a tiny scenario tree in which bus charging can adapt while mandatory duties remain fixed.
3. **Investment:** freeze the controller and compare common-pool deterministic/SAA BESS purchases at equal reliability targets; acquire additional unused weather years and a second climate after fixing the evaluation design.

The new batch is finished, not waiting on dependencies. Array 133707 and smoke 133695 used 2.693 actual allocated CPU-hours; the separate public-code component test took six CPU-seconds. No V2G experiment remains running from this batch. The empty monitor remains paused; the next batch should answer the next registered question. EVSP–DR jobs, held job 537227, original holdout results and the unmerged solver PR remain with their existing owners and provenance.
