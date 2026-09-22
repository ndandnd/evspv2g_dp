# Independent assessment: stochastic extension of EVSP–V2G

Fable, 16 September 2026. Read in this order: submitted manuscript (private manuscript, not exported), reference code at `f69f055` (`instance.py`, `master.py`, `pricing_truck.py`, `colgen.py`), the campaign worker (`campaign_code/worker.py`), the causal controllers (`*_wave1x/dispatch_core.py`), all validated snapshot reports, `REVIEW.md`, `CLOSEST_PAPERS.md`, the Najafi 2025 text, and the fair-policy result JSON. Judgments below are mine; where they differ from `REVIEW.md` or `CATCH_UP.md` I say so.

## 1. Bottom line

The deterministic paper is sound and already contains the hook for the extension: Proposition 2 (fixed skeleton → network-flow energy LP) and Section 8.8 (commit routes, truck profiles and BESS count; redispatch BESS and generation). The stochastic campaign so far has re-implemented exactly the Section 8.8 commitment structure with sample-average training instead of a planning profile, on one 20-trip instance, and then spent most of its effort tuning the stationary-battery dispatch controller. That work is carefully validated but is not yet a publishable contribution: two-stage planning with common vehicle decisions and scenario PV exists (Najafi 2025, Yetkin 2024, Baldua 2025), the 7% saving is the textbook value of the stochastic solution measured against the weakest deterministic baseline, and battery reserve rules are generic microgrid MPC.

The defensible, moderate-effort contribution is the one the paper itself promised in its conclusion: **truck charging and discharging that adapt intraday as weather is observed**, priced exactly inside the existing column-generation DP. Section 5 gives a formulation in which the pricing DP decomposes at the observation time, so the extension costs about K deterministic pricing sweeps per column and keeps the paper's discretization-exactness result. A two-day gate experiment (Section 6, R1) will tell you whether adaptivity is worth anything on this instance before any implementation.

## 2. What the paper establishes (and two things to fix in it)

Established: route-covering master coupled to an islanded power balance; aggregate BESS block (Prop. 1); fixed-skeleton energy scheduling as a network-flow LP (Prop. 2); label-setting DP over (t, ℓ, SoC, k) with exact discretization when η = 0 and data are on the lattice (Cor. 1); LP relaxations solved to 1,050 tasks; final MIP over the generated pool with reported gaps; BESS provides most of the joint value; V2G value depends on γ, charger premium, boundary condition. Section 8.8 is already a two-stage planning study with perfect-information continuous recourse, correctly described as such.

Two manuscript-level issues surfaced by the campaign audits and worth fixing at the next opportunity:

1. **Weather provenance.** Table 7 and Section 8.6 cite ERA5 (Hersbach et al. 2020). The training-data audit reproduced all 8,760 values of `solar_days_2023.csv` from the Open-Meteo historical archive with default Best Match at fixed UTC−7, and an explicit ERA5 query did not reproduce them (max discrepancy 148 W/m²). The honest label is "Open-Meteo historical archive, Best Match reanalysis blend, hourly mean over the preceding hour, fixed UTC−7".
2. **Related work.** Najafi et al. (2025, TRD 141) and Baldua et al. (2025) are absent. Najafi has endogenous bus duties, common charging decisions, storage sizing and scenario PV; its Table 1 row would read Y/N(stationary only)/Y/Y/N(grid-connected)/Y. A referee who knows it will ask. Also verify the "20 MWh/day demand" sentence in Section 8.1: the reference base curve used by the campaign integrates to 279 units = 27.9 MWh/day with peak/mean 2.41.

## 3. What the stochastic campaign has established

All results below are on the 20-trip, 2-location synthetic instance at 2× PV, generation capped at 0.8 × peak base demand (11.2 units per half-hour), depot-only charging, trucks full-to-full, BESS cyclic with a shared initial state. Training days sampled from 2023, evaluation on 2022 (development) or 2024–25 (frozen once, now seen).

| Result | My reading |
|---|---|
| Common-profile SAA master + aggregated-dual pricing implemented and checked (single-scenario equivalence, RC reconstruction, replay, strict reconstruction fix). | Correct and reusable. The pricing derivation (sum raw scenario duals) is right and is the structural hook for everything below. |
| SAA24 vs annual-mean plan on matched pools, V2G+BESS: 3,163 vs 3,413/day causal, 3,095 vs 3,342 oracle; 0 vs 0 failures. | Real, but it is the value of the stochastic solution against the *mean-day* plan. Jensen's inequality only says the mean-day objective underestimates expected cost (the recourse value is convex in Δ); whether that undersizes storage is empirical. Per the BESS briefing SAA buys 20 units vs 18. It has not been compared to the paper's own training-selected monthly profile or any conservative deterministic day. Not yet a claim about stochastic optimization; see R3. |
| SAA24 vs mean, V2G/no BESS at cap 0.8: 6–9 vs 100 failed days. | The strongest stochastic signal in the record. Logical: with no BESS the trucks are the only storage and their profiles cannot adapt, so the plan must be right ex ante. This is exactly the arm where adaptive charging should matter most. |
| 24 → 64 scenarios: no consistent change. Minimax: 2× cost, not uniformly more reliable under causal dispatch. Reduction 24→8: loses feasibility on omitted days. | Sensible; method comparison is done. Stop. |
| Causal BESS dispatch with annual climatology: 14–38 failed days where the oracle had zero; monthly + current-solar forecast: 0–3. Reserve rules: zero failures at +29–34% cost (5 units) or +160–180% (20 units); bounded 0.25–0.5 reserves cheaper. | Useful as an evaluation harness. Scientifically it is MPC of one aggregate battery against a fixed load, with the trucks contributing nothing but that load. Not a contribution of this paper; see R4. |
| 2024/2025 frozen holdout: V2G+BESS SAA 0 and 1 failed days. Deterministic comparator unmatched. | Encouraging; now consumed as test data for anything selected afterwards. |
| Algorithm: sparse scenario templates 1.1–1.3× CG speedup; pool union improves the 120-trip case 2.25% to within 0.27% of the LP bound; persistence mixed. | Good engineering; B&P correctly deferred. |
| Public code: Parmentier resource component compiled; Baldua/Terada/Ricard inspected. | Fine. Nothing here changes the research question. |

## 4. What is missing, and where I disagree with the current framing

1. **Nothing adaptive has been done on the vehicle side.** Every campaign fixes complete truck energy profiles before the day; only BESS and generation adapt. That is Section 8.8 with a different training objective. The user's three interests (adaptive operational decisions, storage, extra duties) all require truck-side recourse.
2. **The baseline is too weak to support a stochastic-optimization claim.** Compare against (a) the paper's training-selected monthly profile, (b) a conservative quantile day, (c) mean plan with Nb forced to the SAA value. If (c) recovers most of the 7%, the finding is "size storage for bad days", not a modeling contribution.
3. **Scale.** All stochastic evidence is at 20 trips and one site. The companion to a paper solving 1,050 tasks cannot stop at 20. With the sparse templates the SAA master at 120 trips and 24 scenarios is small (hundreds of columns, a few thousand continuous variables), and pricing cost is unchanged. There is no computational reason this has not been run.
4. **The reliability results are a function of the generation cap and the aggregate-BESS controller, not of scheduling.** At uncapped generation the six-trip pilot found 0.06–0.65% savings with intervals containing zero. Any paper must say up front that the cap is what makes the problem interesting and vary it (uncapped, 1.0, 0.8).
5. **Novelty as currently framed is not defensible.** "SAA over PV scenarios with common bus duties and storage sizing" is in Najafi 2025; "second-stage bus charging response" is in Yetkin 2024; "shared BESS boundary energy and seasonal scenarios" is in Baldua 2025. `REVIEW.md` reaches the same conclusion and then narrows the question to "mobile vs stationary storage under uncertainty". I agree with the narrowing but not with the means: on fixed profiles that question reduces to "how many more batteries does SAA buy", which is one number.
6. **The data-section draft is premature.** It is organized around the reserve-controller experiments, which I recommend freezing rather than featuring.

## 5. Recommended model: branching-time adaptive columns

> **Correction, 16 September (after `RESPONSE_AND_NEXT_STEPS.md`).** The pricing decomposition below is wrong as first written: independent per-class backward sweeps do not preserve a common task incidence, and collecting −α_i in every class counts the coverage reward K times. The Addendum at the end gives two corrected variants (A: common skeleton with a K-dimensional SoC state; B: class-dependent post-τ routes with per-class coverage rows) and restates the exactness claim as a proposition to verify. Read this section for the information structure and master only.

This is a strict generalization of the paper's model (K = 1) and of the current SAA (τ > T). It is the tractable version of the user's station-arrival idea.

**Information.** Choose an observation time τ (e.g. 10:00). Partition the sampled days Ω into K classes C_1..C_K by an observable statistic of the morning, e.g. cumulative irradiance over [sunrise, τ), with thresholds fixed on training data. Decisions on blocks t < τ are common to all days; decisions on t ≥ τ are common within a class. This is nonanticipative by construction and implementable: at τ the operator computes the statistic, picks the class, and applies that class's schedule.

**Column.** r = (a_r, e_r^0, e_r^1, …, e_r^K): task incidence (common across classes in the first version), a pre-τ profile and K post-τ profiles. Cost c_r = c_v + σ(‖e^0‖₁ + Σ_k p_k ‖e^k‖₁) with p_k = Σ_{ω∈C_k} p_ω.

**Master.** Coverage as before. For each sampled day ω with class k(ω): balance g_ωt − Σ_r e^{k(ω)}_{rt} x_r − c_ωt + d_ωt ≥ Δ_ωt (using e^0 for t < τ), charging cap with positive parts, BESS dynamics with the shared cyclic s⁰, objective Σ_ω p_ω(c_g Σ g + σ Σ(c+d)) + Σ c_r x_r + c_b N_b. This is the current `stochastic_master.py` with class-indexed truck coefficients after τ.

**Pricing decomposes.** With raw duals μ_ωt, ν_ωt (probability-weighted objective, summed not reweighted, as now): μ̄_t = Σ_ω μ_ωt for t < τ and μ̄_{k,t} = Σ_{ω∈C_k} μ_ωt for t ≥ τ. For each class k run one *backward* sweep of the paper's DAG on [τ, T] with arc costs μ̄_{k,t}·e + ν̄_{k,t}·e⁺ + p_k σ|q| and coverage rewards −α_i, giving cost-to-go V_k(t, ℓ, s, κ) for every state with t ≥ τ. Then run the paper's *forward* sweep on t < τ; any arc landing at a state (t′ ≥ τ, ℓ, s, κ) (including task or deadhead arcs that span τ, whose energy is deterministic anyway) terminates with value Σ_k V_k(t′, ℓ, s, κ). Reduced cost = c_v + forward cost + Σ_k V_k. Reconstruction gives e^0 from the forward path and e^k from each backward path. Cost: K + 1 sweeps instead of 1; pricing is a small share of time on the larger instances (Section 8.2).

**Exactness carries over.** For η = 0 and lattice data, the fixed-skeleton continuous problem is min over s_τ ∈ [0, G] of F_0(s_τ) + Σ_k p_k F_k(s_τ), where F_0 and F_k are parametric min-cost-flow values in the supply at τ. Each is convex piecewise-linear with breakpoints on the δ-lattice (integral network), so the sum has a lattice minimizer, and each lattice-restricted flow is totally unimodular. The DP optimum therefore equals the continuous optimum: Corollary 1 extends. Lemma 1 (no simultaneous charge and discharge) applies within each class unchanged.

**Extensions in the same framework.**
- *Several observation times* (a scenario tree): backward recursion over tree nodes, one sweep per node. Cost = number of nodes × one sweep.
- *Extra duties* (R5): let the class also carry an extra task set E_k revealed at τ; post-τ task incidence becomes class-dependent, a_{irk}, with coverage rows for i ∈ E_k only in class k. This is adaptive routing after τ and models "additional vehicle duties" with an explicit information time.
- *Value-of-information curve*: sweep τ from T + 1 (current SAA) toward sunrise; report E-cost(τ) alongside the full-reoptimization perfect-information cost (EVPI). The headline figure is "BESS units avoided by adaptive V2G as a function of forecast lead time".

## 6. Ranked recommendations with continue/abandon evidence

### R1. Gate experiment before any implementation (2–3 days; do first)

On the existing 20-trip instance, three arms (solar+BESS, V2G/noBESS, V2G+BESS), caps {uncapped, 1.0, 0.8}, 2022 days:

1. *EVPI*: solve the deterministic model day by day (365 CG+MIP runs, seconds each). Mean = perfect-information cost with everything adaptive.
2. *Fixed-skeleton adaptive-charging oracle*: take each SAA24 policy's routes (depot-only charging makes the skeleton the task sequence plus depot parking), and per day solve the joint LP of Proposition 2 for all trucks plus BESS and generation. Mean = value of charging adaptivity with perfect information; the τ-model cannot beat this.
3. *Decomposition of the 7%*: re-solve the mean plan with `nb_fixed = 20` and the SAA plan with `nb_fixed = 18`; evaluate both.

Continue to R2 if the adaptive-charging oracle saves ≥ 3% of daily cost or removes most failures in at least one capped arm (expect V2G/noBESS). Abandon the adaptive direction if the gap between fixed-profile oracle and adaptive-charging oracle is < 1% in every arm: BESS absorbs the uncertainty and the honest finding is "size storage for bad days", which belongs in the existing paper's discussion, not a new paper.

### R2. Implement and test branching-time adaptive columns (3–5 weeks)

Pricing (K backward sweeps + forward sweep, reconstruction), master (class-indexed coefficients; `stochastic_master.py` already has the scenario template), class rule (terciles of morning irradiance on 2023), causal evaluation (frozen monthly + current-solar BESS controller; class chosen at τ). Experiments: 20/60/120 trips; 2× and 3× PV; caps {uncapped, 1.0, 0.8}; τ ∈ {none, 08:00, 10:00, 12:00}; K ∈ {2, 3}; three training seeds; paired 14-day block bootstrap as now; at least two more weather sites from the paper's five. Primary outcomes: expected cost, failed days, BESS units purchased, V2G energy, all versus τ.

Continue to a paper if: adaptive columns capture ≥ half of the adaptive-charging oracle gap at τ = 10:00, and the BESS count or V2G/BESS substitution shifts materially with τ. Abandon if the master becomes the bottleneck at 120 trips × 24 scenarios × K = 3 (then Benders on the continuous recourse is the engineering fix, and only then).

### R3. Harden the baseline (1–2 days; run with R1)

Same pool, same MIP budget: training-selected monthly profile (the paper's method), 20th/50th-percentile solar days of 2023, mean plan with Nb from SAA. Report VSS against the best of these. Continue treating SAA as necessary if it still beats the best deterministic heuristic by ≥ 2% at matched reliability. Otherwise state plainly that a conservative planning day suffices for the fixed-profile structure, and let R2 carry the novelty.

### R4. Freeze the BESS controller; stop the reserve sweeps

Fix one controller for all evaluation: monthly climatology + current-solar update, bounded reserve 0.25 at empty start (or half-full boundary), lexicographic shortage-then-cost. Document it in one paragraph as the evaluation harness. Revive only if R2 results are visibly controller-limited (oracle zero failures, causal many, across τ).

### R5. Extra duties: defer, but design now

Use the R2 tree with class-dependent post-τ task sets and a first-stage readiness reserve. Needs a stylized duty model (e.g. with probability p a set of m extra timed tasks appears at τ, drawn from the paper's generator). Do not start until R2 shows that post-τ adaptivity has value; otherwise a reserve-truck count is the whole answer and can be stated analytically.

### R6. Manuscript hygiene (hours)

Correct the weather label; add Najafi and Baldua to Table 1; verify the 20 MWh sentence. Independent of everything else.

### R7. Do not start now

Full branch-and-price, RL, Wasserstein DRO, chance constraints, uncertain prices/travel times/traction energy. The existing gates in `BRANCH_PRICE_DECISION.md` and `CAMPAIGN_PLAN.md` are right. Ricard et al. (2026) cover stochastic traction energy with the same coauthor; coordinate before touching it.

## 7. Effort and stopping rules at a glance

| Step | Effort | Continue if | Stop if |
|---|---|---|---|
| R1 gate | 2–3 days compute + scripting | adaptive-charging oracle ≥ 3% or removes capped failures | gap < 1% everywhere |
| R3 baselines | 1–2 days | SAA ≥ 2% over best deterministic day | deterministic day within 1% |
| R2 adaptive columns | 3–5 weeks | captures ≥ ½ of oracle gap; shifts BESS/V2G split | master intractable at scale, or gains only at τ near sunrise |
| R4 controller freeze | 1 day | always | never |
| R5 extra duties | 3–4 weeks after R2 | R2 positive | R2 negative |
| R6 hygiene | hours | always | never |

## 8. Paper framing if R1 and R2 succeed

Title direction: adaptive vehicle-to-grid under uncertain solar in an isolated microgrid. Contributions: (i) a two-stage (or small-tree) column model where truck charging adapts at an observation time, with mandatory duties committed; (ii) exact pricing by a decomposing label-setting DP with the paper's discretization exactness extended; (iii) an operational finding: the value of intraday information and how much stationary storage adaptive mobile storage displaces, across generation-cap regimes and sites. This is a companion to the submitted paper, not a repeat of it, and it is distinct from Najafi, Yetkin and Baldua on the information structure and the pricing algorithm.

## Addendum, 16 September 2026: corrected pricing and agreed gates

Written after reading `RESPONSE_AND_NEXT_STEPS.md`. Its four corrections to Section 5 are accepted. Two consistent models replace the flawed sketch; both keep the information structure, master and class rule of Section 5.

### Model A: common skeleton, class-adaptive energy (the user's "keep trips committed, adapt charging")

- Task incidence and the whole route skeleton (task sequence, deadheads, parking windows) are common to all classes. Only charge and discharge amounts after τ depend on the class. Coverage rows are unchanged; −α_i is collected once, on the common task arc.
- DP state for t < τ: (t, ℓ, s, κ) as in the paper. For t ≥ τ: (t, ℓ, s_1, …, s_K, κ), one SoC per class, common location and history. Crossing τ maps s to (s, …, s).
- Wait, deadhead and task arcs shift every s_k by the same deterministic amount. Charge/discharge arcs at a station choose e_k per class; the transition cost Σ_k [μ̄_{k,t} e_k + ν̄_{k,t} e_k⁺ + p_k σ |e_k|] is separable, so the min-plus update over the K-dimensional SoC array is K sequential one-dimensional relaxations, each O(ns^K (u⁺ + u⁻)).
- Cost is exponential in K: at δ = 25 kWh, K = 2 gives 841 SoC pairs (trivial), K = 3 gives 24,389 (feasible, vectorized), K = 4 is out. Coarser δ after τ is an option since Corollary 1's lattice condition is per class.
- Exactness (proposition, not yet proved): for a fixed skeleton and η = 0, the continuous problem is min over s_τ ∈ [0, G] of F_0(s_τ) + Σ_k F_k(s_τ), each term a parametric min-cost-flow value in a single supply, hence convex piecewise-linear with breakpoints on the δ-lattice for integral data; the sum has a lattice minimizer and each lattice-restricted flow is totally unimodular. Because the skeleton family is finite, min over skeletons preserves lattice attainment. Verify on the tiny enumerated example before claiming it.

### Model B: class-adaptive routes and energy after τ (the extra-duty model)

- Column (a⁰, {a^k}, e⁰, {e^k}): a⁰ covers tasks starting before τ (tasks in progress at τ count as pre-τ), a^k covers tasks starting at or after τ in class k.
- Master coverage: Σ_r a⁰_ir x_r = 1 for pre-τ tasks; Σ_r a^k_ir x_r = 1 for every post-τ task and every class k. Duals α_i and α_ik.
- Pricing: K backward sweeps on [τ, T] with class-k rewards −α_ik and class-k energy prices; one forward sweep on t < τ with rewards −α_i; join at the first state with t ≥ τ with value Σ_k V_k. No double counting, because each class satisfies its own coverage rows. K + 1 sweeps is correct for this model, not for Model A.
- The "served at least one task" flag: a truck with κ = 0 at τ must serve a task in every class; or drop the requirement when BESS is purchasable (Section 7.2 of the paper shows storage-only trucks are then weakly dominated).
- Exactness: the same convex piecewise-linear argument applies for each fixed tuple of skeletons, and the minimum over the finite family is attained on the lattice. Also a proposition to verify.

Use Model A first (K = 2 or 3); Model B is the route to additional duties and should wait for the gate.

### Nonanticipativity of BESS and generation

Agreed on labeling. For the primary comparison keep full-day BESS/generation recourse in training exactly as the existing SAA does, so the only difference between SAA and the τ-model is truck adaptivity; call it a two-stage planning approximation evaluated causally. Add as a sensitivity a node-indexed variant: BESS decisions common before τ and common within class after τ, generation per day as the physical balancing slack with an explicit shortage variable. It has fewer variables, not more. Fully causal training is a multistage problem that both variants approximate from opposite sides.

### Gate interpretation

Agreed. The decisive gate is Astra's priority 1: fixed truck count, BESS count, initial energy, terminal rule, cap and tasks; fixed skeletons; daily perfect-information charging LP versus fixed profiles; compare shortages as well as cost. Full daily reoptimization is a wait-and-see envelope only. Add an intermediate reference with assets fixed but routes and charging reoptimized per day, which separates route adaptivity from charging adaptivity. Run the V2G/no-BESS arm at caps 1.0 and 0.8 first: it is where adaptivity should matter most and BESS cannot mask it. The Jensen sentence in Section 3 is corrected above; the storage-sizing direction is settled by the `nb_fixed` control, not by theory.

### Agreed batch

Astra's ranked batch (fixed-skeleton oracle; deterministic baselines with matched capacity; implementable policy versus rolling-horizon control; tiny exact branching example with reduced-cost checks; scale and sites) is the plan. Priority 4 should test Model A directly: enumerate all policies on a two-truck, few-task, K = 2 instance, compare the K-dimensional DP's reduced cost to the extensive-form LP reduced cost, and check single-class recovery of the paper's DP.

## Addendum, 19 September 2026: gate results

The R1 gate and the R3 baselines were run on [site identifier omitted] on 17–19 September (jobs 394397, 394405, 394407; causal follow-up 585521). Full tables in `snapshots/gate_wave15_validation/RESULTS.md`; code in `gate_wave15/`.

- Adaptive charging on fixed skeletons (perfect information) is worth 0.00–0.05% of daily cost in both BESS arms at every cap. It is worth 3.7–4.8% and removes every failed day in the no-BESS arm, and turns the mean-day plan there from 100 failed days into zero. The no-BESS fleet still costs about 50% more per day than fleet plus BESS.
- Against the submitted paper's own training-selected monthly planning profile, common-profile SAA is within ±0.3% in both BESS arms. The 7% figure reported against the annual-mean plan does not survive a competent deterministic baseline.
- Matched-capacity controls: SAA keeps roughly three quarters or more of its gain over the annual-mean plan when forced to that plan's storage count, so the gain is in the truck profiles and initial state, not in buying more batteries. Forcing more storage on the mean plan helps in one arm and hurts in the other.
- Quantile-day plans are not conservative plans; a dark planning day buys no storage.

Decision: R2 (adaptive columns) is justified only for the regime without cheap stationary storage. Before implementing pricing, run a BESS price and capacity sweep with both oracles to locate the substitution frontier; if adaptive V2G never displaces stationary storage at plausible prices, the honest paper is a short negative result and the effort should stop.
