# Public software use as of 13 September 2026

We have begun executing public code in isolation. None of these external solvers has been integrated into the EVSP–V2G solver or used to produce waves 7–13. The improvements in our draft algorithm PR and union-pool MIP results came from our own audited implementation.

| Resource | Actual use | Reuse decision and next evidence |
|---|---|---|
| [Parmentier–Martinelli–Vidal implementation](https://github.com/axelparmentier/ElectricalVSP-ColumnGeneration/tree/a13f33ddc3d00aa1fb52ff323a47eac5d521d8e7) | Compiled the unmodified MIT-licensed `ResourceEvsp.cpp` and header on [site identifier omitted], with our isolated C++ test harness. Job 133696 completed successfully. Five right-identity and 121 feasible resource-associativity checks passed. | Use as a reference for compact energy-resource composition. Before adapting dominance or backward bounds, establish equivalence on tiny enumerated V2G paths and include every master dual term. Do not copy its deterministic charge-only resource assumptions directly into stochastic V2G pricing. |
| Full Parmentier CG and branch-and-price | Inspected source and build requirements; not compiled or reproduced. | CPLEX/Concert was not found in the bounded search of standard `/share/apps/software` and `/opt` locations. Stop before a full port. Revisit only if valid full-route gaps affect the scientific comparison after selective pool enrichment. |
| [Baldua csp-res](https://github.com/transnetlab/csp-res) | Inspected author source and Durham inputs; not executed or integrated. | The scenario blocks, common storage boundary and solver Benders partition are relevant. The driver forces an LP and relies on CPLEX annotations; it is not a portable integer-recourse cut library. A two-rotation, eight-period, two-scenario extensive-form equivalence test is the next bounded reuse gate if scenario-master growth becomes a bottleneck. |
| Léa Ricard repository | Inspected the author-linked data/results snapshot; no solver source in that snapshot. | Use a small benchmark trip set only after a documented adapter maps service, energy and charging assumptions. This would support a separate traction-energy benchmark; it is not needed to answer the current weather/controller question. See [verified repository audit](../literature_update_20260912/LEA_CODE.md). |

## Resource test scope

The pinned upstream commit is `a13f33ddc3d00aa1fb52ff323a47eac5d521d8e7`. `provenance.json` records hashes for the original source/header, preserved MIT license and our harness. `resource_result.json` and `logs/resource_133696.log` retain the native output. The six-second test used one allocated CPU on `default_partition`, with the reserved GPU host excluded. No solver dependency or production source was changed.

Five resources represent consumption of one/two/three units and charging of one/two units at capacity seven. The harness checks right-neutral composition and resource-state associativity on 121 triples whose total consumption is at most capacity. It does not exhaust the resource space, independently validate every resource operation, or certify published routing results.

In exact-pricing mode, `isLeq(a,a)` returned false for all five resources. The source uses `left < right + EPS` tests for two charge dimensions. This is a dominance semantics/tolerance issue to understand before transfer, not evidence that the full published solver is incorrect. The component test intentionally records this outcome instead of changing upstream code.

## Branch and price decision

Retain root CG plus finite-pool MIP for this paper's next weather experiments. Our validated 120-trip union pool already improves the best earlier pool cost by about 2.25%, with a 0.272–0.275% gap to the separately valid full-route LP bound in the discretized model. Full branch-and-price would require branch-compatible pricing, node feasibility recovery and valid node bounds. That work has not yet shown greater scientific value than improving causal charging and storage control. The remaining small-case gap warrants honest bounds, not a claim that the MIP heuristic is exact.
