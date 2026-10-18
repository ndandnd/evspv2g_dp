"""Separate post-hoc common-family validation view of the frozen LP study.

No optimization, certificate recomputation, primary-data edit, or timing change
occurs here. Direct supplementary certificates must be cryptographically bound
to the exact result/manifest used in the primary analysis. Every original row
and strict flag is retained verbatim. Supplemental timing ratios still require
objective agreement within 1e-6; a looser validated objective interval is never
relabeled exact equality. All planned outcomes remain visible.
"""
from __future__ import annotations

import argparse
import collections
import copy
import json
import math
from pathlib import Path
import statistics

import plot_lp_scaling as primary_plot

TOL=1e-6
METHODS=primary_plot.METHODS


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def stats(values):
    values=[value for value in values if primary_plot.finite_positive(value)]
    return {"count":len(values),"median":statistics.median(values) if values else None,
            "minimum":min(values) if values else None,"maximum":max(values) if values else None}


def load_supplement(paths):
    indexed={};sources=[]
    for path in paths:
        report=json.loads(path.read_text())
        if report.get("post_hoc") is not True or report.get("primary_results_changed") is not False:
            raise ValueError("Supplement must explicitly declare post-hoc scope and unchanged primary results")
        sources.append({"path":str(path.resolve()),"sha256":primary_plot.digest(path),
                        "checker_sha256":report.get("checker_sha256"),"workers":report.get("workers")})
        for record in report["results"]:
            if not all(key in record for key in ("case","repeat","method")):
                raise ValueError("Supplementary record lacks a unique worker identity")
            key=primary_plot.row_key(record)
            if key in indexed:raise ValueError(f"Duplicate supplementary certificate; no favorable selection: {key}")
            if key not in primary_plot.expected_keys() or record["method"] not in ("dual","barrier"):
                raise ValueError(f"Supplementary record is outside the declared direct methods: {key}")
            indexed[key]=record
    return indexed,sources


def hash_field(record,name):
    # The checker may expose digests at top level or in a named binding object.
    binding=record.get("evidence_binding_sha256",record.get("input_sha256",{}))
    return record.get(f"{name}_sha256") or binding.get(f"{name}.json") or binding.get(name)


def check_record(row,proof,record):
    errors=[]
    if record is None:return {"present":False,"accepted":False,"errors":["No post-hoc direct certificate supplied"]}
    for name in ("result","manifest"):
        expected=proof.get(f"{name}_sha256")
        if not expected or hash_field(record,name)!=expected:
            errors.append(f"Certificate {name} digest is missing or differs from primary analysis")
    if record.get("instance_payload_sha256")!=row.get("instance_sha256") or not row.get("instance_sha256"):
        errors.append("Supplementary and primary instance payload digests differ")
    if not row.get("identity_passed"):errors.append("Primary worker/block provenance has not passed")
    if record.get("no_optimization") is not True or record.get("prespecified_primary_criterion_changed") is not False:
        errors.append("Supplement does not preserve the declared scope")
    if record.get("native_status")!="optimal" or row.get("status")!="optimal":errors.append("Direct solver did not report optimal status")
    if not finite(record.get("objective")) or record.get("objective")!=row.get("objective"):
        errors.append("Supplementary and primary primal objectives differ")
    replay=record.get("prerequisite_replay") or {}
    if record.get("primary_strict_certified") is not replay.get("source_certified"):
        errors.append("Supplementary record contradicts the preserved native strict flag")
    if not replay.get("passed") or not replay.get("instance_hash_passed"):
        errors.append("Independent primal/input replay has not passed")
    for section in ("evidence_hashes","local_reconstruction_code","physical_replay"):
        if not replay.get(section,{}).get("passed"):errors.append(f"Failed prerequisite: {section}")
    if not replay.get("primal_residuals") or any(not finite(v) or v>TOL for v in replay["primal_residuals"].values()):
        errors.append("Independent primal residuals exceed the original feasibility tolerance")
    final=record.get("final_price_diagnostics") or {}
    for field in ("graph_min_reduced_cost","seed_min_reduced_cost","route_min_reduced_cost","unit_bess_reduced_cost"):
        if not finite(final.get(field)) or final[field]<0:errors.append(f"Negative or missing repaired full-family margin: {field}")
    lower=record.get("supplementary_lower_bound");objective=row.get("objective")
    if not finite(lower) or not finite(objective):errors.append("Missing finite primal/bound")
    else:
        gap=objective-lower
        if gap < -TOL or gap>row["n_tasks"]*TOL+TOL:errors.append("Supplementary interval exceeds the declared pricing-tolerance allowance")
        if not finite(record.get("primal_minus_supplementary_bound")) or abs(record["primal_minus_supplementary_bound"]-gap)>1e-10:
            errors.append("Reported supplementary interval width is inconsistent")
        if final.get("dual_objective")!=lower:errors.append("Final dual objective and supplementary bound differ")
    if record.get("pricing_tolerance")!=TOL:errors.append("Unexpected supplementary pricing tolerance")
    if not record.get("final_full_family_dual_feasible") or not record.get("primal_dual_consistent") or not record.get("supplementary_certified"):
        errors.append("Full-family supplementary check did not pass")
    return {"present":True,"accepted":not errors,"errors":errors,
            "checker_claimed_certified":record.get("supplementary_certified"),
            "original_source_strict_certified":record.get("primary_strict_certified"),
            "native_dual_reconstruction_passed":replay.get("native_dual_reconstruction",{}).get("passed"),
            "native_dual_residuals":replay.get("native_dual_reconstruction",{}).get("residuals"),
            "supplementary_lower_bound":lower,"primal_minus_supplementary_bound":record.get("primal_minus_supplementary_bound"),
            "repairs":record.get("repairs"),"final_price_diagnostics":final}


def build_rows(report,records):
    rows=report["raw_worker_rows"];proofs=report.get("worker_evidence",[])
    if len(proofs)!=len(rows):raise ValueError("Primary analysis must include aligned per-worker evidence")
    output=[]
    for row,proof in zip(rows,proofs):
        key=primary_plot.row_key(row)
        check=check_record(row,proof,records.get(key)) if row["method"]!="cg" else {
            "present":False,"accepted":False,"errors":[],"scope":"CG retains original prespecified certificate only"}
        primary_code,primary_seconds=primary_plot.classify(row)
        additional=(row["method"]!="cg" and check["accepted"] and not row.get("accepted_certificate"))
        view_code="H" if additional and primary_plot.finite_positive(row.get("solve_end_to_end_seconds")) else primary_code
        selected_for_summary=bool(check["accepted"] if row["method"]!="cg" else row.get("accepted_certificate"))
        output.append({"case":row["case"],"repeat":row["repeat"],"method":row["method"],
            "n_tasks":row["n_tasks"],"task_locations":row["task_locations"],"draw_seed":row["draw_seed"],
            "primary":copy.deepcopy(row),"supplementary_check":check,
            "original_display_code":primary_code,"supplementary_display_code":view_code,
            "additional_posthoc_validation":bool(additional),
            "posthoc_timing_population_member":bool(selected_for_summary and primary_plot.finite_positive(row.get("solve_end_to_end_seconds"))),
            "unchanged_algorithm_stop_seconds":row.get("solve_end_to_end_seconds"),
            "display_seconds":row.get("solve_end_to_end_seconds") if view_code=="H" else primary_seconds})
    return output


def supplementary_pairs(rows,primary_pairs):
    pair_keys=[(pair["case"],pair["repeat"],pair["direct_method"]) for pair in primary_pairs]
    expected={key for key in primary_plot.expected_keys() if key[2] in ("dual","barrier")}
    if len(pair_keys)!=72 or len(set(pair_keys))!=72 or set(pair_keys)!=expected:
        raise ValueError("Primary pairs must retain all 72 unique prespecified direct/CG comparisons")
    indexed={primary_plot.row_key(row):row for row in rows}
    out=[]
    for original in primary_pairs:
        direct=indexed[(original["case"],original["repeat"],original["direct_method"])];cg=indexed[(original["case"],original["repeat"],"cg")]
        d,c=direct["primary"],cg["primary"]
        pair={key:original.get(key) for key in ("case","repeat","n_tasks","task_locations","draw_seed","direct_method")}
        pair.update(primary_pair=copy.deepcopy(original),classification="posthoc_pair_unavailable",
                    direct_posthoc_accepted=direct["supplementary_check"]["accepted"],cg_primary_accepted=c.get("accepted_certificate",False),
                    ratio_direct_over_cg=None,ratio_lower_bound=None,ratio_upper_bound=None,objective_match_verified=False)
        if not d.get("identity_passed") or not c.get("identity_passed"):
            pair["classification"]="provenance_incomplete_or_failed"
        elif direct["supplementary_check"]["accepted"] and c.get("accepted_certificate"):
            difference=c["objective"]-d["objective"]
            dl=direct["supplementary_check"]["supplementary_lower_bound"];cl=c["objective"]-c["n_tasks"]*TOL
            # Numerical feasibility allows a tiny lower-bound/primal reversal;
            # retain raw endpoints, and explicitly enclose them for comparison.
            di=[min(dl,d["objective"])-TOL,max(dl,d["objective"])+TOL]
            ci=[min(cl,c["objective"])-TOL,max(cl,c["objective"])+TOL]
            pair.update(objective_difference_cg_minus_direct=difference,direct_interval=di,cg_interval=ci,
                        direct_raw_bound_primal=[dl,d["objective"]],cg_raw_bound_primal=[cl,c["objective"]],
                        numerical_interval_padding=TOL,
                        interval_scope="Numerical outer envelope of saved bound/primal endpoints, not an exact-arithmetic enclosure",
                        cg_interval_basis="original n*pricing_tolerance correction")
            if abs(difference)>TOL:
                pair["classification"]=("posthoc_intervals_compatible_not_equal_LP" if max(di[0],ci[0])<=min(di[1],ci[1]) else "incompatible_objective_intervals")
            elif not all(primary_plot.finite_positive(v) for v in (d.get("solve_end_to_end_seconds"),c.get("solve_end_to_end_seconds"))):
                pair["classification"]="invalid_timing"
            else:
                ratio=d["solve_end_to_end_seconds"]/c["solve_end_to_end_seconds"]
                pair.update(classification="posthoc_validated_equal_LP",ratio_direct_over_cg=ratio,
                            ratio_lower_bound=ratio,ratio_upper_bound=ratio,objective_match_verified=True)
        elif direct["supplementary_check"]["accepted"] and c.get("genuine_optimization_time_limit"):
            td=d.get("solve_end_to_end_seconds");tc=c.get("solve_end_to_end_seconds");budget=c.get("budget_seconds")
            if not all(primary_plot.finite_positive(value) for value in (td,tc,budget)):
                pair["classification"]="invalid_timing"
            else:
                cutoff=min(tc,budget)
                pair.update(classification="posthoc_cg_time_censored",ratio_lower_bound=0.,ratio_upper_bound=td/cutoff,
                            bound_is_strict=False,censor_cutoff_seconds=cutoff,
                            censoring_scope="Post-hoc validated direct saved stop versus time to the original CG certificate; no objective equality is inferred for the censored CG arm")
        elif original["classification"] in ("direct_time_censored","cg_time_censored","both_time_censored_ratio_unidentified","external_watchdog_no_optimization_time_bound"):
            pair.update(classification=original["classification"],ratio_lower_bound=original.get("ratio_lower_bound"),ratio_upper_bound=original.get("ratio_upper_bound"),
                        censoring_scope="unchanged prespecified primary comparison; no post-hoc equality inferred")
        out.append(pair)
    return out


def group_summaries(rows,pairs):
    groups=[];paired=[]
    for L in primary_plot.L_VALUES:
        for n in primary_plot.N_VALUES:
            item={"task_locations":L,"n_tasks":n,"methods":{}}
            for method in METHODS:
                chosen=[row for row in rows if (row["task_locations"],row["n_tasks"],row["method"])==(L,n,method)]
                selected=[row["unchanged_algorithm_stop_seconds"] for row in chosen if row["posthoc_timing_population_member"]]
                item["methods"][method]={"planned":6,"primary_accepted":sum(bool(r["primary"].get("accepted_certificate")) for r in chosen),
                    "native_optimal_reported":sum(r["primary"].get("status")=="optimal" for r in chosen),
                    "native_optimal_without_primary_acceptance":sum(r["primary"].get("status")=="optimal" and not r["primary"].get("accepted_certificate") for r in chosen),
                    "supplementary_attempts":sum(r["supplementary_check"]["present"] for r in chosen),
                    "supplementary_accepted":sum(r["supplementary_check"]["accepted"] for r in chosen),
                    "additional_posthoc_validations":sum(r["additional_posthoc_validation"] for r in chosen),
                    "independent_native_diagnostic_checked":sum(r["supplementary_check"].get("native_dual_reconstruction_passed") is not None for r in chosen),
                    "independent_native_diagnostic_passed":sum(r["supplementary_check"].get("native_dual_reconstruction_passed") is True for r in chosen),
                    "independent_native_diagnostic_failed":sum(r["supplementary_check"].get("native_dual_reconstruction_passed") is False for r in chosen),
                    "original_display_counts":dict(collections.Counter(r["original_display_code"] for r in chosen)),
                    "supplementary_display_counts":dict(collections.Counter(r["supplementary_display_code"] for r in chosen)),
                    "saved_stop_seconds_selected_only":stats(selected),
                    "all_native_optimal_stop_seconds":stats([r["unchanged_algorithm_stop_seconds"] for r in chosen
                        if r["primary"].get("status")=="optimal"]),
                    "genuine_time_limits":sum(r["primary"].get("genuine_optimization_time_limit",False) for r in chosen),
                    "genuine_time_limit_cutoffs":stats([min(r["primary"]["solve_end_to_end_seconds"],r["primary"]["budget_seconds"])
                        for r in chosen if r["primary"].get("genuine_optimization_time_limit")
                        and all(primary_plot.finite_positive(r["primary"].get(k)) for k in ("solve_end_to_end_seconds","budget_seconds"))]),
                    "population":"direct post-hoc full-family validation" if method!="cg" else "unchanged primary CG acceptance"}
            groups.append(item)
            for method in ("dual","barrier"):
                selected=[pair for pair in pairs if (pair["task_locations"],pair["n_tasks"],pair["direct_method"])==(L,n,method)]
                exact=[pair["ratio_direct_over_cg"] for pair in selected if pair["classification"]=="posthoc_validated_equal_LP"]
                paired.append({"task_locations":L,"n_tasks":n,"direct_method":method,"planned_pairs":6,
                    "classification_counts":dict(collections.Counter(pair["classification"] for pair in selected)),
                    "posthoc_completed_pair_speedups":stats(exact),"CG_faster_count":sum(r>1 for r in exact),"direct_faster_count":sum(r<1 for r in exact),
                    "censored_bounds":[{k:pair.get(k) for k in ("case","repeat","classification","ratio_lower_bound","ratio_upper_bound","censor_cutoff_seconds","censoring_scope")}
                                       for pair in selected if "censored" in pair["classification"]],
                    "scaling_claim":"No connecting trend or automatic inferential scaling conclusion; inspect every planned outcome and both methods."})
    return groups,paired


def make_plot(rows,report,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import LogLocator,NullFormatter,FuncFormatter
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"pdf.fonttype":42,"ps.fonttype":42,
                         "axes.spines.top":False,"axes.spines.right":False})
    figure=plt.figure(figsize=(10.8,7.9));grid=figure.add_gridspec(2,2,height_ratios=[4.1,1.35],hspace=.045,wspace=.12)
    timed=[row["display_seconds"] for row in rows if primary_plot.finite_positive(row["display_seconds"])]
    ymin=max(min(timed)/1.5,.00001) if timed else 1.;ymax=max([1800.]+timed)*1.5
    if ymax/ymin<10:ymin=ymax/10
    for panel,L in enumerate(primary_plot.L_VALUES):
        ax=figure.add_subplot(grid[0,panel]);strip=figure.add_subplot(grid[1,panel],sharex=ax)
        ax.set_title(f"{chr(97+panel)}) {L} task locations",loc="left",fontweight="bold")
        ax.set_yscale("log");ax.set_ylim(ymin,ymax);ax.set_xlim(-.5,2.5)
        ax.grid(axis="y",which="major",color="#D9DDE2",linewidth=.7,zorder=0)
        ax.axhline(1800,color="#777777",linewidth=.8,linestyle=(0,(4,3)))
        ax.text(.025,1800,"1,800 s budget",transform=ax.get_yaxis_transform(),fontsize=7.5,color="#666666",ha="left",va="bottom")
        ax.yaxis.set_major_locator(LogLocator(base=10));ax.yaxis.set_minor_formatter(NullFormatter())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value,pos:f"{value:g}"))
        ax.tick_params(axis="x",bottom=False,labelbottom=False)
        if panel==0:ax.set_ylabel("Unchanged time to algorithm stop (s; log scale)")
        else:ax.tick_params(axis="y",labelleft=False)
        strip.set_facecolor("#F4F5F7");strip.set_ylim(-.6,len(primary_plot.STRIP_CODES)-.4)
        strip.set_yticks(range(len(primary_plot.STRIP_CODES)),[primary_plot.STRIP_LABELS[code] for code in primary_plot.STRIP_CODES],fontsize=7)
        strip.tick_params(axis="y",length=0,labelleft=panel==0)
        strip.set_xticks(range(3),[str(n) for n in primary_plot.N_VALUES]);strip.set_xlabel("Number of tasks, n")
        strip.spines["left"].set_visible(False)
        if panel==0:strip.set_ylabel("No time bound",fontsize=8)
        for row in rows:
            if row["task_locations"]!=L:continue
            code=row["supplementary_display_code"];color=primary_plot.COLORS[row["method"]]
            slot=row["draw_seed"]*3+row["repeat"]
            x=primary_plot.N_VALUES.index(row["n_tasks"])+primary_plot.METHOD_OFFSET[row["method"]]+(slot-2.5)*.028
            if code=="C":
                ax.scatter(x,row["display_seconds"],s=25,marker="o" if row["draw_seed"]==0 else "s",c=color,edgecolors="white",linewidths=.35,alpha=.85,zorder=4)
            elif code=="H":
                ax.scatter(x,row["display_seconds"],s=47,marker="*",facecolors=color,edgecolors="#222222",linewidths=.35,zorder=5)
            elif code in ("T","N"):
                ax.scatter(x,row["display_seconds"],s=40 if code=="T" else 31,marker="^" if code=="T" else "D",facecolors="none",edgecolors=color,linewidths=1.1,zorder=4)
            else:strip.scatter(x,primary_plot.STRIP_CODES.index(code),s=26,marker="x",c=color,linewidths=1.)
        for position in (.5,1.5):strip.axvline(position,color="white",linewidth=1.5)
    figure.legend(handles=[Line2D([],[],color=primary_plot.COLORS[m],marker="o",linestyle="none",label=primary_plot.METHOD_LABELS[m]) for m in METHODS],
                  loc="upper center",bbox_to_anchor=(.52,.985),ncol=3,frameon=False,columnspacing=2.5)
    handles=[Line2D([],[],color="#444444",marker=marker,linestyle="none",markerfacecolor=face,label=label)
             for marker,face,label in (("o","#444444","Primary accepted: draw 0"),("s","#444444","Primary accepted: draw 1"),
              ("*","#777777","Additional post-hoc family validation"),("^","none","Time limit (lower bound)"),("D","none","Native optimal; still uncertified"))]
    figure.legend(handles=handles,loc="lower center",bbox_to_anchor=(.52,.012),ncol=2,frameon=False,fontsize=8,columnspacing=2.)
    figure.text(.5,.924,"POST-HOC FULL-FAMILY VALIDATION — ORIGINAL STRICT FLAGS RETAINED",ha="center",color="#704A00",fontsize=9,fontweight="bold")
    state=primary_plot.report_state(report)
    if state:figure.text(.5,.895," | ".join(state),ha="center",color="#A52828",fontsize=8)
    figure.subplots_adjust(top=.85,bottom=.18,left=.105,right=.975)
    for suffix in ("pdf","svg","png"):
        figure.savefig(output/f"lp_scaling_posthoc_replicates.{suffix}",**({"dpi":220} if suffix=="png" else {}))
    plt.close(figure)


def latex_table(groups,report):
    lines=[r"% POST-HOC supplementary view. Original strict counts and timings are unchanged.",r"\begin{table}[htbp]",r"\centering",r"\scriptsize",r"\setlength{\tabcolsep}{4pt}",
           r"\begin{tabular}{rrccc}",r"\hline",r"$L$ & $n$ & Direct dual simplex & Direct barrier & Column generation \\",r"\hline"]
    for group in groups:
        cells=[]
        for method in METHODS:
            data=group["methods"][method];s=data["saved_stop_seconds_selected_only"]
            timing=(primary_plot.format_seconds(s["median"])+" ["+primary_plot.format_seconds(s["minimum"])+", "+primary_plot.format_seconds(s["maximum"])+"]") if s["count"] else "--"
            counts=f'P {data["primary_accepted"]}/6'
            if method!="cg":counts+=f'; N {data["native_optimal_without_primary_acceptance"]}; H {data["supplementary_accepted"]}/6'
            cells.append(r"\shortstack{"+timing+r"\\"+counts+"}")
        lines.append(f'{group["task_locations"]} & {group["n_tasks"]} & '+" & ".join(cells)+r" \\")
    lines.extend([r"\hline",r"\end{tabular}"])
    warning=(" "+"; ".join(primary_plot.report_state(report))+".") if primary_plot.report_state(report) else ""
    lines.append(r"\caption{Post-hoc full-family validation view: median [minimum, maximum] of the unchanged algorithm-stop times in seconds. Direct summaries require a separately validated post-hoc graph/seed/BESS bound (H); CG summaries retain the original acceptance rule (P). P counts original strict accepted outcomes out of six planned runs; N counts native-optimal direct outcomes without primary acceptance; H counts supplementary validations and may overlap P. The supplemental allowance is $n\,10^{-6}+10^{-6}$ for the primal--bound gap, with nonnegative repaired pricing margins. It does not replace the original native diagnostic or imply exact arithmetic certification. Post-hoc checking time is excluded; these are saved stop times, not the time required to perform the new certificate. Two draws have three timing repeats each. Incomplete summaries are conditional on validation/completion; all outcomes remain in the companion figure and data."+warning+"}")
    lines.extend([r"\label{tab:lp-scaling-posthoc}",r"\end{table}",""])
    return "\n".join(lines)


def native_stop_latex_table(groups,report):
    """Requested author-facing population, separate from the H-only table."""
    lines=[r"% Native stop-time view; strict P and post-hoc H counts remain separate.",
           r"\begin{table}[htbp]",r"\centering",r"\scriptsize",r"\setlength{\tabcolsep}{4pt}",
           r"\begin{tabular}{rrccc}",r"\hline",r"$L$ & $n$ & Direct dual simplex & Direct barrier & Column generation \\",r"\hline"]
    for group in groups:
        cells=[]
        for method in METHODS:
            data=group["methods"][method]
            s=data["all_native_optimal_stop_seconds"] if method!="cg" else data["saved_stop_seconds_selected_only"]
            timing=(primary_plot.format_seconds(s["median"])+" ["+primary_plot.format_seconds(s["minimum"])+", "+primary_plot.format_seconds(s["maximum"])+"]") if s["count"] else "--"
            counts=(f'O {data["native_optimal_reported"]}/6; P {data["primary_accepted"]}/6; H {data["supplementary_accepted"]}/6'
                    if method!="cg" else f'P {data["primary_accepted"]}/6')
            tails=[]
            if data["genuine_time_limits"]:
                cutoff=data["genuine_time_limit_cutoffs"]["minimum"]
                # A displayed lower bound must never round above its evidence.
                cutoff_text=str(math.floor(cutoff)) if cutoff is not None else "?"
                tails.append(f'T {data["genuine_time_limits"]}/6'+r" ($\geq "+cutoff_text+r"$ s)")
            for code in ("U","F","W","M","R","I"):
                count=data["original_display_counts"].get(code,0)
                if count:tails.append(f"{code} {count}")
            cells.append(r"\shortstack{"+timing+r"\\"+counts+(r"\\"+"; ".join(tails) if tails else "")+"}")
        lines.append(f'{group["task_locations"]} & {group["n_tasks"]} & '+" & ".join(cells)+r" \\")
    lines.extend([r"\hline",r"\end{tabular}"])
    warning=(" "+"; ".join(primary_plot.report_state(report))+".") if primary_plot.report_state(report) else ""
    lines.append(r"\caption{Saved algorithm-stop times in seconds, median [minimum, maximum]. Direct summaries include every native-optimal outcome (O), including those flagged by the original strict numerical diagnostic. CG summaries include original accepted outcomes (P). P counts acceptance under the prespecified strict policy; H separately counts post-hoc full-family bound validation and may overlap P. All counts refer to six planned runs per method and cell. T reports genuine budget-exhausted outcomes and a conservatively rounded censor cutoff; censored times are excluded from medians and are never replaced by the budget. Other outcomes: U, uncertified; F, error; W, external watchdog; M, missing; R, rejected evidence; I, invalid timing. Direct times are not time-to-passing the original strict diagnostic. H uses the disclosed supplementary pricing repairs and numerical bound check; it does not alter original flags or elapsed times. Post-hoc checks are outside the saved stop times. Two task draws have three timing repeats each."+warning+"}")
    lines.extend([r"\label{tab:lp-scaling-native-stops}",r"\end{table}",""])
    return "\n".join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis",required=True,type=Path);parser.add_argument("--workers",type=Path)
    parser.add_argument("--supplement",required=True,type=Path,nargs="+");parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    primary,original=primary_plot.load_analysis(args.analysis,args.workers)
    records,sources=load_supplement(args.supplement)
    rows=build_rows(primary,records);pairs=supplementary_pairs(rows,primary["paired_rows"]);groups,paired=group_summaries(rows,pairs)
    if any(row["primary"]!=source for row,source in zip(rows,original)):raise AssertionError("Primary rows were changed")
    if args.output.exists() and any(args.output.iterdir()):raise FileExistsError("Use a fresh output directory")
    args.output.mkdir(parents=True,exist_ok=True)
    make_plot(rows,primary,args.output)
    (args.output/"lp_scaling_posthoc_table.tex").write_text(latex_table(groups,primary))
    (args.output/"lp_scaling_native_stop_table.tex").write_text(native_stop_latex_table(groups,primary))
    flat=[]
    for row in rows:
        check=row["supplementary_check"]
        flat.append({key:row[key] for key in ("case","repeat","method","n_tasks","task_locations","draw_seed","original_display_code","supplementary_display_code","additional_posthoc_validation","posthoc_timing_population_member","unchanged_algorithm_stop_seconds")}|{
            "original_accepted_certificate":row["primary"].get("accepted_certificate"),"original_saved_certificate_passed":row["primary"].get("saved_certificate_passed"),
            "original_status":row["primary"].get("status"),"posthoc_present":check["present"],"posthoc_accepted":check["accepted"],
            "posthoc_lower_bound":check.get("supplementary_lower_bound"),"posthoc_gap":check.get("primal_minus_supplementary_bound"),
            "independent_native_diagnostic_passed":check.get("native_dual_reconstruction_passed"),"posthoc_errors":"; ".join(check["errors"])})
    primary_plot.write_csv(args.output/"lp_scaling_posthoc_workers.csv",flat)
    primary_plot.write_csv(args.output/"lp_scaling_posthoc_pairs.csv",[{k:v for k,v in pair.items() if k!="primary_pair"} for pair in pairs])
    result={"post_hoc":True,"primary_results_changed":False,"source_primary_sha256":primary_plot.digest(args.analysis),
        "source_worker_csv_sha256":primary_plot.digest(args.workers) if args.workers else None,"supplement_sources":sources,
        "helper_sha256":primary_plot.digest(__file__),"primary_plot_helper_sha256":primary_plot.digest(primary_plot.__file__),
        "planned_outcomes":108,"planned_pairs":72,"state":primary_plot.report_state(primary),
        "primary_status_counts":primary.get("status_counts"),"primary_pair_classifications":primary.get("pair_classifications"),
        "supplementary_certificates_supplied":len(records),"supplementary_certificates_accepted":sum(row["supplementary_check"]["accepted"] for row in rows),
        "additional_posthoc_validations":sum(row["additional_posthoc_validation"] for row in rows),
        "pair_classifications":dict(collections.Counter(pair["classification"] for pair in pairs)),
        "worker_rows":rows,"paired_rows":pairs,"method_summaries":groups,"paired_summaries":paired,
        "interpretation_rules":["This view was added after observing numerical flags and is supplementary, not the prespecified primary analysis.",
            "All original rows, flags, algorithm-stop times, and primary pairs are preserved; no optimization is rerun.",
            "H requires full-family numerical dual feasibility after explicit repairs and a recorded primal--bound interval; H is not a replacement for native certificate flags.",
            "Exact timing ratios require both validation policies and objective agreement within1e-6. Compatible but wider objective intervals do not produce an exact ratio.",
            "Both direct algorithms remain separate; no fastest-method selection or suppression of failures.",
            "Post-hoc verification duration is not included retroactively in saved algorithm-stop times.",
            "Direct timing summaries use H outcomes only; CG summaries use original P outcomes only. Interpret all counts alongside conditional medians.",
            "The separately named native-stop table includes all native-optimal direct stops and original-accepted CG stops, with O/P/H and censor counts explicit. It is not a strict time-to-certificate table.",
            "Repeated timings are not independent task draws; no automatic scaling conclusion is asserted."]}
    (args.output/"lp_scaling_posthoc_analysis.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    caption=("Supplementary post-hoc view of unchanged LP algorithm-stop times. Filled circles/squares retain the primary accepted outcomes for task draws0/1. Stars mark additional direct outcomes with a separately validated full-family graph/seed/BESS bound; their original strict flags remain unchanged. "
             "Open diamonds retain native-optimal direct outcomes without an accepted validation. Open triangles are genuine time censoring; lower-strip positions have no time meaning. "
             "The direct post-hoc bound allows a primal--bound gap up to n×10^-6+10^-6 with nonnegative repaired route/BESS prices. This is floating-point evidence, not exact arithmetic. "
             "Post-hoc checking time is outside the saved stop times. Both direct methods and every planned outcome remain visible; no trend line connects conditional summaries.\n")
    (args.output/"lp_scaling_posthoc_caption.txt").write_text(caption)
    manifest={"post_hoc":True,"primary_results_changed":False,"helper_sha256":primary_plot.digest(__file__),
              "outputs":{p.name:primary_plot.digest(p) for p in sorted(args.output.iterdir()) if p.is_file()}}
    (args.output/"lp_scaling_posthoc_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps({key:result[key] for key in ("planned_outcomes","state","supplementary_certificates_supplied","supplementary_certificates_accepted","additional_posthoc_validations","pair_classifications")},indent=2))


if __name__=="__main__":main()
