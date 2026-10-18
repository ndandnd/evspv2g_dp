"""Post-hoc full-family dual certificate for saved direct LP workers.

No optimization is run and no benchmark result or timing is changed. Native
row prices are explicitly repriced over every graph path, real singleton seed,
and unit periodic BESS. Finite variable-upper-bound multipliers are never simply
discarded as if they were zero. Their omission is justified only if this new
full-family pricing check succeeds.

Tiny shared-price sign defects are projected onto 0 <= mu <= c_g, nu=0 for the
declared uncapped family. If necessary all prices are contracted toward zero to
repair a negative unit-BESS reduced cost. Finally alpha_i is reduced by epsilon,
where epsilon bounds negative route reduced costs: every admissible route serves
at least one task, so this makes route prices feasible and costs n*epsilon in the
dual objective. All adjusted prices are repriced. This is a supplementary
floating-point certificate, not exact rational arithmetic or a replacement for
the prespecified strict native diagnostic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from lp_scaling_instances import build_case
from extension_models import build_extended_graph, _seeds_with_witnesses, _hybrid_matrices
from verify_lp_scaling import verify_worker, _graph_price, _periodic_bess_price
from run_pilot import safe

TOL = 1e-6
RESERVE = 1e-9


def price_family(inst, graph, seeds, alpha, mu, nu):
    graph_rc = _graph_price(inst, graph, alpha, mu, nu)
    seed_rc = min(s.cost(inst.eps_pen)-float(alpha @ s.a)+float(mu @ s.e)
                  +float(nu @ np.maximum(s.e, 0.0)) for s in seeds)
    storage = _periodic_bess_price(inst, mu, nu)
    return {"graph_min_reduced_cost": graph_rc, "seed_min_reduced_cost": seed_rc,
            "route_min_reduced_cost": min(graph_rc, seed_rc),
            "unit_bess_reduced_cost": storage["unit_reduced_cost"],
            "unit_bess_oracle": storage,
            "dual_objective": float(alpha.sum()+mu @ inst.Delta)}


def certify_direct_worker(folder):
    folder = Path(folder).resolve()
    out = {"worker": str(folder), "supplementary_certified": False,
           "scope": "Post-hoc common-family numerical dual certificate; strict benchmark flags/times unchanged",
           "pricing_tolerance": TOL, "repair_reserve": RESERVE,
           "no_optimization": True, "prespecified_primary_criterion_changed": False}
    try:
        manifest = json.loads((folder/"manifest.json").read_text())
        result = json.loads((folder/"result.json").read_text())
        out["evidence_binding_sha256"] = {
            name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
            for name in ("result.json", "manifest.json", "instance.json", "direct_primal.npz", "direct_dual.npz")
            if (folder/name).is_file()}
        out["instance_payload_sha256"] = manifest["instance_sha256"]
        if manifest["method"] not in ("dual", "barrier"):
            raise ValueError("A saved direct LP worker is required")
        out.update(case=manifest["case"]["case"], method=manifest["method"], repeat=manifest["repeat"],
                   primary_strict_certified=bool(result.get("certified")),
                   native_status=result.get("status"), objective=result.get("objective"))
        replay = verify_worker(folder)
        out["prerequisite_replay"] = replay
        if not replay["passed"] or result.get("native_status") != 2:
            out["reason"] = "primal_provenance_or_native_optimality_prerequisite_failed"
            return safe(out)
        inst = build_case(manifest["case"])
        if not (np.isinf(inst.charge_cap) and np.all(np.isinf(np.broadcast_to(inst.gen_cap, (inst.T,))))
                and inst.eta == 0 and inst.c_b > RESERVE and inst.c_g >= 0 and inst.c_v >= 0
                and inst.eps_pen >= 0 and inst.deg_cost >= 0):
            raise ValueError("Certificate is limited to the declared lossless, uncapped, nonnegative-cost family")
        graph = build_extended_graph(inst); seeds, _ = _seeds_with_witnesses(inst)
        _, _, _, ae, be, au, bu, off = _hybrid_matrices(inst, graph, seeds)
        with np.load(folder/"direct_dual.npz", allow_pickle=False) as saved:
            pe, pu = saved["pi_eq"], saved["pi_ub"]
        if pe.shape != be.shape or pu.shape != bu.shape or not np.all(np.isfinite(np.r_[pe, pu])):
            raise ValueError("Invalid saved dual vector shapes or values")
        # Validate row extraction against matrix coefficients, not just positions.
        N, n, T = graph.n_nodes, inst.n_trips, inst.T
        if not (np.all(be[N:N+n] == 1) and np.allclose(bu[:T], -inst.Delta, rtol=0, atol=0)
                and np.allclose(au[:T,off["g"]:off["g"]+T].toarray(), -np.eye(T), rtol=0, atol=0)
                and np.allclose(ae[N:N+n,off["seed_start"]:].toarray(),
                                np.stack([s.a for s in seeds],axis=1), rtol=0, atol=0)):
            raise ValueError("Task/balance row mapping does not match reconstructed matrix metadata")
        alpha = pe[N:N+n].copy(); mu = -pu[:T].copy(); nu = np.zeros(T)
        raw = price_family(inst, graph, seeds, alpha, mu, nu)
        raw_sign = float(max(0, np.max(-mu), np.max(mu-inst.c_g)))
        raw["generation_dual_sign_violation"] = raw_sign
        out["actual_saved_row_price_diagnostics"] = raw
        out["row_mapping"] = {"task_equalities_start": N, "task_equalities_count": n,
                              "balance_inequalities_start": 0, "balance_count": T,
                              "mu_equals_negative_balance_pi": True,
                              "charging_cap_dual": "zero; no finite charging-cap rows exist"}
        if raw_sign > TOL or raw["route_min_reduced_cost"] < -TOL or raw["unit_bess_reduced_cost"] < -TOL:
            out["reason"] = "actual_row_prices_fail_common_family_pricing_or_shared_dual_test"
            return safe(out)
        # Projection repairs sign/range; every oracle is rerun after the change.
        projected_mu = np.clip(mu, 0.0, inst.c_g)
        projection = float(np.max(abs(projected_mu-mu), initial=0.0)); mu = projected_mu
        projected = price_family(inst, graph, seeds, alpha, mu, nu)
        delta = max(0.0, -projected["unit_bess_reduced_cost"])
        scale = 1.0
        if delta > 0:
            # For every unit-storage profile, r(lambda*pi) >= lambda*r(pi)
            # +(1-lambda)*c_b since gross-throughput costs are nonnegative.
            scale = (inst.c_b-RESERVE)/(inst.c_b+delta)
            alpha *= scale; mu *= scale; nu *= scale
        contracted = price_family(inst, graph, seeds, alpha, mu, nu)
        epsilon = max(0.0, -contracted["route_min_reduced_cost"])
        if epsilon > 0:
            epsilon += RESERVE
        if epsilon > TOL:
            out["reason"] = "required_route_repair_exceeds_pricing_tolerance"
            return safe(out)
        alpha -= epsilon
        final = price_family(inst, graph, seeds, alpha, mu, nu)
        objective = float(result["objective"]); bound = final["dual_objective"]
        gap = objective-bound
        # Feasibility is checked again without allowing negative priced margins.
        dual_feasible = (np.min(mu) >= 0 and np.max(mu) <= inst.c_g and np.all(nu == 0)
                         and final["route_min_reduced_cost"] >= 0
                         and final["unit_bess_reduced_cost"] >= 0)
        allowance = n*TOL+TOL
        consistent = -TOL <= gap <= allowance
        out.update(repairs={"max_generation_price_projection": projection,
                            "unit_bess_defect_after_projection": delta,
                            "common_price_scale": scale,
                            "task_price_decrease_epsilon": epsilon,
                            "route_repair_dual_loss_n_epsilon": n*epsilon,
                            "total_dual_objective_change": raw["dual_objective"]-bound},
                   final_price_diagnostics=final, supplementary_lower_bound=bound,
                   primal_minus_supplementary_bound=gap,
                   allowed_primal_dual_gap=allowance,
                   final_full_family_dual_feasible=bool(dual_feasible),
                   primal_dual_consistent=bool(consistent),
                   repaired_prices={"alpha":alpha.tolist(),"mu":mu.tolist(),"nu":nu.tolist()},
                   supplementary_certified=bool(dual_feasible and consistent),
                   reason="verified" if dual_feasible and consistent else "repaired_price_or_gap_check_failed",
                   limitation="Computed with floating-point residual checks, not exact arithmetic. The bound belongs to the entire DP-path-plus-real-seed LP family, with original continuous periodic BESS. No equality with a continuous-energy integer model is claimed.")
    except Exception as exc:
        out.update(reason="verification_exception", error=repr(exc))
    return safe(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a fresh supplementary report path")
    if (args.input/"result.json").is_file():
        folders = [args.input]
    else:
        folders = [p.parent for p in sorted(args.input.rglob("result.json"))
                   if p.parent.name in ("dual", "barrier")]
    rows = [certify_direct_worker(p) for p in folders]
    report = {"post_hoc":True,"primary_results_changed":False,"workers":len(rows),
              "supplementary_certified_workers":sum(r["supplementary_certified"] for r in rows),
              "results":rows,"checker_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(safe(report),indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="results"},indent=2))
    for row in rows:
        print(json.dumps({k:row.get(k) for k in ("case","method","repeat","supplementary_certified","reason","supplementary_lower_bound","primal_minus_supplementary_bound","error")}))
    return int(not rows or not all(r["supplementary_certified"] for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
