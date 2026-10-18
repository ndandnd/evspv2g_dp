"""Six prespecified historical inputs for the bounded minor-revision extension.

The four structured cases extend the existing SCAL pilot to 150/210 tasks.
The two random cases are DIAG2's first task draw (sd=0) at 100 tasks and
4/15 task locations. They are individual draws, NOT Table 4's two-draw medians.

No historical experiment driver is imported: importing overnight3/overnight13
would bring unrelated, mutable dependencies. Its small random generator is
copied verbatim below; all its other inputs come from the already frozen vendor
snapshot. Provenance and historical result-file hashes are embedded in this file
so deployment requires no access to the original Downloads directory.

Important: DIAG2 uses physical rho=1.75 and soc_step=0.5. Its DP floors the
per-block lattice rate to 1.5, while legacy singleton seeds can charge 1.75.
Do not round rho, refine the grid, or treat every legacy seed as a lattice path.
The direct comparison must account for the same column family explicitly.
These builders only create inputs; they do not modify optimization algorithms.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
import recreate_arxiv as historical


_PROVENANCE = {
    "recorded_date": "2026-10-12",
    "source_root_at_inspection": "/Users/nadan/Downloads/paper-rewrite 2/code",
    "vendor_snapshot_source_head": "3fa62572cf32ac1613d91d9a0057c61cf430b334",
    "historical_result_commits_differ_from_snapshot": True,
    "source_files": {
        "overnight3.py": {
            "sha256": "af03c0e37b33bd8d3d7507ffa39398019f6cd454709df738b01c8f80887e3851",
            "bytes": 18628,
            "used": "rand_trips (lines 111-120), constants (46), POOL (50)",
        },
        "overnight13.py": {
            "sha256": "7c1510394bb35b570e4fc749cb50d650124e0e631b832d511e438188efbeb910",
            "bytes": 46769,
            "used": "diag2 (696-716), _solve13 parameter overrides (172-174)",
        },
    },
    "copied_rand_trips_source_sha256":
        "25d9a63d2673099593186deb0cedaf6ab4ef44e7a5edae65844eb4c34956b75b",
    "rand_trips_dependencies": {
        "rng": "numpy.random.default_rng; NumPy version recorded by run manifest",
        "seed_formula": "salt + 1000 * (200 + draw_seed) + 10 * L + n_tasks",
        "salt": 20000,
        "start_hour_bounds": [6, 20],
        "start_hour_upper_bound_exclusive": True,
        "geometry": "overnight3.POOL = list(recreate_arxiv._COORDS) + three extra coordinates; only first 4/15 entries used",
    },
    "vendor_dependencies": {
        "recreate_arxiv.py": "d929fdf58f1a6da777ff8b16628e8abe35d6f23ed3bfb053fa5f69f24849bbbd",
        "instance.py": "3665962eea34daacb70b1d55a9cd9bbdcea93d6b30f07938f972d82abec09cbb",
        "data/delta.csv": "2ea30d7918dc5dbae37c79f01e5989d33fb5509d9e44609107c09a140a62db4d",
    },
    "historical_result_records": {
        "diag2_L04_n100_s0": {
            "relative_source_path": "results/arxiv/overnight13_diag2_s0of24.json",
            "sha256": "89aae820cd48d2a8634f39fe495a5a0b1e3e2fd141fdd310b266ea6b542c191a",
            "record_commit": "654615e", "L": 4, "n_tasks": 100, "seed": 0,
            "recorded_lp_objective_rounded": 5042.37,
            "recorded_restricted_objective_rounded": 5713.5,
            "recorded_batteries": 19,
        },
        "diag2_L15_n100_s0": {
            "relative_source_path": "results/arxiv/overnight13_diag2_s12of24.json",
            "sha256": "cef2729f30ef862c1ae8b6e77737050125bab22fa5a25839518c98000c0e2b29",
            "record_commit": "14835da", "L": 15, "n_tasks": 100, "seed": 0,
            "recorded_lp_objective_rounded": 6231.96,
            "recorded_restricted_objective_rounded": 6441.0,
            "recorded_batteries": 2,
        },
    },
    "interpretation": "Historical outputs document case identity, not new run results or guaranteed reproduction of historical route pools/incumbents.",
}


def source_manifest() -> dict:
    """Return a detached, JSON-compatible record of copied-source provenance."""
    return deepcopy(_PROVENANCE)


def rand_trips(L, n, seed, windows=(6, 20), salt=20_000):
    rng = np.random.default_rng(salt + 1_000 * seed + 10 * L + n)
    out = []
    for _ in range(n):
        i = int(rng.integers(1, L + 1)); j = int(rng.integers(1, L + 1))
        while j == i:
            j = int(rng.integers(1, L + 1))
        out.append((i, j, int(rng.integers(windows[0], windows[1]))))
    return out


def case_specs() -> list[dict]:
    """Return four structured extensions plus two prespecified random cases."""
    common = {
        "model_energy_unit_kwh": 100, "T": 48, "block_hours": 0.5,
        "G": 7.0, "soc_step": 0.5, "eta": 0.0, "energy_per_dist": 0.5,
        "c_v": 45.0, "c_b": 36.0, "eps_pen": 0.025, "deg_cost": 0.0,
        "solar_mult": 7, "truck_boundary": "full/full",
        "stationary_boundary": "periodic", "soc_mode": "cyclic",
        "generation_cap": "unbounded", "charging_cap": "unbounded",
        "scenario": "v2g",
    }
    specs = []
    for points in (6, 7):
        n = 5 * points * (points - 1)
        for energy in (150, 200):
            name = f"n{n:03d}_e{energy}"
            specs.append({
                "case": name, "name": name, "family": "structured_scal",
                "n_tasks": n, "points": points, "task_energy_kwh": energy,
                "draw_seed": None, "rng_seed": None,
                "settings": dict(common, windows_hours=[[4, 9]],
                                 task_duration_hours=2.0, rho=0.5, c_g=5.0,
                                 pv_scale=1.0, stations="depot_only"),
                "provenance": "Frozen recreate_arxiv.build_instance(points, energy/100, SCAL); deterministic Table 3 family",
                "reviewer_scope": "Direct-formulation comparison on medium structured instances (comment 2)",
            })
    for points in (4, 15):
        name = f"diag2_L{points:02d}_n100_s0"
        specs.append({
            "case": name, "name": name, "family": "random_diag2",
            "n_tasks": 100, "points": points, "task_energy_kwh": 100,
            "draw_seed": 0, "rand_trips_seed_argument": 200,
            "rng_seed": 20000 + 1000 * 200 + 10 * points + 100,
            "settings": dict(common, windows_hours=[[6, 20]],
                             task_duration_hours=1.0, rho=1.75, c_g=40.0,
                             pv_scale=2.0, stations="all",
                             dp_grid_rate_per_block=1.5,
                             legacy_singleton_profiles_may_be_off_grid=True),
            "provenance": deepcopy(_PROVENANCE["historical_result_records"][name]),
            "reviewer_scope": "Direct comparison and gap diagnosis on two existing Table 4 family representatives (comments 1 and 2); no added storage-activation axis",
        })
    return specs


def build_case(spec: dict):
    """Create exactly one declared historical input; never solve or write files."""
    canonical = next((s for s in case_specs() if s["case"] == spec.get("case")), None)
    if canonical is None or spec != canonical:
        raise ValueError("Use an unmodified case_specs() entry to prevent input drift")
    if Path(historical.__file__).resolve() != (ROOT / "vendor/recreate_arxiv.py").resolve():
        raise RuntimeError("recreate_arxiv must be loaded from the frozen vendor snapshot")
    for relative, expected in _PROVENANCE["vendor_dependencies"].items():
        actual = hashlib.sha256((ROOT / "vendor" / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Frozen input dependency changed: {relative}")
    cfg = spec["settings"]
    if spec["family"] == "structured_scal":
        inst = historical.build_instance(spec["points"], spec["task_energy_kwh"] / 100,
                                         historical.SCAL)
    else:
        fleet = rand_trips(spec["points"], spec["n_tasks"],
                           spec["rand_trips_seed_argument"])
        # POOL's appended coordinates occur after _COORDS' 16 entries and
        # therefore do not affect either of the selected first-4/first-15 maps.
        pool = list(historical._COORDS) + [(0.75, 0.75), (-0.75, 0.75), (0.75, -0.75)]
        inst = historical.build_instance(spec["points"], 1.0, [(6, 20)],
                                         trip_list=fleet, duration=1.0,
                                         coords_override=pool[:spec["points"]],
                                         stations="all", pv_scale=2.0)
        # These are _solve13's economic/rate overrides, not solver settings.
        inst.c_g, inst.c_b, inst.rho, inst.c_v = 40.0, 36.0, 1.75, 45.0
    for attribute in ("T", "G", "rho", "soc_step", "eta", "energy_per_dist",
                      "c_g", "c_v", "c_b", "eps_pen", "deg_cost"):
        if getattr(inst, attribute) != cfg[attribute]:
            raise AssertionError(f"Input mismatch in {attribute}")
    if inst.n_trips != spec["n_tasks"]:
        raise AssertionError("Unexpected task count")
    return inst
