"""Activity-side world lookup. Activities live outside the workflow sandbox,
so they can import `world` directly and keep lookups cheap.
"""

from ..models import Base, Coordinate, DeliveryPoint
from ..world import DELIVERY_POINTS, DEPOTS

_BASES: dict[str, Base] = {b.id: b for b in DEPOTS}
_DELIVERY_POINTS: dict[str, DeliveryPoint] = {p.id: p for p in DELIVERY_POINTS}


def resolve_location(point_id: str) -> Coordinate:
    """Resolve any base or delivery-point id to its coordinate."""
    if point_id in _BASES:
        return _BASES[point_id].location
    if point_id in _DELIVERY_POINTS:
        return _DELIVERY_POINTS[point_id].location
    raise KeyError(f"Unknown location id: {point_id}")


def resolve_name(point_id: str) -> str:
    """Resolve any base or delivery-point id to its human-readable name."""
    if point_id in _BASES:
        return _BASES[point_id].name
    if point_id in _DELIVERY_POINTS:
        return _DELIVERY_POINTS[point_id].name
    raise KeyError(f"Unknown location id: {point_id}")
