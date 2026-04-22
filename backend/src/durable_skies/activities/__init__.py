from .drone import (
    dropoff_package,
    fly_drone_to_base,
    land_drone,
    navigate_drone,
    pickup_package,
    read_drone_telemetry,
    takeoff_drone,
)
from .fleet import (
    log_fleet_event,
    read_drone_availabilities_activity,
    write_drone_availability_activity,
)

all_activities = [
    takeoff_drone,
    land_drone,
    navigate_drone,
    pickup_package,
    dropoff_package,
    read_drone_telemetry,
    fly_drone_to_base,
    log_fleet_event,
    write_drone_availability_activity,
    read_drone_availabilities_activity,
]

__all__ = [
    "all_activities",
    "dropoff_package",
    "fly_drone_to_base",
    "land_drone",
    "log_fleet_event",
    "navigate_drone",
    "pickup_package",
    "read_drone_availabilities_activity",
    "read_drone_telemetry",
    "takeoff_drone",
    "write_drone_availability_activity",
]
