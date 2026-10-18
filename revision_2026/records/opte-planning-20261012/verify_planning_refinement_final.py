"""Independent no-solve scalar/provenance cross-check of the final refinement.

Uses only the Python standard library. It does not import the population
analyzer, repair code, graph builder, optimizer, or its interval functions.
Decimal calculations verify reported floating-point arithmetic; they do not
turn native solver lower bounds into exact mathematical certificates.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, getcontext
import gzip
import hashlib
import json
from pathlib import Path

getcontext().prec = 50
ROOT = Path(__file__).resolve().parent
ARMS = ("solar", "solar_bess", "v2g_fleet", "v2g")
METRICS = {"BESS_share": (96, 0), "V2G_alone_share": (62, 0),
    "V2G_alone_daily_reduction": (19.6, 1),
    "V2G_with_BESS_daily_reduction_low_gamma": (.6, 1),
    "V2G_with_BESS_daily_reduction_high_gamma": (9.3, 1)}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dec(x):
    return Decimal(str(x))


def med(xs):
    xs = sorted(xs); n = len(xs)
    return xs[n//2] if n % 2 else (xs[n//2-1]+xs[n//2])/2


def outward(pair):
    return [float((pair[0]*10000).to_integral_value(rounding=ROUND_FLOOR)/100),
            float((pair[1]*10000).to_integral_value(rounding=ROUND_CEILING)/100)]


def share(z, arm):
    a, b, d = z["solar"], z[arm], z["v2g"]
    lo = max(Decimal(0), a[0]-b[1])/(a[0]-d[0]) if a[0] > d[0] else Decimal(0)
    edge = min(d[1], b[0])
    hi = (a[1]-b[0])/(a[1]-edge) if a[1] > edge else Decimal(1)
    return [max(Decimal(0), lo), min(Decimal(1), hi)]


def reduction(z, a, b):
    return [max(Decimal(0), 1-z[b][1]/z[a][0]), min(Decimal(1), 1-z[b][0]/z[a][1])]


def verify(folder):
    summary_path = folder/"refinement_summary.json"
    report = read(summary_path)
    primary_path = ROOT/"results/planning_population_analysis_final_20261012/population_summary.json"
    repair_dir = ROOT/"results/planning_population_numerical_sensitivity_verified_20261012"
    prior = read(primary_path)
    repair_report = read(repair_dir/"numerical_sensitivity.json")
    with gzip.open(repair_dir/"repaired_profiles.json.gz", "rt") as stream:
        repaired_old = {(w["case"], w["scenario"]): w for w in json.load(stream)}
    checks = Counter()
    def require(ok, category):
        if not ok: raise AssertionError(category)
        checks[category] += 1
    def same(x, y, category, tolerance=Decimal("5e-10")):
        if isinstance(x, (list, tuple)):
            require(len(x) == len(y), category+" dimension")
            for a, b in zip(x, y): same(a, b, category, tolerance)
        else:
            require(abs(dec(x)-dec(y)) <= tolerance, category)

    workers = report["workers"]
    selection = read(ROOT/"planning_refinement_inputs.json")["selected"]
    old = {(w["case"], w["scenario"]): w for w in prior["workers"]}
    new = {(w["case"], w["scenario"]): w for w in workers}
    expected = {key for key, w in old.items() if w["status"] == "time_limit"}
    require(len(workers) == len(new) == 187 and set(new) == expected, "all and only prior time limits")
    require({w["refinement_index"] for w in workers} == set(range(187)), "all logical indices retained")
    require(all(w["passed"] and w["native_lower_bound_usable"] and w["repaired_objective"] is not None for w in workers), "all new endpoints independently accepted")
    require(report["all_refinement_attempts_finished"], "all attempts finished")
    require(Counter(w["status"] for w in workers) == {"optimal": 106, "time_limit": 81}, "final status reconciliation")
    require(Counter(w["deployment_version"] for w in workers) == {"v1_lisbeth": 95, "v2_cdses": 92}, "final node mapping reconciliation")
    require(sha(primary_path) == report["original_primary_sha256"] and sha(repair_dir/"numerical_sensitivity.json") == report["original_repair_sha256"], "original audit binding")
    require(sha(ROOT/"summarize_planning_refinement.py") == report["checker_sha256"], "analyzer source binding")
    for name, digest in report["checker_dependencies_sha256"].items():
        require(sha(ROOT/name) == digest, "analyzer dependency binding")
    for w in prior["workers"]+workers:
        p = Path(w["directory"])/"result.json"
        require(sha(p) == w["result_sha256"], "source result binding")
        raw = read(p)
        for relative, digest in raw["evidence_sha256"].items():
            q = (p.parent/relative).resolve()
            require(q.is_relative_to(p.parent.resolve()) and sha(q) == digest, "raw evidence binding")
    for w in workers:
        require(w["bound"] <= w["repaired_objective"]+1e-6, "native bound versus repaired incumbent")
        same(w["repaired_objective"]-w["objective"], w["objective_repair_change"], "repair cost accounting")
        same(abs(w["objective"]-w["bound"])/abs(w["objective"]), w["gap"], "native relative gap", Decimal("1e-6"))
        require(all(w[name]["passed"] for name in ("raw_physical_replay", "raw_vendor_master", "raw_primal_consistency", "independent_physical_replay", "original_vendor_master")), "all primal replay layers passed")
    require(sha(folder/"new_repaired_profiles.json.gz") == report["new_repaired_profiles_sha256"], "new repaired profiles binding")

    recovery = report["infrastructure_recovery"]
    require(recovery["recovery_count"] == recovery["original_executions_observed"] == recovery["retry_executions_observed"] == recovery["retry_result_files_present"] == 26, "all recovery executions reconciled")
    require(recovery["interrupted_elapsed_seconds"] == 2199, "interrupted compute retained")
    for name in ("accounting_binding", "retry_accounting_binding"):
        require(sha(Path(recovery[name]["path"])) == recovery[name]["sha256"], "scheduler receipt binding")
    retry_states = {}
    for line in Path(recovery["retry_accounting_binding"]["path"]).read_text().splitlines():
        fields = line.split("|")
        if fields and fields[0].startswith("243484_") and "." not in fields[0]:
            retry_states[int(fields[0].split("_")[1])] = fields[1]
    registered_indices = {e["refinement_index"] for e in recovery["manifest"]["entries"]}
    require(set(retry_states) == registered_indices and set(retry_states.values()) == {"COMPLETED"}, "all 26 retry scheduler states completed")
    base_by_allowance = {}
    rounding = {}
    for label, result in report["allowances"].items():
        allowance = dec(label)
        endpoint_rows = {(x["case"], x["scenario"]): x for x in result["endpoint_sources"]}
        require(len(endpoint_rows) == 1080, "all configuration intervals retained")
        manual_raw = {}
        lower_improved = upper_improved = 0
        for key, previous in old.items():
            lows = [(dec(previous["bound"]), "original60")]
            ups = [(dec(repaired_old[key]["repaired_objective"]), "original60")]
            if key in new:
                lows.append((dec(new[key]["bound"]), "refinement300"))
                ups.append((dec(new[key]["repaired_objective"]), "refinement300"))
            lower, upper = max(v for v, _ in lows), min(v for v, _ in ups)
            lower_improved += int(lower > lows[0][0]+dec("1e-9"))
            upper_improved += int(upper < ups[0][0]-dec("1e-9"))
            require(endpoint_rows[key]["sources"] == {"lower": [s for v, s in lows if v == lower], "upper": [s for v, s in ups if v == upper]}, "endpoint source selection")
            manual_raw[key] = [max(Decimal(0), lower-allowance), upper+allowance]
        require(result["endpoint_improvements"] == {"strict_lower_improvements": lower_improved, "strict_upper_improvements": upper_improved}, "endpoint improvement accounting")
        bases = result["bases"]
        require(len(bases) == len({b["case"] for b in bases}) == 270, "all base identities retained")
        own = {}
        for b in bases:
            raw = {a: manual_raw[(b["case"], a)] for a in ARMS}
            # Closed-form partial-order closure, independent of iterative propagation.
            z = {"solar": [max(raw[a][0] for a in ARMS), raw["solar"][1]],
                 "solar_bess": [max(raw["solar_bess"][0], raw["v2g"][0]), min(raw["solar_bess"][1], raw["solar"][1])],
                 "v2g_fleet": [max(raw["v2g_fleet"][0], raw["v2g"][0]), min(raw["v2g_fleet"][1], raw["solar"][1])],
                 "v2g": [raw["v2g"][0], min(raw[a][1] for a in ARMS)]}
            for a in ARMS:
                same(raw[a], b["raw_cost_intervals"][a], "raw intersection endpoint")
                same(z[a], b["cost_intervals"][a], "closed-form technology nesting")
                require(z[a][0] <= z[a][1], "nonempty nested interval")
            joint = z["solar"][0] > z["v2g"][1]
            conditional = z["solar_bess"][0] > z["v2g"][1]
            require(joint == b["strictly_positive_joint_saving_certified"] and conditional == b["strict_additional_V2G_with_BESS_certified"], "saving sign qualification")
            values = {"BESS_share": share(z, "solar_bess"), "V2G_alone_share": share(z, "v2g_fleet"),
                      "V2G_alone_daily_reduction": reduction(z, "solar", "v2g_fleet")}
            if b["gamma"] <= .35: values["V2G_with_BESS_daily_reduction_low_gamma"] = reduction(z, "solar_bess", "v2g")
            if b["gamma"] > 2: values["V2G_with_BESS_daily_reduction_high_gamma"] = reduction(z, "solar_bess", "v2g")
            require(set(values) == set(b["metrics"]), "fixed gamma subset membership")
            for name, pair in values.items():
                same(pair, b["metrics"][name], "independent ratio endpoint", Decimal("2e-10"))
                require(0 <= pair[0] <= pair[1] <= 1, "unit-interval metric")
            own[b["case"]] = {"metrics": values, "joint": joint}
        rounding[label] = {}
        for name, (original, places) in METRICS.items():
            pop = [b["metrics"][name] for b in own.values() if name in b["metrics"]]
            pair = [med(x[0] for x in pop), med(x[1] for x in pop)]
            saved = result["summary"]["metrics"][name]
            require(len(pop) == saved["count"], "median population size")
            same(pair, saved["median_interval"], "independent exact even-N median", Decimal("2e-10"))
            require(outward(pair) == saved["median_interval_percent_outward_2dp"], "outward publication rounding")
            gate = all(b["joint"] for b in own.values()) if name.endswith("share") else True
            width = Decimal(10)**(-places)
            center = (((pair[0]+pair[1])*50/width)+Decimal(".5")).to_integral_value(rounding=ROUND_FLOOR)*width
            resolved = pair[0]*100 > center-width/2 and pair[1]*100 < center+width/2 and gate
            require(resolved == saved["rounding_decision"]["resolved_to_displayed_precision"] and not saved["rounding_decision"]["publication_decision_provisional"], "strict rounding-cell decision")
            rounding[label][name] = {"outward_percent": outward(pair), "resolved": bool(resolved), "rounded_percent": float(center) if resolved else None}
        certain = [b for b in own.values() if b["joint"]]
        unknown = len(own)-len(certain)
        env = result["positive_saving_population_envelope"]
        require(env["possible_population_size"] == [len(certain), len(own)] and unknown == 11, "unknown positive-saving population retained")
        for name in ("BESS_share", "V2G_alone_share"):
            lower = [b["metrics"][name][0] for b in certain]
            upper = [b["metrics"][name][1] for b in certain]
            pair = [med(lower+[Decimal(0)]*unknown), med(upper+[Decimal(1)]*unknown)]
            same(pair, env["metrics"][name]["median_interval"], "positive-saving median envelope", Decimal("2e-10"))
            for size in range(unknown+1):
                require(pair[0] <= med(lower+[Decimal(0)]*size) and pair[1] >= med(upper+[Decimal(1)]*size), "all possible positive-membership sizes contained")
        base_by_allowance[label] = own

    for first, second in zip(("1e-06", "0.0001"), ("0.0001", "0.001")):
        for case, b in base_by_allowance[first].items():
            for name, pair in b["metrics"].items():
                wider = base_by_allowance[second][case]["metrics"][name]
                require(wider[0] <= pair[0]+Decimal("1e-40") and wider[1] >= pair[1]-Decimal("1e-40"), "larger numerical allowances widen intervals")

    residual_maxima = {name: max(max(w[name]["residuals"].values()) for w in workers) for name in
        ("raw_physical_replay", "raw_vendor_master", "raw_primal_consistency", "independent_physical_replay", "original_vendor_master")}
    native = {s: {"count": sum(w["status"] == s for w in workers),
        "positive_absolute_gap_count": sum(w["status"] == s and w["objective"]-w["bound"] > 1e-9 for w in workers),
        "maximum_absolute_gap": max(w["objective"]-w["bound"] for w in workers if w["status"] == s),
        "maximum_relative_gap": max(w["gap"] for w in workers if w["status"] == s)} for s in ("optimal", "time_limit")}
    return {"passed": True, "optimization_performed": False,
        "scope": "Independent standard-library provenance and Decimal scalar checks; native bounds remain numerical solver evidence",
        "summary_sha256": sha(summary_path), "checker_sha256": sha(__file__),
        "check_categories": dict(checks), "checks_passed": sum(checks.values()),
        "all187_result_and_all1080_prior_result_digests_stable": True,
        "total_logical_refinements": 187, "total_observed_refinement_executions": 213,
        "interrupted_executions": 26, "interrupted_elapsed_seconds": 2199,
        "native_gap_summary": native, "maximum_residuals": residual_maxima,
        "maximum_repair_cost_increase": max(w["objective_repair_change"] for w in workers),
        "minimum_repair_cost_change": min(w["objective_repair_change"] for w in workers),
        "maximum_native_bound_minus_repaired_incumbent": max(w["bound"]-w["repaired_objective"] for w in workers),
        "new_transitions_independently_replayed": sum(w["independent_physical_replay"]["transitions"] for w in workers),
        "outward_intervals_and_rounding": rounding}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise FileExistsError("Fresh cross-check report required")
    result = verify(args.input)
    args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k: result[k] for k in ("passed", "checks_passed", "maximum_residuals", "native_gap_summary")}, indent=2))


if __name__ == "__main__": main()
