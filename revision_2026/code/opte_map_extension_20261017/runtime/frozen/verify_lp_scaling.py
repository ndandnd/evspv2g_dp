"""Independently replay saved LP scaling evidence without an LP/MIP solve.

API: verify_worker(folder) -> JSON-compatible audit dictionary.
CLI: --input WORKER_OR_BATCH [--output AUDIT_JSON]. Existing evidence is read only.

The checker reconstructs the declared input/model, reads raw compressed vectors,
replays physical paths and aggregate balances, reconstructs native direct dual
certificates including bound multipliers, and independently prices graph paths,
finite seeds and unit periodic BESS at saved CG duals. Shortest-path sweeps are
verification outside benchmark timing. Numerical checks do not assert exact
arithmetic certification. No Gurobi optimization is invoked.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy import sparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
import master
from master import Column
from lp_scaling_instances import build_case, instance_record
from extension_models import (build_extended_graph, _seeds_with_witnesses,
                               _hybrid_matrices, _hybrid_replay,
                               validate_extended_selected_columns)
from rmp_solver import replay_rmp
from run_pilot import safe

TOL = 1e-6


def _max(values):
    return float(np.max(values, initial=0.0))


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _primal(c, lb, ub, ae, be, au, bu, x, objective):
    if x.shape != c.shape or not np.all(np.isfinite(x)) or not math.isfinite(objective):
        raise ValueError("Nonfinite or incompatible saved primal vector/objective")
    finite = np.isfinite(ub)
    return {"equalities": _max(abs(ae @ x-be)),
            "inequalities": _max(au @ x-bu),
            "lower_bounds": _max(lb-x), "upper_bounds": _max(x[finite]-ub[finite]),
            "objective": abs(float(c @ x)-objective)}


def _direct_certificate(c, lb, ub, ae, be, au, bu, x, pe, pu, rc, objective):
    if not all(np.all(np.isfinite(v)) for v in (pe, pu, rc)):
        raise ValueError("Nonfinite saved direct dual")
    finite = np.isfinite(ub)
    residuals = _primal(c, lb, ub, ae, be, au, bu, x, objective)
    residuals.update(dual_sign=_max(pu),
                     reduced_cost_identity=_max(abs(c-ae.T @ pe-au.T @ pu-rc)),
                     negative_reduced_cost_without_upper_bound=_max(-rc[~finite]))
    dual_value = float(be @ pe + bu @ pu + lb @ np.maximum(rc, 0.0)
                       + ub[finite] @ np.minimum(rc[finite], 0.0))
    residuals["primal_dual_gap"] = abs(objective-dual_value)
    return {"passed": max(residuals.values()) <= TOL, "residuals": residuals,
            "dual_objective": dual_value, "tolerance": TOL,
            "includes_finite_variable_upper_bound_duals": True}


def _graph_price(inst, graph, alpha, mu, nu):
    # Independent scalar recurrence; do not reuse the benchmark's oracle.
    distances = np.full(graph.n_nodes, np.inf); distances[graph.source] = 0.0
    for edge in range(graph.n_arcs):
        u, v = int(graph.tail[edge]), int(graph.head[edge])
        t = int(graph.states[u, 0]); e = float(graph.energy[edge])
        w = mu[t]*e + nu[t]*max(e, 0.0) + inst.eps_pen*abs(e)
        w += getattr(inst, "deg_cost", 0.0)*max(-e, 0.0)
        if graph.task[edge] >= 0:
            w -= alpha[int(graph.task[edge])]
        candidate = distances[u]+w
        if candidate < distances[v]:
            distances[v] = candidate
    return float(inst.c_v+distances[graph.sink])


def _periodic_bess_price(inst, mu, nu):
    """Unit periodic storage oracle from lossless network integrality.

There are no fixed withdrawals. A common divisor of G and rho gives integral
capacity/rate data; enumerating every initial/end level includes an optimum.
Nonnegative price/throughput conditions make a nonsimultaneous optimum valid.
    """
    if abs(inst.eta) > 1e-12:
        raise ValueError("The independent BESS oracle requires eta=0")
    g, r = Fraction(str(inst.G)), Fraction(str(inst.rho))
    denominator = math.lcm(g.denominator, r.denominator)
    numerator = math.gcd(int(g*denominator), int(r*denominator))
    quantum = float(Fraction(numerator, denominator))
    levels, rate = round(inst.G/quantum), round(inst.rho/quantum)
    if levels > 5000 or quantum <= 0:
        raise ValueError("Unexpected stationary energy lattice")
    best = float("inf")
    for initial in range(levels+1):
        cost = np.full(levels+1, np.inf); cost[initial] = 0.0
        for t in range(inst.T):
            nxt = cost.copy()
            for s in range(levels+1):
                for d in range(1, min(rate, levels-s)+1):
                    candidate = cost[s]+d*quantum*(mu[t]+nu[t]+inst.eps_pen)
                    nxt[s+d] = min(nxt[s+d], candidate)
                for d in range(1, min(rate, s)+1):
                    candidate = cost[s]+d*quantum*(-mu[t]+inst.eps_pen+getattr(inst,"deg_cost",0.0))
                    nxt[s-d] = min(nxt[s-d], candidate)
            cost = nxt
        best = min(best, float(cost[initial]))
    return {"unit_reduced_cost": float(inst.c_b+best),
            "minimum_unit_dispatch_cost": best, "quantum": quantum,
            "soc_levels": levels+1, "rate_levels": rate,
            "boundary": "each unit has identical initial and terminal level; level free"}


def _evidence_hashes(folder, result):
    records = []
    for name, expected in result.get("evidence_sha256", {}).items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()):
            raise ValueError("Evidence path escapes worker directory")
        actual = _hash(path) if path.is_file() else None
        records.append({"path": name, "passed": actual == expected})
    return {"passed": bool(records) and all(x["passed"] for x in records),
            "files_checked": len(records), "failures": [x for x in records if not x["passed"]]}


def verify_worker(folder):
    folder = Path(folder).resolve()
    out = {"worker": str(folder), "passed": False, "independently_certified": False,
           "source_certified": False, "verification_tolerance": TOL,
           "scope": "Independent numerical evidence replay and shortest-path pricing; no LP/MIP optimization"}
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
        result = json.loads((folder / "result.json").read_text())
        raw = json.loads((folder / "instance.json").read_text())
        out.update(method=manifest["method"], case=manifest["case"]["case"],
                   repeat=manifest["repeat"], source_status=result.get("status"),
                   source_certified=bool(result.get("certified", False)))
        hashes = _evidence_hashes(folder, result)
        out["evidence_hashes"] = hashes
        local_code = [{"path": name, "passed": (ROOT/name).is_file() and _hash(ROOT/name) == expected}
                      for name, expected in manifest["code_sha256"].items()]
        out["local_reconstruction_code"] = {"passed": all(x["passed"] for x in local_code),
                                            "failures": [x for x in local_code if not x["passed"]]}
        inst = build_case(manifest["case"])
        reconstructed = instance_record(inst)
        body = dict(raw); stored_hash = body.pop("sha256")
        raw_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        instance_ok = raw_hash == stored_hash == reconstructed["sha256"] == manifest["instance_sha256"]
        instance_ok = instance_ok and result.get("instance_sha256") == stored_hash
        out["instance_hash_passed"] = instance_ok
        prerequisites = hashes["passed"] and out["local_reconstruction_code"]["passed"] and instance_ok
        if not prerequisites:
            out["reason"] = "provenance_or_hash_mismatch"; return safe(out)
        graph = build_extended_graph(inst); seeds, proofs = _seeds_with_witnesses(inst)
        out.update(graph_nodes=graph.n_nodes, graph_arcs=graph.n_arcs,
                   seed_count=len(seeds), off_grid_seed_count=sum(p["off_grid_profile"] for p in proofs))
        objective = result.get("objective")
        if objective is None:
            out.update(passed=not out["source_certified"], reason="no_primal_available; metadata_checked")
            return safe(out)
        required_evidence = ({"direct_primal.npz"} if manifest["method"] in ("dual", "barrier")
                             else {"cg_columns.json.gz", "cg_primal.npz"})
        if (folder / "direct_dual.npz").exists():
            required_evidence.add("direct_dual.npz")
        missing_hashes = sorted(required_evidence-set(result.get("evidence_sha256", {})))
        if missing_hashes:
            out.update(reason="raw_evidence_missing_checksum", missing_checksums=missing_hashes)
            return safe(out)
        if manifest["method"] in ("dual", "barrier"):
            with np.load(folder / "direct_primal.npz", allow_pickle=False) as saved:
                vector = saved["x"]
            c, lb, ub, ae, be, au, bu, off = _hybrid_matrices(inst, graph, seeds)
            physical = _hybrid_replay(inst, graph, seeds, proofs, vector, off, objective, False)
            out["physical_replay"] = {"passed": physical["passed"], "residuals": physical["residuals"],
                                      "fleet": physical["fleet"], "batteries": physical["nb"]}
            primal = _primal(c, lb, ub, ae, be, au, bu, vector, objective)
            out["primal_residuals"] = primal
            passed = physical["passed"] and max(primal.values()) <= TOL
            if (folder / "direct_dual.npz").exists():
                with np.load(folder / "direct_dual.npz", allow_pickle=False) as saved:
                    cert = _direct_certificate(c, lb, ub, ae, be, au, bu, vector,
                                               saved["pi_eq"], saved["pi_ub"],
                                               saved["reduced_cost"], objective)
                out["native_dual_reconstruction"] = cert
                out["independently_certified"] = bool(passed and cert["passed"])
            out["passed"] = bool(passed and (not out["source_certified"] or out["independently_certified"]))
        elif manifest["method"] == "cg":
            with gzip.open(folder / "cg_columns.json.gz", "rt") as f:
                records = json.load(f)
            cols = [Column(r["kind"], np.asarray(r["a"]), np.asarray(r["e"]),
                           r["fixed_cost"], r.get("label", "")) for r in records]
            with np.load(folder / "cg_primal.npz", allow_pickle=False) as saved:
                weights = saved["x"]
                vector = np.r_[weights, saved["g"], saved["charge"], saved["discharge"],
                               saved["soc"], float(saved["nb"])]
            c, au, bu, ae, be, bounds, off, n, T, R, ccrow = master._build_lp(inst, cols, True, soc_mode="cyclic")
            lb = np.asarray([0.0 if low is None else low for low, high in bounds])
            ub = np.asarray([np.inf if high is None else high for low, high in bounds])
            primal = _primal(np.asarray(c), lb, ub, sparse.csr_matrix(ae), np.asarray(be),
                              sparse.csr_matrix(au), np.asarray(bu), vector, objective)
            aggregate = replay_rmp(inst, cols, vector, off, bounds, False, objective)
            witnesses = validate_extended_selected_columns(inst, graph, cols, weights, tol=TOL)
            out["primal_residuals"] = primal
            out["physical_replay"] = {"passed": witnesses["passed"],
                "selected_columns": witnesses["selected_count"],
                "max_path_residual": witnesses["max_residual"],
                "aggregate_residuals": aggregate["residuals"],
                "artificial_mass": aggregate["artificial_mass"]}
            duals = result["certificate"]["stopping_duals"]
            alpha, mu, nu = (np.asarray(duals[k]) for k in ("alpha", "mu", "nu"))
            if (alpha.shape != (inst.n_trips,) or mu.shape != (inst.T,) or nu.shape != (inst.T,)
                    or not all(np.all(np.isfinite(v)) for v in (alpha, mu, nu))):
                raise ValueError("Nonfinite or incompatible saved CG dual vectors")
            if not (np.all(np.isinf(np.broadcast_to(inst.gen_cap, (inst.T,)))) and np.isinf(inst.charge_cap)):
                raise ValueError("This CG shared-dual reconstruction expects the declared uncapped family")
            graph_rc = _graph_price(inst, graph, alpha, mu, nu)
            seed_rc = min((s.cost(inst.eps_pen)-float(alpha @ s.a)+float(mu @ s.e)
                           +float(nu @ np.maximum(s.e, 0.0)) for s in seeds), default=float("inf"))
            bess = _periodic_bess_price(inst, mu, nu)
            minimum = min(graph_rc, seed_rc)
            shared_violation = max(_max(-mu), _max(mu-inst.c_g), _max(abs(nu)),
                                   max(0.0, -bess["unit_reduced_cost"]))
            dual_value = float(alpha.sum()+mu @ inst.Delta)
            certified = (max(primal.values()) <= TOL and witnesses["passed"]
                         and aggregate["artificial_mass"] <= TOL
                         and minimum >= -TOL and shared_violation <= TOL
                         and abs(objective-dual_value) <= TOL)
            out["pricing_reconstruction"] = {"graph_min_reduced_cost": graph_rc,
                "seed_min_reduced_cost": seed_rc, "min_reduced_cost": minimum,
                "periodic_bess_oracle": bess, "shared_dual_violation": shared_violation,
                "dual_objective": dual_value, "primal_dual_difference": abs(objective-dual_value),
                "pricing_corrected_bound": dual_value-inst.n_trips*TOL if certified else None,
                "bound_scope": "Numerical dual feasibility at tolerance; route correction does not convert floating point to an exact certificate"}
            out["independently_certified"] = bool(certified)
            out["passed"] = bool(max(primal.values()) <= TOL and witnesses["passed"]
                                  and (not out["source_certified"] or certified))
        else:
            raise ValueError("Not a method worker directory")
        out["reason"] = "verified" if out["passed"] else "numerical_or_claim_check_failed"
    except Exception as exc:
        out.update(passed=False, reason="verification_exception", error=repr(exc))
    return safe(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.input / "result.json").exists():
        folders = [args.input]
    else:
        folders = sorted({p.parent for p in args.input.rglob("result.json")})
    results = [verify_worker(folder) for folder in folders]
    audit = {"workers": len(results), "passed": bool(results) and all(r["passed"] for r in results),
             "independently_certified_workers": sum(r["independently_certified"] for r in results),
             "results": results, "verifier_sha256": _hash(__file__)}
    encoded = json.dumps(safe(audit), indent=2)+"\n"
    if args.output:
        if args.output.exists():
            raise ValueError("Fresh audit output required")
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(encoded)
    print(encoded)
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
