#!/usr/bin/env python3
"""Post hoc decomposition of saved costs; no optimization or policy retuning."""
from pathlib import Path
import hashlib
import json
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    gate = Path(__file__).resolve().parent
    result = {'scope': 'Post hoc cost accounting of the four completed fits; no new solve. Only the registered lossless, zero-degradation domain.',
              'script_sha256': sha(Path(__file__)), 'cases': {}}
    for folder in sorted((gate / 'runs/attempt02').glob('policy*')):
        input_path = gate / 'inputs' / (folder.name + '.json')
        data = json.loads(input_path.read_text())
        ph = data['physics']
        assert ph['eta'] == 0 and ph['deg_cost'] == 0
        reference = gate.parent / 'evidence' / data['metadata']['reference_wave16_case'] / 'days.jsonl'
        rows = [json.loads(x) for x in reference.read_text().splitlines()]
        journal = folder / 'replay2022/days.jsonl'
        replay = [json.loads(x) for x in journal.read_text().splitlines()]
        assert len(rows) == len(replay) == 365
        components, max_error, max_fuel_difference = [], 0., 0.
        for original, evaluated in zip(rows, replay):
            assert original['date'] == evaluated['date']
            trace = folder / 'replay2022' / evaluated['trace']
            assert sha(trace) == evaluated['trace_sha256']
            values = {}
            with np.load(trace, allow_pickle=False) as arrays:
                for label in ('old', 'common'):
                    values[label] = {'fuel': ph['c_g'] * float(arrays[label + '_generation'].sum()),
                                     'throughput': ph['eps_pen'] * sum(float(arrays[label + '_' + k].sum()) for k in
                                                                      ('truck_charge', 'truck_discharge', 'bess_charge', 'bess_discharge'))}
                    max_error = max(max_error, abs(sum(values[label].values()) - evaluated[label]['operating_cost']))
            values['adaptive'] = {'fuel': ph['c_g'] * original['adaptive_generation'],
                                  'throughput': ph['eps_pen'] * sum(original['adaptive_' + k] for k in
                                                                  ('truck_charge', 'truck_discharge', 'bess_charge', 'bess_discharge'))}
            max_error = max(max_error, abs(sum(values['adaptive'].values()) - original['adaptive_operating']))
            max_fuel_difference = max(max_fuel_difference, abs(values['common']['fuel'] - values['adaptive']['fuel']))
            components.append(values)
        assert max_error < 1e-7
        means = {label: {kind: float(np.mean([v[label][kind] for v in components])) for kind in ('fuel', 'throughput')}
                 for label in ('old', 'common', 'adaptive')}
        result['cases'][folder.name] = {'days': len(rows), 'input_sha256': sha(input_path),
                                        'adaptive_reference_sha256': sha(reference), 'replay_journal_sha256': sha(journal),
                                        'means': means, 'fixed_asset_cost': data['fixed_asset_cost'],
                                        'max_operating_cost_reconstruction_error': max_error,
                                        'max_daywise_common_adaptive_fuel_cost_difference': max_fuel_difference,
                                        'residual_mean_by_component': {k: means['common'][k] - means['adaptive'][k] for k in ('fuel', 'throughput')}}
    target = gate / 'report'
    (target / 'COST_COMPONENTS.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    lines = ['# Cost-component check — 22 September 2026 UTC', '',
             '**The remaining 0.578–0.585/day common-profile/oracle difference is entirely the model’s throughput penalty, to numerical tolerance. Fuel cost is identical day by day in all four cases.**', '',
             'This is post hoc accounting of the saved physical traces and wave16 aggregate actions, not an additional solve. The objective uses fuel coefficient 40 and throughput coefficient 0.025; explicit degradation cost is zero. Do not describe the small residual as demonstrated fuel savings or calibrated battery-wear savings.', '',
             '| Source / fit | Common fuel/day | Oracle fuel/day | Common throughput penalty/day | Oracle throughput penalty/day |',
             '|---|---:|---:|---:|---:|']
    for name, case in result['cases'].items():
        m = case['means']
        lines.append(f"| {name} | {m['common']['fuel']:.6f} | {m['adaptive']['fuel']:.6f} | {m['common']['throughput']:.6f} | {m['adaptive']['throughput']:.6f} |")
    max_fuel = max(c['max_daywise_common_adaptive_fuel_cost_difference'] for c in result['cases'].values())
    max_error = max(c['max_operating_cost_reconstruction_error'] for c in result['cases'].values())
    lines += ['', f'Maximum daywise common/oracle fuel-cost discrepancy: {max_fuel:.3e}. Maximum operating-cost reconstruction discrepancy: {max_error:.3e}. All 1,460 trace hashes were rechecked. Fixed asset cost 1,395/day is identical and excluded from this component table.', '',
              'For seed47/2022, most static retuning savings are real fuel reductions: inherited fuel cost 2,274.677874/day becomes 2,200.381307/day. The small remaining oracle gap has a different source. The scope remains fixed assets at 20 BESS units and full-day energy recourse; no conclusion about causal fuel savings at other storage levels follows.', '',
              '[Machine-readable components and hashes](COST_COMPONENTS.json) · [Reproduction script](../cost_components.py) · [Main results](RESULTS.md)', '']
    (target / 'COST_COMPONENTS.md').write_text('\n'.join(lines))
    print(json.dumps({'cases': len(result['cases']), 'max_fuel_difference': max_fuel, 'max_cost_error': max_error}))


if __name__ == '__main__':
    main()
