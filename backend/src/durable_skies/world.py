"""Hard-coded Paris-area world: depots, delivery points, and initial fleet.

The same coordinates power the Nuxt map and the Temporal workflows — they are
served to the UI via `GET /fleet` so there is a single source of truth.
"""

from typing import NamedTuple

from .models import Base, Coordinate, DeliveryPoint

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


class DroneSpec(NamedTuple):
    id: str
    name: str
    home_base_id: str
    home_location: Coordinate


_DEPOTS_BY_ID: dict[str, Base] = {b.id: b for b in DEPOTS}


def _spec(name: str, base_id: str) -> DroneSpec:
    return DroneSpec(id=name, name=name, home_base_id=base_id, home_location=_DEPOTS_BY_ID[base_id].location)


# 4 drones across 3 depots, NATO-phonetic names. Drone id == display name.
DRONE_SPECS: tuple[DroneSpec, ...] = (
    _spec("Alpha", "base-north"),
    _spec("Bravo", "base-north"),
    _spec("Charlie", "base-south"),
    _spec("Echo", "base-east"),
)
