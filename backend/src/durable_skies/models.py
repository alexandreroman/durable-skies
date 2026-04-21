"""Shared data models used across the API, workflows, activities, and agents.

All types here are plain Pydantic models so they can cross the Temporal/ADK
boundary losslessly. The `WorkflowState` / `FleetEventType` string enums use
the exact casing expected by the frontend — no translation layer needed.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    lat: float
    lon: float


class Base(BaseModel):
    id: str
    name: str
    location: Coordinate


class DeliveryPoint(BaseModel):
    id: str
    name: str
    location: Coordinate


class WorkflowState(StrEnum):
    IDLE = "IDLE"
    CHARGING = "CHARGING"
    DISPATCHED = "DISPATCHED"
    IN_FLIGHT = "IN_FLIGHT"
    DELIVERING = "DELIVERING"
    INCIDENT = "INCIDENT"
    RETURNING = "RETURNING"
    COMPLETED = "COMPLETED"


class FlightLegKind(StrEnum):
    TAKEOFF = "takeoff"
    TO_PICKUP = "to_pickup"
    PICKUP = "pickup"
    TO_DROPOFF = "to_dropoff"
    DROPOFF = "dropoff"
    RETURN = "return"
    LAND = "land"
    DIVERT_TO_BASE = "divert_to_base"


class FlightLegStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"


class FlightLeg(BaseModel):
    kind: FlightLegKind
    from_point_id: str | None = None  # None for instant steps with no movement
    to_point_id: str  # for takeoff/land this is the pad (home or target base)
    status: FlightLegStatus = FlightLegStatus.PENDING


class FlightPlan(BaseModel):
    order_id: str
    legs: list[FlightLeg]
    current_leg_index: int = 0


class DroneRuntimeState(BaseModel):
    id: str
    name: str
    home_base_id: str
    state: WorkflowState = WorkflowState.IDLE
    position: Coordinate
    battery_pct: float = Field(default=100.0, ge=0, le=100)
    workflow_id: str | None = None
    current_order_id: str | None = None
    signals: list[str] = Field(default_factory=list)
    target_point_id: str | None = None
    flight_plan: FlightPlan | None = None


class DroneAvailability(BaseModel):
    """Dispatcher-facing registry snapshot published by each DroneWorkflow.

    Semantically distinct from `DroneRuntimeState`: carries only the fields the
    dispatcher needs to rank candidates, plus `updated_at` for staleness
    filtering on the read side.
    """

    drone_id: str
    name: str
    home_base_id: str
    state: WorkflowState
    battery_pct: float = Field(ge=0, le=100)
    current_order_id: str | None = None
    updated_at: str  # ISO-8601 UTC


class OrderStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    FAILED = "failed"


class Order(BaseModel):
    id: str
    pickup_base_id: str
    dropoff_point_id: str
    payload_kg: float
    created_at: datetime
    status: OrderStatus = OrderStatus.PENDING


class FleetEventType(StrEnum):
    INFO = "info"
    SIGNAL = "signal"
    INCIDENT = "incident"
    SUCCESS = "success"


class FleetEvent(BaseModel):
    id: str
    time: str  # ISO-8601 UTC
    type: FleetEventType
    message: str


class FleetState(BaseModel):
    drones: list[DroneRuntimeState]
    bases: list[Base]
    delivery_points: list[DeliveryPoint]
    events: list[FleetEvent]  # newest first, up to 40
    pending_orders_count: int = 0
    dispatching: bool = False
    dispatchable_drones_count: int = 0
