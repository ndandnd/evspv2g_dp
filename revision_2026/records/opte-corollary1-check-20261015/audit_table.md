| family | delta kWh | G | rho (DP rate) | tasks | deadheads | full boundary | eta | corollary applies | n |
|---|---|---|---|---|---|---|---|---|---|
| Reference planning (L=3, 200 kWh tasks), delta=25, eta=0 | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 180 |
| Planning one-factor arms at delta=25: G in {350,700,1050,1400}, rate 100-500 kW (spine25, pack4; NOT the Fig. 12 source) | 25 | yes | yes (50,100,175,250 -> 50,100,175,250) | yes | yes | yes | 0 | yes | 8 |
| Planning loss arms eta>0, delta=25 | 25 | yes | yes (175 -> 100,125,150) | yes | yes | yes | 0.03,0.05,0.1,0.15,0.2,0.3 | NO | 6 |
| ALIGN/LATTICE discretization check, delta=50, eta=0 | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 16 |
| ALIGN/LATTICE discretization check, delta=25, eta=0 | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 16 |
| ALIGN/LATTICE discretization check, delta=12.5, eta=0 | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 16 |
| Structured timing benchmarks (Table 3, Fig. 2, Table 5 rows 1-12), delta=50, rho=50 | 50 | yes | yes (50 -> 50) | yes | yes | yes | 0 | yes | 18 |
| Random multi-location (Table 4; Table 5 random rows; Tables 6-7), delta=50 | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 24 |
| Charging-location study (Fig. 10, App. B.5; 3,456 solves), delta=50 (builder default) | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 24 |
| Timetable families (App. B.3, five families, 40/80 tasks; sched3 + theory), delta=50 (builder default) | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 90 |
| Planning solar profile, 2023 selection and benchmark (Fig. 8), delta=50 (builder default) | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 1 |
| Planning solar profile, 2022 holdout (Table 16), delta=25 | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 1 |
| Fuel budget (Fig. 11), delta=50 (builder default) | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 12 |
| Pack size (Fig. 12) and its rate arms, delta=50 (builder default) | 50 | yes | mixed (50,100,175,250 -> 50,100,150,250) | yes | yes | yes | 0 | mixed | 112 |
| Pack x workload dense grid (Table 10 range 8-200 tasks), delta=50 (builder default) | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 60 |
| Profile shift by two hours (App. B.3), delta=50 (builder default) | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 1 |
| saved: experiments/opte_cg_followup_20261013/preflight_v1 [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_followup_20261013/preflight_v1 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_cg_followup_20261013/preflight_v1 [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_followup_20261013/preflight_v2 [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_followup_20261013/preflight_v2 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_cg_followup_20261013/preflight_v2 [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_regimes_20261013/preflight_v1 [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_regimes_20261013/preflight_v1 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_cg_regimes_20261013/preflight_v1 [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_regimes_20261013/preflight_v2 [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_cg_regimes_20261013/preflight_v2 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_cg_regimes_20261013/preflight_v2 [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_direct_mip_barrier_20261013/checks_v1 [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_direct_mip_barrier_20261013/checks_v1 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_direct_mip_barrier_20261013/checks_v1 [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_equal_mip_20261015/runtime [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_equal_mip_20261015/runtime [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 9 |
| saved: experiments/opte_integer_extension_20261014/checks_v1 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_integer_extension_20261014/checks_v1 [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 9 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_development [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_development [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_development [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_final [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_final [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_final [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_heterogeneous_development [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_heterogeneous_development [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_lp_hypothesis_20261013/preflight_heterogeneous_development [delta=6.25] | 6.25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/opte_plugs_20261013/checks_v1 [delta=12.5] | 12.5 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 6 |
| saved: experiments/opte_plugs_20261013/checks_v1 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 12 |
| saved: experiments/opte_plugs_20261013/checks_v1 [delta=50] | 50 | yes | yes (100 -> 100) | yes | yes | yes | 0 | yes | 6 |
| saved: experiments/opte_plugs_20261013/checks_v2 [delta=50] | 50 | yes | yes (100 -> 100) | yes | yes | yes | 0 | yes | 5 |
| saved: experiments/opte_second_round/results/cg_reuse_deployment_20261013 [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 82 |
| saved: experiments/opte_second_round/results/cluster_20261012 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 12 |
| saved: experiments/opte_second_round/results/cluster_20261012 [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 149 |
| saved: experiments/opte_second_round/results/direct_mip1000_deployment_20261012 [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 4 |
| saved: experiments/opte_second_round/results/mip1000_preflight_local_20261012 [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 1 |
| saved: experiments/opte_second_round/results/pilot_20261011 [delta=50] | 50 | yes | yes (50 -> 50) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_second_round/results/pilot_20261011_verified [delta=50] | 50 | yes | yes (50 -> 50) | yes | yes | yes | 0 | yes | 8 |
| saved: experiments/opte_second_round/results/planning_population_deployment_20261012 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 1080 |
| saved: experiments/opte_second_round/results/planning_refinement_combined_20261013 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 213 |
| saved: experiments/opte_second_round/results/planning_refinement_deployment_20261013 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 3 |
| saved: experiments/opte_second_round/results/planning_refinement_deployment_cdses_20261013 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 211 |
| saved: experiments/opte_second_round/results/planning_refinement_mixed_node_validation_20261013 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 1 |
| saved: experiments/opte_second_round/results/planning_refinement_validation_v2_20261013 [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 1 |
| saved: experiments/opte_second_round/results/random_extension_20261012 [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 2 |
| saved: experiments/opte_second_round/results/structured_extension_20261012 [delta=50] | 50 | yes | yes (50 -> 50) | yes | yes | yes | 0 | yes | 4 |
| saved: experiments/second_round_scaling_20261013/results [delta=25] | 25 | yes | yes (175 -> 175) | yes | yes | yes | 0 | yes | 2 |
| saved: experiments/second_round_scaling_20261013/results [delta=50] | 50 | yes | NO (175 -> 150) | yes | yes | yes | 0 | NO | 10 |
