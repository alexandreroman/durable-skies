import type { WorkflowState, WorkflowStateStyle } from "../types/fleet";

export const WORKFLOW_STATES: Record<WorkflowState, WorkflowStateStyle> = {
  IDLE: { label: "Idle", color: "#5A5D82", bg: "#1A1A2E" },
  DISPATCHED: { label: "Dispatched", color: "#FFB547", bg: "#2A1F0D" },
  IN_FLIGHT: { label: "In flight", color: "#41D1FF", bg: "#0D2334" },
  DELIVERING: { label: "Delivering", color: "#00D4A0", bg: "#0D2A20" },
  INCIDENT: { label: "Incident", color: "#FF6B6B", bg: "#2D1212" },
  RETURNING: { label: "Returning", color: "#7C5CFF", bg: "#1A1440" },
  COMPLETED: { label: "Completed", color: "#00D4A0", bg: "#0D2A20" },
};

export const SIGNAL_COLORS: Record<string, string> = {
  battery_critical: "#FF6B6B",
  delivered: "#00D4A0",
  dispatched: "#41D1FF",
  incident: "#FF6B6B",
};

export const LOG_COLORS: Record<string, string> = {
  info: "#41D1FF",
  signal: "#FFB547",
  incident: "#FF6B6B",
  success: "#00D4A0",
};

export const MAP_BOUNDS = {
  minLat: 48.8,
  maxLat: 48.91,
  minLng: 2.24,
  maxLng: 2.46,
};

export function latLngToXY(
  lat: number,
  lng: number,
  width: number,
  height: number,
): { x: number; y: number } {
  const { minLat, maxLat, minLng, maxLng } = MAP_BOUNDS;
  const x = ((lng - minLng) / (maxLng - minLng)) * width;
  const y = ((maxLat - lat) / (maxLat - minLat)) * height;
  return { x, y };
}
