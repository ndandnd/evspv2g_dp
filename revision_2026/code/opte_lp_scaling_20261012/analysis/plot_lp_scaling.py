"""Render audited LP scaling outcomes; this module never runs an optimizer.

Input is the final summarize_lp_scaling.py JSON, optionally cross-checked against
its worker CSV. All 108 prespecified outcomes must be present as rows, including
explicit missing outcomes. Outputs are a two-panel replicate plot, a six-row
LaTeX table, unrounded display data, captions, and a provenance manifest.

Certified elapsed times are plotted individually, with no connecting trend or
completed-only median line. Genuine limits get upward censor markers. Solver
optimal but uncertified times get open diamonds. Outcomes without an admissible
LP timing appear in a separate, explicitly non-time outcome strip.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


METHODS=("dual","barrier","cg")
METHOD_LABELS={"dual":"Direct: dual simplex","barrier":"Direct: barrier","cg":"Column generation"}
COLORS={"dual":"#0072B2","barrier":"#D55E00","cg":"#009E73"}
METHOD_OFFSET={"dual":-.25,"barrier":0.,"cg":.25}
N_VALUES=(100,400,1000)
L_VALUES=(4,15)
STATUS_LABELS={"C":"certified","N":"solver optimal, uncertified","T":"genuine time limit",
               "U":"other uncertified stop","F":"worker error","W":"external watchdog",
               "M":"missing","R":"rejected evidence","I":"invalid timing"}
STRIP_CODES=("I","R","U","F","W","M")
STRIP_LABELS={"I":"Invalid time","R":"Rejected","U":"Uncertified","F":"Error",
              "W":"Watchdog","M":"Missing"}


def finite_positive(value):
    return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value) and value>0


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def row_key(row):
    return row["case"],row["repeat"],row["method"]


def expected_keys():
    return {(f"diag2_L{L:02d}_n{n}_s{draw}",repeat,method)
            for L in L_VALUES for n in N_VALUES for draw in (0,1)
            for repeat in range(3) for method in METHODS}


def csv_value(value):
    if value=="":return None
    if value in ("True","False"):return value=="True"
    try:return json.loads(value)
    except (ValueError,TypeError):return value


def load_analysis(path,workers=None):
    report=json.loads(Path(path).read_text())
    rows=report["raw_worker_rows"]
    keys=[row_key(row) for row in rows]
    if len(keys)!=108 or len(set(keys))!=108 or set(keys)!=expected_keys():
        raise ValueError("Input must retain exactly the 108 unique prespecified outcomes, including missing rows")
    if report.get("planned_runs")!=108 or report.get("planned_blocks")!=36:
        raise ValueError("Unexpected study design")
    for row in rows:
        if row["case"]!=f'diag2_L{row["task_locations"]:02d}_n{row["n_tasks"]}_s{row["draw_seed"]}':
            raise ValueError(f"Case metadata disagrees: {row_key(row)}")
        if row.get("accepted_certificate") and not row.get("identity_passed"):
            raise ValueError(f"Accepted certificate has failed identity: {row_key(row)}")
        if row.get("accepted_certificate") and report.get("independent_replay_requested") and row.get("independent_replay")!="passed":
            raise ValueError(f"Accepted certificate lacks requested independent replay: {row_key(row)}")
    if workers is not None:
        with Path(workers).open(newline="") as file:
            csv_rows=[{key:csv_value(value) for key,value in row.items()} for row in csv.DictReader(file)]
        indexed={row_key(row):row for row in csv_rows}
        if len(csv_rows)!=108 or set(indexed)!=set(keys):raise ValueError("Worker CSV identity differs from JSON")
        for row in rows:
            candidate=indexed[row_key(row)]
            for field in set(row)|set(candidate):
                if row.get(field)!=candidate.get(field):
                    raise ValueError(f"CSV/JSON disagreement at {row_key(row)}, {field}")
    return report,rows


def classify(row):
    """Disjoint display classes, never treating a watchdog as a time limit."""
    elapsed=row.get("solve_end_to_end_seconds")
    if not row.get("present") or row.get("status")=="missing":return "M",None
    if row.get("status")=="external_timeout":return "W",None
    if row.get("status") in ("error","worker_error","exception"):return "F",None
    if not row.get("identity_passed"):return "R",None
    if row.get("accepted_certificate"):
        return ("C",elapsed) if finite_positive(elapsed) else ("I",None)
    if row.get("genuine_optimization_time_limit"):
        budget=row.get("budget_seconds")
        return ("T",min(elapsed,budget)) if finite_positive(elapsed) and finite_positive(budget) else ("I",None)
    if row["method"] in ("dual","barrier") and row.get("status")=="optimal":
        return ("N",elapsed) if finite_positive(elapsed) else ("I",None)
    return "U",None


def display_rows(rows):
    output=[]
    for row in sorted(rows,key=lambda r:(r["task_locations"],r["n_tasks"],METHODS.index(r["method"]),r["draw_seed"],r["repeat"])):
        code,seconds=classify(row)
        slot=row["draw_seed"]*3+row["repeat"]
        x=N_VALUES.index(row["n_tasks"])+METHOD_OFFSET[row["method"]]+(slot-2.5)*.028
        output.append({**row,"display_code":code,"display_class":STATUS_LABELS[code],
                       "display_seconds":seconds,"display_x":x,
                       "display_time_meaning":"observed censor cutoff, nonstrict lower bound" if code=="T" else
                         "algorithm stop, uncertified" if code=="N" else
                         "algorithm stop, certified" if code=="C" else "no admissible LP timing"})
    return output


def table_data(rows):
    output=[]
    for L in L_VALUES:
        for n in N_VALUES:
            entry={"task_locations":L,"n_tasks":n,"methods":{}}
            for method in METHODS:
                chosen=[row for row in rows if row["task_locations"]==L and row["n_tasks"]==n and row["method"]==method]
                if len(chosen)!=6:raise ValueError("Expected two draws times three repeats in every table cell")
                counts=dict(collections.Counter(row["display_code"] for row in chosen))
                times=[row["display_seconds"] for row in chosen if row["display_code"]=="C"]
                entry["methods"][method]={"planned":6,"certified":len(times),"counts":counts,
                    "median_seconds":statistics.median(times) if times else None,
                    "minimum_seconds":min(times) if times else None,"maximum_seconds":max(times) if times else None,
                    "summary_population":"certified runs only; missing/censored/rejected outcomes are excluded from numerical summary and counted explicitly"}
            output.append(entry)
    return output


def report_state(report):
    notes=[]
    if report.get("global_errors") or not report.get("all_present_provenance_passed",False):
        notes.append("AUDIT ISSUES")
    if not report.get("all_outcomes_present"):notes.append("INCOMPLETE")
    if report.get("statistics_provisional_without_replay",True) or not report.get("independent_replay_requested"):
        notes.append("PROVISIONAL: independent replay not requested")
    return notes


def plot_outcomes(rows,report,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import LogLocator,NullFormatter,FuncFormatter
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"pdf.fonttype":42,"ps.fonttype":42,
                         "axes.spines.top":False,"axes.spines.right":False})
    fig=plt.figure(figsize=(10.8,7.5))
    grid=fig.add_gridspec(2,2,height_ratios=[4.1,1.35],hspace=.045,wspace=.12)
    timed=[row["display_seconds"] for row in rows if row["display_seconds"] is not None]
    ymin=max(min(timed)/1.5,.00001) if timed else 1.
    ymax=max([1800.]+timed)*1.5
    if ymax/ymin<10:ymin=ymax/10
    for panel,L in enumerate(L_VALUES):
        ax=fig.add_subplot(grid[0,panel]);strip=fig.add_subplot(grid[1,panel],sharex=ax)
        ax.set_title(f"{chr(97+panel)}) {L} task locations",loc="left",fontweight="bold")
        ax.set_yscale("log");ax.set_ylim(ymin,ymax);ax.set_xlim(-.5,2.5)
        ax.grid(axis="y",which="major",color="#D9DDE2",linewidth=.7,zorder=0)
        ax.axhline(1800,color="#777777",linewidth=.8,linestyle=(0,(4,3)))
        ax.text(.025,1800,"1,800 s budget",transform=ax.get_yaxis_transform(),fontsize=7.5,color="#666666",ha="left",va="bottom")
        ax.yaxis.set_major_locator(LogLocator(base=10))
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value,pos:f"{value:g}"))
        ax.tick_params(axis="x",which="both",bottom=False,labelbottom=False)
        if panel==0:ax.set_ylabel("Elapsed time to algorithm stop (s; log scale)")
        else:ax.tick_params(axis="y",labelleft=False)
        strip.set_facecolor("#F4F5F7");strip.set_ylim(-.6,len(STRIP_CODES)-.4)
        strip.set_yticks(range(len(STRIP_CODES)),[STRIP_LABELS[code] for code in STRIP_CODES],fontsize=7)
        if panel==1:strip.tick_params(axis="y",labelleft=False)
        strip.tick_params(axis="y",length=0)
        strip.set_xticks(range(3),[str(n) for n in N_VALUES]);strip.set_xlabel("Number of tasks, n")
        strip.spines["left"].set_visible(False);strip.spines["top"].set_visible(False)
        if panel==0:strip.set_ylabel("No time bound",fontsize=8)
        for row in rows:
            if row["task_locations"]!=L:continue
            code=row["display_code"];color=COLORS[row["method"]];x=row["display_x"]
            if code=="C":
                ax.scatter(x,row["display_seconds"],s=25,marker="o" if row["draw_seed"]==0 else "s",
                           c=color,edgecolors="white",linewidths=.35,alpha=.85,zorder=4)
            elif code=="T":
                ax.scatter(x,row["display_seconds"],s=40,marker="^",facecolors="none",edgecolors=color,linewidths=1.1,zorder=5)
                ax.annotate("",xy=(x,row["display_seconds"]*1.18),xytext=(x,row["display_seconds"]*1.04),
                            arrowprops={"arrowstyle":"-","color":color,"lw":.8})
            elif code=="N":
                ax.scatter(x,row["display_seconds"],s=31,marker="D",facecolors="none",edgecolors=color,linewidths=1.1,zorder=4)
            else:
                strip.scatter(x,STRIP_CODES.index(code),s=26,marker="x",c=color,linewidths=1.)
        for position in (.5,1.5):
            strip.axvline(position,color="white",linewidth=1.5)
    method_handles=[Line2D([],[],color=COLORS[m],marker="o",linestyle="none",label=METHOD_LABELS[m]) for m in METHODS]
    outcome_handles=[Line2D([],[],color="#444444",marker=marker,linestyle="none",markerfacecolor=face,label=label)
                     for marker,face,label in (("o","#444444","Certified: draw 0"),("s","#444444","Certified: draw 1"),
                       ("^","none","Time limit (lower bound)"),("D","none","Solver optimal; uncertified"))]
    fig.legend(handles=method_handles,loc="upper center",bbox_to_anchor=(.52,.985),ncol=3,frameon=False,columnspacing=2.5)
    fig.legend(handles=outcome_handles,loc="lower center",bbox_to_anchor=(.52,.017),ncol=2,frameon=False,fontsize=8,columnspacing=2.)
    state=report_state(report)
    if state:fig.text(.5,.916," | ".join(state),ha="center",color="#A52828",fontsize=9,fontweight="bold")
    fig.subplots_adjust(top=.88,bottom=.16,left=.105,right=.975)
    for suffix in ("pdf","svg","png"):
        kwargs={"dpi":220} if suffix=="png" else {}
        fig.savefig(output/f"lp_scaling_replicates.{suffix}",**kwargs)
    plt.close(fig)


def format_seconds(value):
    return f"{value:.3g}" if value is not None else "--"


def latex_table(data,report):
    lines=[r"% Generated from audited study outcomes; numerical summaries use certified runs only.",
           r"\begin{table}[htbp]",r"\centering",r"\scriptsize",r"\setlength{\tabcolsep}{4pt}",
           r"\begin{tabular}{rrccc}",r"\hline",r"$L$ & $n$ & Direct dual simplex & Direct barrier & Column generation \\",r"\hline"]
    for row in data:
        cells=[]
        for method in METHODS:
            entry=row["methods"][method]
            timing=(format_seconds(entry["median_seconds"])+" ["+format_seconds(entry["minimum_seconds"])+", "+format_seconds(entry["maximum_seconds"])+"]"
                    if entry["certified"] else "--")
            counts=[f'C {entry["certified"]}/6']+[f'{code} {entry["counts"][code]}' for code in STATUS_LABELS if code!="C" and entry["counts"].get(code)]
            cells.append(r"\shortstack{"+timing+r"\\"+"; ".join(counts)+"}")
        lines.append(f'{row["task_locations"]} & {row["n_tasks"]} & '+" & ".join(cells)+r" \\")
    lines.extend([r"\hline",r"\end{tabular}"])
    warnings=report_state(report)
    caution=(" "+"; ".join(warnings).replace(":","---")+".") if warnings else ""
    lines.append(r"\caption{LP computation times in seconds: median [minimum, maximum] over certified runs only, followed by C (certified out of six planned runs). Each cell contains two task draws with three timing repeats. Other counts: N, solver optimal but uncertified; T, genuine time limit; U, other uncertified stop; F, worker error; W, external watchdog; M, missing; R, rejected evidence; I, invalid timing. These counts partition the six planned outcomes; absent categories have zero count. Censored outcomes are not replaced by the time budget. Summaries of fewer than six certified runs are conditional on completion and do not establish a scaling trend."+caution+"}")
    lines.extend([r"\label{tab:lp-scaling-times}",r"\end{table}",""])
    return "\n".join(lines)


def write_csv(path,rows):
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis",required=True,type=Path)
    parser.add_argument("--workers",type=Path,help="Optional matching lp_scaling_workers.csv; every field is cross-checked")
    parser.add_argument("--output",required=True,type=Path,help="New directory; existing files are never overwritten")
    args=parser.parse_args()
    report,raw=load_analysis(args.analysis,args.workers)
    rows=display_rows(raw);table=table_data(rows)
    if args.output.exists() and any(args.output.iterdir()):raise FileExistsError("Output directory is not empty")
    args.output.mkdir(parents=True,exist_ok=True)
    plot_outcomes(rows,report,args.output)
    (args.output/"lp_scaling_table.tex").write_text(latex_table(table,report))
    (args.output/"lp_scaling_table_data.json").write_text(json.dumps(table,indent=2,allow_nan=False)+"\n")
    write_csv(args.output/"lp_scaling_plot_data.csv",rows)
    caption=("LP computation times for two task-location counts. Color denotes the prespecified method; filled circles and squares distinguish the two independent task draws, each with three timing repeats. "
             "Every planned run has a marker, with fixed horizontal offsets for visibility. Open upward triangles show genuine optimization-time censoring at the smaller of the observed elapsed time and the allocated budget; the time to certification is at least this cutoff. "
             "Open diamonds show a reported native optimal direct solve that did not pass the full certificate policy. The lower strips classify outcomes for which no admissible LP timing is plotted; their vertical coordinates have no time meaning. "
             "External watchdog expiry includes diagnostic time and is not treated as an optimization-time bound. The dashed line marks the 1,800-second budget. No line connects completed-only summaries. "
             "Elapsed time includes method construction and computation through algorithm stopping, but excludes final independent diagnostics. The CG arm is the frozen cold-RMP implementation without basis reuse. "
             "Draws at different task counts are not nested. "+("State: "+"; ".join(report_state(report))+". " if report_state(report) else "")+"\n")
    (args.output/"lp_scaling_figure_caption.txt").write_text(caption)
    output_hashes={path.name:digest(path) for path in sorted(args.output.iterdir()) if path.is_file()}
    manifest={"schema_version":1,"source_analysis":str(args.analysis.resolve()),"analysis_sha256":digest(args.analysis),
              "source_workers":str(args.workers.resolve()) if args.workers else None,"workers_sha256":digest(args.workers) if args.workers else None,
              "helper_sha256":digest(__file__),"analysis_analyzer_sha256":report.get("analyzer_sha256"),
              "planned_outcomes":108,"displayed_outcomes":len(rows),"display_class_counts":dict(collections.Counter(row["display_code"] for row in rows)),
              "state":report_state(report),"all_outcomes_included":True,"connecting_trend_lines":False,
              "timing_rounding":"raw CSV/JSON unrounded; LaTeX displays three significant figures",
              "output_sha256":output_hashes}
    (args.output/"lp_scaling_display_manifest.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"output":str(args.output.resolve()),"outcomes":len(rows),"classes":manifest["display_class_counts"],"state":manifest["state"]},indent=2))


if __name__=="__main__":main()
