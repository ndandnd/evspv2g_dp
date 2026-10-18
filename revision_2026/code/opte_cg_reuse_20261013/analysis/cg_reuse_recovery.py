"""Read-only recovery-map validation and complete execution accounting.

Only scheduling provenance is handled here. This module never submits jobs,
changes the frozen runtime, copies results, or chooses attempts by performance.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re

from run_cg_reuse import VARIANTS, experiment_plan

ROOT = Path(__file__).resolve().parent
POLICY = ROOT/"CG_REUSE_RECOVERY_POLICY.md"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("Recovery registration timestamps require a UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def confined(base, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Recovery block paths must be relative to the input collection")
    result = (base/relative).resolve()
    if result == base or base not in result.parents:
        raise ValueError("Recovery block path escapes its input collection")
    return result


def submitted_node(registration):
    """Require a successful, single-node, explicit Slurm submission receipt."""
    if (registration.get("status") != "submitted" or registration.get("returncode") != 0
            or not str(registration.get("job_id", "")).isdigit()):
        raise ValueError("Recovery requires a successfully submitted registration receipt")
    command = registration.get("command")
    if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
        raise ValueError("Recovery submission must retain its structured command")
    nodes = []
    for i, arg in enumerate(command):
        if arg.startswith("--nodelist="): nodes.append(arg.split("=", 1)[1])
        elif arg in ("--nodelist", "-w") and i+1 < len(command): nodes.append(command[i+1])
    if len(nodes) != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", nodes[0]):
        raise ValueError("Recovery submission must request exactly one explicit node")
    return nodes[0].lower().rstrip(".")


def normalized_host(host):
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise ValueError("Recovery manifest is missing a valid host name")
    return host.lower().rstrip(".")


def preemption_receipt(spec, map_dir):
    path = (map_dir/spec["path"]).resolve()
    if not path.is_file() or digest(path) != spec["sha256"]:
        raise ValueError("Preemption receipt digest mismatch")
    raw = path.read_text(); wrapped = None
    if raw.lstrip().startswith("{"):
        wrapped = json.loads(raw)
        if wrapped.get("returncode", 0) != 0: raise ValueError("Accounting command failed")
        raw = wrapped["stdout"]
    fields = spec.get("fields") or (wrapped or {}).get("sacct_fields") or ["JobID", "State", "ElapsedRaw", "AllocCPUS"]
    id_field = "JobID" if "JobID" in fields else "JobIDRaw"
    if id_field not in fields or "State" not in fields:
        raise ValueError("Accounting receipt needs JobID and State fields")
    candidates = []; preempted_ids = []
    for line in raw.splitlines():
        values = line.split("|")
        if len(values) < len(fields): continue
        row = dict(zip(fields, (v.strip() for v in values)))
        if row["State"].split() and row["State"].split()[0].rstrip("+") == "PREEMPTED":
            preempted_ids.append(row[id_field])
        if row[id_field] == spec["job_id"]: candidates.append(row)
    if len(candidates) != 1:
        raise ValueError("Receipt must contain exactly one matching parent job row")
    row = candidates[0]
    if row["State"].split()[0].rstrip("+") != "PREEMPTED":
        raise ValueError("Only an external PREEMPTED scheduler state permits recovery")
    return {"path": str(path), "sha256": spec["sha256"], "job_id": spec["job_id"],
            "state": "PREEMPTED", "accounting_fields": row,
            "preempted_ids_in_receipt": preempted_ids}


def load_recovery_map(path, base):
    if path is None:
        return {}, {"used": False, "registered_recovery_blocks": 0}
    path = Path(path).resolve(); base = Path(base).resolve(); data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or data.get("policy_sha256") != digest(POLICY):
        raise ValueError("Recovery schema/policy hash mismatch")
    policy_time = utc(data["policy_registered_utc"])
    array_job = str(data["original_array_job_id"])
    plan = {b["block_index"]: b for b in experiment_plan()}
    selected = {}; records = []
    for entry in data["entries"]:
        index = entry["block_index"]
        if index not in plan: raise ValueError("Recovery refers to an unplanned block")
        block = plan[index]; key = block["case_name"], block["repeat"]
        if key in selected: raise ValueError("More than one recovery for a logical block is forbidden")
        registered = utc(entry["registered_utc"])
        if registered < policy_time: raise ValueError("Recovery registered before its prospective policy")
        if not entry.get("registration_receipt"):
            raise ValueError("A digest-bound prospective registration/submission receipt is mandatory")
        ref = entry["registration_receipt"]; receipt_path = (path.parent/ref["path"]).resolve()
        if not receipt_path.is_file() or digest(receipt_path) != ref["sha256"]:
            raise ValueError("Recovery registration receipt digest mismatch")
        registration = json.loads(receipt_path.read_text())
        requested_node = submitted_node(registration)
        if (utc(registration["utc"]) != registered or index not in registration["indices"]
                or registration.get("policy_sha256") != data["policy_sha256"]
                or registration.get("scientific_outcomes_used") is not False
                or registration.get("selection_basis") != "scheduler_PREEMPTED_without_completed_block"):
            raise ValueError("Recovery registration differs from its preserved submission receipt")
        original = confined(base, entry["original_relative_dir"])
        recovery = confined(base, entry["recovery_relative_dir"])
        if original == recovery or original in recovery.parents or recovery in original.parents:
            raise ValueError("Original and recovery directories must be separate")
        if not (original/"manifest.json").is_file(): raise ValueError("Original block manifest missing")
        manifest = json.loads((original/"manifest.json").read_text())
        if (manifest.get("variant") != "all" or manifest.get("case", {}).get("case") != key[0]
                or manifest.get("repeat") != key[1]):
            raise ValueError("Original block identity disagrees with recovery registration")
        if (original/"block_summary.json").is_file():
            summary = json.loads((original/"block_summary.json").read_text())
            if summary.get("completed") is True:
                raise ValueError("A completed original block is not eligible for recovery")
        receipt = preemption_receipt(entry["preemption_receipt"], path.parent)
        if receipt["job_id"] != f"{array_job}_{index}":
            raise ValueError("Preemption receipt belongs to a different array block")
        hashes = entry.get("original_artifact_sha256", entry.get("original_artifact_hashes"))
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError("Recovery registration must preserve all original artifact hashes")
        prefix = f"results/block_{index}/"
        registered_hashes = {k[len(prefix):]: v for k, v in
            registration.get("original_artifact_sha256", {}).items() if k.startswith(prefix)}
        if hashes != registered_hashes:
            raise ValueError("Original artifact hashes differ from the prospective submission receipt")
        if receipt["sha256"] != registration.get("accounting_sha256"):
            raise ValueError("Accounting receipt differs from the prospective registration")
        if entry.get("recovery_job_id") != f"{registration['job_id']}_{index}":
            raise ValueError("Recovery job identity differs from its submission receipt")
        actual_paths = {str(f.relative_to(original)) for f in original.rglob("*") if f.is_file()}
        if set(hashes) != actual_paths:
            raise ValueError("Original artifact inventory changed or was incompletely registered")
        for relative, expected in hashes.items():
            item = confined(original, relative)
            if isinstance(expected, dict): expected = expected["sha256"]
            if digest(item) != expected: raise ValueError(f"Original artifact was altered: {relative}")
        recovery_host = None
        worker_manifests = [recovery/v/"manifest.json" for v in VARIANTS if (recovery/v/"manifest.json").is_file()]
        if worker_manifests and not (recovery/"manifest.json").is_file():
            raise ValueError("Recovery workers require a containing block manifest")
        if (recovery/"manifest.json").is_file():
            recovered = json.loads((recovery/"manifest.json").read_text())
            recovery_host = normalized_host(recovered.get("environment", {}).get("host"))
            if (recovery_host != requested_node if "." in requested_node
                    else recovery_host.split(".")[0] != requested_node):
                raise ValueError("Recovery block host differs from its submitted node")
            for name in ("case", "repeat", "variant", "budget_seconds", "max_cg_iterations",
                         "worker_watchdog_grace_seconds", "instance_sha256", "code_sha256",
                         "vendor_manifest", "protocol"):
                if recovered.get(name) != manifest.get(name):
                    raise ValueError(f"Recovery changed frozen block metadata: {name}")
            for field in ("cpu_model", "gurobi", "python", "numpy", "scipy"):
                if recovered.get("environment", {}).get(field) != manifest.get("environment", {}).get(field):
                    raise ValueError(f"Recovery changed runtime environment: {field}")
            for file in [recovery/"manifest.json"]+worker_manifests:
                observed = json.loads(file.read_text())
                if normalized_host(observed.get("environment", {}).get("host")) != recovery_host:
                    raise ValueError("Recovery worker host differs from its block manifest")
                if utc(observed["started_utc"]) < registered:
                    raise ValueError("Recovery began before prospective registration")
        second = (preemption_receipt(entry["recovery_preemption_receipt"], path.parent)
                  if entry.get("recovery_preemption_receipt") else None)
        if second and second["job_id"] != entry.get("recovery_job_id"):
            raise ValueError("Second preemption receipt belongs to a different recovery job")
        selected[key] = {"original": original, "recovery": recovery,
                         "original_preemption": receipt, "recovery_preemption": second,
                         "registered_utc": entry["registered_utc"], "block_index": index}
        records.append({"block_index": index, "case": key[0], "repeat": key[1],
            "registered_utc": entry["registered_utc"], "original_folder": str(original),
            "selected_recovery_folder": str(recovery), "original_artifacts_preserved": len(hashes),
            "original_preemption": receipt, "recovery_preemption": second,
            "submission_receipt_path": str(receipt_path), "submission_receipt_sha256": ref["sha256"],
            "submitted_node": requested_node, "observed_recovery_host": recovery_host,
            "worker_hosts_checked": len(worker_manifests),
            "selection_rule": "One whole registered recovery, independent of its outcomes; no fallback or mixing"})
    for item in selected.values():
        for job_id in item["original_preemption"]["preempted_ids_in_receipt"]:
            prefix = array_job+"_"
            suffix = job_id[len(prefix):] if job_id.startswith(prefix) else ""
            if suffix.isdigit() and int(suffix) in plan:
                b = plan[int(suffix)]; key = b["case_name"], b["repeat"]
                original = base/f"block_{int(suffix)}"
                completed = ((original/"block_summary.json").is_file()
                    and json.loads((original/"block_summary.json").read_text()).get("completed") is True)
                if not completed and key not in selected:
                    raise ValueError("Receipt contains another eligible preempted block omitted from recovery registration")
    return selected, {"used": True, "path": str(path), "sha256": digest(path),
        "policy_path": str(POLICY), "policy_sha256": digest(POLICY),
        "policy_registered_utc": data["policy_registered_utc"],
        "registered_recovery_blocks": len(selected), "entries": records}


def execution_ledger(block, folder, attempt, selected, preemption=None):
    """Three execution slots, including unstarted slots and partial evidence."""
    rows = []
    for variant in VARIANTS:
        worker = folder/variant if folder is not None else None
        result_path = worker/"result.json" if worker is not None else None
        manifest_path = worker/"manifest.json" if worker is not None else None
        result = json.loads(result_path.read_text()) if result_path and result_path.is_file() else None
        started = bool(manifest_path and manifest_path.is_file())
        if result is not None: state = "saved_result"
        elif started and preemption: state = "externally_preempted_without_saved_result"
        elif started: state = "started_without_saved_result"
        elif preemption: state = "not_started_before_external_preemption"
        else: state = "not_started_or_missing"
        row = {"case": block["case_name"], "repeat": block["repeat"], "block_index": block["block_index"],
            "variant": variant, "attempt": attempt, "selected_for_logical_outcome": selected,
            "worker_folder": str(worker) if worker else None, "started": started,
            "saved_result": result is not None, "execution_state": state,
            "block_scheduler_state": "PREEMPTED" if preemption else None,
            "scheduler_receipt": preemption,
            "result_sha256": digest(result_path) if result is not None else None,
            "manifest_sha256": digest(manifest_path) if started else None,
            "source_status": result.get("status") if result else None,
            "source_certified": result.get("certified") if result else None,
            "source_native_status": result.get("native_status") if result else None,
            "source_objective": result.get("objective") if result else None,
            "source_algorithm_stop_seconds": result.get("solve_end_to_end_seconds") if result else None,
            "algorithm_time_censor_from_scheduler_preemption": False}
        rows.append(row)
    return rows


def execution_counts(rows):
    out = {}
    for attempt in ("original", "recovery"):
        selected = [r for r in rows if r["attempt"] == attempt]
        out[attempt] = {"planned_execution_arm_slots": len(selected),
            "workers_started": sum(r["started"] for r in selected),
            "saved_result_outcomes": sum(r["saved_result"] for r in selected),
            "selected_logical_slots": sum(r["selected_for_logical_outcome"] for r in selected),
            "externally_preempted_without_saved_result": sum(r["execution_state"] == "externally_preempted_without_saved_result" for r in selected),
            "unstarted_slots": sum(not r["started"] for r in selected)}
    return out
