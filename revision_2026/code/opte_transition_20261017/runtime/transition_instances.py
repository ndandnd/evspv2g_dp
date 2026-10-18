"""Transition study (17 October 2026): where the direct arc-flow MIP stops delivering schedules.

Locations L in {25, 30} with tasks n in {60, 90, 120, 180, 240, 360}, plus brackets L = 20 (n = 40, 120, 240) and
L = 35 (n = 70, 120, 240); six task draws per cell; 25 kWh SoC grid, task energies 75-125 kWh.
RNG namespaces follow the grid study (n = 2L: [20261016, 2016, L, draw]; otherwise [20261016, 3016, L, n, draw]),
so draws 0 and 1 reproduce the existing inputs of Tables 8 and 21 where the cells overlap.
Generator: panel_instances.balanced_trips / balanced_energies, unchanged.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import panel_instances as P

CELLS = [(L, n) for L in (25, 30) for n in (60, 90, 120, 180, 240, 360)] + \
        [(20, 40), (20, 120), (20, 240), (35, 70), (35, 120), (35, 240)]
DRAWS = range(6)


def case_specs():
    rows = []
    for L, n in CELLS:
        for sd in DRAWS:
            ns = [20261016, 2016, L, sd] if n == 2 * L else [20261016, 3016, L, n, sd]
            rows.append({"case": f"tr_L{L:03d}_n{n:04d}_draw{sd}", "family": "transition",
                         "n_tasks": n, "points": L, "soc_step": .25, "draw_seed": sd,
                         "task_energy_support_kwh": [75, 125], "task_energy_mean_kwh": 100,
                         "rng_namespace": ns, "energy_rng_namespace": ns + [1], "diagonal": n == 2 * L,
                         "generator": "panel_instances.balanced_trips/balanced_energies, unchanged"})
    return rows


def build_case(spec):
    canonical = next((s for s in case_specs() if s["case"] == spec.get("case")), None)
    if spec != canonical:
        raise ValueError("Undeclared transition input")
    original = P.case_specs
    try:
        P.case_specs = lambda: [spec]
        return P.build_case(spec)
    finally:
        P.case_specs = original
