| case | arm | status | host | CG s | iters | cols | LP | master s (build/engine/valid) | pricing s | s per master call |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|
| diag2_L04_n1000_s0 | A | completed | samitha-compute-01 | 11,602.6 | 1729 | 3793 | 48,050.4250 | 11,583.7 (72.0/11,511.1/) | 18.1 | 6.696 |
| diag2_L04_n1000_s0 | A0 | completed | scaglione-compute-01 | 16,401.8 | 1729 | 3793 | 48,050.4250 | 16,369.0 (130.9/16,236.0/) | 32.0 | 9.462 |
| diag2_L04_n1000_s0 | B | completed | samitha-compute-01 | 11,349.1 | 1729 | 3768 | 48,050.4250 | 11,330.0 (82.2/11,245.4/) | 18.5 | 6.549 |
| diag2_L04_n1000_s0 | C | completed | samitha-compute-01 | 3,428.3 | 1733 | 3772 | 48,050.4250 | 3,392.2 (265.7/3,074.4/51.6) | 19.6 | 1.956 |
| diag2_L04_n1000_s0 | D | completed | samitha-compute-01 | 1,032.8 | 1849 | 3888 | 48,050.4250 | 1,010.4 (60.0/888.9/58.9) | 20.0 | 0.546 |
| diag2_L04_n1000_s0 | E | completed | samitha-compute-01 | 4,062.7 | 1762 | 3826 | 48,050.4250 | 4,042.7 (1,047.6/2,983.0/) | 19.3 | 2.293 |
| diag2_L15_n1000_s0 | A | completed | samitha-compute-01 | 9,122.5 | 1704 | 3768 | 54,681.6875 | 9,050.9 (85.1/8,963.3/) | 70.9 | 5.308 |
| diag2_L15_n1000_s0 | A0 | completed | scaglione-compute-01 | 13,056.5 | 1704 | 3768 | 54,681.6875 | 12,932.0 (129.5/12,800.2/) | 123.7 | 7.585 |
| diag2_L15_n1000_s0 | B | completed | samitha-compute-01 | 9,082.0 | 1704 | 3743 | 54,681.6875 | 9,010.2 (88.0/8,919.2/) | 71.2 | 5.285 |
| diag2_L15_n1000_s0 | C | completed | samitha-compute-01 | 3,114.5 | 1716 | 3755 | 54,681.6875 | 3,026.7 (268.2/2,706.5/51.4) | 71.2 | 1.763 |
| diag2_L15_n1000_s0 | D | completed | samitha-compute-01 | 886.0 | 1767 | 3806 | 54,681.6875 | 810.5 (58.2/694.2/55.8) | 73.4 | 0.458 |
| diag2_L15_n1000_s0 | E | completed | samitha-compute-01 | 3,635.6 | 1728 | 3792 | 54,681.6875 | 3,562.4 (986.9/2,563.3/) | 72.5 | 2.060 |

| case | ratio | value | meaning |
|---|---|---:|---|
| diag2_L04_n1000_s0 | A0/A | 1.414 | CPU: Silver 4214 node vs EPYC 9654, original code |
| diag2_L04_n1000_s0 | A/B | 1.022 | 25 enrichment rounds vs none (original code) |
| diag2_L04_n1000_s0 | A/E | 2.856 | original code: HiGHS (scipy, dense rebuild) vs its own Gurobi backend (rebuild) |
| diag2_L04_n1000_s0 | A/C | 3.384 | HiGHS dense rebuild (original) vs Gurobi cold rebuild (frozen, Table 18 'rebuild') |
| diag2_L04_n1000_s0 | C/D | 3.319 | Gurobi rebuild vs persistent master with basis reuse (frozen) |
| diag2_L04_n1000_s0 | A/D | 11.234 | original Table 4 code vs Table 20 code, same CPU |
| diag2_L04_n1000_s0 | A0/D | 15.881 | original code on original node type vs Table 20 code on EPYC 9654 |
| diag2_L04_n1000_s0 | historical/A0 | 1.023 | Table 4 run (4 CPUs, busy node) vs rerun of the same code on the same node |
| diag2_L04_n1000_s0 | D/Table20 | 0.693 | Table 20 code on EPYC 9654 vs the printed EPYC 9555 run |
| diag2_L15_n1000_s0 | A0/A | 1.431 | CPU: Silver 4214 node vs EPYC 9654, original code |
| diag2_L15_n1000_s0 | A/B | 1.004 | 25 enrichment rounds vs none (original code) |
| diag2_L15_n1000_s0 | A/E | 2.509 | original code: HiGHS (scipy, dense rebuild) vs its own Gurobi backend (rebuild) |
| diag2_L15_n1000_s0 | A/C | 2.929 | HiGHS dense rebuild (original) vs Gurobi cold rebuild (frozen, Table 18 'rebuild') |
| diag2_L15_n1000_s0 | C/D | 3.515 | Gurobi rebuild vs persistent master with basis reuse (frozen) |
| diag2_L15_n1000_s0 | A/D | 10.297 | original Table 4 code vs Table 20 code, same CPU |
| diag2_L15_n1000_s0 | A0/D | 14.737 | original code on original node type vs Table 20 code on EPYC 9654 |
| diag2_L15_n1000_s0 | historical/A0 | 1.008 | Table 4 run (4 CPUs, busy node) vs rerun of the same code on the same node |
| diag2_L15_n1000_s0 | D/Table20 | 1.277 | Table 20 code on EPYC 9654 vs the printed EPYC 9555 run |
