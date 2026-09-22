"""Independent physical, objective and provenance checks for common-profile LP exports.

No model matrices or solver implementation are imported. Truck quantities in primal
files are aggregated by each selected column's multiplicity; truck states/actions
have exactly two dimensions, so a weather-dependent truck policy cannot pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    tmp.replace(path)


def load_json(path):
    return json.loads(Path(path).read_text())


def physical_fingerprint(data):
    """The same source-specific feasible domain, excluding weather and profiles."""
    fields = ("multiplicity", "connected", "withdraw", "incidence")
    return digest({"physics": data["physics"], "bess": data["bess"],
                   "fixed_asset_cost": data["fixed_asset_cost"],
                   "fleet": [{k: f[k] for k in fields if k in f} for f in data["fleet"]],
                   "tasks": data.get("tasks")})


def population_fingerprint(data):
    return digest({k: data[k] for k in ("dates", "deltas", "probabilities")})


def input_is_bound(data, input_path, result):
    return (result.get("input_semantic_sha256") == digest(data)
            or result.get("source_input_sha256") == sha(input_path)
            or result.get("input_sha256") in (sha(input_path), digest(data)))


def phases_complete(stage):
    phases = stage.get("phases", {})
    return bool(phases and all(phases.get(k, {}).get("optimality_certified", phases.get(k, {}).get("complete", False))
                              for k in ("shortage", "cost")))


def resolve_source(path, metadata, source_root=None):
    path = Path(path)
    original = metadata.get("provenance_root", metadata.get("source_root"))
    if source_root is not None:
        if path.is_absolute() and original:
            try:
                return Path(source_root) / path.relative_to(original)
            except ValueError:
                pass
        if not path.is_absolute():
            return Path(source_root) / path
    return path if path.is_absolute() else Path(original or ".") / path


def verify_sources(data, source_root=None):
    metadata = data.get("metadata", {})
    declared = metadata.get("source_hashes", {})
    checked, errors = [], []
    for name, expected in declared.items():
        if isinstance(expected, dict):
            name, expected = expected.get("path", name), expected["sha256"]
        path = resolve_source(name, metadata, source_root)
        actual = sha(path) if path.is_file() else None
        checked.append({"path": str(path), "expected": expected, "actual": actual})
        if actual != expected:
            errors.append("source hash mismatch or missing file: " + str(path))
    return {"state": "verified" if checked and not errors else ("failed" if errors else "not_declared"),
            "checked": checked, "errors": errors}


def input_dimensions(data):
    delta = np.asarray(data["deltas"], dtype=float)
    if delta.ndim != 2 or min(delta.shape) < 1 or not np.isfinite(delta).all():
        raise ValueError("deltas must be a finite nonempty W,T array")
    W, T = delta.shape
    if len(data["dates"]) != W or len(set(data["dates"])) != W:
        raise ValueError("scenario dates must be distinct and align with deltas")
    p = np.asarray(data["probabilities"], dtype=float)
    if p.shape != (W,) or not np.isfinite(p).all() or np.min(p) <= 0 or abs(p.sum() - 1) > 1e-10:
        raise ValueError("scenario probabilities must be positive and sum to one")
    if not data["fleet"]:
        raise ValueError("selected fleet is empty")
    for j, fleet in enumerate(data["fleet"]):
        mult = float(fleet["multiplicity"])
        if not np.isfinite(mult) or mult <= 0 or abs(mult - round(mult)) > 1e-7:
            raise ValueError(f"fleet {j}: multiplicity must be a positive integer")
        for k in ("connected", "withdraw", "profile"):
            a = np.asarray(fleet[k], dtype=float)
            if a.shape != (T,) or not np.isfinite(a).all():
                raise ValueError(f"fleet {j}: malformed {k}")
        if not np.isin(fleet["connected"], [0, 1]).all() or min(fleet["withdraw"]) < 0:
            raise ValueError(f"fleet {j}: invalid connected/withdraw")
    physics = data["physics"]
    for k in ("G", "rho", "c_g", "c_b", "eps_pen", "deg_cost"):
        if not np.isfinite(float(physics.get(k, 0))) or float(physics.get(k, 0)) < 0:
            raise ValueError("invalid physical parameter " + k)
    if not 0 <= float(physics["eta"]) < 1:
        raise ValueError("eta denotes a charging loss fraction in [0,1)")
    for k in ("gen_cap", "charge_cap"):
        v = physics.get(k)
        if v is not None and (not np.isfinite(v) or v < 0):
            raise ValueError("invalid " + k)
    nb, s0 = float(data["bess"]["units"]), float(data["bess"]["initial"])
    if not np.isfinite(nb + s0) or nb < 0 or not 0 <= s0 <= nb * physics["G"]:
        raise ValueError("invalid BESS units/initial state")
    if not np.isfinite(data["fixed_asset_cost"]):
        raise ValueError("nonfinite fixed asset cost")
    return W, T, len(data["fleet"])


def inherited_trucks(data):
    """Reconstruct actions and all states from the serialized inherited profile."""
    _, T, J = input_dimensions(data)
    mult = np.asarray([f["multiplicity"] for f in data["fleet"]])
    e = np.asarray([f["profile"] for f in data["fleet"]]) * mult[:, None]
    withdrawal = np.asarray([f["withdraw"] for f in data["fleet"]]) * mult[:, None]
    s = np.empty((J, T + 1))
    s[:, 0] = mult * data["physics"]["G"]
    s[:, 1:] = s[:, :1] + np.cumsum(e - withdrawal, axis=1)
    return {"truck_charge": np.maximum(e, 0), "truck_discharge": np.maximum(-e, 0), "truck_soc": s}


def validate_primal(data, arrays, pinned=False, tolerance=1e-6):
    """Check every exported action/state against physical equations, independently."""
    W, T, J = input_dimensions(data)
    shapes = {"truck_charge": (J, T), "truck_discharge": (J, T), "truck_soc": (J, T + 1),
              "bess_charge": (W, T), "bess_discharge": (W, T), "bess_soc": (W, T + 1),
              "generation": (W, T), "emergency": (W, T)}
    a = {}
    for key, shape in shapes.items():
        a[key] = np.asarray(arrays[key], dtype=float)
        if a[key].shape != shape or not np.isfinite(a[key]).all():
            raise ValueError(f"{key}: expected finite shape {shape}, got {a[key].shape}")
    p, ph = np.asarray(data["probabilities"]), data["physics"]
    mult = np.asarray([f["multiplicity"] for f in data["fleet"]])
    conn = np.asarray([f["connected"] for f in data["fleet"]], dtype=float)
    withdrawal = mult[:, None] * np.asarray([f["withdraw"] for f in data["fleet"]])
    cap, rate = mult[:, None] * ph["G"], mult[:, None] * ph["rho"] * conn
    nb, s0 = data["bess"]["units"], data["bess"]["initial"]
    tc, td, ts = a["truck_charge"], a["truck_discharge"], a["truck_soc"]
    bc, bd, bs, g, u = (a[k] for k in ("bess_charge", "bess_discharge", "bess_soc", "generation", "emergency"))
    residuals = {}
    def upper(name, values):
        residuals[name] = max(0.0, float(np.max(values, initial=0.0)))
    def equal(name, values):
        residuals[name] = float(np.max(np.abs(values), initial=0.0))
    for key, value in a.items():
        upper(key + "_nonnegative", -value)
    equal("truck_dynamics", ts[:, 1:] - ts[:, :-1] - tc + td + withdrawal)
    equal("truck_initial_full", ts[:, :1] - cap)
    equal("truck_terminal_full", ts[:, -1:] - cap)
    upper("truck_soc_capacity", ts - cap)
    upper("truck_charge_rate_and_connection", tc - rate)
    upper("truck_discharge_rate_and_connection", td - (rate if ph.get("allow_discharge", True) else 0))
    equal("bess_dynamics", bs[:, 1:] - bs[:, :-1] - (1 - ph["eta"]) * bc + bd)
    equal("bess_initial", bs[:, 0] - s0)
    equal("bess_terminal", bs[:, -1] - s0)
    upper("bess_soc_capacity", bs - nb * ph["G"])
    upper("bess_charge_rate", bc - nb * ph["rho"])
    upper("bess_discharge_rate", bd - nb * ph["rho"])
    if ph.get("gen_cap") is not None:
        upper("generation_cap", g - ph["gen_cap"])
    if ph.get("charge_cap") is not None:
        upper("shared_charge_cap", bc + tc.sum(axis=0)[None, :] - ph["charge_cap"])
    net = (tc - td).sum(axis=0)
    upper("energy_balance", np.asarray(data["deltas"]) + net[None, :] + bc - bd - g - u)
    if all("incidence" in f for f in data["fleet"]):
        incidence = np.asarray([f["incidence"] for f in data["fleet"]], dtype=float)
        if incidence.ndim != 2 or not np.isfinite(incidence).all():
            raise ValueError("malformed task incidence")
        if not np.isin(incidence, [0, 1]).all():
            raise ValueError("task incidence is not binary")
        equal("task_coverage", mult @ incidence - 1)
    if pinned:
        old = inherited_trucks(data)
        for key, values in old.items():
            equal("inherited_" + key, a[key] - values)
    truck_cost = ph["eps_pen"] * float(tc.sum() + td.sum()) + ph["deg_cost"] * float(td.sum())
    op = truck_cost + ph["c_g"] * g.sum(axis=1) + ph["eps_pen"] * (bc + bd).sum(axis=1) + ph["deg_cost"] * bd.sum(axis=1)
    short = u.sum(axis=1)
    total = op + float(data["fixed_asset_cost"])
    feasible = short <= tolerance
    worst = max(residuals.values(), default=0.0)
    return {"state": "valid" if worst <= tolerance else "invalid", "max_residual": worst,
            "residuals": residuals, "errors": [f"{k}: {v:.9g}" for k, v in residuals.items() if v > tolerance],
            "common_truck_profile": {"checked": True, "representation": "one J,T action array and J,T+1 state array; shared by all scenarios", "truck_groups": J},
            "scenario_emergency": short.tolist(), "scenario_operating_cost": op.tolist(),
            "scenario_total_cost": [float(v) if ok else None for v, ok in zip(total, feasible)],
            "expected_emergency": float(p @ short), "expected_operating_cost": float(p @ op),
            "expected_total_cost": float(p @ total) if feasible.all() else None,
            "economic_value_at_lexicographic_shortage": float(p @ total), "zero_shortage_all": bool(feasible.all()),
            "expected_feasible_cost_all": float(p @ total) if feasible.all() else None,
            "profile": (tc - td).tolist(), "profile_per_unit": ((tc - td) / mult[:, None]).tolist()}


def primal_path(result_path, stage):
    result_path = Path(result_path)
    artifact = stage["solution"]["primal_artifact"]
    if isinstance(artifact, dict):
        artifact = artifact["path"]
    path = Path(artifact)
    return path if path.is_absolute() else result_path.parent / path


def validate_result(input_path, result_path, source_root=None, tolerance=1e-6, cost_tolerance=1e-4):
    data, result = load_json(input_path), load_json(result_path)
    sources = verify_sources(data, source_root)
    report = {"state": "valid", "input_sha256": sha(input_path), "result_sha256": sha(result_path),
              "validator_sha256": sha(__file__), "physical_fingerprint": physical_fingerprint(data),
              "sources": sources, "errors": list(sources["errors"]), "stages": {}}
    # Solvers may serialize either the source file hash or canonical input hash.
    if not input_is_bound(data, input_path, result):
        report["errors"].append("result input_sha256 does not identify the provided input")
    for key in ("inherited", "common"):
        stage = result.get(key)
        if not stage or not stage.get("solution"):
            continue
        path = primal_path(result_path, stage)
        with np.load(path, allow_pickle=False) as arrays:
            checked = validate_primal(data, arrays, pinned=key == "inherited", tolerance=tolerance)
        checked["primal_sha256"] = sha(path)
        solution = stage["solution"]
        artifact = solution["primal_artifact"]
        if isinstance(artifact, dict) and artifact.get("sha256") != sha(path):
            checked["errors"].append("primal artifact hash mismatch")
        for field in ("expected_emergency", "expected_operating_cost", "expected_total_cost", "scenario_emergency", "scenario_operating_cost", "profile", "profile_per_unit"):
            if field in solution:
                if solution[field] is None or checked[field] is None:
                    if solution[field] != checked[field]:
                        checked["errors"].append("reported solution mismatch: " + field)
                    continue
                reported = np.asarray(solution[field], dtype=float)
                recomputed = np.asarray(checked[field], dtype=float)
                limit = cost_tolerance if "cost" in field else tolerance
                if reported.shape != recomputed.shape or not np.isfinite(reported).all() or np.max(np.abs(reported - recomputed), initial=0.0) > limit:
                    checked["errors"].append("reported solution mismatch: " + field)
        phases = stage.get("phases", {})
        for phase, field, limit in (("shortage", "expected_emergency", tolerance), ("cost", "expected_operating_cost", cost_tolerance)):
            item = phases.get(phase, {})
            if item.get("objective") is not None and abs(item["objective"] - checked[field]) > limit:
                checked["errors"].append("lexicographic " + phase + " objective mismatch")
            for artifact_key in ("primal_artifact", "dual_artifact"):
                saved = item.get(artifact_key)
                if isinstance(saved, dict):
                    saved_path = Path(saved["path"])
                    saved_path = saved_path if saved_path.is_absolute() else Path(result_path).parent / saved_path
                    if not saved_path.is_file() or sha(saved_path) != saved.get("sha256"):
                        checked["errors"].append(phase + " " + artifact_key + " hash mismatch")
            if item.get("log") and item.get("log_sha256"):
                log = Path(result_path).parent / item["log"]
                if not log.is_file() or sha(log) != item["log_sha256"]:
                    checked["errors"].append(phase + " native log hash mismatch")
        target = phases.get("cost", {}).get("lexicographic_shortage_target")
        if target is not None and abs(target - checked["expected_emergency"]) > tolerance:
            checked["errors"].append("cost-phase shortage target mismatch")
        checked["phases_complete"] = phases_complete(stage)
        if checked["errors"]:
            checked["state"] = "invalid"
        report["stages"][key] = checked
        report["errors"].extend(key + ": " + e for e in checked["errors"])
    if not report["stages"]:
        report["errors"].append("no primal solution to validate")
    old, common = report["stages"].get("inherited"), report["stages"].get("common")
    if old and common and common["phases_complete"]:
        if common["expected_emergency"] > old["expected_emergency"] + tolerance:
            report["errors"].append("common minimum shortage exceeds the inherited feasible witness")
        if common["zero_shortage_all"] and old["zero_shortage_all"] and common["expected_total_cost"] > old["expected_total_cost"] + cost_tolerance:
            report["errors"].append("common zero-shortage cost exceeds the inherited feasible witness")
    report["state"] = "invalid" if report["errors"] else "valid"
    report["optimality_note"] = "Physical feasibility and cost recomputation are independent. Optimality additionally requires completed solver phases and valid LP bounds; a valid time-limited primal is only a feasible witness."
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    try:
        report = validate_result(args.input, args.result, args.source_root)
    except Exception as exc:
        report = {"state": "invalid", "errors": [repr(exc)]}
    atomic(args.output or args.result.parent / "validation.json", report)
    print(json.dumps({"state": report["state"], "errors": report["errors"]}))
    raise SystemExit(0 if report["state"] == "valid" else 1)


if __name__ == "__main__":
    main()
