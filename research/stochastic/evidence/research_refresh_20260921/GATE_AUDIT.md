# Audit of the wave-15 gate and the proposed capacity screen

21 September 2026. Read-only audit of saved experiments and their code. The original campaign files were not modified. Reproducible checks are in `gate_audit/check_saved_gate.py`; machine-readable findings are in `gate_audit/audit.json`. Four first-day LP witnesses were solved locally; no MIP, full new campaign, cluster submission or other-project action was performed by this audit.

## Finding

Wave 15 is completed evidence, not a proposed experiment. Its principal correction to the earlier research story is supported: on this development instance, the training-selected monthly planning profile reproduces the earlier SAA advantage over the annual-mean comparator when BESS is available. Separately, perfect-information adaptive charging on a fixed, reconstructed route skeleton is materially valuable without BESS and nearly valueless with the existing large BESS installations. This supports one controlled capacity screen. It does not justify either an adaptive-pricing implementation yet or a general conclusion that causal charging adaptation has no value.

The next bounded run should add a small set of fixed BESS capacities to the four existing no-BESS profiles, with the same assets within each fixed/adaptive pair. The new `capacity_gate_wave16` implementation does this appropriately; the short pre-launch audit below found no blocking defect.

## What is actually completed

I inspected the native archive under `snapshots/gate_wave15_validation/campaigns/`, not just its report.

| Campaign | Completed outputs | Independent audit performed |
|---|---:|---|
| `gate_oracle_wave15` | 48 cases, 17,520 day records | All complete statuses, date sequences, hash chains, status digests, source pool/MIP hashes, all recorded nesting checks |
| `gate_baselines_wave15` | 54 native MIP incumbents | Native result statuses; frozen pool/source consistency; selected-profile physical replay |
| `gate_baselines_eval_wave15` | 108 cases, 39,420 day records | Same journal, provenance and nesting checks as the oracle campaign |
| `gate_causal_wave15` | 22 cases, 8,030 day records | All complete statuses, date sequences, hash chains, status digests and source pool/MIP hashes |

Total: **64,970 daily records**. Every journal/hash check passed. All **468 recorded pinned-profile LP witnesses** agree with the fixed oracle, maximum checked discrepancy approximately **1.02 × 10⁻¹⁰**. All **66 selected-policy skeleton sets**—12 original mean/SAA policies and 54 new baselines—replay within truck capacity with full-to-full terminal energy. Their net signed profile energy equals reconstructed traction. I also freshly reproduced the first 2022 day for no-BESS policies 10, 11, 14 and 17, including the pinned LP.

The native baseline MIP status counts are **48 optimal within configured tolerance and six time-limited**, all with incumbents. `RESULTS.md` says nine time-limited no-BESS MIPs; that sentence is wrong. The six are cases 21, 22, 28, 29, 30 and 33, with gaps **0.182%–3.116%**. This audit did not rerun the MIPs or independently reconstruct every native full recourse vector. Existing finite-pool certification must not be promoted to full-route integer optimality.

The launch record reports 4.02 allocated CPU-hours including causal follow-up and duplicate oracle allocation. This audit did not independently retrieve scheduler accounting. The ordinary `campaigns/gate_*` folders mostly hold configuration/launch files; the completed local outputs are in the snapshot.

## Quantitative findings that survive the audit

All results below use the single 20-trip, two-location development instance, 2× PV and 2022 evaluation, with weather scaling/forecast fitting based on 2023. They do not supply new untouched validation data.

### Charging adaptation at generation cap 0.8

| Plan | Fixed / adaptive failed days | Jointly feasible days | Oracle saving per day | Saving relative to fixed oracle |
|---|---:|---:|---:|---:|
| No BESS, annual mean | 100 / 0 | 265 | 65.51 | 1.58% |
| No BESS, SAA seed 11 | 6 / 0 | 359 | 185.73 | 3.81% |
| No BESS, SAA seed 29 | 8 / 0 | 357 | 193.82 | 3.99% |
| No BESS, SAA seed 47 | 9 / 0 | 356 | 232.44 | 4.76% |
| V2G+BESS, annual mean | 0 / 0 | 365 | 1.65 | 0.0495% |
| V2G+BESS, SAA seeds | 0 / 0 | 365 | 0.0349–0.0430 | 0.00113%–0.00139% |
| Solar+BESS, annual mean | 0 / 0 | 365 | 0.3143 | 0.00898% |
| Solar+BESS, SAA seeds | 0 / 0 | 365 | 0.0079–0.0155 | 0.00025%–0.00049% |

No-BESS mean all-day shortage is 0.90969 model energy units; the three SAA values are 0.03807, 0.08363 and 0.05439. Adaptive shortage is zero on every saved day in those cases. All-day adaptive costs are 4,808.81 for the mean plan and 4,790.12 for each SAA seed. Those all-day values must not be compared directly with a fixed-profile mean calculated only over successful days.

The BESS/no-BESS cost comparison uses different preselected fleets and assets: no-BESS mean/SAA fleets contain 16/15 trucks, while these BESS arms use five trucks plus 18–23 storage units. Their roughly 50% cost difference is not a matched-asset estimate of BESS value.

### Stronger deterministic baseline

The stated training-only monthly selection rule reproduces **April** for Solar+BESS and **August** for V2G+BESS. On 2022 under the fixed oracle:

- Solar+BESS selected monthly plan: 3,149.72/day, versus SAA 3,157.85 / 3,144.71 / 3,142.33.
- V2G+BESS selected monthly plan: 3,095.08/day, versus SAA 3,094.52 / 3,096.17 / 3,098.46.

All are feasible on all 365 days. Thus the particular claim that SAA materially beats a credible monthly-profile method does not survive this gate. The old annual-mean comparison remains a real measured contrast, but it does not establish a general advantage over deterministic planning methods.

The causal current-solar comparison independently confirms that conclusion in V2G+BESS. The selected monthly plan costs **3,162.0397/day**, with zero failures. Recomputed paired 14-calendar-day circular-block intervals, 2,000 replicates, seed 7291, for *other policy minus selected monthly* are:

| Comparator | Mean cost | Difference/day | Descriptive 95% interval |
|---|---:|---:|---:|
| Annual mean | 3,412.9136 | 250.8739 | [154.2140, 349.7308] |
| SAA seed 11 | 3,162.4092 | 0.3695 | [−3.0365, 3.8907] |
| SAA seed 29 | 3,163.7808 | 1.7411 | [−2.0883, 6.2513] |
| SAA seed 47 | 3,174.0266 | 11.9869 | [4.0153, 21.3712] |

These are all-day paired cost comparisons with zero failures for each plan, not conditional supports. The three training seeds share the same test weather and are not independent replications of a population experiment. The selected Solar+BESS monthly plan has one causal current-solar failure versus two/two/three for original SAA; separate conditional cost means do not establish cost dominance there.

Matching BESS counts leaves substantial gains from reoptimizing the common truck profiles and initial BESS state. It does **not** uniquely identify a mechanism: the controls reoptimize multiple decisions together, and holding count constant does not hold initial stored energy or signed truck schedules constant. Their interpretation should be “storage count alone does not explain the annual-mean gap,” rather than an exact decomposition of its causes.

The lower-irradiance quantile plans are poor economic comparators here, but the phrase “a dark planning day buys no storage” is false for the recorded BESS cases. The 10th-percentile plans buy **seven units in Solar+BESS and five in V2G+BESS**; the 25th-percentile plans buy eleven/nine, and median plans twenty-one/eighteen. Low irradiance does not imply a robust planning profile, but it does not literally imply zero BESS in these data.

## Code and inference limitations

1. **The oracle difference is not a general upper bound on gains over a causal baseline.** Let Fᴾᴵ and Aᴾᴵ denote fixed-profile and adaptive perfect-information costs, and Fᶜ the fixed-profile causal cost. The measured gate is Fᴾᴵ−Aᴾᴵ. An adaptive causal controller obeys Aᶜ ≥ Aᴾᴵ, so its gain over Fᶜ is bounded by Fᶜ−Aᴾᴵ, not by Fᴾᴵ−Aᴾᴵ. In the monthly V2G+BESS plan alone, Fᶜ−Fᴾᴵ is about 66.96/day. Near-zero oracle-to-oracle value therefore shows substitution under full information, not that truck flexibility cannot mitigate forecast/control limitations. `oracle.py` line 10 and broad “worth nothing” readings require this qualification.

2. **Skeletons are reconstructed, not preserved original route paths.** `oracle.py:skeleton` minimizes traction and then maximizes depot time subject to task incidence and nonzero profile slots. It enforces the tasks and valid locations/timing, and every tested fixed profile is feasible on the reconstructed path. However, the saved columns do not contain the original deadhead/parking paths. Claim fixed reconstructed profile-compatible skeletons. This is a valid controlled energy screen, but not proof that the exact routes returned by the earlier pricing algorithm had these windows. The new screen serializes full connected/withdrawal/incidence/profile arrays, which is stronger provenance than wave 15's aggregate skeleton summaries.

3. **Important dormant model bugs are neutralized only by current physics.** Truck SoC in `oracle.py:101` uses charge coefficient −1 and omits `(1−eta)`, while BESS correctly includes it. `setup` hardcodes infinite fixed-oracle charging allowance, whereas the adaptive LP applies `inst.charge_cap`. Fixed cost uses `c_v` instead of the original column fixed cost, and fixed truck operating cost includes only the small throughput penalty, omitting degradation that pricing can fold into column fixed cost. All audited policies have **eta=0, deg_cost=0, charge_cap=∞, column fixed_cost=45**, so these defects do not invalidate existing results. Do not reuse the LP for lossy charging, positive degradation, finite shared charging caps, extra constraints or altered asset pricing without fixing both comparators. The new capacity worker asserts these exact conditions.

4. **Nonanticipativity is limited.** `causal.py` fixes all truck decisions; only BESS and generation are dispatched using the current observation plus a training forecast. It is not causal vehicle adaptation. The current half-hour average is assumed known before selecting that slot's action; historical endpoint-hour/weather averaging conventions make this an idealized information model. Full-day oracle decisions have no nonanticipativity constraints. The independent review's class-dependent truck model also does not make scenario-indexed BESS decisions nonanticipative. Its originally claimed independent suffix pricing was corrected because common task incidence and repeated coverage duals were unresolved.

5. **Rolling-horizon feasibility is not shortage-free reliability.** The inherited dispatch shrinks to the true end of day and retains hard cyclic BESS energy. Each optimization permits unbounded nonnegative emergency energy. With fixed nonnegative charging allowances, an executed feasible first step retains the later energy schedule as a possible continuation; future solar changes can be absorbed by emergency supply/curtailment. That protects mathematical feasibility of the elastic LP, not absence of energy deficits. A future adaptive-truck MPC must preserve all remaining traction withdrawals, connection windows and truck terminal states. A short look-ahead controller with an arbitrary terminal target needs its own viability tests. Wave-15 causal journals discard action trajectories (`z.pop('steps')`), retaining online maximum replay residuals rather than enabling a new full trajectory replay from the saved journal alone.

6. **Same pool is a controlled comparison, not equal total method-development cost.** Every new baseline uses the same arm-specific frozen wave-7 pool, which is appropriate for isolating selection/training differences. That pool came from previous method-union generation, including stochastic/robust searches. The twelve-month search plus 2023 selection consumes more planning evaluations than a single deterministic fit. Claim comparative quality on a common admissible pool, not an end-to-end runtime advantage or full-route optimum of either method.

7. **Conditional-cost bootstrap removes dates prematurely.** `summarize.py:30–33` constructs only jointly feasible rows before block resampling, so a “14-day” block is actually fourteen successful observations and can bridge deleted calendar dates. The fixed mean savings are correct. Recomputing by resampling all 365 calendar dates first, then conditioning within each replicate, yields the following no-BESS intervals: mean **[33.15, 105.08]**, SAA11 **[156.50, 220.19]**, SAA29 **[156.32, 237.57]**, SAA47 **[202.40, 264.17]**. The finding survives, but future summaries should preserve calendar positions. Use failure/shortage outcomes over all days, and cost supports explicitly. These development-year intervals do not repair selection bias or establish rare-event reliability.

8. **Source provenance is adequate to audit now, weaker than an immutable full release.** All current gate code hashes equal saved identities, all audited source pool/MIP hashes match, and calling the inherited `w.identity` verifies its complete release manifest now. Wave-15 oracle/causal identities themselves hash their entry point and dispatch dependency but do not bind all worker, reference, weather, case-list and protocol files or verify the inherited manifest at evaluation start. A hash chain certifies internal consistency, not independent authenticity or historical absence of edits. New campaigns should hash the entire dependency/input closure and immutable configuration. Also, `prepare_cases.py` currently regenerates only 36 original oracle cases; the final saved list contains 48 including 2023. Preserve the saved cases rather than assuming that script alone reproduces the full campaign registration.

## Highest-value next bounded run

Run the **24-case matched capacity sensitivity** already drafted in `capacity_gate_wave16`: policies 10/11/14/17 × Nb {0,1,2,5,10,20}, common 2022 days, 0.8 generation cap, unchanged fleets/tasks/profiles/skeletons, BESS empty-to-empty. Compare fixed and adaptive perfect-information LPs on identical assets. This locates how rapidly stationary capacity reduces the *conditional oracle opportunity* without paying for new route optimization.

Use the existing no-BESS source policy directories and their pooled profiles, immutable inherited worker/reference/weather files, and the audited oracle formulation with asserted lossless/infinite-cap/zero-degradation scope. Preserve all 24 results and their failed-day severity. Nb=0 should reproduce wave 15; increasing Nb cannot worsen each minimum-shortage optimum, and cannot worsen its operating cost when shortage optima tie. Total cost need not be monotone because BESS is charged at 36/day per unit. The difference between two nested optima also need not be monotone; do not enforce monotone adaptive gain as a validation rule.

The screen holds the original, relatively large 15/16-truck fleets. It cannot locate a globally optimal investment or market price frontier because a new investment model would also reoptimize fleet, routes, initial energy and admissible policies. A price sweep applied only to these fixed assets adds linear accounting; it is not a new investment solution. A negative result should narrow the next regime, not automatically terminate causal adaptivity or additional-duty research. If a material gap remains at modest stationary capacity, the next gate after this one should be an implementable adaptive-energy controller versus an equally informed deterministic MPC, with a tiny explicit nonanticipativity/feasibility witness before adaptive pricing.

## Short pre-launch review of `capacity_gate_wave16`

Reviewed `run_capacity.py`, `PROTOCOL.md`, `manifest.json` and `run.sbatch` at execution commit `caecc0af3568fb63ba8a5e09052abdd4e555b419`. Verified all **34 manifest file hashes** and the case-list hash locally; imported reference paths resolve through the release symlink to the hashed root reference files. All **24 setup calls** passed assertions and correctly override Nb, capacity/rate and empty initial state independent of the source arm's `battery=False` flag.

No blocking defect found in the requested scientific scope, paired asset treatment or normal interrupted-run resume path. The worker binds serialized skeletons and manifest hash in its identity, validates journal sequences/digests and allows a stale status to lag a durably appended journal record. The first three and every 90th day run pinned witnesses; the inherited LP checks relaxation dominance per day. It deliberately does not introduce causal or procurement claims.

The submitted script requests default partition, one CPU, 2 GiB, 20 minutes, nice 1000, reserved-GPU exclusion, requeue and a 120-second warning with worker signal forwarding. **The launch command must supply `--array=0-23%4`**, since the four-way cap is not specified inside the script. **Unset `CAPACITY_EXTRA_ARGS` for the main run** so a smoke `--max-days` argument cannot silently truncate every task. Those were communicated before launch. The parent owns scheduler access, the cluster smoke/main decision and deployment-state verification.

For later validation, compare Nb=0 daywise with original results, test per-policy capacity nesting using operating cost only when shortages tie, verify all source/identity/journal digests, and resample calendar-day blocks before conditioning cost. Solver residual checks and pinned witnesses are useful, but the saved aggregate LP results do not contain full adaptive action vectors for a separate after-the-fact trajectory replay.

## Reusable completion validator

`gate_audit/validate_capacity.py` validates a downloaded wave-16 campaign without running a solver or modifying campaign artifacts. Invoke it with `--campaign <downloaded campaign directory> --output <new validation directory>`; `--root` defaults to this research root, and `--wave15` can override the archived comparison directory. It writes `RESULTS.md` and `validation.json` separately from the campaign.

Checks include source closure and case registration, identity/source and serialized-profile correspondence, pinned state replay, date/hash/status consistency, reported summary recomputation, pinned LP records and fixed/adaptive dominance, Nb=0 daywise reproduction for all comparable fields, and within-policy adjacent-capacity shortage/operating-cost nesting. Cost comparisons require tied minimum shortage. Paired intervals preserve the full calendar and condition within each bootstrap replicate. Missing cases or partial journals are explicitly `incomplete`; invalid evidence is `invalid` (exit 2); only all 24 completed and checked cases receive `validated_complete`.

The empty registered campaign was checked and correctly reported incomplete 0/24 without a scientific claim. The statistic helper independently reproduced archived SAA11's 359-day conditional support, six fixed failures, zero adaptive failures, 185.7283/day mean saving and corrected calendar-block interval [156.5019, 220.1911]. Completed wave-16 claims remain contingent on downloaded completed outputs and this validation.
