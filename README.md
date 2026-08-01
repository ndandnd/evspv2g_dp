# EVSP-V2G research code

This repository contains the code, input profiles, selected computational
results, and final figures for the manuscript **Electric Vehicle Scheduling
and Vehicle-to-Grid Integration in Microgrids** by Nathan Cho, Andrea Lodi,
and Anna Scaglione.

The model assigns timed transport tasks to electric trucks and coordinates
truck charging, vehicle-to-grid discharge, stationary storage, solar energy,
and fossil generation. Column generation solves the master LP relaxation, and
a dynamic program generates feasible truck routes and energy profiles. The
final integer schedule is obtained by solving a restricted master MIP over the
generated routes. The code does not implement branch-and-price.

## Repository contents

- `instance.py`: instance data structures and synthetic instance generation.
- `master.py` and `gurobi_master.py`: restricted master LP and MIP models.
- `pricing_truck.py` and `pricing_battery.py`: pricing routines.
- `colgen.py`: column generation and solution summaries.
- `smoke_test.py`: a small deterministic check of column generation and the
  final restricted master MIP.
- `overnight13.py` and `overnight14.py`: drivers for the principal
  experiment families reported in the manuscript.
- `data/`: demand and solar input profiles.
- `results/`: selected JSON and CSV outputs from the computational study.
- `paper_figures/`: the final figures using the numbering in the manuscript.

## Environment

The reported study used Python 3.10. Install the Python dependencies in an
isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

SciPy/HiGHS solves the restricted master LPs. CBC is used for the structured
benchmark MIPs, while Gurobi 12.0.3 is used for the remaining final restricted
master MIPs. A Gurobi license is therefore needed for the large experiment
drivers that select the Gurobi backend.

## Quick verification

Run the small deterministic check with:

```bash
python3 smoke_test.py
```

The command checks that column generation prices out and that the final MIP
finds an artificial-free schedule. It is a functional check, not a rerun of
the computational study.

The full experiment drivers are substantially more expensive. Their selected
saved outputs are included under `results/`.

## Citation

Please cite the manuscript:

> Nathan Cho, Andrea Lodi, and Anna Scaglione. *Electric Vehicle Scheduling
> and Vehicle-to-Grid Integration in Microgrids*. Manuscript submitted to
> Optimization and Engineering.
