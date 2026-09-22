# Reproduce the common-profile diagnostic

Run commands from the repository root. The successful cluster release is commit `f8f8101557f2ee2983f3cdc6e7369def28338ded`. The report and journal were added after execution; they do not change the fitting code or inputs. The exact file identities remain in `manifest.json` and `RESULT_ARTIFACTS.json`.

Observed cluster environment: Python 3.12.13, NumPy 1.26.4, SciPy 1.13.1, gurobipy/Gurobi 12.0.3. Gurobi requires the reader's own valid license. Small semantic checks also support SciPy/HiGHS; the native-Gurobi test requires a license. Full runs below use Gurobi explicitly and never silently substitute another solver.

```bash
python3 -m unittest discover -s research/stochastic/common_profile_gate -p test_solver.py -v
```

For one retrospective fit, choose a new output directory; the solver refuses to overwrite an existing attempt:

```bash
python3 research/stochastic/common_profile_gate/solver.py \
  --input research/stochastic/common_profile_gate/inputs/policy17_nb20_fit2022.json \
  --output /tmp/v2g17-new-fit --backend gurobi --time-limit 600 --method 2

python3 research/stochastic/common_profile_gate/validate.py \
  --input research/stochastic/common_profile_gate/inputs/policy17_nb20_fit2022.json \
  --result /tmp/v2g17-new-fit/result.json \
  --source-root research/stochastic/evidence

python3 research/stochastic/common_profile_gate/evaluate.py \
  --input research/stochastic/common_profile_gate/inputs/policy17_nb20_fit2022.json \
  --fit-input research/stochastic/common_profile_gate/inputs/policy17_nb20_fit2022.json \
  --result /tmp/v2g17-new-fit/result.json \
  --output-dir /tmp/v2g17-new-replay \
  --source-root research/stochastic/evidence \
  --reference-case research/stochastic/evidence/snapshots/capacity_gate_wave16_validation/campaigns/capacity_gate_wave16/cases/0023
```

For a training-only fit with respect to 2022, use `fit2023.json` for the solver and `--fit-input`, keeping evaluation `--input` at 2022. For policy 14, use its input files and reference case `0017`. These four combinations were declared before solving; do not reinterpret the 2022 fitting case as independent evaluation.

Regenerate the statistical report from the included outputs without Gurobi:

```bash
python3 research/stochastic/common_profile_gate/report.py \
  --runs research/stochastic/common_profile_gate/runs/attempt02 \
  --output-dir /tmp/v2g17-report
```

The report verifies saved identities and recomputes statistics. The separate full trace/physics audit is recorded in `INDEPENDENT_RESULT_AUDIT.json`. Native Gurobi logs are `fit/{inherited,common}_{shortage,cost}.log`; fitted arrays, phase objectives/bounds, residuals and version metadata are adjacent. `replay2022/traces/` contains every independent daily action/state trace. The accounting file is filtered by submission date and job name as well as job ID to avoid including historical records with reused IDs.

Run `python3 research/stochastic/common_profile_gate/cost_components.py` to reproduce the post hoc fuel/throughput accounting in `report/COST_COMPONENTS.md` and `.json` from the archived runs. This does not fit or change any policy.

The first submission failed in the shell before any optimizer started; `runs/attempt01/` preserves it. Successful jobs have independent output directories in `runs/attempt02/`. Do not reuse an existing fit directory or truncate an old journal to retry. A resumed daily replay verifies its input, profile, code, journal and trace identities.

This LP has 90,140 continuous variables in each full-year fitting case. Its numerical LP optimality is scoped to fixed serialized skeletons/assets and the stated lossless, zero-degradation, unlimited-shared-charger domain. It is not a fleet-investment, full-route integer, causal-policy or population-reliability certificate.
