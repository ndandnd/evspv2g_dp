# Run / figure TODOs (post coauthor-draft, 2026-07-09)

Queued on cluster (first + second wave):
- BOUNDARY resume x3 + MODESX2  -> completes Fig "boundary" curves at 2.5x/3.5x/4x
- CAPS2 + CAPS3                 -> cliff densify (gen 1.0-1.2, n to 200) + error bars
                                   for Fig "caps"(b)
- SATFIX                        -> true fixed-fleet concavity figure (replaces the cut
                                   linear "diminishing" figure)
- OUTAGE + ENDURANCE            -> N-1 contingency ladder (gives the V2G failure CURVE
                                   that Fig "caps"(a) currently lacks) + days-of-autonomy

Needs small code work before running:
- Gantt deadhead shading: export per-lane deadhead intervals in the timeline
  generator (overnight2 S7), re-render Fig "timeline" with a third shade.
- WEATHER-CITIES: fetch 2023 hourly GHI (Open-Meteo ERA5 archive) for a Gulf
  desert site (~24.5N 54.4E), Tromso, London, Seoul; loop the 365-day study
  per city. Data files must be fetched locally and committed (cluster has no
  internet).
- T=96 time-step sensitivity (de Vos-style discretization experiment;
  build_instance currently hardcodes half-hour blocks).

Medium code work (third wave):
- Mixed ICE/EV transition-fraction sweep (two truck column classes + an
  EV-count constraint in the master; look for generation-capacity deferral
  cliffs a la Chae et al.).
- NREL-style generator-reliability post-processing layer (survival
  probabilities around the deterministic schedules; needed before making any
  outage-survival claims in the paper beyond feasibility).

Added 2026-07-09 (post-send):
- SCHED (overnight8, ready to queue): the retiming study -- same tasks, four
  timetable families (uniform / siesta / night / midday-occupied) at identical
  gamma, across 5 solar levels x 3 fleet sizes x 3 seeds. Revives the
  breaks-vs-uniform table as a controlled counterexample to reading gamma as
  the whole story; also plot "value of retiming" vs gamma (hypothesis: peaks
  in the transition region). Feeds a new table + small figure in Sec 8.4.
- Zhou/An/Schmoecker (2025) full text: obtain via library access or author
  copy (T&F paywalled; only the abstract is verified). Needed to check
  whether trip coverage is a genuine decision variable in their cross-line
  strategy or a reallocation under fixed timetables, and to firm up the
  intro/lit differentiation accordingly.

- Consider delta=25 kWh for the final experiment rerun: LATTICE shows the
  50 kWh lattice overestimates the LP by ~0.7% (converged at 25; 12.5
  identical) at negligible extra time. Cheap accuracy if we rerun anyway.

Status 2026-07-09 (second batch):
- INVALID DATA: overnight7_endurance_s*.json (fuel budget was absent from the
  CG LP path; charge-only recorded feasible at 5% fuel). Superseded by
  overnight9 ENDUR2. overnight7 OUTAGE is valid but measures the greenfield
  (re-sizable) design question; overnight9 OUTAGE2 is the fixed-asset stress
  test.
- STILL MISSING on git: overnight3_modes_sX2* (MODESX2), overnight4_caps2_s*,
  overnight4_caps3_s* -- check cluster .out logs / uncommitted files, then
  relaunch (commands in the handoff message).
- SATFIX (overnight6) is valid but linear-to-the-floor by design (endogenous
  assets); SATFIX2 (two-stage, fixed assets) is the Theorem-1 concavity view.
