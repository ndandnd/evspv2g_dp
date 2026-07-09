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
