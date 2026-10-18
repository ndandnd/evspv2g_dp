"""Map-size x task-count grid (16 October 2026), 25 kWh SoC grid, task energies 75-125 kWh.

Two families, one protocol (that of Table 9: CG capped at 1,200 s, then the MIP over its routes at most
1,800 s; direct arc-flow MIP 3,000 s):
- grid: locations L in {15, 30, 45, 60, 90, 120} x tasks n in {120, 240, 480, 960}, with n >= 2L
  (the generator needs every location to be the origin and destination of at least two tasks);
- diagonal: n = 2L for L in {15, 20, 30, ..., 120}, the Table 9 series, rerun on one CPU type.
Diagonal cells use exactly the Table 9 RNG namespace, so their inputs are identical to Table 9's
(hashes are checked in the preflight); the other cells use a fresh namespace.
Generator: panel_instances.balanced_trips / balanced_energies, unchanged.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import panel_instances as P

GRID_L = (15, 30, 45, 60, 90, 120)
GRID_N = (120, 240, 480, 960)
DIAG_L = (15, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120)


def cells():
    out = {(L, 2 * L) for L in DIAG_L}
    out |= {(L, n) for L in GRID_L for n in GRID_N if n >= 2 * L}
    return sorted(out)


def case_specs():
    rows = []
    for L, n in cells():
        for sd in (0, 1):
            if n == 2 * L:   # identical to the Table 9 input
                ns = [20261016, 2016, L, sd]
            else:
                ns = [20261016, 3016, L, n, sd]
            rows.append({"case": f"grid_L{L:03d}_n{n:04d}_draw{sd}", "family": "map_task_grid",
                         "n_tasks": n, "points": L, "soc_step": .25, "draw_seed": sd,
                         "task_energy_support_kwh": [75, 125], "task_energy_mean_kwh": 100,
                         "rng_namespace": ns, "energy_rng_namespace": ns + [1],
                         "diagonal": n == 2 * L,
                         "generator": "panel_instances.balanced_trips/balanced_energies, unchanged"})
    return rows


def build_case(spec):
    canonical = next((s for s in case_specs() if s["case"] == spec.get("case")), None)
    if spec != canonical:
        raise ValueError("Undeclared grid input")
    original = P.case_specs
    try:
        P.case_specs = lambda: [spec]
        return P.build_case(spec)
    finally:
        P.case_specs = original
