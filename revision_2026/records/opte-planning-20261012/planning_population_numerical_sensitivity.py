"""Uniform no-solve primal repair and numerical sensitivity, separate from primary.

All original worker evidence and the prespecified 1e-6 analysis are preserved.
The same constructive repair is applied to every saved incumbent, including
already feasible ones. No outcome selects a case or a computation budget.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import summarize_planning_population as audit

PROOF = """# Uniform constructive primal validation and numerical sensitivity

This is a separately labeled post-solve check. It preserves the original
prespecified 1e-6 analysis and all 1,080 cold-solve results. It does not optimize,
rerun, drop or select a configuration. Native lower bounds remain floating-point
solver evidence.

The planning family has lossless storage, uncapped generation and aggregate
charging, identical nonnegative costs, and periodic BESS. For every incumbent,
round its truck-path multiplicities and BESS count to integers. Require exact
task coverage by the rounded multiplicities and independently replay the same
grid-valid physical truck paths. Let u be the saved BESS SoC clipped into
[0,G*Nb], with u[T]=u[0]. Let h=max(abs(diff(u))) and lambda=min(1,rho*Nb/h),
using lambda=1 when h=0. For Nb=0 use the identically zero state. The repaired
state s=lambda*u+(1-lambda)*u[0] is periodic, in capacity, and its increments
obey the rate limit. A tiny outward floating-point guard is used when scaling
is necessary. Set charge=max(diff(s),0) and discharge=max(-diff(s),0). Finally
set generation=max(Delta+truck_net+charge-discharge,0). Uncapped generation makes
this a feasible dispatch; no simultaneous BESS actions remain. Evaluate all
costs, including gross throughput. Independent physical and original-vendor
master-row checks verify the repaired vector. The same vector is replayed in
every permitted more flexible technology configuration before transferring its
upper bound.

Intervals use the new native bound minus an allowance and the repaired feasible
objective plus that allowance. We report the same uniformly applied allowances
1e-6, 1e-4 and 1e-3 dollars for all 1,080 configurations. Technology nesting,
ratio endpoints, denominator checks and exact even-population median rules are
unchanged. No original rounded incumbent or selected 1,800-second result enters
these sensitivities. Changes to sign counts are numerical validation effects,
not new optimization results or revised benchmark timings.

A separate share statistic concerns the population of all bases whose true
joint savings are positive. Every base with a positive lower saving bound must
belong to this population; the remaining bases have unknown membership. If
their joint savings are zero, their share is undefined and they do not belong.
Every defined share lies in [0,1] by technology nesting alone. To bound the
median over every possible membership, append one zero per uncertain member
to the lower endpoints of the certain members, and one one per uncertain
member to their upper endpoints. The median is coordinatewise monotone.
Moreover, adding a zero cannot increase a median of [0,1] values, and adding
a one cannot decrease it; this holds for both the odd median and the mean of
the two central order statistics for even populations. Consequently these
padded medians bound every admissible positive-saving population, including
every possible subset of uncertain members. No uncertain member is silently
discarded, and no strict positivity of a numerical tie is assumed. This is a
secondary estimand, distinct from the conditional all-270-base share analysis.
"""


def repair(worker):
    folder = Path(worker["directory"])
    require = audit.require
    require(audit.sha(folder / "result.json") == worker["result_sha256"],
            "Source result changed since the primary audit")
    raw = audit.read(folder / "instance.json")
    result = audit.read(folder / "result.json")
    for name, expected in result["evidence_sha256"].items():
        require(audit.sha(folder / name) == expected,
                f"Source evidence changed since the primary audit: {name}")
    with gzip.open(folder / "physical_replay.json.gz", "rt") as stream:
        val = json.load(stream)
    inst = audit.instance_from_record(raw)
    require(inst.eta == inst.deg_cost == 0, "Repair scope requires lossless storage and zero extra discharge cost")
    require(raw["generation_cap"] == raw["charging_cap"] == "unbounded"
            and raw["stationary_boundary"] == "periodic",
            "Repair scope requires uncapped generation/charging and periodic stationary storage")
    original, columns = audit.replay_direct(inst, {**result, "validation": val}, True)
    fixed = copy.deepcopy(val)
    for p in fixed["paths"] + fixed.get("singleton_paths", []):
        p["weight"] = int(round(p["weight"]))
        require(p["weight"] > 0, "Rounded selected path has zero multiplicity")
    weights = np.asarray([p["weight"] for p in fixed["paths"]+fixed.get("singleton_paths", [])])
    coverage = sum((w*c.a for w,c in zip(weights, columns)), np.zeros(inst.n_trips))
    require(np.array_equal(coverage, np.ones(inst.n_trips)), "Rounded routes fail exact task coverage")
    truck_net = sum((w*c.e for w,c in zip(weights, columns)), np.zeros(inst.T))
    nb = int(round(fixed["nb"]))
    require(nb >= 0, "Rounded battery count must be nonnegative")
    u = np.clip(np.asarray(fixed["battery_soc"]), 0, inst.G*nb)
    u[-1] = u[0]
    h = float(np.max(abs(np.diff(u)), initial=0))
    if nb == 0:
        soc = np.zeros(inst.T+1); scale = 0.
    elif h > inst.rho*nb:
        scale = math.nextafter(inst.rho*nb/h, 0.)
        soc = scale*u+(1-scale)*u[0]
    else:
        scale = 1.; soc = u
    soc[-1] = soc[0]
    changes = np.diff(soc)
    charge = np.maximum(changes, 0); discharge = np.maximum(-changes, 0)
    generation = np.maximum(inst.Delta+truck_net+charge-discharge, 0)
    objective = float(sum(w*c.cost(inst.eps_pen) for w,c in zip(weights, columns))
        + inst.c_g*generation.sum()+inst.c_b*nb+inst.eps_pen*(charge.sum()+discharge.sum()))
    fixed.update(nb=nb, generation=generation.tolist(), battery_charge=charge.tolist(),
        battery_discharge=discharge.tolist(), battery_soc=soc.tolist(),
        fleet=int(weights.sum()), dag_fleet=sum(p["weight"] for p in fixed["paths"]),
        singleton_fleet=sum(p["weight"] for p in fixed.get("singleton_paths", [])))
    repaired_result = {**result, "objective": objective, "validation": fixed}
    physical, repaired_columns = audit.replay_direct(inst, repaired_result, True)
    audit.scenario_replay(fixed, worker["scenario"])
    vendor = audit.original_master_replay(inst, repaired_result, fixed, repaired_columns, worker["scenario"])
    require(max(physical["residuals"].values()) <= 1e-9
            and max(vendor["residuals"].values()) <= 1e-9, "Constructive repair leaves excessive residuals")
    for target in worker["upper_bound_transfers"]:
        audit.scenario_replay(fixed, target)
        audit.original_master_replay(inst, repaired_result, fixed, repaired_columns, target)
    objective = max(objective, physical["replayed_objective"], vendor["objective"])
    require(worker["bound"] <= objective+1e-6,
            "Native lower bound exceeds the repaired feasible objective plus the smallest allowance")
    return {"case": worker["case"], "scenario": worker["scenario"],
        "source_result_sha256": audit.sha(folder / "result.json"),
        "original_objective": result["objective"], "repaired_objective": objective,
        "objective_change": objective-result["objective"], "soc_scaling_factor": scale,
        "native_bound_minus_repaired_objective": worker["bound"]-objective,
        "source_evidence_digests_revalidated": True,
        "independent_physical_replay": physical, "original_vendor_master": vendor,
        "upper_bound_transfers_revalidated": worker["upper_bound_transfers"],
        "profile": {k:fixed[k] for k in ("nb", "generation", "battery_charge", "battery_discharge",
                                         "battery_soc", "fleet", "dag_fleet", "singleton_fleet")},
        "path_weights": weights.tolist()}


def positive_population_envelope(bases):
    certain = [b for b in bases if b["strictly_positive_joint_saving_certified"]]
    uncertain = [b for b in bases if not b["strictly_positive_joint_saving_certified"]]
    audit.require(certain, "The positive-saving population must be nonempty")
    metrics = {}
    for name in ("BESS_share", "V2G_alone_share"):
        lower = sorted([b["metrics"][name][0] for b in certain]+[0.]*len(uncertain))
        upper = sorted([b["metrics"][name][1] for b in certain]+[1.]*len(uncertain))
        interval = [audit.median(lower), audit.median(upper)]
        headline, places = audit.METRICS[name]
        metrics[name] = {"median_interval": interval,
            "median_interval_percent_outward_2dp": [math.floor(interval[0]*10000)/100,
                                                     math.ceil(interval[1]*10000)/100],
            "rounding_decision": audit.rounded_claim(interval, headline, places, True)}
    return {"scope": "Secondary envelope for the median among all truly positive-joint-saving bases; unknown membership retained",
        "possible_population_size": [len(certain), len(bases)],
        "uncertain_members": [b["case"] for b in uncertain],
        "uncertain_members_assigned_interval": [0., 1.],
        "padded_population_size": len(bases),
        "median_rule": "Mean of padded order statistics 135 and 136",
        "metrics": metrics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require = audit.require
    require(not args.output_dir.exists(), "Fresh derived output directory required")
    primary = audit.read(args.primary)
    require(primary["summary"]["all_workers_present_and_audited"], "Complete independently audited primary required")
    rows = []
    for index, worker in enumerate(primary["workers"]):
        rows.append(repair(worker))
        if (index+1)%270 == 0: print(f"Repaired and checked {index+1}/1080 saved incumbents", flush=True)
    specs = audit.read(audit.INPUTS)["cases"]
    sensitivities = {}
    for allowance in (1e-6, 1e-4, 1e-3):
        audit.TOL = allowance
        workers = copy.deepcopy(primary["workers"])
        for worker, corrected in zip(workers, rows):
            worker["validated_upper_bound"] = corrected["repaired_objective"]+allowance
            worker["independent_physical_replay"] = corrected["independent_physical_replay"]
            worker["original_vendor_master"] = corrected["original_vendor_master"]
        bases = [audit.summarize_base(spec, workers[4*i:4*i+4]) for i,spec in enumerate(specs)]
        require(all(b["passed"] for b in bases), "Repaired intervals inconsistent")
        sensitivities[str(allowance)] = {"allowance_dollars": allowance,
            "summary": audit.population_summary(bases, workers), "bases": bases,
            "positive_saving_population_envelope": positive_population_envelope(bases)}
    report = {"optimization_performed": False, "original_primary_sha256": audit.sha(args.primary),
        "original_primary_path": str(args.primary.resolve()), "checker_sha256": audit.sha(__file__),
        "interval_analyzer_sha256": audit.sha(audit.__file__),
        "scope": "Uniformly repaired saved incumbents and separately labeled post-solve numerical sensitivities; original primary unchanged",
        "repair_summary": {"count": len(rows),
            "minimum_objective_change": min(r["objective_change"] for r in rows),
            "maximum_objective_increase": max(r["objective_change"] for r in rows),
            "maximum_native_bound_minus_repaired_objective": max(r["native_bound_minus_repaired_objective"] for r in rows),
            "maximum_physical_residual": max(max(r["independent_physical_replay"]["residuals"].values()) for r in rows),
            "maximum_vendor_residual": max(max(r["original_vendor_master"]["residuals"].values()) for r in rows)},
        "sensitivities": sensitivities}
    args.output_dir.mkdir(parents=True)
    with gzip.open(args.output_dir / "repaired_profiles.json.gz", "wt") as stream:
        json.dump(rows, stream, allow_nan=False)
    report["repaired_profiles_sha256"] = audit.sha(args.output_dir / "repaired_profiles.json.gz")
    (args.output_dir / "numerical_sensitivity.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    (args.output_dir / "repair_proof.md").write_text(PROOF)
    compact = {key: {"positive_joint":v["summary"]["bases_with_positive_joint_saving_certified"],
        "strict_conditional_V2G":v["summary"]["bases_with_strict_additional_V2G_with_BESS_certified"],
        "outward_percent_intervals":{m:x["median_interval_percent_outward_2dp"] for m,x in v["summary"]["metrics"].items()}}
        for key,v in sensitivities.items()}
    print(json.dumps({"repair_summary": report["repair_summary"], "sensitivities":compact}, indent=2))


if __name__ == "__main__":
    main()
