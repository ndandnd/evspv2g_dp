# Map extension of Table 8 (17 October 2026)

Inputs: Table 8 diagonal (two tasks per location) extended to L = 160 and 200 locations (n = 320 and 400 tasks), draws 0 and 1 (samples 1 and 2). 25 kWh SoC grid, task energies 75-125 kWh, generator `panel_instances.balanced_trips/balanced_energies`, RNG namespace `[20261016, 2016, L, draw]` (energies `+ [1]`), exactly as in Table 8.

Code: `runtime/` is a byte-for-byte copy of `experiments/opte_grid_scaling_20261016/runtime/` except `grid_instances.py`, where `DIAG_L` gains 160 and 200 (two added comment lines). `preflight_local.json` shows all 64 earlier inputs reproduce their `instance_sha256` (also equal to the 136 Table 8/21 raw manifests); `plan()` puts the eight new arms at task indices 0-7, and only those are submitted.

Protocol (agreed): CG to pricing convergence (safety cap 14,400 s; time reported separately), then the MIP over its routes 1,800 s from its model construction. Direct arc-flow MIP: 1,800 s from model construction (root LP included), read at 1,800 s; note Table 8's direct runs continued to 3,600 s for the bound, so LB* here uses the direct bound at 1,800 s (as in Table 22). Single one-thread Gurobi 12.0.3 runs, `--require-single-cpu --require-cpu-model=9654`.

Memory: `probe_graph_memory.py` builds the full graph (the CG arm's memory peak is its post-run validation graph) and records peak RSS; direct arms request 3.0 GB per million estimated arcs + 8 GB.

Cluster: `~/opte-map-extension-20261017/` on unicorn (`results/`, `logs/`, `probe/`, `submit_receipt.json`). Local copies of the worker and submit scripts and the receipt: `cluster/`.
