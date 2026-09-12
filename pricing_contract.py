"""Validated, immutable physical inputs for the exact-grid pricing DAG.

Only physical transitions are cached. Duals, costs, DP labels and predecessors
are never cached. Every lookup fingerprints mutable instance contents, and an
explicit prepared object must match the current physical identity exactly.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import math
import numpy as np


@dataclass(frozen=True)
class PhysicalTrip:
    idx: int
    start: int
    end: int
    sloc: int
    eloc: int
    energy: float
    shift: int


@dataclass(frozen=True)
class PreparedPricing:
    identity: tuple
    T: int
    step: float
    nloc: int
    nlevels: int
    origin: int
    up: int
    down: int
    stations: tuple
    # outgoing/incoming entries: (other location, time, energy-level shift)
    outgoing: tuple
    incoming: tuple
    trips_start: tuple
    trips_end: tuple


def _integer(value, label, minimum=0):
    if not np.isfinite(value) or value != int(value) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return int(value)


def grid_index(value, step, label):
    """Accept representation noise only; do not round physical input to a grid."""
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
    q = value / step
    if not math.isfinite(q):
        raise ValueError(f"{label}/step is not finite")
    idx = int(round(q))
    # ULP-scaled allowance handles e.g. 0.3/0.1, not 1e-6 physical errors.
    if abs(q - idx) > 16 * np.finfo(float).eps * max(1.0, abs(q)):
        raise ValueError(f"{label}={value} is not aligned with SoC step {step}")
    return idx


def validate_storage(inst, step):
    step = float(getattr(inst, "soc_step", 5.0) if step is None else step)
    if not math.isfinite(step) or step <= 0:
        raise ValueError("SoC step must be finite and positive")
    T = _integer(inst.T, "T", 1)
    Gidx = grid_index(inst.G, step, "capacity G")
    rho, eta = float(inst.rho), float(inst.eta)
    if not math.isfinite(rho) or rho < 0:
        raise ValueError("rho must be finite and nonnegative")
    if not math.isfinite(eta) or not 0 <= eta < 1:
        raise ValueError("eta must lie in [0, 1)")
    # Rate greater than capacity is valid: no move can traverse more than G.
    up = int(math.floor(min(Gidx, (1 - eta) * rho / step)))
    down = int(math.floor(min(Gidx, rho / step)))
    return T, step, Gidx + 1, up, down


def physical_identity(inst, step=None, ice=False):
    step = float(getattr(inst, "soc_step", 5.0) if step is None else step)
    dist = np.asarray(inst.dist, dtype=float)
    return ("pricing-grid-v11", step, bool(ice), inst.T, float(inst.G),
            float(inst.rho), float(inst.eta), float(inst.energy_per_dist),
            inst.depot, dist.shape, tuple(dist.ravel()),
            tuple(getattr(inst, "charge_locs", None) or [inst.depot]),
            tuple((tr.idx, tr.start, tr.end, tr.sloc, tr.eloc, float(tr.energy))
                  for tr in inst.trips))


def _build(identity):
    (_, step, ice, T, G, rho, eta, epd, origin, shape, flat,
     stations, trip_data) = identity
    # A lightweight namespace lets both pricing helpers share storage checks.
    from types import SimpleNamespace
    T, step, nL, up, down = validate_storage(
        SimpleNamespace(T=T, G=G, rho=rho, eta=eta), step)
    if len(shape) != 2 or shape[0] != shape[1] or shape[0] < 1:
        raise ValueError("dist must be a nonempty square matrix")
    nloc = shape[0]
    origin = _integer(origin, "depot")
    if origin >= nloc:
        raise ValueError("depot is outside dist")
    if not math.isfinite(epd) or epd < 0:
        raise ValueError("energy_per_dist must be finite and nonnegative")
    stations = tuple(sorted(set(_integer(h, "station") for h in stations)))
    if any(h >= nloc for h in stations):
        raise ValueError("station is outside dist")
    outgoing, incoming = [[] for _ in range(nloc)], [[] for _ in range(nloc)]
    for a in range(nloc):
        for b in range(nloc):
            distance = flat[a * nloc + b]
            dt = _integer(distance, f"dist[{a},{b}]", 0 if a == b else 1)
            if a == b:
                if dt != 0:
                    raise ValueError("dist diagonal must be zero")
                continue
            shift = 0 if ice else grid_index(distance * epd, step, f"deadhead energy[{a},{b}]")
            if shift < nL and dt <= T:
                outgoing[a].append((b, dt, shift))
                incoming[b].append((a, dt, shift))
    starts = [[[] for _ in range(nloc)] for _ in range(T)]
    ends = [[[] for _ in range(nloc)] for _ in range(T + 1)]
    indices = []
    for idx, start, end, sloc, eloc, energy in trip_data:
        idx = _integer(idx, "trip index")
        start, end = _integer(start, "trip start"), _integer(end, "trip end", 1)
        sloc, eloc = _integer(sloc, "trip start location"), _integer(eloc, "trip end location")
        if not start < end <= T or sloc >= nloc or eloc >= nloc:
            raise ValueError("trip must advance time within the horizon and use valid locations")
        if not math.isfinite(energy) or energy < 0:
            raise ValueError("trip energy must be finite and nonnegative")
        shift = 0 if ice else grid_index(energy, step, f"trip {idx} energy")
        tr = PhysicalTrip(idx, start, end, sloc, eloc, energy, shift)
        indices.append(idx)
        if shift < nL:
            starts[start][sloc].append(tr)
            ends[end][eloc].append(tr)
    if sorted(indices) != list(range(len(trip_data))):
        raise ValueError("trip indices must be unique and cover 0..n_trips-1")
    freeze = lambda groups: tuple(tuple(tuple(g) for g in row) for row in groups)
    return PreparedPricing(identity, T, step, nloc, nL, origin, up, down,
                           stations, tuple(map(tuple, outgoing)), tuple(map(tuple, incoming)),
                           freeze(starts), freeze(ends))


_cached_build = lru_cache(maxsize=16)(_build)


def prepare_pricing(inst, step=None, ice=False, use_cache=True):
    """Prepare/reuse immutable physical arcs; uncached mode is a benchmark control."""
    key = physical_identity(inst, step, ice)
    return (_cached_build if use_cache else _build)(key)


def checked_prepared(inst, step=None, ice=False, prepared=None, use_cache=True):
    if prepared is None:
        return prepare_pricing(inst, step, ice, use_cache)
    if not isinstance(prepared, PreparedPricing) or prepared.identity != physical_identity(inst, step, ice):
        raise ValueError("prepared pricing physical identity mismatch; prepare again after input changes")
    return prepared


def pricing_cache_info():
    return _cached_build.cache_info()


def clear_pricing_cache():
    _cached_build.cache_clear()


def validate_duals(inst, alpha, mu, nu):
    alpha, mu = np.asarray(alpha, dtype=float), np.asarray(mu, dtype=float)
    nu = np.zeros(inst.T) if nu is None else np.asarray(nu, dtype=float)
    if alpha.shape != (inst.n_trips,) or mu.shape != (inst.T,) or nu.shape != (inst.T,):
        raise ValueError("pricing dual dimensions do not match trips/horizon")
    if not all(np.isfinite(x).all() for x in (alpha, mu, nu)):
        raise ValueError("pricing duals must be finite")
    for label in ("c_v", "eps_pen", "deg_cost"):
        if not math.isfinite(float(getattr(inst, label, 0.0))):
            raise ValueError(f"{label} must be finite")
    return alpha, mu, nu


def check_reconstructed_cost(reported, direct, terms, horizon):
    # Summing a valid path in a different order can differ by floating-point ULPs.
    # This guard never selects a predecessor: every chosen arc must match exactly.
    bound = 128 * np.finfo(float).eps * (horizon + 1) * max(1.0, sum(abs(float(x)) for x in terms))
    if not math.isfinite(direct) or abs(reported - direct) > bound:
        raise RuntimeError(f"pricing reconstruction reduced-cost mismatch: DP={reported}, column={direct}, bound={bound}")
