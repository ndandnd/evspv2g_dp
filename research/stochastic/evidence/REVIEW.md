Update, 21 September 2026: [new literature evidence](literature_refresh_20260921/REVIEW.md) and [current research briefing](research_refresh_20260921/BRIEFING.md) supersede the earlier status and next-step narrative where they differ. Original formulation/source notes below are retained for provenance.

# Stochastic extensions of EVSP–V2G

The current priority is **weather-aware commitment of mandatory truck duties, complete truck energy profiles and integer stationary storage, followed by continuous BESS/fossil dispatch in an isolated microgrid**. Retain validated root column generation and the finite-pool MIP while completing the current 64-scenario validation. Full branch-and-price should follow evidence that missing columns or unresolved global gaps affect the scientific conclusions; first test bounded diving and selective model reuse.

The **12 September literature audit identifies Najafi et al. (2025) as the strongest newly found structural overlap**: it already combines endogenous bus duties, common charging decisions, storage sizing and uncertain PV. Generic integrated scheduling, renewable uncertainty, SAA or shared initial BESS energy are not independent novelty claims. The narrower research question is how mandatory precommitted mobile-energy duties and integer stationary storage substitute for or complement one another under common weather, local generation scarcity and operational information. Najafi's audited discharge equations concern stationary BES, but introductory wording also mentions bus discharge; verify the exact V2G distinction before claiming its absence. [^24]

The six-trip pilot below is **historical evidence from 10 September**, not the latest campaign result. The [latest validated matched-control report](snapshots/fair_policy_validation/RESULTS.md) finds 7.0–7.3% SAA savings for V2G+BESS with the frozen current-solar controller against the same-pool deterministic plan, with all 365 development days feasible for both. This is 2022 development evidence across three training seeds, not a population reliability guarantee or a full-route integer proof. The [separate frozen 2024/2025 holdout](snapshots/holdout_validation/RESULTS.md) retains its original scope. Current execution and validation gates are in [CAMPAIGN_PLAN.md](CAMPAIGN_PLAN.md).

This review concerns the submitted *Electric Vehicle Scheduling and Vehicle-to-Grid Integration in Microgrids*, local file “evspv2g_revision (9).pdf,” and [GitHub commit f69f055](https://github.com/ndandnd/evspv2g_dp/tree/f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0). The initial review dates from 10 September 2026; the closest-paper, software and algorithm assessment was updated on 12 September. This is a targeted review, not an exhaustive priority certification. Preview-only sources are identified. EVSP–DR is outside the experimental scope.

Audit records: [closest papers](literature_update_20260912/CLOSEST_PAPERS.md), [Léa Ricard code/data verification](literature_update_20260912/LEA_CODE.md), branch-and-price decision (original research artifact `literature_update_20260912/BRANCH_PRICE_DECISION.md`; not included in this export), and Google Docs briefing tab (private document link omitted).

The subsequent [algorithm/code audit](code_review_20260912/README.md) adds [Parmentier, Martinelli and Vidal's scalable EVSP column-generation paper](https://arxiv.org/abs/2104.03823) and its [MIT C++/CPLEX implementation](https://github.com/axelparmentier/ElectricalVSP-ColumnGeneration/tree/a13f33ddc3d00aa1fb52ff323a47eac5d521d8e7). This is a useful source for resource dominance, forward/backward pricing bounds, stabilization and diving; charge-only deterministic resources require rederivation for coupled weather/BESS/V2G. As of 13 September, the standalone MIT energy-resource component has been compiled and exercised on [site identifier omitted]; the full CG/branch-and-price solver remains unreproduced and no code is integrated. See [actual software use and test limits](public_code_checks/RESULTS.md). Whitaker's receding-horizon charging code remains unverified. The audit also compares current DR branches, executes pricing/status witnesses, and measures coefficient-identical scenario-template reuse. No production solver or running campaign was changed.

## 1. Submitted formulation and existing uncertainty work

The submitted model serves every timed task exactly once. Each truck column contains its task sequence and fixed charging/discharging profile. The implementation uses an aggregate continuous stationary-battery block with an integer unit count. Fossil generation is explicit. The model has a **systemwide charging-energy limit**, not a demonstrated station-by-time plug-capacity model. Modeled charging locations share one electrical node. These details matter when transferring methods from grid-connected transit models. [^1][^2]

The general column formulation is

\[
\min_{x,g}\sum_r c_rx_r+c_g\sum_tg_t,\qquad Ax=\mathbf1,
\]
\[
g_t-\sum_{r,h}e_{rht}x_r\ge D_t-P_t,\qquad
\sum_{r,h}e^+_{rht}x_r\le\kappa_t,\qquad
0\le g_t\le\bar g_t,\quad x\in\mathbb Z_+.
\]

Positive \(e\) means grid draw; negative \(e\) means discharge. Excess absorption/curtailment is permitted. The balance dual is an **endogenous marginal energy value**, not a stochastic market price. The battery aggregation requires identical units with linear dynamics and compatible boundary conditions. [^1] (pp. 6–12)

| Existing experiment | Before observation | Allowed adaptation | Correct interpretation |
|---|---|---|---|
| Section 8.6 daily weather solves | No common schedule across days | All optimized decisions | Daily perfect-foresight comparison |
| Sections 8.7/B.8 fixed-portfolio outage studies | Asset counts | Operational redispatch within that portfolio | Conditional feasibility; no outage probabilities |
| Sections 8.8/B.9 planning-profile study | Routes, truck charging, BESS count | BESS and generation dispatch | Committed schedule with whole-day operational foresight |

Section 8.8 selects planning profiles using 2023 and evaluates selected plans on 2022. Reported 2022 gaps to daily perfect-foresight incumbents are 5.8% at 2× PV and 11.4% at 3× PV; gaps to their LP bounds are 6.5% and 12.7%. These compare different information/commitment structures, so they are **not values of a stochastic solution**. Both years already informed the submitted study; a new extension needs untouched evaluation data. [^1] (pp. 31–32, 42)

The reference implementation confirms the fixed-profile structure in [master.py](https://github.com/ndandnd/evspv2g_dp/blob/f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0/master.py), [colgen.py](https://github.com/ndandnd/evspv2g_dp/blob/f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0/colgen.py) and [pricing_truck.py](https://github.com/ndandnd/evspv2g_dp/blob/f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0/pricing_truck.py). The truck option “cyclic” starts and finishes full; “periodic” permits a chosen repeated level. The stationary cyclic block permits a chosen initial level. Option names alone are insufficient to establish information consistency. [^2]

## 2. Uncertainty and observation times

Start with **solar trajectories only**, preserving the common trip set, travel times and traction requirements. Add base-load uncertainty after that experiment is understood.

| Random input | Information timing | Decisions before observation | Possible recourse | Main feasibility consequence |
|---|---|---|---|---|
| PV / base load | Forecast before day; realizations progressively observed | Assets, duties, possibly truck energy plans | Generation, BESS; later adaptive truck charging | Balance, fossil/fuel limits, charging availability |
| Electricity prices | Day-ahead settlement or real-time releases, market dependent | Routes/assets; purchases/bids if introduced | Charging/trades after relevant release | Usually costs; additional market obligations may constrain feasibility |
| DR activation | Specified notification time, potentially after bidding | Accepted availability/capacity obligations | Deliverable response and balancing | Response must coexist with transport and SoC readiness |
| Travel times | Updated traffic and realized arrival information | Assignments and dispatch commitments | Future dispatch, spare vehicles, revised connections | Compatibility, lateness and charging windows |
| Traction energy | Forecast before travel; realized consumption during/after trip | Route/energy reserves | Later charging and authorized recovery | SoC feasibility even with unchanged arrival times |

Electricity prices and DR calls are absent from the submitted isolated-grid baseline. Introducing them changes the application. Randomizing an optimization dual is not a substitute for specifying an uncertain physical or market input.

Write an information filtration \(\mathcal F_t\). If an action follows the current observation, require \(u_t\) to be \(\mathcal F_t\)-measurable; if it precedes that observation, use \(\mathcal F_{t-1}\). In a scenario tree, paths with the same observed history must share actions, including route, charging-location and reservation decisions when applicable.

Independent full-day scenario copies are a legitimate **two-stage planning approximation** when the complete trajectory is assumed revealed before recourse. They are a foresight relaxation of sequential operations, not an online controller. Initial BESS energy must be fixed or shared if chosen before weather is known. Scenario-specific cyclic initial energy can conceal advance knowledge.

A small analytical falsifier: an initially empty unit battery may buy energy at cost 1 before tomorrow’s weather. Tomorrow’s unit load receives either one free PV unit or none, each with probability 1/2; emergency generation costs 10. A causal policy buys one unit now, costing 1. A policy that sees tomorrow before buying spends only in the cloudy case, with expected cost 0.5. That improvement is information, not algorithm quality. This example is analytical and separate from the executed pilot.

## 3. Recommended mathematical extension

### Committed profiles with continuous recourse

Let \(x_r\) select a complete truck profile, \(N_b\) count stationary batteries, and \(s^0\) be common initial aggregate storage energy. First-stage commitments are

\[
z=(x,N_b,s^0),\quad Ax=\mathbf1,\quad
x\in\mathbb Z_+,\ N_b\in\mathbb Z_+,\ 0\le s^0\le GN_b.
\]

For a full-day scenario \(\omega\), define the LP

\[
Q(z,\omega)=\min\sum_t[c_gg_t^\omega+\sigma(c_t^\omega+d_t^\omega)]
\]

subject to

\[
g_t^\omega-\sum_{r,h}e_{rht}x_r-c_t^\omega+d_t^\omega\ge\Delta_t^\omega,
\qquad \sum_{r,h}e^+_{rht}x_r+c_t^\omega\le\kappa_t,
\]
\[
s_{t+1}^\omega=s_t^\omega+(1-\eta)c_t^\omega-d_t^\omega,\quad
0\le s_t^\omega\le GN_b,\quad
0\le c_t^\omega,d_t^\omega\le\rho N_b,
\]
\[
0\le g_t^\omega\le\bar g_t,\qquad s_0^\omega=s_T^\omega=s^0.
\]

The stochastic optimization problem is

\[
\min_z\ a(z)+\mathbb E Q(z,\omega),\quad
a(z)=\sum_r[c_v+\sigma\sum_{h,t}|e_{rht}|]x_r+c_bN_b. \tag{S}
\]

Only BESS and generation adapt. Shared \(z\) enforces first-stage nonanticipativity. Conditional on \(z\), scenarios separate into LPs; the master still couples all routes. This is a proposed extension of the submitted model, not a quotation of a prior formulation.

Unlimited fossil generation can make weather-only feasibility trivial for a physically feasible committed truck plan. With finite generation/fuel limits, relatively complete recourse cannot be presumed. Reject infeasible designs, add valid feasibility cuts, or introduce a **separately reported emergency resource**. Power shortfall must never silently excuse an unserved transport task. Large finite penalties alone do not prove physical feasibility.

### Reusing the route-pricing DP

For an extensive-form LP, let \(\alpha_i\) be shared coverage duals and \(\mu_{\omega t},\nu_{\omega t}\) scenario balance/capacity duals. When these are raw duals from a probability-weighted objective,

\[
\bar c_r=c_r-\sum_i a_{ir}\alpha_i+
\sum_{h,t}e_{rht}\underbrace{\sum_\omega\mu_{\omega t}}_{\bar\mu_t}
+\sum_{h,t}e^+_{rht}\underbrace{\sum_\omega\nu_{\omega t}}_{\bar\nu_t}. \tag{P}
\]

Thus the existing DP can price a **common fixed-profile column at aggregated scenario dual prices**. Do not multiply raw weighted-objective duals by probabilities again. Normalized per-scenario duals instead need weights once. Every additional coupling row needs its reduced-cost term.

This derivation is the most useful low-effort structural opportunity: weather scenarios enlarge the master without necessarily enlarging the DP state. It is not yet a verified novelty claim. Check the formula against explicit matrix reduced costs and tiny exhaustive column sets. The manuscript reports the master as the main large-instance bottleneck, so faster pricing alone may not improve scaling. [^1] (Section 8.2)

### Richer recourse changes the algorithm

**Fixed skeleton, adaptive charging:** commit task sequence, deadheads and charging opportunities, then optimize scenario-specific truck/BESS flows. For skeleton \(r\), bounds such as \(0\le c_{rht}^\omega,d_{rht}^\omega\le\rho b_{rht}x_r\), scaled SoC bounds and withdrawals \(w_{rt}x_r\) give continuous conditional dispatch. However, shared energy/charging constraints couple the trucks. Generating new skeletons requires a multi-scenario pricing argument; the current Column object stores incidence/net energy rather than a complete reusable skeleton.

**Fleet first, routes second:** commit \((N_v,N_b)\), then choose integer \(x^\omega\), with \(Ax^\omega=\mathbf1\) and \(\sum_rx_r^\omega\le N_v\). Recourse is now integer scheduling. Standard LP Benders cuts alone do not represent its integer value.

**Sequential energy control:** fix duties and use a scenario tree or rolling-horizon controller. Decisions at shared histories agree. This is the natural operational validation of a two-stage design, but it requires forecast vintages or a defensible conditional model, not only realized weather.

## 4. Closest literature

Updated 12 September 2026. Missing code links mean “not verified,” not “does not exist.” Preview evidence can reject broad novelty claims without supporting a faithful reproduction. Application overlap and implementation usefulness are separate rankings; [the detailed audit](literature_update_20260912/CLOSEST_PAPERS.md) records commitments, recourse and access limits.

| Study and access | Model and algorithm | Implication | Code/data |
|---|---|---|---|
| **Najafi et al. (2025), institutional version-of-record PDF** [^24] | Common trip arcs/charging and continuous PV/BES sizes; scenario grid purchases and PV/BESS dispatch under three PV scenarios; GAMS/CPLEX Benders with binary BESS modes | Strongest structural overlap. Eq. 42 directly links common charging to scenario supply. Distinguish isolated-grid integer storage and complete truck energy profiles; do not assert “no V2G” without resolving the paper's wording. Initial BESS energy is a parameter. | Downloadable author implementation and complete runnable data not verified. |
| Terada et al. (2025), publisher preview and author code [^5] | Shared PV/BESS/thermal/charger capacities; scenario EV connections and outage operations; Pyomo/Gurobi MILP | Closest technology mix. Code uses given EV arrival/departure windows, not endogenous mandatory trip chains. Matching pre-outage SoC alone does not prove full control nonanticipativity. | Actual model and JSON inputs now found; setup discrepancies and missing linked LICENSE leave reuse licensing unresolved. Full journal formulation unavailable. |
| Yetkin et al. (2024), publisher full text [^3] | Wind uncertainty; common bus positioning and baseline actions; generator ramping versus extra bus charging/discharging recourse | Strong precedent for transit/grid cooperation and recourse comparison. Different service-duty and storage-procurement scope; scenario dispatch is not a verified causal controller. | Modified MATPOWER cases described; exact author implementation not verified. |
| **Baldua et al. (2025 preprint), full text and csp-res** [^4] | Continuous grid/BESS/PV sizing and shared initial/final BESS energy; scenario charging LP. Separate heuristic supplies scenario-dependent rotations/fleet counts. | Most useful public implementation reference for continuous planning/dispatch. Seasonal scenarios are not automatically i.i.d. daily SAA. Integer common duties and fixed truck profiles differ. | MIT Python/CPLEX source and Durham inputs; solver Benders annotations, not a portable cut-generation library. Driver explicitly forces LP. Inspected, not executed. |
| Son et al. (2025), publisher/author previews [^6] | Two-stage bus/V2G optimization with discharging-price and energy uncertainty | Rejects generic stochastic V2G novelty. Exact staging, integrality and detailed duty assignment remain unverified; do not infer their absence from the SSRN LP description. | Full formulation and code not verified. |
| Zheng, Cao & Liu (2024), publisher preview [^7] | Uncertain ESS discharge efficiency; bus fast/ESS charging; SAA with K-means/K-means++, greedy/genetic approaches | Direct SAA-plus-clustering precedent. Exact staging and weather/V2G comparability remain unverified. | Shanghai case; downloadable code/data not verified. |
| Tang, Lin & He (2019), publisher preview [^8] | Stochastic traffic; static buffer-distance strategy and dynamic rescheduling; branch-and-price | Robust/static-versus-dynamic bus scheduling is established; travel uncertainty is a larger extension. | Beijing case; code/data not verified. |
| Avishan et al. (2023), publisher preview [^9] | Fleet procurement, trips and charging under travel/energy uncertainty; budgeted RO and matheuristic; Monte Carlo evaluation | Robust fleet sizing/charging alone is not new. Physical service uncertainty differs from weather-only recourse. | Binghamton case; package not verified. |
| Ricard et al. (2026), publisher and full 2025 preprint [^10] | Integer schedule selection; fleetwide SoC-band chance constraint; stochastic-energy labels and exact dominance; diving branch-and-price heuristic | Closest stochastic EVSP pricing reference, with Andrea Lodi as coauthor. Independent schedule-event factorization needs reconsideration under common weather/shared BESS. Exact pricing does not make an incomplete tree exact. | Author-linked Apache-2.0 benchmark data/results verified: 24 tracked files, 15 trip sets, 390 result rows; no solver source in the inspected snapshot. Paper uses GENCOL 4.5/CPLEX 22.1. |
| Qi et al. (2025), full author preprints [^11] | Hierarchical RL charging under uncertainty; constrained extension includes PV, prices, travel and limited chargers | RL charging already requires substantial simulator/safety/baseline work. | No verified drop-in implementation. |

Najafi requires explicit manuscript positioning: compare trip decisions, bus discharge, asset integrality, equations 42/56 and observation timing equation by equation. The defensible hypothesis concerns **mandatory precommitted duties and the mobile-versus-stationary storage tradeoff under uncertain isolated-grid supply**. Establish it through matched technology and commitment experiments, with precise V2G differences; it is not a priority certification.

**Selective software reuse.** Ricard's repository supplies usable benchmark inputs and reported results, not an executable solver or chosen schedules; begin with one small trip set and map its physical assumptions separately. Baldua's pinned `csp-res` contains CPLEX requirements and compressed Durham inputs, making it the best candidate for a runnable reference after setup, but no author pipeline was run during this audit. Reuse only the capacity/shared-boundary and scenario constraint/partition pattern first: two fixed rotations, eight periods and two solar profiles, with extensive-form/decomposition objective and energy-balance checks. Keep our integer scheduling/storage layer. Terada's actual `linear_model.py` and JSON inputs support comparison, but the README filename/requirements/gap discrepancies and missing LICENSE need resolution before source reuse. [^4][^5][^10]

**Algorithm decision.** Retain root CG plus finite-pool MIP for the current weather study. Compare bounded diving/enrichment, the current MIP and a longer-MIP control on a fixed difficult/easy panel at equal total one-core budgets before committing to full branch-and-price. Report full-family LP bounds, pool bounds and incumbents separately, only for matching objectives/scenarios/formulations. A complete tree requires branch-compatible pricing, feasibility pricing and valid node bounds; this is a separate implementation project. See the bounded decision protocol (original research artifact `literature_update_20260912/BRANCH_PRICE_DECISION.md`; not included in this export).

## 5. Candidate methods and controlled tests

“Two-stage” specifies information/recourse, SAA specifies an approximation, clustering may change that approximation, and Benders specifies an algorithm. They can all be parts of one experiment.

| Candidate | Mathematical formulation and first-stage integers | Recourse / nonanticipativity | Structure, primary reference and implementation | Falsification experiment |
|---|---|---|---|---|
| **SAA** | (S) with \(N^{-1}\sum_jQ(z,\omega_j)\); integer \(x,N_b\), shared \(s^0\) | Scenario energy LPs; common z; whole-day reveal | Aggregate-price DP + scenario blocks; Kleywegt et al. [^12]; reference code + local finite-pool pilot | N=8,24,64, multiple training seeds; paired untouched-day comparison to annual/month-selected baselines |
| **Finite minimax / budgeted RO** | \(\min_z a(z)+\max_{\omega\in U}Q(z,\omega)\); integer \(x,N_b\). Budget set may use \(\Delta=\hat\Delta+d\odot u,\ |u_t|\le1,\sum|u_t|\le\Gamma\) | Adjustable continuous energy, shared z; sequential RO additionally restricts histories | Finite U epigraph MILP; continuous U requires adversarial separation; Bertsimas–Sim [^13], Zeng–Zhao [^14]. Pilot implements finite U only | Sweep conservatism at matched cost; reject if expensive protection brings no out-of-sample reliability benefit |
| **Wasserstein DRO** | \(\min_z a(z)+\sup_{P:W(P,\hat P_N)\le\varepsilon}E_PQ\); same integers | Same declared policy class and NA | Reformulations depend on support/recourse/growth assumptions; Esfahani–Kuhn [^15]; no EVSP-ready code verified | Tune radius on validation years; test shifted year/site; compare calibrated SAA/RO at equal effort |
| **Scenario reduction** | \(\min_z a(z)+\sum_{k=1}^K\tilde p_kQ(z,\tilde\omega_k)\); same integers | Same recourse; reduced trees must preserve information | Fewer scenario LPs, altered distribution; Heitsch–Römisch [^16], SCENRED [^17]; Zheng et al. [^7] | Against unreduced model and random K-sampling at equal total runtime; evaluate costs AND extremes |
| **Benders / L-shaped** | \(\min_z a(z)+\sum_jp_j\theta_j\), \(\theta_j\ge\pi_j^T(h_j-T_jz)\), plus feasibility cuts; integer x,Nb | Continuous scenario LPs; shared z | Valid LP-dual cuts; Van Slyke–Wets [^18], csp-res [^4]. A column-generating master must price active cuts too | Compare extensive form and decomposition at N=8,32,128 on same hardware/tolerances |
| **PH / scenario bundles** | Copies \(z_j=z\); scenario objectives plus multipliers and quadratic consensus penalty; integer copies xj,Nbj | Scenario/bundle recourse; common implementable commitments must be recovered | Parallel MIPs/LPs; integer consensus generally heuristic; Rockafellar–Wets [^19], Crainic et al. [^20], mpi-sppy [^21] | Compare single-scenario/bundled PH and extensive form at equal core-hours; report repaired feasible cost and valid bound separately |
| **Chance constraints / CVaR** | \(P\{\text{any failure}\}\le\alpha\), or \(\zeta+(1-\beta)^{-1}\sum_jp_j[L_j-\zeta]_+\); first-stage integer commitments; sampled chance models may add binaries | Same explicit recourse/NA; distinguish joint day/fleet from per-block risk | CVaR admits linear epigraph; Ricard et al. [^10] is a distinct SoC-risk precedent; standard CVaR reference [^23] | Correlated weather/energy shocks at equal cost; distinguish recommended SoC-band violations from breakdown |
| **Fixed-skeleton adaptive charging** | Integer skeleton selections/Nb; scenario flows bounded by selected skeletons | Coupled truck/BESS/generation LP; whole-day or tree-node NA | Submitted fixed-route flow structure [^1], recourse comparison [^3]; exporter/pricer still required | Identical skeletons/information: fixed versus adaptive energy; reject if BESS already absorbs nearly all uncertainty |
| **RL / constrained MDP** | \(\min_\pi E\sum_tc(s_t,a_t)\) with explicit physical/risk constraints; initially freeze optimized integer duties/assets | \(a_t=\pi(s_t)\), observed state/history only | Simulation/training then fast inference; Qi et al. [^11]; source implementation not verified | Same forecasts/actions against rolling-horizon LP/MPC; count training, deployment, repair and out-of-distribution failures |

“Cluster integer” is ambiguous. **Reduction** removes/reweights scenarios. **Bundling** retains scenarios and solves groups inside decomposition, potentially leaving the target unchanged. **Cluster-specific integer policies** restrict recourse to a decision per observed class. Using the completed day's weather to classify morning route choices leaks information. Aggregating vehicles/tasks is a fourth possibility requiring disaggregation and service-feasibility checks.

For reduction, preserve complete weather trajectories. Evaluate probability-distance representatives, medoids and operational features such as solar during parked intervals, evening deficit and cloudy-spell duration. K-means centroids may smooth extremes; silhouette scores do not validate decisions. Fit any operational weighting on training/validation data only.

## 6. Pricing meanings and certificates

Three algorithms must not be conflated:

1. **Common profiles with scenario-dependent marginal costs:** equation (P) applies; exact DP can certify absence of improving common columns.
2. **Adaptive routes/charging policies:** columns represent different objects; common-history actions must agree. One independent deterministic route solve per full weather day does not price causal policies.
3. **Random approximate search:** random dual perturbations, sampled routes or learned pricing may find improving columns. Failure to find one is not proof of absence.

The manuscript's deterministic certificate is explicit: exact pricing at current RMP duals over the admitted family, with reduced-cost tolerance \(\epsilon\), supports \(z_{RMP}-n\epsilon\), since every real truck serves at least one task. Physically feasible artificial-free integer incumbents are upper bounds. A restricted-pool MIP solver bound is **not** a full-route integer lower bound. [^1] (pp. 17–20)

For (S), the same correction can be derived under matching structural conditions, valid pricing for every omitted column, and dual feasibility of all other variables/cuts. A finite SAA bound is not automatically a population-expectation bound. A reduced-scenario optimum is not generally a lower bound for the unreduced problem.

The continuous-profile certificate additionally needs zero charging loss and lattice alignment of capacities, rates, travel withdrawals and boundary levels, with identical route skeleton families. Otherwise the bound concerns the discretized/augmented family. Random traction energy can break alignment. Negative market prices may break the no-simultaneous-charge/discharge proof and require additional modeling.

Store distinct labels: feasible incumbent; restricted-pool MIP bound; full-discrete-family LP bound; continuous-family LP bound; sample-problem bound; statistical bound. Approximate pricing needs a final exact pass or a valid global reduced-cost lower bound before claiming LP optimality. Timeouts, duplicate proposals and positive artificial penalties are not certificates.

## 7. Executed local pilot

**Historical — 10 September 2026.** This section preserves the initial screening evidence. Subsequent validated findings are in the [matched-control snapshot](snapshots/fair_policy_validation/RESULTS.md) and [frozen new-year holdout](snapshots/holdout_validation/RESULTS.md); the small pilot is not the current campaign conclusion.

This screening experiment uses six prescribed trips, 48 half-hour periods, reference geometry/costs, 2× PV, no generation/charging cap, zero loss and a 25-kWh SoC step. Every policy uses the same **67 feasible truck profiles**, generated from 2023 mean/darkest/brightest days. This is a finite-pool comparison, not fully priced stochastic CG. The pool uses all 2023 weather; N-sensitivity is conditional on that pool, not an entire learning pipeline given only N days.

Shared decisions are integer profile selections, BESS count and initial BESS energy. Truck profiles stay fixed; daily BESS/generation LPs see the full realized day and restore the common initial level. Training/selection uses 2023; evaluation uses all 365 days of 2022. PV normalization uses training data only. The pilot recorded an ERA5 label. A later [training-data provenance audit](weather_validation/training_audit_result.json) reproduced campaign weather as Open-Meteo default BestMatch with fixed UTC−7, rather than explicit ERA5. Retain the physical-clock/indexing caveat; these weather proxies are not measured site PV or archived forecasts. These years are disjoint for fitting/evaluation here but already used scientifically in the submitted paper.

The annual-mean plan and twelve monthly candidates share the pool. Monthly selection uses **2023 redispatch cost**, choosing April for this instance. SAA uses 8/24 distinct training days with seeds 11,29,47. Reduction selects eight actual trajectories from seed-11's 24-day sample by deterministic farthest-first selection and nearest-representative probability allocation; it is not K-means. Finite minimax uses the same 24 days, breaking minimax ties with expected training cost.

The original deterministic smoke test passed: 12 tasks, 64 columns, no artificial coverage, LP/MIP 1135.70. The prototype's single-scenario formulation agrees with the reference CBC MIP within \(2\times10^{-8}\); duplicated half-weight scenarios preserve its optimum. Constraint residuals are recorded. These establish basic consistency, not validation of every proposed extension.

| Policy | Mean 2022 cost ($/day) | Savings vs annual mean ($/day) | Paired 95% interval | 95th percentile cost ($/day) |
|---|---:|---:|---:|---:|
| Annual mean | 2,306.85 | +0.00 | [+0.00, +0.00] | 6,779.21 |
| Training-selected April | 2,303.59 | +3.26 | [-41.45, +45.04] | 6,707.21 |
| SAA N=8, seed 11 | 2,379.24 | -72.39 | [-146.60, +2.40] | 6,671.21 |
| SAA N=24, seed 11 | 2,302.30 | +4.55 | [-39.83, +46.65] | 6,707.21 |
| 24→8 representatives, seed 11 | 2,303.60 | +3.25 | [-41.47, +45.03] | 6,707.21 |
| Finite minimax, seed 11 | 6,085.97 | -3,779.12 | [-4179.00, -3323.92] | 7,562.34 |
| SAA N=8, seed 29 | 2,292.57 | +14.28 | [-1.74, +29.16] | 6,743.21 |
| SAA N=24, seed 29 | 2,305.41 | +1.44 | [-45.01, +44.52] | 6,707.21 |
| SAA N=8, seed 47 | 2,346.29 | -39.44 | [-118.27, +34.37] | 6,671.21 |
| SAA N=24, seed 47 | 2,291.87 | +14.98 | [-0.88, +29.80] | 6,743.21 |

Positive savings mean lower cost than the annual-mean plan. Intervals are 95% paired circular moving-block bootstrap intervals, 14-day blocks and 1,000 replicates, conditional on each fitted policy. These are descriptive approximations from one seasonal year, not distribution-free guarantees. Full results store every daily cost, mean-cost intervals, and 5th/50th/95th/99th cost percentiles. [^22]

!Paired savings and uncertainty intervals (original research artifact `pilot_results/paired_savings.png`; not included in this export)

Every policy is feasible on 365/365 days. This is not evidence of a reliability benefit: generation is unlimited and truck profiles are deterministically feasible. Under an iid Bernoulli interpretation, 0/365 failures would yield a two-sided 95% exact upper bound of approximately 1.01%; dependent weather does not justify that iid interpretation.

N=24 savings span $1.44–$14.98/day, about 0.06%–0.65%. Every SAA paired interval includes zero. The selected-month baseline is close, while small samples can worsen cost. Finite minimax is much more expensive on typical days; it targets worst sampled cost, not expected cost or a reliability threshold. This does not establish that calibrated RO is ineffective.

The final pilot, including monthly training evaluations and ten test policies, took **28.5 seconds** on macOS/arm64, Python 3.12.2, NumPy 2.5.3 and SciPy 1.18.1. Each MIP had a 45-second limit and relative gap tolerance \(10^{-6}\); all returned optimal status for the finite pool. Package versions differ from the manuscript environment and are recorded. No cluster jobs were submitted during the initial local review. [^22]

Subsequent cluster validation: [site identifier omitted] job **802556** completed successfully on scaglione-cpu-04, reproducing the deterministic LP/MIP objective 1135.70 without artificial coverage. Source hashes matched the pinned reference. This is an environment check, not the proposed stochastic campaign. See the validation record (original research artifact `cluster/README.md`; not included in this export).

## 8. Proposed experiment campaign and decision gates

**Historical proposal — 10 September 2026.** The budget, launch sequence and engineering estimates below document the initial plan, not current authorization or status. Follow [CAMPAIGN_PLAN.md](CAMPAIGN_PLAN.md) and [EXPERIMENT_REGISTER.md](EXPERIMENT_REGISTER.md) for the active 64-scenario validation and subsequent priorities.

A working question is: **Does weather-aware duty commitment change the mobile-versus-stationary storage tradeoff and protect service under limited local generation?** This gives the study a more defensible focus than comparing a list of algorithms.

**Gate 1 — formulation and deterministic checks.** Implement the full SAA master and aggregated-dual DP pricing. Require single-scenario equivalence, duplicated-scenario equivalence, reduced-cost reconstruction, tiny exhaustive-route agreement, artificial-free feasibility and common initial energy. Verify sample LP bounds separately from final integer quality. Avoid beginning with random-route instances whose deterministic integer gaps are already large.

**Gate 2 — bounded screening.** Use validated 20/60-task instances with corrected full-recharge windows, 2×/3× PV, and an uncapped plus a training-calibrated stressed generation cap. Freeze the physical cap across weather days; do not resize the generator to each realized peak. Compare annual-mean, training-selected-profile and SAA policies first. Add risk treatment only when shortfall is nontrivial.

Start with **24 training jobs**: 2 sizes × 2 PV levels × 2 cap regimes × 3 scenario seeds, one V2G+BESS arm at N=24, with matched deterministic baselines inside each job. Set one core-hour per job, at most four simultaneous jobs and a 24 core-hour ceiling. This is a proposed cap, not a runtime forecast. Account for solver threads and include diagnostics within each job budget.

If the screen passes, expand to the four technology arms, N=8/24/64, five scenario seeds and common trip seeds. Use symmetric common pools for incumbent comparisons and separately retain properly priced LP bounds. Do not preferentially enrich only the proposed method. Compare fixed-profile and fixed-skeleton recourse after establishing a signal. Profile the master before implementing decomposition.

**Gate 3 — untouched evaluation and causal operation.** Reserve an additional complete year before tuning method/risk/reduction parameters. Multiple temporally blocked years are preferable. Both 2022 and 2023 should now be development data. Weather repetitions do not create independent task instances. Report seasonal results, workload sensitivity and variability across training seeds.

For each frozen policy report total cost, fossil use, assets, cycling, median/upper cost quantiles, fraction of days with any energy shortfall, shortfall magnitude and transport violations. Report original infeasibility separately from emergency repair. Use paired trajectories; use dependence-aware intervals for historical weather or exact/binomial intervals for independent simulated episodes. Never drop infeasible days from mean-cost reporting without an explicit treatment.

Independent SAA replications with valid full-problem optimization lower bounds can support statistical lower-bound estimation under sampling assumptions. Independent evaluation estimates a frozen feasible policy's expected cost. Restricted-pool MIP bounds cannot substitute for unrestricted SAA lower bounds. Do not select a seed or method on test performance.

Evaluate the same assets/duties with whole-day dispatch and causal rolling-horizon LP/MPC using identical forecasts. Archive forecast issue times. If gains vanish under causal operation, report that they depend on foresight. Realized weather records alone cannot establish forecast-aware deployment performance.

**Gate 4 — novelty and stopping.** Updated 12 September: prioritize the Najafi equation audit and obtain the unresolved full Terada/Son formulations before a priority claim. Terada's author code is now located, with reuse licensing unresolved. The closest accessible implementation reference is csp-res; it is a seasonal continuous-planning LP with CPLEX Benders annotations, not an identical truck-assignment solver.

Predeclare a practical screen, for example 2% cost improvement at matched reliability or a meaningful shortfall reduction at matched cost. This is a proposed research decision threshold, not a publication rule. If gains remain smaller, BESS cheaply absorbs uncertainty, or improvement requires foresight, stop the generic SAA narrative. A negative result can guide the existing study without necessarily supporting a new paper.

Engineering estimate: several days for a checked extensive-form/aggregated-pricing prototype, roughly one to two weeks for bounded benchmarks and the data protocol, then several further weeks for analysis/writing if the signal survives. These are judgments, not promises. Integer recourse, adaptive skeleton pricing or RL would substantially increase work. No journal recommendation or acceptance claim follows from this review.

## 9. Shared evidence for EVSP–DR

| Finding | Evidence | Actionable transfer |
|---|---|---|
| Information structure comes first | Sections 2–3 | Separate DR bids, calls and prices from immutable service obligations |
| Shared fixed profiles allow summed scenario dual prices | Equation (P), derived here | Include every station/time and DR coupling row; verify reduced costs |
| Reduction differs from bundling | Section 5, [^16][^20] | Validate reduced distributions; retain original scenarios for pure decomposition |
| Approximate pricing cannot certify termination | Section 6, submitted Proposition 4 | Keep feasible incumbents and require exact pricing/global reduced-cost bounds for LP claims |
| Historical six-trip screening showed no clear SAA gain; later matched storage results differ | Section 7, [^22]; [latest matched controls](snapshots/fair_policy_validation/RESULTS.md) | Compare matched policies and preserve development/holdout scope; do not transfer V2G savings to DR |

These are methodological findings only. Experimental code, configurations and results remain separate from EVSP–DR.

## Sources

[^1]: Cho, N., Lodi, A., Scaglione, A. *Electric Vehicle Scheduling and Vehicle-to-Grid Integration in Microgrids*. Submitted local “evspv2g_revision (9).pdf,” 48 pages. Formulation pp. 6–12; pricing/certificates pp. 14–20; weather pp. 31–32,42. SHA-256 in pilot manifest.
[^2]: [EVSP–V2G repository at pinned commit](https://github.com/ndandnd/evspv2g_dp/tree/f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0). Read-only reference; no edits.
[^3]: Yetkin, M., Augustino, B., Lamadrid, A.J., Snyder, L.V. (2024). [Co-optimizing the smart grid and electric public transit bus system](https://link.springer.com/article/10.1007/s11081-023-09878-w). *Optimization and Engineering* 25:2425–2472. Publisher full formulation, Sections 2–4 and appendices, audited 12 September. [Author preprint v4](https://arxiv.org/html/2012.08087v4) is dated August 2026; journal/preprint equivalence is not assumed.
[^4]: Baldua, M., Nath, R.B., Vasudeva, V., Rambha, T. (2025). [Charge Schedule Optimization and Infrastructure Planning for Solar-Integrated Electric Bus Transit Systems](https://arxiv.org/html/2504.20790v1). April 29 preprint, Sections 3–5. [Pinned MIT code/data](https://github.com/transnetlab/csp-res/tree/615817bc86cb6a7d5e96efd1532ec45b7e9ee2a2); [constraint builders and LP-forcing driver](https://github.com/transnetlab/csp-res/blob/615817bc86cb6a7d5e96efd1532ec45b7e9ee2a2/csp.py). CPLEX 22.1.1.0 Benders annotations; Durham archive inspected, not deserialized or run.
[^5]: Terada, L.Z., Magalhães, M.M., Cortez, J.C., Soares, J., Vale, Z., Rider, M.J. (2025). [Multi-objective optimization for microgrid sizing, electric vehicle scheduling and vehicle-to-grid integration](https://doi.org/10.1016/j.segan.2025.101773). *Sustainable Energy, Grids and Networks* 43:101773. Publisher preview plus [pinned author code/data](https://github.com/TeradaZenichi/ev-scheduler/tree/2253383a761305fd807afab7d59b6b342bbb3d6b) and [actual Pyomo model](https://github.com/TeradaZenichi/ev-scheduler/blob/2253383a761305fd807afab7d59b6b342bbb3d6b/linear_model.py), inspected 12 September. Full journal formulation remains unavailable; code/article equivalence and reuse licensing remain unresolved (README claims MIT but linked LICENSE is absent).
[^6]: Son, J., Im, J., Kim, D. (2025). [Urban transit optimization: Efficient electric bus operations and vehicle-to-grid integration](https://doi.org/10.1016/j.cie.2025.111169). *Computers & Industrial Engineering* 205:111169. [Author preprint record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5077045); full formulation verification outstanding.
[^7]: Zheng, F., Cao, R., Liu, M. (2024). [Stochastic fast charging scheduling of battery electric buses with energy storage systems design](https://doi.org/10.1016/j.cie.2024.110177). *Computers & Industrial Engineering* 191:110177. Publisher preview; authors checked through Crossref.
[^8]: Tang, X., Lin, X., He, F. (2019). [Robust scheduling strategies of electric buses under stochastic traffic conditions](https://doi.org/10.1016/j.trc.2019.05.032). *Transportation Research C* 105:163–182. Publisher preview.
[^9]: Avishan, F., Yanıkoğlu, İ., Alwesabi, Y. (2023). [Electric bus fleet scheduling under travel time and energy consumption uncertainty](https://doi.org/10.1016/j.trc.2023.104357). *Transportation Research C* 156:104357. Publisher preview.
[^10]: Ricard, L., Desaulniers, G., Lodi, A., Rousseau, L.-M. (2026). [Chance-constrained battery management for electric bus scheduling](https://doi.org/10.1016/j.ejor.2026.05.046). *EJOR*, online June 1. Publisher method/runtime and [2025 preprint](https://arxiv.org/html/2503.19853v1), Sections 2–4, checked in the 12 September audit; equivalence to every version detail not asserted. [Author-linked dataset/results](https://github.com/learicard/evsp-policy-battery/tree/8562206fe1349445f1d8e7b7b6ebd67960ab9bda) contains Apache-2.0 licensed CSV data, no solver source. [Complete availability audit](literature_update_20260912/LEA_CODE.md).
[^11]: Qi, J., Lei, L., Jonsson, T., Niyato, D. (2025). [Optimizing Electric Bus Charging Scheduling with Uncertainties Using Hierarchical Deep Reinforcement Learning](https://arxiv.org/abs/2505.10296); [Safe and Sustainable Electric Bus Charging Scheduling with Constrained Hierarchical DRL](https://arxiv.org/html/2512.03059v1), November preprint. Version status as inspected.
[^12]: Kleywegt, A.J., Shapiro, A., Homem-de-Mello, T. (2002). [The Sample Average Approximation Method for Stochastic Discrete Optimization](https://doi.org/10.1137/S1052623499363220). *SIAM Journal on Optimization* 12(2):479–502.
[^13]: Bertsimas, D., Sim, M. (2004). [The Price of Robustness](https://doi.org/10.1287/opre.1030.0065). *Operations Research* 52(1):35–53.
[^14]: Zeng, B., Zhao, L. (2013). [Solving two-stage robust optimization problems using a column-and-constraint generation method](https://doi.org/10.1016/j.orl.2013.05.003). *Operations Research Letters* 41(5):457–461.
[^15]: Mohajerin Esfahani, P., Kuhn, D. (2018; online 2017). [Data-driven distributionally robust optimization using the Wasserstein metric: performance guarantees and tractable reformulations](https://doi.org/10.1007/s10107-017-1172-1). *Mathematical Programming* 171:115–166.
[^16]: Heitsch, H., Römisch, W. (2003). [Scenario Reduction Algorithms in Stochastic Programming](https://doi.org/10.1023/A:1021805924152). *Computational Optimization and Applications* 24:187–206.
[^17]: GAMS. [Scenario Reduction and Tree Construction](https://www.gams.com/53/docs/T_LIBINCLUDE_SCENRED.html). Official SCENRED documentation.
[^18]: Van Slyke, R.M., Wets, R. (1969). [L-Shaped Linear Programs with Applications to Optimal Control and Stochastic Programming](https://doi.org/10.1137/0117061). *SIAM Journal on Applied Mathematics* 17(4):638–663.
[^19]: Rockafellar, R.T., Wets, R.J.-B. (1991). [Scenarios and Policy Aggregation in Optimization Under Uncertainty](https://doi.org/10.1287/moor.16.1.119). *Mathematics of Operations Research* 16(1):119–147.
[^20]: Crainic, T.G., Hewitt, M., Rei, W. (2014). [Scenario grouping in a progressive hedging-based meta-heuristic for stochastic network design](https://doi.org/10.1016/j.cor.2013.08.020). *Computers & Operations Research* 43:90–99. [Earlier author report](https://www.cirrelt.ca/documentstravail/cirrelt-2012-41.pdf).
[^21]: Pyomo contributors. [mpi-sppy](https://github.com/Pyomo/mpi-sppy), official stochastic-programming repository.
[^22]: Executed local pilot: source (original research artifact `pilot.py`; not included in this export), daily outcomes and intervals (original research artifact `pilot_results/results.json`; not included in this export), summary (original research artifact `pilot_results/summary.csv`; not included in this export), configuration/input hashes and runtime (original research artifact `pilot_results/manifest.json`; not included in this export), verification (original research artifact `pilot_results/verification.json`; not included in this export), monthly training selection (original research artifact `pilot_results/planning_profiles.json`; not included in this export). September 10, 2026.
[^23]: Rockafellar, R.T., Uryasev, S. (2000). [Optimization of Conditional Value-at-Risk](https://doi.org/10.21314/JOR.2000.038). *Journal of Risk* 2(3):21–41. Bibliographic record confirmed on the [author publication page](https://uryasev.github.io/publications/).

[^24]: Najafi, Gao, Parishwad, Tsaousoglou, Jin & Yi (2025). [Integrated optimization of charging infrastructure, electric bus scheduling and energy systems](https://backend.orbit.dtu.dk/ws/files/391952206/1-s2.0-S1361920925000744-main.pdf). *Transportation Research D* 141:104664. Institutional version-of-record PDF, printed pp. 6–14, especially equations 42/56; audited 12 September. Common trip/charging decisions with scenario energy supply are a direct structural precedent. No author implementation was verified.
