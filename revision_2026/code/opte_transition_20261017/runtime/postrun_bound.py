"""Untimed post-run full-family lower bound for a CG arm, from its saved stopping duals.

Same repair as frozen/direct_common_certificate.py: project generation prices onto
[0, c_g] (no charging-cap rows), contract all prices if a unit periodic BESS has
negative reduced cost, then lower every task price by epsilon = max(0, -min route
reduced cost) over every DP path and real singleton seed. The repaired prices are
dual feasible, so their objective is a valid lower bound on the full-family LP and on
the integer optimum (weak duality). No optimization; the timed result is unchanged.
"""
import json, sys
from pathlib import Path
import numpy as np
RUNTIME = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME))
import run_transition as R                 # sets up frozen paths
from direct_common_certificate import price_family, RESERVE
from extension_models import build_extended_graph, _seeds_with_witnesses

def bound(folder):
    folder = Path(folder)
    res = json.loads((folder / 'result.json').read_text())
    man = json.loads((folder / 'manifest.json').read_text())
    spec = man['case']; inst = R.build_case(spec)
    with np.load(folder / 'cg_stopping_primal.npz') as z:
        alpha, mu, nu = z['alpha'].astype(float).copy(), z['mu'].astype(float).copy(), z['nu'].astype(float).copy()
    graph = build_extended_graph(inst); seeds, _ = _seeds_with_witnesses(inst)
    raw = price_family(inst, graph, seeds, alpha, mu, nu)
    mu = np.clip(mu, 0.0, inst.c_g); nu = np.zeros_like(nu)
    p = price_family(inst, graph, seeds, alpha, mu, nu)
    delta = max(0.0, -p['unit_bess_reduced_cost']); scale = 1.0
    if delta > 0:
        scale = (inst.c_b - RESERVE) / (inst.c_b + delta); alpha *= scale; mu *= scale
    c = price_family(inst, graph, seeds, alpha, mu, nu)
    eps = max(0.0, -c['route_min_reduced_cost']); eps = eps + RESERVE if eps > 0 else 0.0
    alpha -= eps
    f = price_family(inst, graph, seeds, alpha, mu, nu)
    feasible = bool(f['route_min_reduced_cost'] >= -1e-9 and f['unit_bess_reduced_cost'] >= -1e-9 and mu.min() >= 0 and mu.max() <= inst.c_g)
    out = {'case': spec['case'], 'cg_status': res.get('cg_status'), 'z_rmp': (res.get('cg_lp') or {}).get('objective'),
           'raw_route_min_rc': raw['route_min_reduced_cost'], 'raw_dual_objective': raw['dual_objective'],
           'scale': scale, 'epsilon': eps, 'postrun_lower_bound': f['dual_objective'] if feasible else None,
           'repaired_dual_feasible': feasible, 'timed_result_unchanged': True}
    (folder / 'postrun_bound.json').write_text(json.dumps(out, indent=1))
    return out

if __name__ == '__main__':
    for f in sys.argv[1:]:
        try: print(json.dumps(bound(f)))
        except Exception as e: print(json.dumps({'folder': f, 'error': repr(e)}))
