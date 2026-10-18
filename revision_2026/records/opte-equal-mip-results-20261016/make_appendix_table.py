"""LaTeX table for the 23-input equal-MIP-time study (Appendix D)."""
import json
rows=json.load(open('prelim_rows.json'))
import os
def first_inc(c):
    p=f'raw/{c}/direct_mip/result.json'
    d=json.load(open(p)); ev=d.get('incumbent_events') or []
    return ev[0]['objective'] if ev else None
g=lambda U,B: None if U is None or B is None else max(0.0,100*(U-B)/U)
def lab(c):
    if c.startswith('panel_energy'):
        st={'25':'25','12p5':'12.5','6p25':'6.25'}[c.split('energy')[1].split('_')[0]]; return f"100/15/{st}", 'var.', c[-1]
    if c.startswith('panel_map'):
        L=c.split('map')[1].split('_')[0]; return f"200/{L}/25", 'var.', c[-1]
    if c.startswith('scale_'):
        n=c.split('_n')[1].split('_')[0]; L=int(c.split('_L')[1].split('_')[0]); d=c.split('_d')[1].split('_')[0]; return f"{n}/{L}/{d}", '100', c[-1]
    L=int(c.split('_L')[1].split('_')[0]); return f"1000/{L}/50", '100', c[-1]
def fm(x,d=0): return '--' if x is None else f"{x:,.{d}f}".replace(',', '{,}')
order={'panel_energy25':0,'panel_energy12p5':1,'panel_energy6p25':2}
rows.sort(key=lambda r:(0 if r['case'].startswith('panel') else 1 if r['case'].startswith('scale') else 2, order.get(r['case'].rsplit('_',1)[0],9), r['case']))
out=[]
for r in rows:
    inp,E,dr=lab(r['case'])
    root=r.get('d_root_s'); rs='unfinished' if root is None else fm(root)
    gp=g(r.get('pool_U'),r['LBstar'])
    d=r.get('d_U1800'); gd=g(d,r['LBstar'])
    fb = d is not None and abs(d-first_inc(r['case']))<1e-6 and gd is not None and gd>20
    ds='fallback' if fb else (f"{gd:.2f}" if gd is not None else '--')
    cg=fm(r['cg_s']) + ('' if r.get('cg_conv',True) else '$^\\ast$')
    win = (gp is not None and gd is not None and gp < gd - 1e-9)
    gps=f"{gp:.2f}"
    if win: gps='\\textbf{'+gps+'}'
    elif not fb and gd is not None and gd < gp - 1e-9: ds='\\textbf{'+ds+'}'
    out.append(f"{inp}/{int(dr) + 1} & {E} & {r['arcs']/1e6:.2f} & {cg} & {rs} & {gps} & {ds} \\\\")
    if r['case'] in ('panel_map75_draw1','scale_n4000_L15_d50_s0'): out.append('\\midrule')
open('appendix_table_rows.tex','w').write('\n'.join(out)+'\n'); print('\n'.join(out))
