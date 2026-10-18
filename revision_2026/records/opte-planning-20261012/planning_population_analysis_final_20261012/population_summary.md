# Uniform 60-second population verification

All 1080 configuration outcomes and 270 bases are retained. 1080 results are present; 1080 pass the independent audit. 1080 new incumbents are physically replayed and 1080 new native bounds are usable.

Status counts: optimal: 893, time_limit: 187.

Positive joint savings are certified for 260/270 bases. Any remaining share intervals are conditional on positive joint saving. These are floating-point bounds, not exact-arithmetic certificates.

| Statistic | Cases | Original incumbent median (%) | New median interval (%) | Rounded value resolved | Original display supported |
|---|---:|---:|---:|---:|---:|
| BESS_share | 270 | 95.64986558 | 96.25–96.75 | unresolved | no / unresolved |
| V2G_alone_share | 270 | 61.57413592 | 69.63–75.38 | unresolved | no / unresolved |
| V2G_alone_daily_reduction | 270 | 19.60027504 | 21.68–21.73 | 21.7 | no / unresolved |
| V2G_with_BESS_daily_reduction_low_gamma | 30 | 0.58128392 | 0.09–0.10 | 0.1 | no / unresolved |
| V2G_with_BESS_daily_reduction_high_gamma | 100 | 9.27800787 | 9.36–9.62 | unresolved | no / unresolved |

The primary intervals use only this uniform run. Original rounded results and the three selected 1,800-second diagnostics are excluded. Native optimal status does not erase a nonzero objective-bound gap. A null upper cost endpoint in JSON means unbounded, not a zero cost. Displayed interval endpoints are rounded outward to two decimal percentage places; rounding decisions use the full-precision JSON endpoints. No optimization is performed by this analyzer.
