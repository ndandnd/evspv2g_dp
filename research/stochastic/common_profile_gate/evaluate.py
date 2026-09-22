"""Freeze one common truck profile; replay daily full-foresight BESS/generator LPs.

Uses an independent SciPy formulation and a resumable, hash-chained journal with
full per-slot traces. Same-population retrospective decomposition is distinguished
from a 2023-fitted frozen profile evaluated on 2022. Emergency energy is unpriced;
money is reported as an unconditional comparison only on all-day zero shortage.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, vstack

try:
    from .validate import (atomic, digest, inherited_trucks, input_dimensions, input_is_bound, load_json,
                           phases_complete, physical_fingerprint, population_fingerprint, primal_path,
                           sha, validate_primal, verify_sources)
except ImportError:
    from validate import (atomic, digest, inherited_trucks, input_dimensions, input_is_bound, load_json,
                          phases_complete, physical_fingerprint, population_fingerprint, primal_path,
                          sha, validate_primal, verify_sources)


class FixedDispatch:
    """One-day sparse BESS LP with a fixed truck action schedule.

    All weather is supplied at once. This evaluates a nonadaptive truck profile,
    but the storage and generator recourse remains a perfect-information oracle.
    """
    def __init__(self, data, trucks):
        _, T, J = input_dimensions(data)
        self.data, self.T, self.trucks = data, T, {k: np.asarray(v, float) for k, v in trucks.items()}
        ph = data["physics"]
        tc, td = self.trucks["truck_charge"], self.trucks["truck_discharge"]
        if tc.shape != (J, T) or td.shape != (J, T):
            raise ValueError("frozen truck actions have the wrong shape")
        self.net = (tc - td).sum(axis=0)
        self.truck_cost = ph["eps_pen"] * float(tc.sum() + td.sum()) + ph["deg_cost"] * float(td.sum())
        # Variables: c_B[T], d_B[T], s_B[T+1], g[T], u[T].
        self.oc, self.od, self.os, self.og, self.ou = 0, T, 2 * T, 3 * T + 1, 4 * T + 1
        n = 5 * T + 1
        nb, s0 = data["bess"]["units"], data["bess"]["initial"]
        lb, ub = np.zeros(n), np.full(n, np.inf)
        ub[:2 * T] = nb * ph["rho"]
        ub[self.os:self.og] = nb * ph["G"]
        lb[self.os] = ub[self.os] = s0
        lb[self.os + T] = ub[self.os + T] = s0
        if ph.get("gen_cap") is not None:
            ub[self.og:self.ou] = ph["gen_cap"]
        if ph.get("charge_cap") is not None:
            available = ph["charge_cap"] - tc.sum(axis=0)
            if available.min() < -1e-6:
                raise ValueError("frozen truck charging violates the shared charger cap")
            ub[:T] = np.minimum(ub[:T], np.maximum(available, 0))
        rows, cols, values = [], [], []
        for t in range(T):
            rows.extend([t] * 4)
            cols.extend([self.os + t + 1, self.os + t, self.oc + t, self.od + t])
            values.extend([1, -1, -(1 - ph["eta"]), 1])
        self.aeq = coo_matrix((values, (rows, cols)), shape=(T, n)).tocsr()
        rows, cols, values = [], [], []
        for t in range(T):
            rows.extend([t] * 4)
            cols.extend([self.oc + t, self.od + t, self.og + t, self.ou + t])
            values.extend([1, -1, -1, -1])
        self.aub = coo_matrix((values, (rows, cols)), shape=(T, n)).tocsr()
        self.c1, self.c2 = np.zeros(n), np.zeros(n)
        self.c1[self.ou:] = 1
        self.c2[:T] = ph["eps_pen"]
        self.c2[T:2 * T] = ph["eps_pen"] + ph["deg_cost"]
        self.c2[self.og:self.ou] = ph["c_g"]
        self.aeq2 = vstack([self.aeq, self.c1[None, :]], format="csr")
        self.bounds = list(zip(lb, ub))

    def solve(self, delta, date="replay", tolerance=1e-6):
        T = self.T
        rhs = -(np.asarray(delta, dtype=float) + self.net)
        options = {"primal_feasibility_tolerance": 1e-8, "dual_feasibility_tolerance": 1e-8}
        shortage = linprog(self.c1, A_ub=self.aub, b_ub=rhs, A_eq=self.aeq,
                           b_eq=np.zeros(T), bounds=self.bounds, method="highs", options=options)
        if not shortage.success:
            raise RuntimeError("fixed-profile shortage LP: " + shortage.message)
        cost = linprog(self.c2, A_ub=self.aub, b_ub=rhs, A_eq=self.aeq2,
                       b_eq=np.r_[np.zeros(T), shortage.fun], bounds=self.bounds,
                       method="highs", options=options)
        if not cost.success:
            raise RuntimeError("fixed-profile cost LP: " + cost.message)
        z = cost.x
        arrays = dict(self.trucks,
                      bess_charge=z[:T][None, :], bess_discharge=z[T:2 * T][None, :],
                      bess_soc=z[self.os:self.og][None, :], generation=z[self.og:self.ou][None, :],
                      emergency=z[self.ou:][None, :])
        one = dict(self.data, deltas=[list(delta)], dates=[date], probabilities=[1.0])
        checked = validate_primal(one, arrays, tolerance=tolerance)
        if checked["state"] != "valid":
            raise RuntimeError("independent dispatch replay failed: " + repr(checked["errors"]))
        total_op = float(cost.fun + self.truck_cost)
        if abs(total_op - checked["expected_operating_cost"]) > 1e-5 or abs(shortage.fun - checked["expected_emergency"]) > tolerance:
            raise RuntimeError("dispatch objective recomputation mismatch")
        row = {"shortage": float(shortage.fun), "operating_cost": total_op,
               "total_cost": float(total_op + self.data["fixed_asset_cost"]) if shortage.fun <= tolerance else None,
               "max_residual": checked["max_residual"], "generation": float(arrays["generation"].sum()),
               "truck_charge": float(arrays["truck_charge"].sum()), "truck_discharge": float(arrays["truck_discharge"].sum()),
               "bess_charge": float(arrays["bess_charge"].sum()), "bess_discharge": float(arrays["bess_discharge"].sum()),
               "phase_statuses": {"shortage": int(shortage.status), "cost": int(cost.status)}}
        return row, arrays


def read_journal(path):
    records, previous = [], "0" * 64
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            record = json.loads(line)
            saved = record.pop("hash")
            if record["previous"] != previous or record["sequence"] != len(records) or digest(record) != saved:
                raise ValueError("invalid journal chain: " + str(path))
            record["hash"] = saved
            previous = saved
            records.append(record)
    return records, previous


def reference_records(data, case_dir, tolerance=1e-6):
    """Bind old/adaptive values to exact serialized source fleet and boundaries."""
    case_dir = Path(case_dir)
    identity = load_json(case_dir / "identity.json")
    legacy = identity["physics"]
    for key, target in (("G", "G"), ("rho", "rho"), ("eta", "eta"), ("c_g", "c_g"), ("c_b", "c_b"), ("cap", "gen_cap")):
        if data["physics"].get(target) is None or abs(legacy[key] - data["physics"][target]) > tolerance:
            raise ValueError("wave16 physics differs: " + key)
    if data["physics"]["eta"] != 0 or data["physics"]["deg_cost"] != 0 or data["physics"].get("charge_cap") is not None:
        raise ValueError("wave16 reference has eta=0, deg_cost=0 and unlimited charging")
    if not data["physics"].get("allow_discharge", True):
        raise ValueError("wave16 reference allows truck discharge")
    if abs(identity["task"]["bess_units"] - data["bess"]["units"]) > tolerance or abs(data["bess"]["initial"]) > tolerance:
        raise ValueError("wave16 BESS assets/boundaries differ")
    if len(identity["skeletons"]) != len(data["fleet"]):
        raise ValueError("wave16 fleet length differs")
    for j, (source, current) in enumerate(zip(identity["skeletons"], data["fleet"])):
        for key in ("multiplicity", "connected", "withdraw", "incidence", "profile"):
            a, b = np.asarray(source[key], dtype=float), np.asarray(current[key], dtype=float)
            if a.shape != b.shape or np.max(np.abs(a - b), initial=0.0) > tolerance:
                raise ValueError(f"wave16 source fleet {j} differs: {key}")
    records, final = read_journal(case_dir / "days.jsonl")
    status = load_json(case_dir / "status.json")
    if status["state"] != "complete" or status["days"] != len(records) or status["journal_hash"] != final:
        raise ValueError("wave16 reference campaign not complete or journal not bound to status")
    for record in records:
        for prefix in ("fixed", "adaptive"):
            if record[prefix + "_cost"] is not None and abs(record[prefix + "_cost"] - record[prefix + "_operating"] - data["fixed_asset_cost"]) > 1e-4:
                raise ValueError("wave16 fixed asset cost differs")
    return {r["date"]: r for r in records}, {"case_dir": str(case_dir), "identity_sha256": sha(case_dir / "identity.json"),
            "days_sha256": sha(case_dir / "days.jsonl"), "status_sha256": sha(case_dir / "status.json"),
            "journal_hash": final, "task": identity["task"], "source": identity["source"]}


def summarize(records, data, fit_data, stage, reference_available, tolerance=1e-6):
    complete = len(records) == len(data["dates"])
    same = population_fingerprint(data) == population_fingerprint(fit_data)
    p = np.asarray(data["probabilities"][:len(records)], dtype=float)
    if len(p):
        p /= p.sum()
    summary = {"state": "complete" if complete else "partial", "days": len(records), "target_days": len(data["dates"]),
               "same_fit_and_evaluation_population": same,
               "scope": "retrospective development mechanism test" if same else "frozen training-profile evaluation on a different weather population",
               "information": "Truck actions frozen for every day; full-day BESS/generator foresight. This is not a causal control-policy comparison.",
               "cost_convention": "Fixed assets included. Emergency energy is lexicographically minimized and unpriced; all-population money requires zero shortage on every day.",
               "statistics": {}, "errors": []}
    if not records:
        return summary
    labels = ["old", "common"] + (["adaptive"] if reference_available else [])
    for label in labels:
        short = np.asarray([r[label]["shortage"] for r in records])
        cost = [r[label]["total_cost"] for r in records]
        ok = short <= tolerance
        total = np.asarray([np.nan if v is None else v for v in cost])
        summary["statistics"][label] = {"failures": int((~ok).sum()), "mean_shortage": float(p @ short),
                                          "mean_cost_all": float(p @ total) if ok.all() else None,
                                          "mean_operating_all_diagnostic": float(p @ np.asarray([r[label]["operating_cost"] for r in records]))}
    joint = np.asarray([all(r[label]["total_cost"] is not None for label in labels) for r in records])
    summary["jointly_feasible_days"] = int(joint.sum())
    summary["means_on_joint_support"] = {}
    if joint.any():
        q = p[joint] / p[joint].sum()
        for label in labels:
            summary["means_on_joint_support"][label] = float(q @ np.asarray([r[label]["total_cost"] for r, keep in zip(records, joint) if keep]))
    all_zero = bool(joint.all())
    certified = phases_complete(stage)
    if same and complete and certified:
        for field, measured, limit in (("expected_emergency", summary["statistics"]["common"]["mean_shortage"], tolerance),
                                       ("expected_operating_cost", summary["statistics"]["common"]["mean_operating_all_diagnostic"], 1e-4)):
            expected = stage["solution"].get(field)
            if expected is not None and abs(expected - measured) > limit:
                summary["errors"].append("independent same-population replay does not reproduce " + field)
        if summary["statistics"]["common"]["mean_shortage"] > summary["statistics"]["old"]["mean_shortage"] + tolerance:
            summary["errors"].append("same-population minimum shortage exceeds inherited witness")
    if reference_available and all_zero:
        old, common, adaptive = [summary["statistics"][key]["mean_cost_all"] for key in labels]
        gaps = {"old_minus_common": old - common, "common_minus_adaptive": common - adaptive,
                "old_minus_adaptive": old - adaptive,
                "identity_residual": abs((old - common) + (common - adaptive) - (old - adaptive))}
        eligible = same and complete and certified
        summary["decomposition"] = dict(gaps, interpretation="same-population nesting decomposition" if eligible else "signed descriptive contrasts; no cross-population ordering asserted",
                                          nesting_asserted=eligible, solved_common_optimum=certified)
        if eligible:
            for key in ("old_minus_common", "common_minus_adaptive"):
                if gaps[key] < -1e-4:
                    summary["errors"].append("same-population nesting violated: " + key)
        if same and complete and certified:
            expected = stage["solution"].get("expected_total_cost")
            if expected is not None and abs(expected - common) > 1e-4:
                summary["errors"].append("independent same-population replay does not reproduce common LP objective")
    else:
        summary["decomposition"] = None
        summary["comparison_note"] = "Reliability first; no monetary nesting decomposition without full shared zero-shortage support and matching adaptive reference."
    if summary["errors"]:
        summary["state"] = "invalid"
    return summary


def run(input_path, result_path, output_dir, fit_input_path=None, reference_case=None,
        source_root=None, max_days=None, stage_name="common"):
    input_path, result_path, output_dir = Path(input_path), Path(result_path), Path(output_dir)
    fit_input_path = Path(fit_input_path) if fit_input_path else input_path
    data, fit_data, result = load_json(input_path), load_json(fit_input_path), load_json(result_path)
    input_dimensions(data)
    input_dimensions(fit_data)
    if physical_fingerprint(data) != physical_fingerprint(fit_data):
        raise ValueError("fitting/evaluation inputs differ in source skeleton, physics, assets or boundaries")
    if not input_is_bound(fit_data, fit_input_path, result):
        raise ValueError("result is not bound to the fitting input")
    sources = {"evaluation": verify_sources(data, source_root), "fit": verify_sources(fit_data, source_root)}
    if any(v["errors"] for v in sources.values()):
        raise ValueError("source hash verification failed: " + repr(sources))
    stage = result[stage_name]
    artifact = primal_path(result_path, stage)
    artifact_record = stage["solution"]["primal_artifact"]
    if isinstance(artifact_record, dict) and sha(artifact) != artifact_record.get("sha256"):
        raise ValueError("fitting primal artifact hash mismatch")
    with np.load(artifact, allow_pickle=False) as exported:
        checked = validate_primal(fit_data, exported, pinned=stage_name == "inherited")
        trucks = {key: exported[key].copy() for key in ("truck_charge", "truck_discharge", "truck_soc")}
    if checked["state"] != "valid":
        raise ValueError("fitting primal invalid: " + repr(checked["errors"]))
    common_lp, old_lp = FixedDispatch(data, trucks), FixedDispatch(data, inherited_trucks(data))
    reference, reference_identity = ({}, None) if reference_case is None else reference_records(data, reference_case)
    if reference and not all(date in reference for date in data["dates"]):
        raise ValueError("evaluation dates missing in reference")
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = open(output_dir / "lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    identity = {"input_sha256": sha(input_path), "fit_input_sha256": sha(fit_input_path), "result_sha256": sha(result_path),
                "primal_sha256": sha(artifact), "physical_fingerprint": physical_fingerprint(data),
                "fit_population_fingerprint": population_fingerprint(fit_data), "evaluation_population_fingerprint": population_fingerprint(data),
                "evaluator_sha256": sha(__file__), "validator_sha256": sha(Path(__file__).with_name("validate.py")),
                "reference": reference_identity, "stage": stage_name, "sources": sources,
                "numpy": np.__version__, "scipy": scipy.__version__}
    ident_path = output_dir / "identity.json"
    if ident_path.exists() and load_json(ident_path) != identity:
        raise ValueError("resume identity mismatch")
    atomic(ident_path, identity)
    profile_path = output_dir / "frozen_truck_profile.npz"
    if not profile_path.exists():
        np.savez_compressed(profile_path, **trucks)
    else:
        with np.load(profile_path, allow_pickle=False) as saved_profile:
            if any(key not in saved_profile or not np.array_equal(saved_profile[key], value) for key, value in trucks.items()):
                raise ValueError("resume frozen truck profile differs from fitting output")
    records, previous = read_journal(output_dir / "days.jsonl")
    if [r["date"] for r in records] != data["dates"][:len(records)]:
        raise ValueError("resume journal dates differ")
    for record in records:
        if sha(output_dir / record["trace"]) != record["trace_sha256"]:
            raise ValueError("resume trace hash mismatch")
    atomic(output_dir / ("attempt_" + str(time.time_ns()) + ".json"),
           {"hostname": platform.node(), "python": platform.python_version(), "resumed_days": len(records),
            "job_id": os.environ.get("SLURM_JOB_ID"), "restart_count": os.environ.get("SLURM_RESTART_COUNT")})
    end = len(data["dates"]) if max_days is None else min(len(data["dates"]), max_days)
    (output_dir / "traces").mkdir(exist_ok=True)
    for k in range(len(records), end):
        date, delta = data["dates"][k], data["deltas"][k]
        started = time.monotonic()
        common, common_arrays = common_lp.solve(delta, date)
        old, old_arrays = old_lp.solve(delta, date)
        row = {"date": date, "sequence": k, "previous": previous, "common": common, "old": old}
        if reference:
            saved = reference[date]
            cost_error = abs(old["operating_cost"] - saved["fixed_operating"])
            shortage_error = abs(old["shortage"] - saved["fixed_shortage"])
            if cost_error > 1e-4 or shortage_error > 1e-6:
                raise ValueError(f"{date}: old profile replay differs from wave16 ({cost_error=}, {shortage_error=})")
            row["reference_old_errors"] = {"operating_cost": cost_error, "shortage": shortage_error}
            row["adaptive"] = {"shortage": saved["adaptive_shortage"], "operating_cost": saved["adaptive_operating"], "total_cost": saved["adaptive_cost"]}
        trace = Path("traces") / f"{k:04d}.npz"
        np.savez_compressed(output_dir / trace, **{"common_" + key: value for key, value in common_arrays.items()},
                            **{"old_" + key: value for key, value in old_arrays.items()})
        row.update(trace=str(trace), trace_sha256=sha(output_dir / trace), seconds=time.monotonic() - started)
        previous = digest(row)
        row["hash"] = previous
        with open(output_dir / "days.jsonl", "a") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        records.append(row)
        atomic(output_dir / "status.json", {"state": "running", "days": len(records), "journal_hash": previous})
        if len(records) % 25 == 0:
            print(json.dumps({"state": "running", "days": len(records), "target": end}), flush=True)
    summary = summarize(records, data, fit_data, stage, bool(reference))
    summary.update(journal_hash=previous, identity_sha256=sha(ident_path), frozen_profile_sha256=sha(profile_path))
    atomic(output_dir / "status.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="evaluation population JSON")
    parser.add_argument("--fit-input", type=Path, help="fitting population JSON; default evaluation input")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-case", type=Path, help="validated wave16 case directory")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--stage", choices=("common", "inherited"), default="common")
    parser.add_argument("--max-days", type=int)
    args = parser.parse_args()
    try:
        summary = run(args.input, args.result, args.output_dir, args.fit_input, args.reference_case,
                      args.source_root, args.max_days, args.stage)
    except Exception as exc:
        atomic(args.output_dir / "error.json", {"state": "error", "error": repr(exc)})
        raise
    print(json.dumps(summary, allow_nan=False))
    raise SystemExit(1 if summary["state"] == "invalid" else 0)


if __name__ == "__main__":
    main()
