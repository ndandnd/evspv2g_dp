"""Adversarial siesta test: can a siesta-style timetable beat midday tasks
when the surplus window is NARROW and fully occupied by the tasks, and
stationary storage is priced out?

Construction (Nathan's spec):
- Net demand: 10 units/h (1,000 kW) all day, EXCEPT hours 11:00 and 12:00
  which have 4 units/h of net SURPLUS (-4). Total surplus = 800 kWh, exactly
  a 2-hour spike.
- Two 2-hour 200-kWh tasks between the two task locations, both starting at
  the same hour, so they need two trucks in parallel in both variants.
    midday variant: tasks 11:00-13:00  -> trucks BUSY during the whole surplus
    siesta variant: tasks 07:00-09:00  -> trucks idle during the surplus
- Stationary batteries priced at $100,000/day: storage is out of the picture.
- Cyclic SoC (s0 = sT = G), eta = 0, planning prices otherwise.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from recreate_arxiv import build_instance, BREAKS
from overnight12 import _solve12

dh = np.array([10] * 24)
dh[11] = dh[12] = -4                       # the only surplus: 11:00-13:00
BASELINE = float(np.maximum(dh, 0).sum())  # no-fleet fossil burn (units)

for label, start in (("midday (tasks 11-13, ON the surplus)", 11.0),
                     ("siesta (tasks 7-9, surplus left free)", 7.0)):
    trips = [(1, 2, start), (2, 1, start)]
    for scen in ("solar", "v2g"):
        inst = build_instance(2, 2.0, BREAKS, trip_list=trips,
                              delta_hourly=dh.copy())
        r = _solve12(inst, scen, tl=60.0, c_b=100_000.0)
        if r is None:
            print(f"{label:44s} {scen:6s}  INFEASIBLE")
            continue
        print(f"{label:44s} {scen:6s}  fuel {r['g_units']:7.2f} units "
              f"(baseline {BASELINE:.0f})  trucks {r['trucks']} "
              f"batteries {r['batteries']}  total ${r['total']:.0f} "
              f"gap {r['gap']:.2f}%")
