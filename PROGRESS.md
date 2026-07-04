# Progress summary: DP-based EVSP-V2G — validation and computational study

**Scope.** This repo replaces the conference version's Gurobi-MILP pricing with a
labeling-DP pricing oracle under the revised model (cyclic SoC, explicit fossil
generation, aggregate battery block). This note summarizes (A) the validation
chain showing the DP code matches the MILP-based original, (B) the recreation of
the original computational study, and (C) the new planning results. Every claim
has a runnable artifact in this repo; all numbers below are from those runs.

---

## A. Does the new DP match the old MILP? (validation chain)

*(Self-contained version of this section, focused on the LP-equivalence
evidence: `DP_MIP_EQUIVALENCE.md`.)*

### A1. Implementation equivalence — exact
Three independently written codebases (this repo; a from-scratch PuLP/CBC
implementation; a third independent implementation) were run on
matched-granularity instances (integer deadheads, aligned SoC lattice, identical
costs). **All three match the LP optimum to the digit** — 70 / 80 / 78 on the
three toy cases, and 80 / 110 / 140 / **152.8571** / 170 as the instance scales
(the fractional optimum rules out coincidence). The DP prices the same model the
MILP formulation defines.

### A2. Do we need Gurobi? No (a practical question, answered) (`solver_compare.py`)
This was never a research question — just "can the paper stand on open-source
solvers?" Answer: **yes for everything scientific.** HiGHS and Gurobi return
identical LP objectives on shared pools up to 1000 tasks, and column generation
converges to the same bound with either backend (HiGHS is even faster inside the
CG loop). Gurobi is an optional convenience for the final *integer* master at
200+ tasks (600 tasks to ~1% gap: 29.6 s vs CBC's 7.5 h); it changes no numbers
that matter, only waiting time.

### A3. Setting reversibility — phenomena reproduced (`arxiv_settings_check.py`)
One flag (`soc_mode="free"`) restores the original arXiv setting (free full
initial charge; trucks end at any SoC; batteries start full free). On the
original instance:

| 20 tasks, breaks (eps=2.5, V2G) | fuel (gal) | trucks | batteries |
|---|---|---|---|
| original arXiv (published Table 2)   | **-158.6** | 12.33 | deployed |
| **this DP, free mode (arXiv setting)** | **-245.5** | 7 | **9** |
| this DP, cyclic (revised model)      | +124.2 | 13 | 0 |

Free mode reproduces every signature phenomenon of the original — **negative
fuel (net export), stationary batteries deployed, EV fuel far below ICE** — and
cyclic mode removes all of them. The free initial energy is thus isolated as the
single cause of the level differences between the papers.

### A4. Residual differences — tested, not just asserted
Digit equality between two ~1%-gap integer heuristics was never expected. Each
candidate cause was examined:

1. **Model revision (the point of the paper):** cyclic SoC vs free start.
   Handled by the `soc_mode` flag — the DP-free column IS the temporarily
   de-revised model, and it restores the original's phenomena.
2. **The original's L<=4 charging-session cap: empirically NON-binding.** An
   audit of every selected route in our free-mode solutions shows at most 2-3
   station visits (cap was 4) at 20/60/120 tasks. Two consequences: the cap
   needs no reimplementation, and **our (smaller-fleet) solutions were feasible
   in the original's own model** — the fleet-size differences are therefore
   attributable to the original's heuristic optimization, not to model scope.
3. **Anti-cycling: 1.01 charge premium vs eps_pen.** Both are ~0.5%-scale
   churn dampers (the premium hit charging only; eps_pen hits charge+discharge
   throughput). Negligible; ignored by agreement.
4. **Discharge crediting: closer than first thought.** Reading the original
   master: discharge was capped by the hourly deficit with a flat fuel-price
   credit — which is economically the same as the revised model's endogenous
   price mu_t (= c_g exactly in deficit hours). Not a meaningful difference.
   (A one-hour shift in the uniform-window definition was also tested and
   changes nothing.) One small structural difference remains: the original used
   covering (>= 1) where we use partitioning (= 1).
5. **The primary residual: the original's numbers are one draw of a heuristic.**
   Its pricing collected up to 3,400 pool solutions per iteration (feasible, not
   best-first), its final master stopped at MIPGap 1%, and its Table-2 fleet
   counts are averages over replications (12.33, 30.67, ...). Crucially, *fuel
   is a side metric, not the objective*: near-cost-optimal solutions can differ
   widely in fuel (our knob grid shows 27-vs-1-battery solutions within ~1% of
   each other's cost), so side-metric orderings between two ~1% heuristics —
   e.g. breaks-vs-uniform in free mode — are not reproducible in principle.
   The definitive head-to-head, if wanted, is a fresh run of the original code
   on the small deterministic cells (Gurobi required, ~minutes).

### A5. Head-to-head vs the original code — resolved to 0.5% (`original_headtohead.py`)
A fresh Gurobi run of the original repo on its own default cell (20 tasks,
eps=2.5, mode 3) printed objective **295.00**. Our DP, fully aligned (free
start, covering, base-load constant removed), gave **237.10** — a 19.6% gap that
led to a finding: the original `build_master` (which produces its FINAL LP/MIP)
prices battery routes with `bus_cost` (45) instead of `batt_cost` (36); the
`batt_cost` argument is never used. Replicating that slip on our side
(`c_b = 45`) gives **296.50 vs their 295.00 — a 0.5% match**, and reproduces the
original's truck-heavy/battery-light solution structure (9 trucks + 1 battery
instead of 7 + 9). Two corollaries: (i) the original's published solutions had
battery deployment suppressed by ~25% overpricing in the final solve, which
also explains the remaining fleet-size differences; (ii) the original's final
"MIP" is built with `binary=False` in the code version at hand (its LP and MIP
print identical to 13 decimals), i.e. the published MIP values are LP values.
Independent verification: change `bus_cost` -> `batt_cost` on the two
`route_costs_batt` lines of the old repo's `build_master` and rerun — it should
then print ~237, our intended-model number.

**Claim to make:** same model => same LP to the digit; same settings => same
phenomena — including a 0.5% objective match against a fresh run of the
original code once its own final-master battery-cost slip is accounted for;
every residual difference is enumerated above.

---

## B. Recreation of the original computational study (`recreate_arxiv.py`)

Exact instance port (deterministic trip enumeration — 20/60/120 tasks at 2/3/4
locations under the breaks schedule; the scalability window gives 10..450 at
2..10 locations; delta.csv transform; original geometry with exact 0.5-block
deadheads on a half-block grid; original costs). All five experiments rerun
under the revised model:

| quantity | original (MILP pricing, Gurobi) | this repo (DP pricing, open-source) |
|---|---|---|
| 450-task instance | 29,722 s (8.3 h), gap 0.71% | **27.1 s, gap 0.033%** |
| 280-task, eps=1.5 | 21,433 s, gap 0.94% | **7.4 s, gap 0.000%** |
| entire 5-experiment suite | hours per instance | **94.6 s total** |
| columns generated (450 tasks) | 45,906 | **1,404** |
| pricing share of runtime | >95% (up to 99.95%) | **25–50%** (bottleneck reversed) |
| "relaxed eps is much slower" | yes (reported) | gone (DP cost is instance-size-fixed) |
| gaps | ~1% (MIPGap target) | <=1.5% everywhere, mostly <0.5% |

Trends reproduced: EV fleets larger than ICE; breaks-scheduling saves fuel at
the cost of more trucks; fuel falls concavely in available solar (the empirical
signature of Theorem 1). Levels differ exactly as A3/A4 predict.

---

## C. New planning results (the "beneficial when..." study)

**Correcting one indefensible price.** The original toy priced fossil generation
at $0.05/kWh — ~10x below remote-microgrid diesel ($0.30–1.00+/kWh) — while its
battery cost ($36/day per 700 kWh) matches today's LFP capex. At corrected
prices the storage economics activate.

**Knob grid** (`knob_grid.py`, 54 realistic combos x 3 regimes): V2G beats
charge-only Solar by >1% of total cost in 37/54 combos, by up to 90%. Structure:
- **Surplus is the gate, price is the multiplier**: at low solar, V2G ~= Solar at
  *any* fuel price; at high solar it approaches full fossil displacement.
- **Fleet-as-storage substitution**: raising battery cost $26 -> $51/day swaps
  27 batteries for ~1 (+ a few trucks) with nearly unchanged savings — with
  V2G-capable trucks, stationary storage is nearly optional.
- **Electrification has its own threshold**: ICE is cheapest when solar is
  scarce; EVs win from moderate solar up.

**Planning ratio** (`planning_grid.py`): all cells collapse onto
**R = daily solar surplus / fleet traction energy**, regardless of which knob
(trip count, task intensity, PV size) moves it: V2G adds **<1% below R ~ 0.3,
>=5% above R ~ 1.1**, and 65–83% above R ~ 2.

**Scale invariance** (`scale_ladder.py`): with the microgrid co-scaled to the
fleet, the savings at fixed R hold from 20 to 560 tasks — 0.1–0.8% at R=0.31,
23.6–29.9% at R=1.40, 70.3–77.4% at R=2.57. The mild drift at scale is
attributable to the growing deadhead share (R uses task energy only) and to
~1.9% MILP gaps at the largest cells. 560-task cells solve in ~40 s of column
generation. **The planning rule is scale-free:**

> Deploying EVSP-V2G is beneficial when the microgrid's daily solar surplus
> exceeds the fleet's traction demand (R >~ 1) at realistic remote-microgrid
> fuel prices; below that, V2G coincides with charge-only operation, and below
> a solar threshold electrification itself does not pay.

**Technology-tier decomposition** (`tech_tiers.py`): all four regimes
(VSP -> plain EVSP -> EVSP-Solar -> EVSP-V2G; the plain-EV tier is the
original's mode 1, added to this repo as the `ev` scenario). The three marginal
values are NEARLY SEPARABLE: electrification value is constant in R (it scales
with traction and the drivetrain-efficiency x fuel-price product), solar-aware
charging switches on with the first surplus kWh and saturates near R ~ 1, and
V2G switches on near R ~ 1 and keeps growing where solar saturates (4.4x the
solar value at R = 4.2). Break-even drivetrain efficiency for electrification:
~1.4x at parity truck cost, ~1.7x at a 2x EV premium -- real EV drivetrains are
2.5-3.5x, so electrification is robust ONCE energy is accounted honestly; under
the equal-energy assumption it never pays. (The explicit ICE_EFF knob also
resolves the original paper's internal inconsistency: Table 1 equates at
10 kWh/gal while its code converts at 33 kWh/gal -- the 3.3x ratio between them
IS the efficiency advantage.)

**Profile-shape robustness** (`profile_robustness.py`): sum-preserving reshapes
of the demand/solar profiles (solar +-2h, demand +-2h, flat demand, wide solar
bell) x pv sweep. The savings-vs-R curve COLLAPSES across shapes: +-2h timing
shifts change savings by < 0.3 pts at matched R (storage flexibility absorbs
timing entirely); shape enters almost only through the surplus integral (wide
solar -> less exceeds demand -> lower R -> the same curve at the new R);
residual shape effects are ~3-4 pts, traceable to rate limits (thin flat-demand
deficits need more parallel batteries: 32 vs 24 at R ~ 2.6). Consequence: the
planning rule needs only TWO SCALARS -- daily surplus and fleet traction -- with
no hourly profile detail, within the tested family (single daily cycle, depot
charging, uncapped infrastructure).

---

## Artifacts (all on branch `solver-comparison`)

| file | what it shows |
|---|---|
| `solver_compare.py` | HiGHS/CBC vs Gurobi on shared pools (A2) |
| `recreate_arxiv.py` | the original 5-experiment study under the revised model (B) |
| `arxiv_settings_check.py` | reversibility: original settings => original phenomena (A3) |
| `knob_grid.py` | realistic-parameter factorial with cost decomposition (C) |
| `planning_grid.py` | the R-ratio collapse and boundary (C) |
| `scale_ladder.py` | scale-invariance of the rule up to 560 tasks (C) |
| `scalability.py` | method scalability + realism capacity ceiling |
| `results/arxiv/` vs `results/arxiv_free/` | 1-1 experiment matrix, cyclic vs original settings |
