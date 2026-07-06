# Paper notes: what is READY for the LaTeX now vs. AWAITING the cluster

## A. Ready now (stable -- tonight's runs cannot change these)

### Setup paragraph anchors (each -> references.bib key)
| parameter | value/range in the study | citation |
|---|---|---|
| EV truck daily cost | 1.0--2.0x ICE ($45--90/day) | basma2023total (MSRPs 1.3--2.4x diesel) |
| drivetrain efficiency | 2.5--3.5x sweep band; sensitivity 1.0--3.3x | nacfe2023runonless |
| cycling degradation | $0--0.13/kWh discharged (sweep) | peterson2010lithium; sagaria2025vehicle (EUR 70--132/MWh); uddin2017possibility (can be ~0 with smart control) |
| bidirectional charger premium | $0--8/truck-day | hardware $3--8k over unidirectional, amortized 5--10 y; doefemp2024bidirectional; steward2017critical for framing |
| stationary battery | $26--51/day per 700 kWh | LFP capex $200--400/kWh over 15 y |
| solar irradiance | 365 real days, 2023, site coordinates | hersbach2020era5 (via Open-Meteo) |
| fossil generation | $0.20--1.00/kWh | remote island/military diesel range (setting-level justification) |

### Finalized result claims (numbers frozen)
1. DP pricing = MILP pricing: exact LP matches (70/80/78; fractional 152.8571); 0.5%
   vs a fresh run of the original code after its battery-cost slip is replicated.
2. Recreation: 450 tasks 27 s @ 0.033% vs 29,722 s @ 0.71%; suite in ~95 s;
   1,404 vs 45,906 columns; pricing share 25--50% vs >95%.
3. Free-start artifact: one flag reproduces the original's negative fuel and
   battery deployment; cyclic removes them.
4. Electrification break-evens: 240 heterogeneous fleets -> means 1.33/1.47/1.60
   (at 1.0/1.5/2.0x ICE cost), p95 1.48/1.67/1.88, worst 1.97 -- all below the
   measured 2.5--3.5x band. Solar provably contributes zero width.
5. R-rule: V2G value collapses onto R = surplus/traction; ~0 below R~0.3, on
   near R~1, saturating >2.5; scale-free 20--560 tasks; +-2h profile shifts
   change savings <0.3 pts at matched R.
6. Computed enablement break-even R* ~ 0.35--0.47 (charger premium dominates;
   NOTE: extend to deg=$0.13/kWh before quoting final R* -- see B).
7. Real weather (365 days): annual mean ~= design-day value at every PV sizing;
   V2G value volatile at mid PV (p10 ~2% at 2.0x), firm at 3x (p10 19%);
   worthless year-round at the original 1.0x sizing.
8. Charge rate: second-order, transition region only, converged by ~200 kW.
9. Cyclic model exports honestly with enough solar (-36 gal/day at 2x,
   -446 gal/day at 3x on the 60-task cell).

## B. Awaiting cluster (do NOT hardcode yet)
- Table 8.4 grid values (S9: tasks 20--200 x solar; sign boundary).
- Final Fig 8.5 dot count + collapse-quality stat (S10 high-R densify).
- Fig 8.6 shape-noise verdict at fixed surplus (S11).
- Final Fig 8.7 Gantt pair incl. fleet-as-storage variant (S7 rerun).
- Tightened eps=1.5 ladder gaps (S8 rerun).
- R* re-quoted after extending BE_DEG to $0.13/kWh (one small S3 job).
