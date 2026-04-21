"""Hard-coded Paris-area world: depots, delivery points, and initial fleet.

The same coordinates power the Nuxt map and the Temporal workflows — they are
served to the UI via `GET /fleet` so there is a single source of truth.
"""

from .models import Base, Coordinate, DeliveryPoint, DroneRuntimeState, WorkflowState

DEPOTS: list[Base] = [
    Base(id="base-north", name="North Depot", location=Coordinate(lat=48.893, lon=2.342)),
    Base(id="base-south", name="South Depot", location=Coordinate(lat=48.818, lon=2.358)),
    Base(id="base-east", name="East Depot", location=Coordinate(lat=48.862, lon=2.412)),
]

DELIVERY_POINTS: list[DeliveryPoint] = [
    DeliveryPoint(id="dp-1", name="DP-1", location=Coordinate(lat=48.874, lon=2.295)),
    DeliveryPoint(id="dp-2", name="DP-2", location=Coordinate(lat=48.841, lon=2.301)),
    DeliveryPoint(id="dp-3", name="DP-3", location=Coordinate(lat=48.883, lon=2.378)),
    DeliveryPoint(id="dp-4", name="DP-4", location=Coordinate(lat=48.828, lon=2.389)),
    DeliveryPoint(id="dp-5", name="DP-5", location=Coordinate(lat=48.856, lon=2.268)),
    DeliveryPoint(id="dp-6", name="DP-6", location=Coordinate(lat=48.871, lon=2.431)),
    DeliveryPoint(id="dp-7", name="DP-7", location=Coordinate(lat=48.838, lon=2.334)),
    DeliveryPoint(id="dp-8", name="DP-8", location=Coordinate(lat=48.848, lon=2.426)),
]

# 4 drones across 3 depots, NATO-phonetic names.
_DRONE_ASSIGNMENTS: tuple[tuple[str, str], ...] = (
    ("Alpha", "base-north"),
    ("Bravo", "base-north"),
    ("Charlie", "base-south"),
    ("Echo", "base-east"),
)


def _base_by_id(base_id: str) -> Base:
    for base in DEPOTS:
        if base.id == base_id:
            return base
    raise KeyError(base_id)


def initial_drones() -> list[DroneRuntimeState]:
    """Build the initial fleet; each call returns fresh instances."""
    drones: list[DroneRuntimeState] = []
    for name, base_id in _DRONE_ASSIGNMENTS:
        base = _base_by_id(base_id)
        drones.append(
            DroneRuntimeState(
                id=name,
                name=name,
                home_base_id=base_id,
                state=WorkflowState.IDLE,
                position=base.location.model_copy(),
                battery_pct=100.0,
            )
        )
    return drones


def initial_drone_startups() -> list[tuple[str, str, str, Coordinate]]:
    """Return (drone_id, name, home_base_id, home_location) tuples for startup."""
    startups: list[tuple[str, str, str, Coordinate]] = []
    for name, base_id in _DRONE_ASSIGNMENTS:
        base = _base_by_id(base_id)
        startups.append((name, name, base_id, base.location.model_copy()))
    return startups
