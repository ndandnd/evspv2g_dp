# Conservative SoC grid, six planning bases (reviewer comment 5) - 17 October 2026

Question: in the 15 October step sweep (`records/opte-corollary1-check-20261015/`), a 20 kWh step mapped 50 kWh deadheads to 40 kWh and produced infeasible routes. Redo it with a safe (conservative) rounding so every route is feasible, and report what it costs.

## Inputs (unchanged from the 15 Oct sweep)
Six bases of `overnight4.lattice_ladder` (`overnight4.py` of the first-submission code at the repository root, lines 262-288): three task locations plus depot, `rand_trips(3, n, seed, salt=50_000)` (verbatim copy in `run.py`), n = 60/120/200, seed 0/1, BREAKS, solar x2.5, eta = 0, c_g/c_b/rho/c_v = 40/36/1.75/45 (model unit 100 kWh), V2G with stationary storage, full recharge (start and end at 700 kWh), 48 half-hour blocks, charging only at the depot. True energies: tasks 200 kWh (2 h), deadheads 50 kWh (depot to each site, sites 1-2 and 1-3; 30 min) and 100 kWh (sites 2-3; 1 h), capacity 700 kWh, block limit 175 kWh (350 kW x 0.5 h).

## Code
- `vendor/`: byte copies of the frozen vendor (`experiments/opte_equal_mip_20261015/runtime/frozen/vendor`), hashes in `COPY_MANIFEST.json`. Not modified.
- `grid_dp.py`: copy of the frozen cyclic pricing core with two rules, `nearest` (frozen index rules) and `conservative` (all energy quantities rounded in the safe direction; see the module docstring). Records a full event trace per route.
- `replay.py`: independent physical replay with the true energies (stop charging when full; checks continuity, task times, stations, rate, 0 <= SoC <= G, final SoC = G, coverage, booked profile). Also checks the proof invariant (real SoC >= grid SoC after every event).
- `run.py`: CG with the frozen `colgen.column_generation` (warm start, enrich 0, tolerance 1e-6, HiGHS restricted-master LPs), replay of every route column, master-row checks with booked and executed profiles, re-solved LP with executed profiles, and the restricted route MIP (Gurobi 12.0.1 locally; Threads 1, Seed 0, MIPGap 1e-6, MIPGapAbs 1e-10, tolerances 1e-8, 600 s, truck columns only).
- `summarize.py`: tables and checks.

## Arms
frozen25 (exact reference), exact25 (nearest rule copy, must equal frozen25), cons25 (must equal frozen25), cons20, cons50, cons10, near20 (negative control: the 15 October sweep's case), rate160_10 (10 kWh grid with a 160 kWh block limit; separates the rate floor from traction rounding). Route MIP on exact25 and cons20.

## Run
`python3 -B experiments/opte_conservative_grid_20261017/run.py 4` then `... summarize.py`, from the repo root. Local laptop, 4 worker processes; total CG CPU is a few minutes (15 Oct sweep log). CG times are not timing evidence. Outputs only under `output/opte-conservative-grid-20261017/`; an existing `result.json` is never overwritten.
