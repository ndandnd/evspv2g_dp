# Cost-component check — 22 September 2026 UTC

**The remaining 0.578–0.585/day common-profile/oracle difference is entirely the model’s throughput penalty, to numerical tolerance. Fuel cost is identical day by day in all four cases.**

This is post hoc accounting of the saved physical traces and wave16 aggregate actions, not an additional solve. The objective uses fuel coefficient 40 and throughput coefficient 0.025; explicit degradation cost is zero. Do not describe the small residual as demonstrated fuel savings or calibrated battery-wear savings.

| Source / fit | Common fuel/day | Oracle fuel/day | Common throughput penalty/day | Oracle throughput penalty/day |
|---|---:|---:|---:|---:|
| policy14_nb20_fit2022 | 2200.381307 | 2200.381307 | 7.582741 | 7.004304 |
| policy14_nb20_fit2023 | 2200.381307 | 2200.381307 | 7.588923 | 7.004304 |
| policy17_nb20_fit2022 | 2200.381307 | 2200.381307 | 7.582741 | 7.004304 |
| policy17_nb20_fit2023 | 2200.381307 | 2200.381307 | 7.588893 | 7.004304 |

Maximum daywise common/oracle fuel-cost discrepancy: 2.728e-12. Maximum operating-cost reconstruction discrepancy: 2.001e-11. All 1,460 trace hashes were rechecked. Fixed asset cost 1,395/day is identical and excluded from this component table.

For seed47/2022, most static retuning savings are real fuel reductions: inherited fuel cost 2,274.677874/day becomes 2,200.381307/day. The small remaining oracle gap has a different source. The scope remains fixed assets at 20 BESS units and full-day energy recourse; no conclusion about causal fuel savings at other storage levels follows.

[Machine-readable components and hashes](COST_COMPONENTS.json) · [Reproduction script](../cost_components.py) · [Main results](RESULTS.md)
