"""Task-count scaling inputs (16 October 2026): only the number of tasks changes.

Every input uses the Table 19 panel generator (panel_instances.balanced_trips and
balanced_energies, unchanged): the fixed 15-location map, one-hour tasks starting
between 06:00 and 20:00, task energies spread evenly over 75-125 kWh with mean
100 kWh, 2x solar, 700 kWh trucks, 175 kWh per block. Two SoC grids (25 and
12.5 kWh) and two task draws per task count. Fresh RNG namespace 20261016.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import panel_instances as P

TASK_COUNTS = (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)
STEPS = ((.25, "25"), (.125, "12p5"))
POINTS = 15


def case_specs():
    return [{"case": f"tasks_n{n:04d}_d{lab}_draw{sd}", "family": "task_count_scaling",
             "n_tasks": n, "points": POINTS, "soc_step": step, "draw_seed": sd,
             "task_energy_support_kwh": [75, 125], "task_energy_mean_kwh": 100,
             "rng_namespace": [20261016, 1016, n, int(step * 1000), sd],
             "energy_rng_namespace": [20261016, 1016, n, int(step * 1000), sd, 1],
             "generator": "panel_instances.balanced_trips/balanced_energies (Table 19 panel), unchanged"}
            for step, lab in STEPS for n in TASK_COUNTS for sd in (0, 1)]


def build_case(spec):
    canonical = next((s for s in case_specs() if s["case"] == spec.get("case")), None)
    if spec != canonical:
        raise ValueError("Undeclared task-scaling input")
    # Reuse the panel builder body verbatim by bypassing only its canonical-spec check.
    original = P.case_specs
    try:
        P.case_specs = lambda: [spec]
        return P.build_case(spec)
    finally:
        P.case_specs = original
