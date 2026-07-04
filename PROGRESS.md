# Progress summary: DP-based EVSP-V2G — validation and computational study

**Scope.** This repo replaces the conference version's Gurobi-MILP pricing with a
labeling-DP pricing oracle under the revised model (cyclic SoC, explicit fossil
generation, aggregate battery block). This note summarizes (A) the validation
chain showing the DP code matches the MILP-based original, (B) the recreation of
the original computational study, and (C) the new planning results. Every claim
has a runnable artifact in this repo; all numbers below are from those runs.

---

## A. Does the new DP match the old MILP? (validation chain)

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

**Claim to make:** same model => same LP to the digit; same settings => same
phenomena; every residual difference is enumerated above.

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
