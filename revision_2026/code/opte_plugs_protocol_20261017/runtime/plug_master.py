"""Append-only master with explicit connector rows and two-phase objectives."""
from __future__ import annotations
import time
from pathlib import Path
import numpy as np
from plug_problem import rmp_matrices,column_key,validate_column_data


class PlugMaster:
    def __init__(self,problem,phase='feasibility'):
        self.problem=problem;self.phase=phase;self.env=None;self.model=None
        self.cols=[];self.keys=[];self.route_vars=[];self.shared_vars=[];self.basis=None
        self.eq=[];self.le=[];self.plug_start=None;self.basis_restorations=0

    def close(self):
        if self.model is not None:self.model.dispose();self.model=None
        if self.env is not None:self.env.dispose();self.env=None

    def initialize(self,cols,log_path):
        import gurobipy as gp
        mat=rmp_matrices(self.problem,cols,self.phase)
        self.env=gp.Env(empty=True);self.env.setParam('OutputFlag',1 if log_path else 0);self.env.setParam('LogToConsole',0)
        if log_path:self.env.setParam('LogFile',str(log_path))
        self.env.start();self.model=gp.Model('connector_constrained_persistent_RMP',env=self.env)
        m=self.model;m.Params.Threads=1;m.Params.Seed=0;m.Params.Method=-1;m.Params.LPWarmStart=1
        m.Params.FeasibilityTol=1e-8;m.Params.OptimalityTol=1e-8
        variables=m.addMVar(len(mat.c),lb=mat.lb,ub=mat.ub,obj=mat.c)
        eq=m.addMConstr(mat.ae,variables,'=',mat.be);le=m.addMConstr(mat.au,variables,'<',mat.bu)
        m.update();native=list(variables.tolist());self.route_vars=native[:len(cols)];self.shared_vars=native[len(cols):]
        self.eq=list(eq.tolist());self.le=list(le.tolist());self.plug_start=mat.plug_start
        self.cols=list(cols);self.keys=[column_key(c) for c in cols]

    def append(self,cols):
        import gurobipy as gp
        if len(cols)<len(self.cols) or any(old is not new or column_key(new)!=key for old,key,new in zip(self.cols,self.keys,cols)):
            raise ValueError('Persistent master requires unchanged append-only columns')
        added=cols[len(self.cols):];validate_column_data(self.problem,added)
        for col in added:
            rows=[];values=[]
            for i in np.flatnonzero(col.a):rows.append(self.eq[int(i)]);values.append(float(col.a[i]))
            for t in np.flatnonzero(col.e):rows.append(self.le[int(t)]);values.append(float(col.e[t]))
            occupancy=col.occupancy.ravel()[self.problem.finite_cells]
            for j in np.flatnonzero(occupancy):rows.append(self.le[self.plug_start+int(j)]);values.append(float(occupancy[j]))
            objective=(float(col.kind=='artificial') if self.phase=='feasibility' else col.cost(self.problem.inst.eps_pen))
            upper=0. if self.phase=='economic' and col.kind=='artificial' else gp.GRB.INFINITY
            self.route_vars.append(self.model.addVar(lb=0.,ub=upper,obj=objective,column=gp.Column(values,rows)))
            self.cols.append(col);self.keys.append(column_key(col))
        self.model.update()
        if self.basis is not None:
            vb,cb=self.basis
            self.model.setAttr('VBasis',self.model.getVars(),vb+[-1]*len(added))
            self.model.setAttr('CBasis',self.model.getConstrs(),cb);self.model.update();self.basis_restorations+=1
        return len(added)

    def economic_phase(self):
        if self.phase!='feasibility' or self.model is None:raise ValueError('Invalid PhaseI/II transition')
        self.phase='economic';mat=rmp_matrices(self.problem,self.cols,self.phase)
        order=self.route_vars+self.shared_vars
        self.model.setAttr('Obj',order,mat.c.tolist());self.model.setAttr('UB',order,mat.ub.tolist());self.model.update()

    def coefficient_check(self):
        from scipy import sparse
        mat=rmp_matrices(self.problem,self.cols,self.phase);m=self.model
        order=[v.index for v in self.route_vars+self.shared_vars]
        expected=sparse.vstack((mat.ae,mat.au),format='csr');difference=m.getA()[:,order]-expected
        residuals={'matrix':float(np.max(abs(difference.data),initial=0)),
            'objective':float(np.max(abs(np.asarray(m.getAttr('Obj'))[order]-mat.c),initial=0)),
            'rhs':float(np.max(abs(np.asarray(m.getAttr('RHS'))-np.r_[mat.be,mat.bu]),initial=0))}
        return {'passed':max(residuals.values())==0,'residuals':residuals}

    def solve(self,cols,deadline,log_path=None):
        import gurobipy as gp
        began=time.perf_counter()
        if log_path:
            log_path=Path(log_path);log_path.parent.mkdir(parents=True,exist_ok=True)
        if self.model is None:self.initialize(cols,log_path);added=len(cols)
        else:
            if log_path:self.model.Params.LogFile=str(log_path)
            added=self.append(cols)
        built=time.perf_counter();left=deadline-built;m=self.model
        diag={'phase':self.phase,'columns':len(cols),'columns_added':added,'model_build_seconds':built-began,
            'remaining_solver_budget_seconds':max(0.,left),'status':'budget_exhausted_before_optimize',
            'native_status':None,'objective':None,'basis_restorations':self.basis_restorations,
            'variables':m.NumVars,'constraints':m.NumConstrs,'nonzeros':m.NumNZs}
        if left<=0:return None,diag
        m.Params.TimeLimit=left;solve_started=time.perf_counter();m.optimize();stop=time.perf_counter()
        names={2:'optimal',3:'infeasible',4:'infeasible_or_unbounded',5:'unbounded',9:'time_limit',11:'interrupted',12:'numeric',13:'suboptimal'}
        diag.update(status=names.get(m.Status,str(m.Status)),native_status=int(m.Status),
            objective=float(m.ObjVal) if m.SolCount else None,solution_count=int(m.SolCount),
            solver_runtime_seconds=float(m.Runtime),solve_seconds=stop-solve_started,total_seconds=stop-began)
        if m.Status!=gp.GRB.OPTIMAL:return None,diag
        vector=np.asarray(m.getAttr('X',self.route_vars+self.shared_vars));ep=np.asarray(m.getAttr('Pi',self.eq));ip=np.asarray(m.getAttr('Pi',self.le))
        self.basis=(list(m.getAttr('VBasis')),list(m.getAttr('CBasis')))
        pi=np.zeros_like(self.problem.capacities);pi.ravel()[self.problem.finite_cells]=-ip[self.plug_start:]
        inst=self.problem.inst
        solution={'objective':float(m.ObjVal),'vector':vector,'alpha':ep[:inst.n_trips],
            'mu':-ip[:inst.T],'nu':np.zeros(inst.T),'plug_price':pi,'phase':self.phase,
            'artificial_mass':float(sum(vector[j] for j,c in enumerate(cols) if c.kind=='artificial')),
            'native_eq_dual':ep,'native_ub_dual':ip,'native_reduced_cost':np.asarray(m.getAttr('RC',self.route_vars+self.shared_vars))}
        return solution,diag
