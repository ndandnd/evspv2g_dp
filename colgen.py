"""
Column generation for the covering-plus-arbitrage EVSP-V2G.

Trucks are priced by the labeling DP (pricing_truck); the stationary battery fleet
is an aggregate block solved inside the RMP, so CG only needs to price trucks
(coverage). Dual stabilization (smoothing) with a true-dual fallback controls the
tail while keeping termination correct.
"""
from __future__ import annotations
import time
import numpy as np
from instance import Instance, make_instance
from master import Column, solve_lp, solve_milp, reduced_cost
from pricing_truck import price_truck_dp
from column_validation import column_key, replay_column


def _col_key(c: Column):
    return column_key(c)


SCENARIOS = {                          # (ice, allow_charge, allow_discharge, battery)
    "vsp":   dict(ice=True,  allow_charge=False, allow_discharge=False, battery=False),
    "ev":    dict(ice=False, allow_charge=True,  allow_discharge=False, battery=False,
                  flat_price=True),     # plain EVSP (original mode 1): solar-blind, every
                                        # charged kWh pays c_g flat; fleet does not touch
                                        # the power balance (energy folded into route cost)
    "solar": dict(ice=False, allow_charge=True,  allow_discharge=False, battery=False),
    "solar_bess": dict(ice=False, allow_charge=True, allow_discharge=False, battery=True),
                                        # charge-only trucks WITH purchasable stationary
                                        # storage -- the missing factorial arm (V1G+BESS)
    "v2g":   dict(ice=False, allow_charge=True,  allow_discharge=True,  battery=True),
    "v2g_fleet": dict(ice=False, allow_charge=True, allow_discharge=True, battery=False),
                                        # V2G-capable fleet at a depot WITHOUT stationary
                                        # storage -- isolates what the fleet alone can do
}


def _flatten_col(col: Column, inst: Instance) -> Column:
    """Flat-price scenario: fold energy cost (c_g per drawn unit) into the fixed
    cost and zero the profile, so the master's balance neither sees nor credits it."""
    draw = float(np.maximum(col.e, 0.0).sum())
    if draw <= 1e-12:
        return col
    return Column(col.kind, col.a, np.zeros(inst.T), col.fixed_cost + inst.c_g * draw + inst.eps_pen * col.throughput(),
                  col.label + "|flat")


def single_trip_column(inst: Instance, tr, ice: bool = False, free_start: bool = False) -> Column:
    """Full-start single-trip seed, physically feasible on the declared lattice."""
    from pricing_contract import grid_index, validate_storage
    try:
        T,step,nlevels,_,_=validate_storage(inst,None)
        outbound=grid_index(inst.dist[inst.depot,tr.sloc],1.,'outbound time')
        inbound=grid_index(inst.dist[tr.eloc,inst.depot],1.,'inbound time')
        if tr.start!=int(tr.start) or tr.end!=int(tr.end) or not 0<=tr.start<tr.end<=T:return None
        dep=tr.start-outbound;ret=tr.end+inbound
        if dep<0 or ret>T:return None
        a=np.zeros(inst.n_trips);a[tr.idx]=1.;e=np.zeros(T)
        if not ice:
            levels=sum(grid_index(value,step,'single-trip traction') for value in
                       (tr.energy,inst.deadhead_energy(inst.depot,tr.sloc),
                        inst.deadhead_energy(tr.eloc,inst.depot)))
            if levels>nlevels-1:return None
            if not free_start:
                rate=min(inst.rho,float(inst.charge_cap))
                if rate<0:return None
                # Match pricing's conservative floor; do not admit one extra
                # level using an absolute epsilon around a rate boundary.
                per=int(np.floor(min(nlevels-1,(1-inst.eta)*rate/step)))
                left=levels
                if left>(T-ret)*per:return None
                for t in range(ret,T):
                    q=min(per,left);e[t]=q*step/(1-inst.eta);left-=q
                    if not left:break
    except (ValueError,TypeError,OverflowError):return None
    return Column('truck',a,e,inst.c_v,f'single[{tr.idx}]')


def dp_greedy_columns(inst: Instance, caps: dict, rounds: int = 40, rng=None,
                      soc_mode: str = "cyclic", *, pricing_cache: bool = True) -> list[Column]:
    """Multi-trip covering columns via repeated DP: reward uncovered trips, forbid
    re-covering already-covered ones, peel off a route each round. With an rng, the
    per-trip reward is randomized so repeated calls yield distinct full covers."""
    cols = []
    remaining = set(range(inst.n_trips))
    mu = np.full(inst.T, 0.0)
    for _ in range(rounds):
        if not remaining:
            break
        alpha = np.full(inst.n_trips, -1e6)
        for i in remaining:
            alpha[i] = (rng.uniform(2.0, 4.0) if rng is not None else 3.0) * inst.c_v
        out = price_truck_dp(inst, alpha, mu, allow_charge=caps["allow_charge"],
                             allow_discharge=caps["allow_discharge"], ice=caps["ice"],
                             soc_mode=soc_mode,use_cache=pricing_cache)
        if not out:
            break
        col = out[0][0]
        covered = set(np.flatnonzero(col.a > 0.5).tolist()) & remaining
        if not covered:
            break
        cols.append(col)
        remaining -= covered
    return cols


ARTIFICIAL_COST = 1e6                    # Phase-I penalty. Artificials carry zero
                                         # energy, so the initial RMP is feasible under
                                         # any caps PROVIDED the no-fleet power balance
                                         # is itself feasible (they cover tasks but
                                         # cannot relax the balance). NOTE: positive artificial mass in
                                         # the priced-out ECONOMIC LP is only a trigger,
                                         # not a certificate -- a finite penalty can park
                                         # fractional mass on a feasible instance whose
                                         # marginal coverage cost exceeds 1e6 near a cap
                                         # boundary. Infeasibility is certified by a true
                                         # Phase-I (min artificial mass, real costs
                                         # zeroed) priced to optimality; see
                                         # overnight13._phase1_certify.

def artificial_column(inst: Instance, tr) -> Column:
    a = np.zeros(inst.n_trips); a[tr.idx] = 1.0
    return Column("artificial", a, np.zeros(inst.T), ARTIFICIAL_COST, label=f"art[{tr.idx}]")


def initial_columns(inst: Instance, start: str, caps: dict,
                    soc_mode: str = "cyclic", *, pricing_cache: bool = True) -> list[Column]:
    base = []
    for tr in inst.trips:
        # the single-trip constructor assumes a full-charge start and a
        # restore-to-full ending, which is boundary-infeasible under a pinned
        # level c < G; pinned runs initialize from artificials + DP covers only
        c = None if soc_mode.startswith("pin") else \
            single_trip_column(inst, tr, ice=caps["ice"], free_start=(soc_mode == "free"))
        if c is not None:
            base.append(c)
        base.append(artificial_column(inst, tr))   # Phase-I coverage for EVERY task:
                                                   # seeds can violate shared caps that
                                                   # pricing would respect, and the RMP
                                                   # must never be infeasible before
                                                   # pricing has run
    if start == "cold":
        return base
    extra = dp_greedy_columns(inst, caps, soc_mode=soc_mode,pricing_cache=pricing_cache)
    seen = set(_col_key(c) for c in base)
    return base + [c for c in extra if _col_key(c) not in seen]


def column_generation(inst: Instance, scenario: str = "v2g", start: str = "warm",
                      tol: float = 1e-6, rc_stop: float = 0.0, beta: float = 0.5,
                      max_iter: int = 1000, do_milp: bool = True, verbose: bool = False,
                      enrich: int = 25, lp_solver: str = "highs", milp_solver: str = "cbc",
                      soc_mode: str = "cyclic", extra_cols: list | None = None,
                      *, pricing_cache: bool = True, warm_max_columns: int = 512,
                      warm_max_candidates: int = 4096, warm_max_seconds: float = 60.):
    """CG with explicit exact-pricing termination and bounded validated imports.

    A finite-pool incumbent is separate from a priced LP lower bound. The lower
    bound correction applies to the admitted lattice/profile family with exact
    trip partitioning and zero artificial mass; it is omitted for covering mode.
    """
    from pricing_truck import prepare_pricing
    import master as master_module
    if max_iter<0 or tol<=0 or rc_stop<0 or not 0<=beta<=1:
        raise ValueError('Invalid iteration, tolerance or smoothing setting')
    if min(warm_max_columns,warm_max_candidates,warm_max_seconds)<0:
        raise ValueError('Warm import budgets must be nonnegative')
    caps=SCENARIOS[scenario];batt=caps['battery'];flat=caps.get('flat_price',False)
    wall_start=time.perf_counter();cpu_start=time.process_time()
    prepare_pricing(inst,ice=caps['ice'],use_cache=pricing_cache)
    timers=dict(initialization_seconds=0.,warm_import_seconds=0.,lp_seconds=0.,
                lp_build_seconds=0.,lp_solve_seconds=0.,pricing_seconds=0.,
                replay_seconds=0.,enrichment_seconds=0.,mip_seconds=0.)
    validated=set()
    def validate(col):
        key=_col_key(col)
        if key in validated:return
        t=time.perf_counter()
        ok=replay_column(inst,col,allow_charge=caps['allow_charge'],allow_discharge=caps['allow_discharge'],ice=caps['ice'],soc_mode=soc_mode)
        timers['replay_seconds']+=time.perf_counter()-t
        if not ok:raise ValueError('Column fails independent physical replay: '+col.label)
        if col.kind=='truck':
            expected=inst.c_v+inst.deg_cost*float(np.maximum(-col.e,0).sum())
            if abs(col.fixed_cost-expected)>1e-8*max(1.,abs(expected)):
                raise ValueError('Column fixed cost does not match current physics')
        validated.add(key)
    t=time.perf_counter();cols=initial_columns(inst,start,caps,soc_mode=soc_mode,pricing_cache=pricing_cache)
    for col in cols:validate(col)
    timers['initialization_seconds']=time.perf_counter()-t
    keys={_col_key(c) for c in cols}
    warm=dict(scanned=0,accepted=0,rejected=0,duplicates=0,stop='exhausted',
              max_columns=warm_max_columns,max_candidates=warm_max_candidates,max_seconds=warm_max_seconds)
    t=time.perf_counter()
    if extra_cols is not None:
        for col in extra_cols:
            if warm['accepted']>=warm_max_columns:warm['stop']='column_limit';break
            if warm['scanned']>=warm_max_candidates:warm['stop']='scan_limit';break
            if time.perf_counter()-t>=warm_max_seconds:warm['stop']='time_limit';break
            warm['scanned']+=1
            try:
                key=_col_key(col)
                if key in keys:warm['duplicates']+=1;continue
                if col.kind!='truck':raise ValueError('Warm imports must be real trucks')
                validate(col)
            except (ValueError,TypeError,IndexError):warm['rejected']+=1;continue
            cols.append(col);keys.add(key);warm['accepted']+=1
    timers['warm_import_seconds']=time.perf_counter()-t
    phase_result=None
    if max_iter>0 and not flat and not master_module.COVERING:
        from phase1 import find_feasible_pool
        phase_result=find_feasible_pool(inst,cols,caps,soc_mode=soc_mode,tol=tol,max_iter=max_iter,pricing_cache=pricing_cache)
        timers['phase1_seconds']=phase_result['telemetry']['total_wall_seconds']
        if phase_result['status']=='feasible':
            cols=phase_result['cols']
            for c in cols:validate(c)
        else:
            # Keep the diagnosed augmented pool for reporting, but do not run
            # economic pricing or interpret a restricted LP exit as proof.
            max_iter=0;enrich=0
    if flat:cols=[_flatten_col(c,inst) for c in cols]
    keys={_col_key(c) for c in cols}
    session=None
    if lp_solver=='gurobi_persistent':
        from persistent_master import PersistentGurobiMaster
        session=PersistentGurobiMaster(inst,battery_allowed=batt,soc_mode=soc_mode)
    def solve():
        t=time.perf_counter()
        sol=session.solve(cols,inst=inst) if session else solve_lp(inst,cols,battery_allowed=batt,solver=lp_solver,soc_mode=soc_mode)
        timers['lp_seconds']+=time.perf_counter()-t
        st=getattr(sol,'timings',{}) or {}
        timers['lp_build_seconds']+=st.get('build_seconds',0.)+st.get('append_seconds',0.)
        timers['lp_solve_seconds']+=st.get('solve_seconds',0.)
        return sol
    def price(alpha,mu,nu):
        if flat:mu=np.full(inst.T,inst.c_g);nu=np.zeros(inst.T)
        t=time.perf_counter()
        cand=price_truck_dp(inst,alpha,mu,nu=nu,allow_charge=caps['allow_charge'],
                            allow_discharge=caps['allow_discharge'],ice=caps['ice'],
                            soc_mode=soc_mode,tol=max(tol,rc_stop),use_cache=pricing_cache)
        timers['pricing_seconds']+=time.perf_counter()-t
        result=[]
        for col,reported in cand:
            direct=col.cost(inst.eps_pen)-col.a@alpha+col.e@mu+np.maximum(col.e,0)@nu
            error=abs(direct-reported)
            if error>max(1e-10,1e-10*abs(direct)):
                raise RuntimeError('Pricing minimum and reconstructed column disagree')
            validate(col)
            result.append((_flatten_col(col,inst) if flat else col,reported))
        return result
    prev=None;lp=None;lp_count=-1;iters=0;stop=max(tol,rc_stop)
    events=[];converged=False;term_reason='max_iter';last_exact_minimum=None
    try:
        for it in range(max_iter):
            lp=solve();lp_count=len(cols);iters=it+1
            if lp.status!='optimal':term_reason='lp_'+lp.status;break
            nv=lp.nu if lp.nu is not None else np.zeros(inst.T)
            if prev is None:duals=(lp.alpha,lp.mu,nv)
            else:duals=tuple(beta*a+(1-beta)*b for a,b in zip(prev,(lp.alpha,lp.mu,nv)))
            prev=tuple(x.copy() for x in (lp.alpha,lp.mu,nv))
            added=0;duplicates=0;best=0.;fallback=False
            for exact in [False,True]:
                if exact and added:break
                d=(lp.alpha,lp.mu,nv) if exact else duals
                candidates=price(*d);fallback=exact
                if exact:
                    last_exact_minimum=min((rc-getattr(lp,'fleet_dual',0.) for col,rc in candidates),default=-stop)
                for col,reported in candidates:
                    rc=reduced_cost(col,lp,inst);best=min(best,rc)
                    if rc < -stop:
                        if _col_key(col) in keys:
                            duplicates+=1
                            if exact:raise RuntimeError('Exact pricing returned an improving duplicate; no certificate')
                            continue
                        cols.append(col);keys.add(_col_key(col));added+=1
                if exact:break
            event=dict(iteration=it,objective=float(lp.obj),columns=lp_count,added=added,
                       best_true_reduced_cost=float(best),exact_fallback=fallback,improving_duplicates=duplicates)
            events.append(event)
            if verbose and ((it+1)%10==0 or not added):print(event,flush=True)
            if not added:
                if not fallback:raise RuntimeError('Termination requires exact current-dual pricing')
                converged=True;term_reason='priced_out';break
        if lp is None or lp_count!=len(cols):lp=solve();lp_count=len(cols)
        if lp.status!='optimal':converged=False;term_reason='lp_'+lp.status
        artificial_mass=float(sum(lp.x[k] for k,c in enumerate(cols) if c.kind=='artificial')) if lp.status=='optimal' else None
        if converged and artificial_mass>1e-7:
            converged=False;term_reason='priced_out_with_artificials_unresolved'
        lower=float(lp.obj-inst.n_trips*stop) if converged and not master_module.COVERING else None
        # Enrichment follows certification and never changes the bound's scope.
        t=time.perf_counter()
        if enrich>0 and lp.status=='optimal':
            rng=np.random.default_rng(0);nu=lp.nu if lp.nu is not None else np.zeros(inst.T)
            for _ in range(enrich):
                duals=[x*rng.uniform(.7,1.3,size=x.shape) for x in (lp.alpha,lp.mu,nu)]
                for col,_ in price(*duals):
                    if _col_key(col) not in keys:cols.append(col);keys.add(_col_key(col))
        timers['enrichment_seconds']=time.perf_counter()-t
        if lp_count!=len(cols):lp=solve()
    finally:
        if session:session.close()
    if phase_result is not None and phase_result['status']!='feasible':
        converged=False;term_reason='phase1_'+phase_result['status'];lower=None
    t=time.perf_counter()
    mip=None
    if do_milp:
        real_indices=[k for k,c in enumerate(cols) if c.kind=='truck']
        mip=solve_milp(inst,[cols[k] for k in real_indices],time_limit=120.,battery_allowed=batt,solver=milp_solver,soc_mode=soc_mode)
        real_x=mip.x.copy();mip.x=np.zeros(len(cols));mip.x[real_indices]=real_x
        mip.source_column_indices=real_indices
        mip.scope='finite real-column pool; artificials excluded; native vector uses source_column_indices'
    timers['mip_seconds']=time.perf_counter()-t
    timers['total_wall_seconds']=time.perf_counter()-wall_start
    timers['process_cpu_seconds']=time.process_time()-cpu_start
    return dict(scenario=scenario,lp_obj=lp.obj,mip_obj=mip.obj if mip else None,
                iters=iters,n_cols=len(cols),time=timers['total_wall_seconds']-timers['mip_seconds'],
                pricing_time=timers['pricing_seconds'],lp=lp,mip=mip,cols=cols,
                converged=converged,term_reason=term_reason,artificial_selected=artificial_mass,
                full_lp_lower_bound=lower,certificate_tolerance=stop,
                certificate_scope='exact trip-partitioning lattice-profile LP; zero artificial mass' if lower is not None else None,
                telemetry=timers,iterations=events,warm_import=warm,phase1=phase_result)


def summarize(inst: Instance, res: dict) -> dict:
    mip = res["mip"]; cols = res["cols"]; x = mip.x
    trucks = int(sum(round(x[r]) for r in range(len(cols))))
    fossil = float(mip.g.sum())
    # ICE (VSP): traction is fuel, add it; EV scenarios: traction already in g_t via charging
    traction_fuel = sum(tr.energy for tr in inst.trips) if res["scenario"] == "vsp" else 0.0
    return {"trucks": trucks, "batteries": int(round(mip.nb)),
            "fuel_kwh": round(fossil + traction_fuel, 1), "obj": round(mip.obj, 1)}


if __name__ == "__main__":
    inst = make_instance(n_trips=12, n_locations=3, eps=2.0, seed=7)
    for scen in ("vsp", "solar", "v2g"):
        t = time.time(); res = column_generation(inst, scenario=scen, start="warm", do_milp=True)
        dt = time.time() - t
        gap = (res["mip_obj"] - res["lp_obj"]) / abs(res["mip_obj"]) * 100
        print(f"{scen:6s}: iters={res['iters']:2d} cols={res['n_cols']:3d} gap={gap:.2f}% "
              f"time={dt:.1f}s -> {summarize(inst, res)}")
