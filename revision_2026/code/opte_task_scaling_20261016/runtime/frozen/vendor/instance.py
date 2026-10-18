"""
Instance generation for the microgrid EVSP-V2G (covering-plus-arbitrage model).

Notation matches the formulation checkpoint (main.tex):
    I  : tasks (trips)            T : time blocks (hours)
    D_t: base demand   P_t: solar     Delta_t = D_t - P_t   (kWh per block)
    G  : battery capacity   rho: per-block charge/discharge rate (kWh)
    eta: round-trip loss    eps_pen: tiny activity regularizer
    c_g: $/kWh fossil   c_v,c_b: fixed deployment cost of a truck / battery

Units: energy in kWh, time in 1-hour blocks. Depot and all stations are at the
origin (single-bus, copper-plate microgrid), so the only spatial structure is the
deadhead distance between task locations.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Trip:
    idx: int
    start: int          # start time block
    end: int            # end time block (start + duration)
    sloc: int           # start location index
    eloc: int           # end location index
    energy: float       # traction energy required (kWh)


@dataclass
class Instance:
    T: int                          # number of time blocks
    D: np.ndarray                   # base demand per block (kWh)
    P: np.ndarray                   # solar generation per block (kWh)
    trips: list[Trip]
    dist: np.ndarray                # location-to-location distance matrix (== travel time in blocks)
    G: float                        # battery capacity (kWh)
    rho: float                      # charge/discharge rate per block (kWh)
    eta: float                      # round-trip loss in [0,1)
    energy_per_dist: float          # deadhead traction energy per distance unit (kWh)
    c_g: float                      # fossil cost ($/kWh)
    c_v: float                      # truck fixed cost ($)
    c_b: float                      # battery fixed cost ($)
    eps_pen: float = 1e-3           # activity regularizer ($/kWh of charge+discharge)
    depot: int = 0                  # depot/station location index (origin)
    gen_cap: float = float("inf")   # max fossil generation per block (kWh); inf = uncapped
    charge_cap: float = float("inf")# max total charging power per block (kWh); inf = uncapped
    fuel_budget: float = float("inf") # max total fossil generation over the day (units); inf = none
    nb_fixed: float = -1.0          # if >=0, fix the stationary-battery count (two-stage studies)
    max_trucks: float = float("inf")# cap on total truck columns selected (two-stage studies)
    soc_step: float = 5.0           # SoC lattice step for the pricing DP (same units as G)
    deg_cost: float = 0.0           # $ per unit of DISCHARGE throughput (cycling degradation)
    stations: list = None           # charging locations H0 (paper Sec. 3); None -> depot only

    @property
    def charge_locs(self) -> list:
        """The station set H0: locations where a parked truck may charge/discharge.
        Defaults to [depot] -- the single-station special case every prior
        experiment uses (copper-plate bus: energy balance stays global)."""
        return self.stations if self.stations else [self.depot]

    @property
    def Delta(self) -> np.ndarray:
        return self.D - self.P

    @property
    def n_trips(self) -> int:
        return len(self.trips)

    def deadhead_time(self, a: int, b: int) -> int:
        """Travel time (blocks) between locations a and b (speed = 1 unit/block)."""
        return int(round(self.dist[a, b]))

    def deadhead_energy(self, a: int, b: int) -> float:
        return self.dist[a, b] * self.energy_per_dist


def _demand_profile(T: int, total_kwh: float, peak: float, base: float) -> np.ndarray:
    """A smooth base-load curve between `base` and `peak` kW, scaled to integrate
    to `total_kwh` over T hourly blocks. Morning and evening bumps, midday dip --
    qualitatively the San Nicolas Island shape."""
    t = np.arange(T)
    # two gaussian-ish bumps (morning ~8h, evening ~19h) on a base level
    morning = np.exp(-0.5 * ((t - 8) / 2.5) ** 2)
    evening = np.exp(-0.5 * ((t - 19) / 2.5) ** 2)
    shape = 0.45 * morning + 0.55 * evening
    raw = base + (peak - base) * shape / shape.max()
    raw = raw * (total_kwh / raw.sum())          # rescale to exact daily energy
    return raw


def _solar_profile(T: int, total_kwh: float, sunrise: int = 6, sunset: int = 18) -> np.ndarray:
    """A midday solar bell, zero outside [sunrise, sunset], scaled to total_kwh/day."""
    t = np.arange(T)
    noon = 0.5 * (sunrise + sunset)
    width = (sunset - sunrise) / 4.0
    bell = np.exp(-0.5 * ((t - noon) / width) ** 2)
    bell[(t < sunrise) | (t > sunset)] = 0.0
    if bell.sum() > 0:
        bell = bell * (total_kwh / bell.sum())
    return bell


def make_instance(
    n_trips: int = 30,
    n_locations: int = 3,
    eps: float = 2.0,
    T: int = 24,
    daily_demand_kwh: float = 20_000.0,
    daily_solar_kwh: float = 14_000.0,
    G: float = 700.0,
    rho: float = 350.0,
    eta: float = 0.10,
    c_g: float = 1.0,
    c_v: float = 100.0,
    c_b: float = 40.0,
    energy_per_dist: float = 5.0,
    trip_window: tuple[int, int] = (4, 22),
    duration: int = 2,
    gen_cap: float = 1500.0,
    charge_cap: float = 1800.0,
    seed: int = 0,
) -> Instance:
    """Build a reproducible instance imitating the reference operational setup.

    eps in {1.5, 2.0, 2.5} -> 150/200/250 kWh traction per task.
    Trips are generated with fixed 2-hour windows inside `trip_window`.
    """
    rng = np.random.default_rng(seed)

    D = _demand_profile(T, daily_demand_kwh, peak=975.0, base=500.0)
    P = _solar_profile(T, daily_solar_kwh)

    # distance matrix between locations (location 0 = depot/origin).
    # Manhattan distances on a small grid; depot at origin. Coordinates are
    # distinct so every deadhead between distinct locations takes >= 1 block
    # (keeps the pricing DP a clean time-forward DAG).
    # Default 4x4 grid (16 points); grow it only when more locations are requested
    # so instances with <= 17 locations are byte-for-byte unchanged.
    side = 4
    while side * side < n_locations - 1:
        side += 1
    grid_pts = [(x, y) for x in range(1, side + 1) for y in range(1, side + 1)]
    rng.shuffle(grid_pts)
    coords = np.zeros((n_locations, 2))
    for k in range(1, n_locations):
        coords[k] = grid_pts[k - 1]                   # distinct small integer coordinates
    dist = np.zeros((n_locations, n_locations))
    for a in range(n_locations):
        for b in range(n_locations):
            dist[a, b] = abs(coords[a, 0] - coords[b, 0]) + abs(coords[a, 1] - coords[b, 1])

    # generate trips with fixed start times spread over the working window
    lo, hi = trip_window
    trips: list[Trip] = []
    energy = eps * 100.0
    for i in range(n_trips):
        start = int(rng.integers(lo, hi - duration + 1))
        sloc = int(rng.integers(0, n_locations))
        eloc = int(rng.integers(0, n_locations))
        trips.append(Trip(idx=i, start=start, end=start + duration,
                          sloc=sloc, eloc=eloc, energy=energy))
    trips.sort(key=lambda tr: (tr.start, tr.idx))
    for new_idx, tr in enumerate(trips):
        tr.idx = new_idx

    return Instance(
        T=T, D=D, P=P, trips=trips, dist=dist, G=G, rho=rho, eta=eta,
        energy_per_dist=energy_per_dist, c_g=c_g, c_v=c_v, c_b=c_b, depot=0,
        gen_cap=gen_cap, charge_cap=charge_cap,
    )


if __name__ == "__main__":
    inst = make_instance(n_trips=30, n_locations=3, eps=2.0, seed=1)
    print(f"T={inst.T}  trips={inst.n_trips}  locations={inst.dist.shape[0]}")
    print(f"daily demand = {inst.D.sum():.0f} kWh   daily solar = {inst.P.sum():.0f} kWh")
    print(f"midday surplus blocks (Delta<0): {[int(t) for t in np.where(inst.Delta < 0)[0]]}")
    print(f"max surplus = {(-inst.Delta).max():.0f} kWh   peak deficit = {inst.Delta.max():.0f} kWh")
    print(f"G={inst.G} rho={inst.rho} eta={inst.eta}  c_g={inst.c_g} c_v={inst.c_v} c_b={inst.c_b}")
    print("first 3 trips:", [(t.idx, t.start, t.end, t.sloc, t.eloc, t.energy) for t in inst.trips[:3]])
