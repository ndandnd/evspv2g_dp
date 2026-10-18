"""Small, excluded preflight checks for the additive persistent RMP.

--structural-only performs no optimization. Default additionally solves only
small ten-task fixed pools and cold/reuse CG (30seconds maximum per CG arm).
Output must be a new directory. No existing source or result is modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"vendor"))
import numpy as np
import colgen
import recreate_arxiv as historical
from persistent_rmp import PersistentRMP
from rmp_solver import solve_rmp
from run_cg_reuse import solve_reuse_cg, sha, DEPENDENCIES
from lp_scaling_models import solve_cg_lp
from run_pilot import write_json


def instance():
    inst = historical.build_instance(2, 1.5, [(6, 11)])
    assert inst.n_trips == 10
    return inst


def check(output, structural_only=False):
    report = {"excluded_from_main_statistics": True, "optimization_performed": not structural_only,
              "code_sha256": {p: sha(ROOT/p) for p in DEPENDENCIES}, "checks": []}
    for cap in (float("inf"), 100.0):
        inst = instance(); inst.charge_cap = cap; inst.gen_cap = 1000.0
        cols = colgen.initial_columns(inst, "warm", colgen.SCENARIOS["v2g"], soc_mode="cyclic")
        artificials = [c for c in cols if c.kind == "artificial"]
        real = [c for c in cols if c.kind == "truck"]
        assert len(artificials) == 10 and real
        adapter = PersistentRMP()
        try:
            adapter._initialize(inst, artificials, None, 1e-6)
            before = adapter.canonical_model_check(inst, artificials)
            adapter._append(inst, artificials+real, restore_basis=False)
            after = adapter.canonical_model_check(inst, artificials+real)
            assert before["passed"] and after["passed"]
            changed = real[-1].fixed_cost; real[-1].fixed_cost += 1
            try:
                adapter._append(inst, artificials+real, restore_basis=False)
                raise AssertionError("Mutation was silently accepted")
            except ValueError as exc:
                assert "changed" in str(exc)
            finally: real[-1].fixed_cost = changed
            report["checks"].append({"name": "zero_optimization_matrix_append_and_mutation_guard",
                "finite_charging_cap": bool(np.isfinite(cap)), "before": before, "after": after,
                "mutation_rejected": True})
        finally: adapter.close()
        if structural_only: continue
        adapter = PersistentRMP(); snapshots = []
        try:
            pool = artificials
            for round_number in range(3):
                if round_number == 1: pool = pool+real
                if round_number == 2:
                    candidate = colgen.price_truck_dp(inst, warm.alpha, warm.mu, nu=warm.nu,
                        allow_charge=True, allow_discharge=True, soc_mode="cyclic")
                    pool = pool+[c for c, rc in candidate]
                warm, wdiag = adapter.solve(inst, pool, False, 15.0, None)
                cold, cdiag = solve_rmp(inst, pool, False, 15.0, None)
                matrix = adapter.canonical_model_check(inst, pool)
                assert warm.status == cold.status == "optimal"
                assert abs(warm.obj-cold.obj) <= 1e-6 and matrix["passed"]
                snapshots.append({"round": round_number, "columns": len(pool), "warm_objective": warm.obj,
                    "cold_objective": cold.obj, "absolute_difference": abs(warm.obj-cold.obj),
                    "basis_restored": wdiag["explicit_basis_restored"], "matrix": matrix,
                    "warm_primal_replay": wdiag["validation"], "cold_primal_replay": cdiag["validation"]})
            assert adapter.basis_restorations == 2
            report["checks"].append({"name": "fixed_pool_LPs", "finite_charging_cap": bool(np.isfinite(cap)),
                                     "snapshots": snapshots})
        finally: adapter.close()
    if not structural_only:
        cold = solve_cg_lp(instance(), 30.0, output/"tiny_cold")
        reuse = solve_reuse_cg(instance(), 30.0, output/"tiny_reuse")
        write_json(output/"tiny_cold"/"result.json", cold)
        write_json(output/"tiny_reuse"/"result.json", reuse)
        assert cold["certified"] and reuse["certified"]
        assert abs(cold["objective"]-reuse["objective"]) <= 1e-6
        report["checks"].append({"name": "ten_task_full_CG", "cold_objective": cold["objective"],
            "reuse_objective": reuse["objective"], "cold_certified": cold["certified"],
            "reuse_certified": reuse["certified"], "basis_restorations": reuse["basis_restorations"],
            "cold_graph_rc": cold["certificate"]["graph_min_reduced_cost"],
            "reuse_graph_rc": reuse["certificate"]["graph_min_reduced_cost"]})
    report["passed"] = True
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--structural-only", action="store_true")
    a = p.parse_args()
    if a.output.exists(): raise ValueError("Use a fresh output directory")
    a.output.mkdir(parents=True)
    report = check(a.output, a.structural_only)
    write_json(a.output/"checks.json", report)
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "output": str(a.output.resolve())}))


if __name__ == "__main__": main()
