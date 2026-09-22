# EVSP–V2G stochastic research

Start with the [dated research journal](journal/RESEARCH_JOURNAL.md). Entries run oldest to newest; scroll down for current work. The [evidence index](journal/EVIDENCE_INDEX.md) separates historical observations, corrections, and new experiments.

This research extends the submitted deterministic EVSP–V2G implementation at `f69f055ab6b82d2417daf5fe5a1b8a3e5ab7fdd0`. It is isolated from EVSP–DR and does not modify its campaigns. Frozen historical inputs are included for reproducibility. Downloaded third-party papers are linked in the review rather than redistributed.

## Current experiment

[Common-profile gate protocol](common_profile_gate/PROTOCOL.md): on fixed truck duties and assets, optimize one truck charging plan shared by all weather days. This distinguishes retuning an inherited plan after adding BESS from the remaining value of knowing each day's weather. It is an extensive continuous LP, not route generation, a new MIP, or a causal controller.

Public evidence is a curated snapshot. Historical source identities are preserved; paths inside raw identity files refer to their original research tree. New portable inputs and run manifests identify their exact dependencies by SHA-256. Native solver logs, full primal exports, independent validation and scheduler accounting accompany new results. Claims about LP optimality, physical feasibility and statistical generalization are recorded separately.
