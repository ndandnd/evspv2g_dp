"""Export the final independently audited LP comparison without hiding censors."""
import argparse, hashlib, json, os
from pathlib import Path
import numpy as np
os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/opte-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

def main():
    p=argparse.ArgumentParser();p.add_argument('--analysis',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    d=json.loads(a.analysis.read_text())
    if not d['global_checks_passed'] or not d['independent_verification_requested']:
        raise ValueError('Final complete independently audited analysis required')
    rows=d['raw_worker_rows']
    assert len(rows)==54 and len({(r['case'],r['repeat'],r['variant']) for r in rows})==54
    if a.output.exists():raise ValueError('Fresh output directory required')
    a.output.mkdir(parents=True)
    variants=['cold','reuse','barrier'];colors=['#70777D','#0072B2','#009E73']
    names=['Cold-master CG','Reused-master CG','Direct barrier'];sizes=[100,400,1000]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'pdf.fonttype':42,'ps.fonttype':42})
    fig,axes=plt.subplots(1,2,figsize=(10.5,4.7),layout='constrained')
    shown=[]
    for j,(v,c) in enumerate(zip(variants,colors)):
        for k,n in enumerate(sizes):
            group=sorted([r for r in rows if r['variant']==v and r['n_tasks']==n],
                         key=lambda r:(r['draw_seed'],r['repeat']))
            assert len(group)==6
            completed=[];memory=[]
            for index,r in enumerate(group):
                x=k+(j-1)*.23+(index-2.5)*.013
                accepted=bool(r['primary_accepted'] or r.get('supplementary_accepted'))
                t=r.get('solve_end_to_end_seconds')
                if accepted:
                    if t is None or t<=0:raise ValueError('Invalid completed clock')
                    axes[0].scatter(x,t,s=23,c=c,alpha=.8,edgecolors='none');completed.append(t)
                    kind='certified completion'
                elif r.get('genuine_optimization_time_limit'):
                    t=min(t,r['budget_seconds'])
                    axes[0].scatter(x,t,s=49,marker='^',facecolors='none',edgecolors=c)
                    kind='time-limit lower bound'
                else:
                    raise ValueError('Unplotted failed outcome: '+str((r['case'],v,r['status'])))
                rss=r.get('process_peak_rss_at_stop_bytes')
                if rss is None or rss<=0:raise ValueError('Missing peak RSS')
                mib=rss/2**20;memory.append(mib)
                if accepted:
                    axes[1].scatter(x,mib,s=23,c=c,alpha=.8,edgecolors='none')
                else:
                    axes[1].scatter(x,mib,s=49,marker='^',facecolors='none',edgecolors=c)
                shown.append({'case':r['case'],'repeat':r['repeat'],'variant':v,
                              'time_kind':kind,'display_seconds':t,'peak_rss_mib':mib})
            center=k+(j-1)*.23
            if len(completed)==6:
                axes[0].plot([center-.055,center+.055],[np.median(completed)]*2,color=c,lw=2.5)
            axes[1].plot([center-.055,center+.055],[np.median(memory)]*2,color=c,lw=2.5)
    for ax in axes:
        ax.set_xticks(range(3),['100','400','1,000']);ax.set_xlabel('Tasks')
        ax.grid(axis='y',color='#E3E6E8',lw=.6);ax.set_axisbelow(True)
    axes[0].set_yscale('log');axes[0].set_ylabel('Algorithm time (seconds, log scale)')
    axes[0].axhline(1800,color='#AAA',linestyle=':',lw=.8)
    axes[0].set_title('LP computation',loc='left',fontweight='bold')
    axes[1].set_ylabel('Peak process RSS at algorithm stop (MiB)')
    axes[1].set_title('Observed memory use',loc='left',fontweight='bold')
    handles=[Line2D([],[],marker='o',linestyle='none',color=c,label=name) for c,name in zip(colors,names)]
    handles+=[Line2D([],[],marker='^',linestyle='none',markerfacecolor='none',color='#444',label='Time-limited run (unfinished)')]
    fig.legend(handles=handles,loc='outside lower center',ncol=2,frameon=False)
    fig.suptitle('Fifteen-location LP comparison: two task draws, three timing repetitions',fontsize=12)
    for ext in ('png','pdf'):fig.savefig(a.output/f'lp_implementation_comparison.{ext}',dpi=200)
    plt.close(fig)
    note={'analysis_sha256':hashlib.sha256(a.analysis.read_bytes()).hexdigest(),
          'all_54_logical_outcomes_plotted':True,'data':shown,
          'scope':'Selected complete matched blocks only; original interrupted executions retained in source analysis. Independent validation excluded from clocks. Repetitions are not independent task draws. Dashes are medians; none shown for time-limited groups. Peak RSS for timeouts is an observed partial-run peak, not memory needed to complete.'}
    (a.output/'plot_provenance.json').write_text(json.dumps(note,indent=2)+'\n')
    (a.output/'README.md').write_text('# LP implementation comparison\n\n'+note['scope']+'\n\nSee the source analysis for host/recovery provenance, strict versus supplementary certificates and every outcome. This standalone research figure does not alter the manuscript figure numbering.\n')

if __name__=='__main__':main()
