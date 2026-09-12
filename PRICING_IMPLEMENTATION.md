# Pricing candidate implementation — 12 September 2026

Scope: isolated `algorithm_candidate_v11`; the GitHub reference, immutable experiment workers, cluster campaigns and EVSP–DR are unchanged. Only `pricing_truck.py`, `pricing_battery.py`, `pricing_contract.py`, this report and `tests/test_pricing*.py` are owned by this change.

## Changes and API

`price_truck_dp` retains its existing arguments and adds keyword-only `prepared=None, use_cache=True`. `prepare_pricing(inst, step=None, ice=False, use_cache=True)` is exported by `pricing_contract` and `pricing_truck`. Normal calls cache automatically; an explicitly prepared object avoids repeated preparation and checks its full physical identity on every public pricing call. `use_cache=False` forces new physical preparation when no explicit object is supplied.

The prepared cache stores only immutable trips, charging locations, permitted deadhead transitions, and time-indexed trip starts/ends. Its identity includes horizon, step, ICE flag, capacity, rate, loss, deadhead energy coefficient, depot, full distance matrix, stations and full trip records. Changes to these values either create a new cache entry or reject an explicitly supplied stale object. The LRU is bounded to 16 identities. Duals, prices, fixed costs, labels and predecessors are read/calculated afresh. Periodic sweeps share physical preparation while constructing separate label arrays for each initial SoC.

Backward reconstruction now requires exact equality with the floating-point expression that generated a forward label. Every chosen transition advances time strictly in the forward direction, so reconstruction must reach the exact initial `(time, location, SoC, task flag)` within the horizon. Missing predecessors or source failure raise a diagnostic. An independent direct column reduced-cost recomputation checks agreement at a scale derived from floating-point precision. No absolute `1e-5` predecessor tolerance remains. This preserves the original label-array memory size and avoids storing a large parent array.

Capacity, compulsory traction and deadhead energies must be grid-aligned; only floating-point representation noise is accepted. Validation also checks positive SoC step, finite nonnegative capacity/rate/traction, loss in `[0,1)`, integral strictly advancing time and valid trip indices/locations. Rate greater than capacity is accepted by capping transition shifts at the available SoC levels. These guards reject unsafe rounding; they do not make the charging grid an exact continuous-resource formulation.

The legacy battery helpers retain their explicit full-start/free-terminal boundary. Their reconstruction, high-rate handling, degradation costs and example call were fixed. The continuous LP raises when simultaneous charging/discharging prevents faithful representation by a net-energy column. They are still separate from the aggregate cyclic-storage master. The NetworkX truck checks now include degradation.

Fleet-cap duals remain a master/integration responsibility. They are constant across truck columns and must be included both when interpreting reduced costs and when deciding whether the pricing minimum is nonnegative. This pricing API reports its documented route cost without that additional master dual.

## Verification

Command from the candidate directory:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 ../.venv/bin/python -m unittest discover -s tests -p 'test_pricing*.py' -v
```

Ten tests passed. The independent physical enumerator, copied from the review and not derived from the new recurrence, covered 128 aligned cases and 1,278 complete feasible paths. Features include cyclic/free/periodic/pinned SoC, ICE/EV, loss, charger-cap duals, discharge degradation, multiple station sets and charge-only/V2G. Largest difference between enumerated minimum, DP value and reconstructed column was **8.88e-16**. Cached and uncached outputs matched exactly throughout these cases.

Additional tests reproduce near-tied route reconstruction at rewards `5e-6`, `5e-9`, `5e-11`; the legacy battery near tie; over-capacity rate; unsafe capacity/traction rounding; invalid deadhead time/energy, trip data, dual shapes and nonfinite inputs; prepared-object immutability; nested instance mutation; and dual/cost freshness.

## Local timing probe

Command: `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 ../.venv/bin/python tests/test_pricing_benchmark.py`.

Measured locally with the root Python 3.12 environment, one BLAS/OpenMP thread, seed 20260912, three independent dual vectors per size, five timing repetitions per vector with rotated implementation order. Instances use BREAKS2, task energy 2, rate 1.75, step 0.25, 48 time blocks and 29 SoC levels. Each timing includes a pricing call and reconstruction when improving. Medians below are milliseconds.

| Service points | Mandatory trips | GitHub-reference DP | Candidate, uncached | Candidate, cached | Reference / cached |
|---|---:|---:|---:|---:|---:|
| 2 | 20 | 1.491 | 1.468 | 1.319 | 1.13× |
| 4 | 120 | 2.581 | 2.531 | 2.028 | 1.27× |
| 10 | 900 | 8.904 | 9.793 | 6.669 | 1.34× |

The DP minima matched the reference exactly for all nine vectors. Preparation reuse and direct trip-start lookup improve these bounded pricing calls. Uncached validation can cost time at the largest size. These are local microbenchmarks, not cluster CG/MIP speedups or evidence about the complete stochastic algorithm. Parent integration should preserve a cold-cache control and measure complete CG objective, iteration count, pool and proof status before promoting the candidate.

## Integration audit follow-up

Independent replay in `column_validation.py` now uses the same scalar grid/storage contract, while deriving reachability directly from the instance without cached transitions or pricing labels. Integer SoC increments determine activity, preventing tiny-unit energy exchange from being ignored during trips/deadheads. Incidence must be exactly binary; near-grid charging and moves beyond the pricing rate floor are rejected. Single-trip seeds validate individual traction components and use the same conservative rate floor. Greedy warm initialization forwards its `pricing_cache` flag.

Nine regressions in `tests/test_column_validation.py` cover these changes and replay every cached/uncached output of the 128-case independent pricing enumeration. Together with the existing CG contract tests, all 18 `test_col*.py` tests passed. Parent integration is responsible for forwarding the top-level cache option to `initial_columns`.

The audit also confirmed a pre-existing limitation: coverage artificials cannot repair an initially infeasible power-balance RMP. Such a result withholds the LP certificate but does not prove full-problem infeasibility. A balance-relaxing Phase I/Farkas pricing method is a separate follow-up, not part of these pricing safeguards.
