# EVSP-V2G Experiment Code

This repository contains the Python code used to generate the deterministic
experiment artifacts for the EVSP-V2G rewrite.

## Contents

- `instance.py` - synthetic instance generation for the microgrid EVSP-V2G model.
- `master.py` - restricted master problem data structures and LP/MILP solves.
- `pricing_truck.py` - truck pricing dynamic program.
- `pricing_battery.py` - battery pricing routines.
- `colgen.py` - column-generation loop and summaries.
- `experiments.py` - experiment driver for the main figures and JSON outputs.
- `make_validation_artifacts.py` - validation summary and diagnostic figure builder.
- `results/` - generated figures, JSON summaries, and validation text.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python3 experiments.py
python3 make_validation_artifacts.py
```

Outputs are written to `results/`.

