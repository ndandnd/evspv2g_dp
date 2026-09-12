"""True Phase I for an initially infeasible trip-partitioning restricted LP.

Artificial trip coverage and per-slot emergency generation are feasibility
slacks. Zero Phase-I cost is followed by a real-pool LP check; positive economic
artificial penalties alone never classify full-family infeasibility.
"""
from __future__ import annotations
from copy import deepcopy
from time import perf_counter, process_time
import numpy as np
import master
from master import Column
from column_validation import column_key, replay_column
from pricing_truck import price_truck_dp
from stochastic_master import StochasticTemplate, lp as phase_lp


def _check_phase_vector(model, result, tol=1e-6):
    c, au, bu, ae, be, lo, hi, _ = model
    x = result.x
    if x is None or np.shape(x) != np.shape(c) or not np.isfinite(x).all():
        return False, float('inf')
    violation = max(0., float(np.max(au@x-bu,initial=0)),
        float(np.max(np.abs(ae@x-be),initial=0)), float(np.max(lo-x,initial=0)),
        float(np.max(x-hi,initial=0)))
    match = np.isfinite(result.fun) and abs(c@x-result.fun) <= max(1e-6,1e-9*abs(result.fun))
    return bool(violation <= tol and match), violation


def find_feasible_pool(inst, cols, caps, soc_mode='cyclic', tol=1e-6,
                       max_iter=1000, pricing_cache=True):
    """Return `status`, cols, proof, iterations and telemetry.

    `feasible` means a real-column LP has an independently verified feasible
    vector, not that an integer policy exists. On this outcome the returned pool
    has artificials removed and requires a fresh persistent-master session.
    `infeasible_certified` refers only to the admitted grid/profile LP family,
    with at least one covered trip per truck and exact trip partitioning.
    Unsupported transformations or inconclusive numerical/budget exits return
    `unresolved`; invalid columns raise ValueError, not an infeasibility claim.
    """
    if not np.isfinite(tol) or tol <= 0 or max_iter < 0:
        raise ValueError('Phase-I tolerance must be positive and iteration budget nonnegative')
    start, cpu = perf_counter(), process_time()
    pool = list(cols)
    telemetry = dict(template_seconds=0.,lp_build_seconds=0.,lp_solve_seconds=0.,
                     pricing_seconds=0.,replay_seconds=0.,normal_lp_seconds=0.,
                     added_columns=0, added_artificials=0)
    events=[]
    scope=('trip-partitioning LP over physically replayed admitted lattice/profile truck routes; '
           'each real truck covers at least one trip; not an integer infeasibility proof beyond that family')
    def finish(status, reason, proof=None, answer_pool=None):
        telemetry['total_wall_seconds']=perf_counter()-start
        telemetry['process_cpu_seconds']=process_time()-cpu
        p=dict(scope=scope,reason=reason,exact_pricing=False,
               full_family_lower_bound=None,phase_objective=None)
        p.update(proof or {})
        return dict(status=status,cols=pool if answer_pool is None else answer_pool,
                    proof=p,iterations=events,telemetry=telemetry)
    if master.COVERING:
        return finish('unresolved','Phase I requires exact trip partitioning; covering not certified')
    if caps.get('flat_price',False):
        return finish('unresolved','flattened-energy arm needs a separate Phase-I model')
    flags={k:bool(caps[k]) for k in ('allow_charge','allow_discharge','ice')}
    keys=set()
    t=perf_counter()
    for col in pool:
        if not replay_column(inst,col,soc_mode=soc_mode,**flags):
            raise ValueError('Phase-I input fails physical replay: '+col.label)
        if col.kind=='truck':
            expected=inst.c_v+inst.deg_cost*float(np.maximum(-col.e,0).sum())
            if abs(col.fixed_cost-expected)>1e-8*max(1.,abs(expected)):
                raise ValueError('Phase-I input cost differs from original physics')
        key=column_key(col)
        if key in keys:
            # Existing exact duplicates do not invalidate the LP; preserve the
            # input pool while treating any new improving duplicate as an error.
            continue
        keys.add(key)
    telemetry['replay_seconds']+=perf_counter()-t
    # Artificial coverage for every trip is needed even when the incoming pool
    # contains a capacity-incompatible selection of physically valid real routes.
    artificial_trips={int(np.flatnonzero(c.a)[0]) for c in pool if c.kind=='artificial'}
    for i in range(inst.n_trips):
        if i not in artificial_trips:
            a=np.zeros(inst.n_trips);a[i]=1.
            col=Column('artificial',a,np.zeros(inst.T),1e6,f'phase_art[{i}]')
            pool.append(col);keys.add(column_key(col));telemetry['added_artificials']+=1
    t=perf_counter()
    template=StochasticTemplate([inst],weights=[1.],battery_allowed=bool(caps['battery']),
                                method='saa',soc_mode='cyclic' if soc_mode.startswith('pin') else soc_mode)
    telemetry['template_seconds']+=perf_counter()-t
    pricing_inst=deepcopy(inst)
    pricing_inst.c_v=0.;pricing_inst.eps_pen=0.;pricing_inst.deg_cost=0.
    last={}
    for iteration in range(max_iter):
        t=perf_counter();model=template.build(pool,phase_cap=inst.gen_cap)
        telemetry['lp_build_seconds']+=perf_counter()-t
        t=perf_counter();result=phase_lp(model)
        telemetry['lp_solve_seconds']+=perf_counter()-t
        if not result.success:
            return finish('unresolved','Phase-I native LP exit: '+str(result.message),
                          dict(native_status=int(result.status)))
        valid,residual=_check_phase_vector(model,result)
        if not valid:
            return finish('unresolved','Phase-I primal/objective verification failed',
                          dict(primal_violation=residual))
        R=len(pool)
        artificial=float(sum(result.x[j] for j,c in enumerate(pool) if c.kind=='artificial'))
        emergency=float(np.sum(result.x[-inst.T:]))
        objective=float(result.fun)
        last=dict(phase_objective=objective,artificial_mass=artificial,
                  emergency_energy=emergency,primal_violation=residual)
        event=dict(iteration=iteration,columns=R,phase_objective=objective,
                   artificial_mass=artificial,emergency_energy=emergency,added=0)
        events.append(event)
        if objective <= tol:
            real=[c for c in pool if c.kind=='truck']
            t=perf_counter();normal=master.solve_lp(inst,real,battery_allowed=bool(caps['battery']),soc_mode=soc_mode)
            telemetry['normal_lp_seconds']+=perf_counter()-t
            if normal.has_incumbent and normal.status in ('optimal','feasible'):
                last.update(real_pool_objective=normal.obj,
                            real_pool_primal_violation=normal.validation_max_violation,
                            real_pool_columns=len(real),requires_session_reset=True,
                            full_family_lower_bound=0.,
                            phase_optimality_certificate='nonnegative objective and verified feasible zero-slack real pool')
                return finish('feasible','verified real-pool LP without artificial/emergency variables',last,real)
            # A tiny positive slack can matter to feasibility; do not declare a
            # feasible pool solely from the Phase-I objective threshold.
        dual=template.pricing_duals(result)
        if not all(np.isfinite(v).all() for v in dual.values()):
            return finish('unresolved','nonfinite Phase-I duals',last)
        fleet=float(dual['fleet_price'])
        if fleet < -1e-8:
            return finish('unresolved','fleet dual sign invalid for Phase-I certificate',last)
        t=perf_counter()
        candidates=price_truck_dp(pricing_inst,dual['alpha'],dual['mu'],nu=dual['nu'],
            soc_mode=soc_mode,tol=tol,use_cache=pricing_cache,**flags)
        telemetry['pricing_seconds']+=perf_counter()-t
        minimum=min((float(rc)+fleet for _,rc in candidates),default=-tol+fleet)
        event['minimum_reduced_cost_lower_bound']=minimum
        event['exact_pricing']=True
        effective_tol=max(tol,tol-fleet)  # retain a tiny negative marginal in the bound
        for priced,reported in candidates:
            direct=template.reduced_cost(priced,result,phase=True)
            if abs(direct-(reported+fleet))>max(1e-10,1e-10*abs(direct)):
                raise RuntimeError('Phase-I DP and master reduced costs disagree')
            if direct >= -tol:
                continue
            restored=Column('truck',np.array(priced.a,copy=True),np.array(priced.e,copy=True),
                inst.c_v+inst.deg_cost*float(np.maximum(-priced.e,0).sum()),priced.label+'|phase1')
            t=perf_counter();valid=replay_column(inst,restored,soc_mode=soc_mode,**flags)
            telemetry['replay_seconds']+=perf_counter()-t
            if not valid:
                raise RuntimeError('Phase-I reconstructed truck fails physical replay')
            key=column_key(restored)
            if key in keys:
                raise RuntimeError('Phase-I exact pricing returned an improving duplicate; no certificate')
            pool.append(restored);keys.add(key);event['added']+=1;telemetry['added_columns']+=1
        if not event['added']:
            lower=max(0.,objective-inst.n_trips*effective_tol)
            last.update(exact_pricing=True,certificate_tolerance=effective_tol,
                        minimum_reduced_cost_lower_bound=minimum,
                        full_family_lower_bound=lower)
            if lower > tol:
                return finish('infeasible_certified','positive true Phase-I LP lower bound',last)
            return finish('unresolved','Phase-I bound overlaps zero and real-pool feasibility was not verified',last)
    return finish('unresolved','Phase-I iteration budget exhausted',last)
