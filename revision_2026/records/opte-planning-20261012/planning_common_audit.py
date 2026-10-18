"""Recompute the 270-base planning summaries from saved COMMON4 records.

Read-only with respect to historical sources; never imports an experiment
driver or invokes an optimizer. The output embeds every input row and its
file/index provenance so --snapshot can repeat the arithmetic without Downloads.
Printed totals are rounded to cents and LP values to four decimals. Solver
bounds are NOT unrounded incumbent objectives, even when status is 'optimal'.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
ARMS = ("solar", "solar_bess", "v2g_fleet", "v2g")
CHOSEN = (
    (20, 1.0, 1, "low", "One-cent rounded incumbent difference; numerical sign is unresolved"),
    (120, 1.75, 0, "middle", "Wide share uncertainty and an uncertified V2G-with-BESS improvement"),
    (120, 4.0, 4, "high", "Largest saved four-arm LP-to-incumbent gap (8.609%)"),
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recompute(records):
    groups = defaultdict(dict)
    for item in records:
        row = item["record"]; key = (row["n_tasks"], row["pv"], row["seed"])
        if row["scenario"] in groups[key]:
            raise ValueError(f"Duplicate base/arm {key}/{row['scenario']}")
        groups[key][row["scenario"]] = item
    if len(records) != 1080 or len(groups) != 270 or any(set(g) != set(ARMS) for g in groups.values()):
        raise ValueError("Expected 270 complete four-configuration bases")
    rows = [item["record"] for item in records]
    if not all(r["cg_converged"] and r["cg_term"] == "priced_out" and r["lp_check_ok"]
               and r["lp_artificial_mass"] == 0 and r["artificials"] == 0
               and r["feasible"] and r["soc_step"] == .25 and not r["nesting_viol"] for r in rows):
        raise ValueError("Historical feasibility/LP/shared-pool metadata check failed")
    point_shares = {"BESS_added_to_charge_only": [], "V2G_without_BESS": []}
    brackets = {key: [] for key in point_shares}
    daily = []; differences = []; near_zero = []; certified = []; unresolved = []
    naive_certified = 0; rounding_sensitive_certificates = []
    calculations = []
    # Conservative outward allowances: printed LP/UB rounding and n*1e-6
    # pricing correction. These still rely on validity of the saved CG flags
    # and incumbents; this arithmetic audit is not a fresh dual/path audit.
    lp_rounding = .00005; incumbent_rounding = .005; tiny = 1e-9
    for key, group in sorted(groups.items()):
        g = {arm: group[arm]["record"] for arm in ARMS}
        totals = {arm: g[arm]["total"] for arm in ARMS}
        lo = {arm: g[arm]["lp_union"] - lp_rounding - key[0]*1e-6 - tiny for arm in ARMS}
        up = {arm: totals[arm] + incumbent_rounding + tiny for arm in ARMS}
        combined = totals["solar"] - totals["v2g"]
        if combined <= 0:
            raise ValueError("Unexpected nonpositive combined incumbent saving")
        point_shares["BESS_added_to_charge_only"].append((totals["solar"]-totals["solar_bess"])/combined)
        point_shares["V2G_without_BESS"].append((totals["solar"]-totals["v2g_fleet"])/combined)
        daily.append((totals["solar"]-totals["v2g_fleet"])/totals["solar"])
        reduction = totals["solar_bess"] - totals["v2g"]; differences.append(reduction)
        reduction_bounds = [lo["solar_bess"]-up["v2g"], up["solar_bess"]-lo["v2g"]]
        naive_margin = g["solar_bess"]["lp_union"]-totals["v2g"]
        naive_certified += naive_margin > 0
        if naive_margin > 0 and reduction_bounds[0] <= 0:
            rounding_sensitive_certificates.append({"base":list(key),"naive_lower_margin":naive_margin,
                                                    "safe_interval":reduction_bounds,
                                                    "rows":{a:group[a] for a in ("solar_bess","v2g")}})
        (certified if reduction_bounds[0] > 0 else unresolved).append(key)
        share_bounds = {}
        denominator_lo = max(0, lo["solar"]-up["v2g"])
        denominator_up = up["solar"]-lo["v2g"]
        for label, arm in (("BESS_added_to_charge_only", "solar_bess"), ("V2G_without_BESS", "v2g_fleet")):
            low = max(0, lo["solar"]-up[arm])/denominator_up
            high = min(1, (up["solar"]-lo[arm])/denominator_lo) if denominator_lo > 0 else 1
            share_bounds[label] = [low, high]; brackets[label].append([low, high])
        if abs(reduction) <= .01 + tiny:
            near_zero.append({"base":list(key),"rounded_incumbent_difference":reduction,
                              "difference_interval_from_rounding_only":[reduction-.01-tiny,reduction+.01+tiny],
                              "rows":{arm:group[arm] for arm in ("solar_bess","v2g")}})
        calculations.append({"base":list(key),"rounded_incumbent_reduction":reduction,
                             "certified_optimum_reduction_interval":reduction_bounds,
                             "conservative_optimum_share_intervals":share_bounds,
                             "largest_recorded_gap_pct":max(g[a]["gap_union_pct"] for a in ARMS)})
    selected = []
    for n, pv, seed, regime, reason in CHOSEN:
        key = (n,pv,seed); group = groups[key]
        selected.append({"n_tasks":n,"pv_scale":pv,"seed":seed,"solar_regime":regime,
                         "selection_reason":reason,"selection_type":"Prespecified diagnostic, not a representative estimator",
                         "configurations":list(ARMS),"historical_rows":[group[a] for a in ARMS],
                         "builder":{"locations_excluding_depot":3,"task_energy_model_units":2.0,
                                    "duration_hours":2.0,"task_generator":"overnight3.rand_trips(3,n,seed,salt=50000)",
                                    "rng_seed":50000+1000*seed+30+n,"start_hours_inclusive":[6,19],
                                    "trip_list_overrides_BREAKS":True,"soc_step":.25,"rho":1.75,
                                    "G":7.,"eta":0.,"c_g":40.,"c_v":45.,"c_b":36.,"eps_pen":.025,
                                    "solar_mult":7,"pv_scale":pv,"charging_locations":[0],
                                    "truck_boundary":"full/full","BESS_boundary":"periodic"}})
    all_keys = sorted(set().union(*(r.keys() for r in rows)))
    raw_incumbent_fields = sorted(set(all_keys).intersection({"obj","objective","ObjVal","mip_obj","incumbent_objective","primal_objective"}))
    return {
        "row_count":len(rows),"base_count":len(groups),"configurations":list(ARMS),
        "metadata_checks_passed":True,"saved_status_counts":dict(Counter(r["milp_status"] for r in rows)),
        "rounded_record_statistics":{
            "median_BESS_share":median(point_shares["BESS_added_to_charge_only"]),
            "median_V2G_without_BESS_share":median(point_shares["V2G_without_BESS"]),
            "median_V2G_without_BESS_daily_cost_reduction":median(daily),
            "strict_positive_differences_above_1e_6":sum(d>1e-6 for d in differences),
            "displayed_ties_within_1e_6":sum(abs(d)<=1e-6 for d in differences),
            "positive_differences_robust_to_cent_rounding":sum(d>.01+tiny for d in differences),
            "differences_unresolved_at_cent_precision":len(near_zero)},
        "saved_optimum_bound_statistics":{
            "strict_reductions_certified_after_outward_allowances":len(certified),
            "naive_certified_count_without_rounding_or_pricing_allowances":int(naive_certified),
            "unresolved":len(unresolved),
            "minimum_positive_certified_margin":min(x["certified_optimum_reduction_interval"][0]
                                                     for x in calculations if x["certified_optimum_reduction_interval"][0]>0),
            "conservative_median_share_intervals":{label:[median(x[0] for x in values),median(x[1] for x in values)]
                                                     for label,values in brackets.items()},
            "interpretation":"Conditional on valid saved LP lower bounds and feasible incumbents; not fresh optimization or dual certification"},
        "precision_audit":{"all_saved_fields":all_keys,"unrounded_incumbent_fields_available":raw_incumbent_fields,
                           "solver_bound_is_not_incumbent":True,"rounding_half_width_total":incumbent_rounding,
                           "rounding_half_width_lp":lp_rounding,"pricing_correction_per_task":1e-6,
                           "near_zero_comparisons":near_zero,
                           "rounding_sensitive_optimum_sign_certificates":rounding_sensitive_certificates,
                           "count_caution":"265 reproduces rounded totals. One positive cent difference is not robust to rounding; no unrounded objective field exists. Even an optimal status can retain a solver-tolerance gap. Do not substitute solver_bound for ObjVal or assert an exact tie from equal bounds alone."},
        "selected_planning_diagnostics":selected,"base_calculations":calculations,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,default=Path('/Users/nadan/Downloads/paper-rewrite 2/code'))
    parser.add_argument("--snapshot",type=Path,help="Replay input records embedded in an earlier audit")
    parser.add_argument("--output",type=Path,default=ROOT/'results/planning_common_audit_20261012.json')
    args=parser.parse_args()
    if args.snapshot:
        prior=json.loads(args.snapshot.read_text());records=prior["input_records"];sources=prior["source_provenance"]
    else:
        files=sorted((args.source_root/'results/arxiv').glob('overnight14_common4*_s*of*.json'))
        if len(files)!=36:raise ValueError(f'Expected 36 historical shards, got {len(files)}')
        records=[{"source_file":str(p.relative_to(args.source_root)),"row_index":i,"record":row}
                 for p in files for i,row in enumerate(json.loads(p.read_text()))]
        sources={"root_at_snapshot":str(args.source_root),"result_files":{str(p.relative_to(args.source_root)):digest(p) for p in files},
                 "source_files":{name:digest(args.source_root/name) for name in ('overnight14.py','overnight3.py','recreate_arxiv.py','master.py','colgen.py','data/delta.csv')}}
    report={"created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"checker_sha256":digest(__file__),
            "purpose":"Reproducible arithmetic/precision audit and prespecified planning diagnostic selection; no optimizer invoked",
            "source_provenance":sources,**recompute(records),"input_records":records}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({"output":str(args.output),"statistics":report['rounded_record_statistics'],
                      "bound_statistics":report['saved_optimum_bound_statistics']}))


if __name__=='__main__':main()
