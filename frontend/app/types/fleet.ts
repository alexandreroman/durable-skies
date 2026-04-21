export type WorkflowState =
  | "IDLE"
  | "DISPATCHED"
  | "IN_FLIGHT"
  | "DELIVERING"
  | "INCIDENT"
  | "RETURNING"
  | "COMPLETED";

export type FleetEventType = "info" | "signal" | "incident" | "success";

export interface Coordinate {
  lat: number;
  lon: number;
}

export interface Base {
  id: string;
  name: string;
  location: Coordinate;
}

export interface DeliveryPoint {
  id: string;
  name: string;
  location: Coordinate;
}

export type FlightLegKind =
  | "takeoff"
  | "to_pickup"
  | "pickup"
  | "to_dropoff"
  | "dropoff"
  | "return"
  | "land"
  | "divert_to_base";

export type FlightLegStatus = "pending" | "active" | "done";

export interface FlightLeg {
  kind: FlightLegKind;
  from_point_id: string | null;
  to_point_id: string;
  status: FlightLegStatus;
}

export interface FlightPlan {
  order_id: string;
  legs: FlightLeg[];
  current_leg_index: number;
}

export interface Drone {
  id: string;
  name: string;
  home_base_id: string;
  state: WorkflowState;
  position: Coordinate;
  battery_pct: number;
  workflow_id: string | null;
  current_order_id: string | null;
  signals: string[];
  target_point_id: string | null;
  flight_plan: FlightPlan | null;
}

export interface FleetEvent {
  id: string;
  time: string;
  type: FleetEventType;
  message: string;
}

export interface FleetState {
  drones: Drone[];
  bases: Base[];
  delivery_points: DeliveryPoint[];
  events: FleetEvent[];
  pending_orders_count: number;
}

export interface WorkflowStateStyle {
  label: string;
  color: string;
  bg: string;
}
