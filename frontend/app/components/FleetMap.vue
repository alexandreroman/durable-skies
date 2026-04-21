<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { Base, DeliveryPoint, Drone, FlightLegKind, FlightLegStatus } from "../types/fleet";
import { WORKFLOW_STATES, latLngToXY } from "../composables/fleetConstants";

const props = defineProps<{
  drones: Drone[];
  bases: Base[];
  deliveryPoints: DeliveryPoint[];
  selectedDrone: string | null;
}>();

const emit = defineEmits<{ select: [id: string | null] }>();

const canvasRef = ref<HTMLCanvasElement | null>(null);

// Client-side tween state. The backend polls every 500 ms and replaces the
// `drones` prop wholesale, which would make drones jump between snapshots.
// We keep a non-reactive Map of per-drone tweens and lerp between the last
// rendered position and the newly-polled target over TWEEN_DURATION_MS.
// The map is mutated in place — this is a render-layer concern, not
// application state, so it deliberately sits outside Vue's reactivity.
const TWEEN_DURATION_MS = 500;

interface TweenEntry {
  fromLat: number;
  fromLon: number;
  targetLat: number;
  targetLon: number;
  startedAt: number;
}

const tweens = new Map<string, TweenEntry>();

function tweenProgress(entry: TweenEntry, now: number): number {
  if (entry.startedAt === 0) return 1;
  return Math.min(1, Math.max(0, (now - entry.startedAt) / TWEEN_DURATION_MS));
}

function renderedPosition(droneId: string, now: number): { lat: number; lon: number } {
  const entry = tweens.get(droneId);
  if (!entry) {
    // Defensive fallback: the watcher should have populated the map already.
    const drone = props.drones.find((d) => d.id === droneId);
    return drone ? { lat: drone.position.lat, lon: drone.position.lon } : { lat: 0, lon: 0 };
  }
  const t = tweenProgress(entry, now);
  return {
    lat: entry.fromLat + (entry.targetLat - entry.fromLat) * t,
    lon: entry.fromLon + (entry.targetLon - entry.fromLon) * t,
  };
}

watch(
  () => props.drones,
  (incoming) => {
    const now = performance.now();
    const seen = new Set<string>();
    for (const drone of incoming) {
      seen.add(drone.id);
      const entry = tweens.get(drone.id);
      if (!entry) {
        tweens.set(drone.id, {
          fromLat: drone.position.lat,
          fromLon: drone.position.lon,
          targetLat: drone.position.lat,
          targetLon: drone.position.lon,
          startedAt: 0,
        });
        continue;
      }
      if (drone.position.lat !== entry.targetLat || drone.position.lon !== entry.targetLon) {
        const t = tweenProgress(entry, now);
        const currentLat = entry.fromLat + (entry.targetLat - entry.fromLat) * t;
        const currentLon = entry.fromLon + (entry.targetLon - entry.fromLon) * t;
        entry.fromLat = currentLat;
        entry.fromLon = currentLon;
        entry.targetLat = drone.position.lat;
        entry.targetLon = drone.position.lon;
        entry.startedAt = now;
      }
    }
    for (const id of tweens.keys()) {
      if (!seen.has(id)) tweens.delete(id);
    }
  },
  { deep: true, immediate: true },
);

const legendStates = Object.entries(WORKFLOW_STATES).filter(([k]) => k !== "IDLE") as Array<
  [string, (typeof WORKFLOW_STATES)[keyof typeof WORKFLOW_STATES]]
>;

const STATE_STROKE: Record<string, string> = {
  IN_FLIGHT: "#41D1FF",
  RETURNING: "#7C5CFF",
  DELIVERING: "#00D4A0",
  INCIDENT: "#FF6B6B",
  DISPATCHED: "#FFB547",
};

const INCIDENT_STROKE = "#FF6B6B";

interface RenderedLeg {
  fromLat: number;
  fromLon: number;
  toLat: number;
  toLon: number;
  status: FlightLegStatus;
  kind: FlightLegKind;
}

function legsToRender(
  drone: Drone,
  findCoord: (id: string | null) => { lat: number; lon: number } | null,
): RenderedLeg[] {
  const plan = drone.flight_plan;
  if (!plan) return [];
  const out: RenderedLeg[] = [];
  for (const leg of plan.legs) {
    // Skip non-movement legs: takeoff/pickup/dropoff/land share from==to or have no origin.
    if (leg.from_point_id === null || leg.from_point_id === leg.to_point_id) continue;
    const from = findCoord(leg.from_point_id);
    const to = findCoord(leg.to_point_id);
    if (!from || !to) continue;
    out.push({
      fromLat: from.lat,
      fromLon: from.lon,
      toLat: to.lat,
      toLon: to.lon,
      status: leg.status,
      kind: leg.kind,
    });
  }
  return out;
}

// Cached CSS-pixel size of the canvas and current device pixel ratio.
// Updated by the ResizeObserver and the DPR matchMedia listener so the
// rAF draw loop doesn't need to hit the DOM on every frame.
let rectW = 0;
let rectH = 0;
let dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;

function findPointCoord(id: string | null): { lat: number; lon: number } | null {
  if (!id) return null;
  const base = props.bases.find((b) => b.id === id);
  if (base) return base.location;
  const dp = props.deliveryPoints.find((p) => p.id === id);
  if (dp) return dp.location;
  return null;
}

function syncCanvasSize(): void {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  rectW = rect.width;
  rectH = rect.height;
  const bitmapW = Math.round(rectW * dpr);
  const bitmapH = Math.round(rectH * dpr);
  if (canvas.width !== bitmapW) canvas.width = bitmapW;
  if (canvas.height !== bitmapH) canvas.height = bitmapH;
}

function draw(): void {
  const canvas = canvasRef.value;
  if (!canvas) return;
  if (rectW <= 0 || rectH <= 0) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  // Scale so subsequent draw calls use CSS-pixel units.
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const W = rectW;
  const H = rectH;

  ctx.clearRect(0, 0, W, H);

  const now = performance.now();

  ctx.strokeStyle = "rgba(124,92,255,0.05)";
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, H);
    ctx.stroke();
  }
  for (let y = 0; y < H; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }

  for (const p of props.deliveryPoints) {
    const { x, y } = latLngToXY(p.location.lat, p.location.lon, W, H);
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,181,71,0.28)";
    ctx.fill();
    ctx.strokeStyle = "#FFB547";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - 7, y);
    ctx.lineTo(x + 7, y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y - 7);
    ctx.lineTo(x, y + 7);
    ctx.stroke();
    ctx.font = '8px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillStyle = "rgba(232,233,243,0.6)";
    ctx.textAlign = "center";
    ctx.fillText(p.name, x, y + 16);
  }

  for (const b of props.bases) {
    const { x, y } = latLngToXY(b.location.lat, b.location.lon, W, H);
    ctx.beginPath();
    ctx.arc(x, y, 12, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(124,92,255,0.12)";
    ctx.fill();
    ctx.strokeStyle = "#7C5CFF";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#7C5CFF";
    ctx.font = 'bold 10px "JetBrains Mono", ui-monospace, monospace';
    ctx.textAlign = "center";
    ctx.fillText("⬡", x, y + 4);
    ctx.font = '9px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillStyle = "rgba(232,233,243,0.75)";
    ctx.fillText(b.name, x, y + 22);
  }

  for (const drone of props.drones) {
    if (drone.state === "IDLE" || drone.state === "COMPLETED") continue;
    const rendered = renderedPosition(drone.id, now);
    const pos = latLngToXY(rendered.lat, rendered.lon, W, H);

    const lineColor = STATE_STROKE[drone.state] ?? "#5A5D82";

    if (props.selectedDrone === drone.id) {
      for (const leg of legsToRender(drone, findPointCoord)) {
        const a = latLngToXY(leg.fromLat, leg.fromLon, W, H);
        const b = latLngToXY(leg.toLat, leg.toLon, W, H);
        const isDivert = leg.kind === "divert_to_base";
        const baseColor = isDivert ? INCIDENT_STROKE : lineColor;

        ctx.beginPath();
        if (leg.status === "done") {
          ctx.setLineDash([]);
          ctx.strokeStyle = `${baseColor}33`;
          ctx.lineWidth = 1;
        } else if (leg.status === "active") {
          ctx.setLineDash([]);
          ctx.strokeStyle = baseColor;
          ctx.lineWidth = 2;
        } else {
          ctx.setLineDash([4, 4]);
          ctx.strokeStyle = `${baseColor}44`;
          ctx.lineWidth = 1;
        }
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    if (props.selectedDrone === drone.id) {
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 16, 0, Math.PI * 2);
      ctx.strokeStyle = lineColor;
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    if (drone.state === "INCIDENT") {
      const pulse = (Math.sin(Date.now() / 200) + 1) / 2;
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, 12 + pulse * 6, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,107,107,${0.3 + pulse * 0.4})`;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    ctx.beginPath();
    ctx.arc(pos.x, pos.y, 8, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();

    ctx.fillStyle = "#0B0B1F";
    ctx.font = "bold 9px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("✈", pos.x, pos.y + 3);

    ctx.fillStyle = lineColor;
    ctx.font = '8px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillText(drone.name, pos.x, pos.y - 13);
  }
}

// Single rAF loop: redraws every frame so INCIDENT pulses animate smoothly
// and polled state changes show up immediately.
let rafId: number | null = null;
let resizeObserver: ResizeObserver | null = null;
let dprMedia: MediaQueryList | null = null;

function animate(): void {
  draw();
  rafId = requestAnimationFrame(animate);
}

function handleDprChange(): void {
  dpr = window.devicePixelRatio || 1;
  syncCanvasSize();
  // Re-subscribe: matchMedia queries are DPR-specific, so a new one is
  // needed after the ratio changes (e.g. dragging to an external monitor).
  if (dprMedia) dprMedia.removeEventListener("change", handleDprChange);
  dprMedia = window.matchMedia(`(resolution: ${dpr}dppx)`);
  dprMedia.addEventListener("change", handleDprChange);
}

onMounted(() => {
  const canvas = canvasRef.value;
  if (!canvas) return;

  syncCanvasSize();

  resizeObserver = new ResizeObserver(() => {
    syncCanvasSize();
  });
  resizeObserver.observe(canvas);

  dprMedia = window.matchMedia(`(resolution: ${dpr}dppx)`);
  dprMedia.addEventListener("change", handleDprChange);

  animate();
});

onBeforeUnmount(() => {
  if (rafId !== null) cancelAnimationFrame(rafId);
  if (resizeObserver) resizeObserver.disconnect();
  if (dprMedia) dprMedia.removeEventListener("change", handleDprChange);
});

function handleClick(event: MouseEvent): void {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  // With HiDPI backing store, client coords and the drawing coord space are
  // both in CSS pixels, so no scale factor is needed.
  const mx = event.clientX - rect.left;
  const my = event.clientY - rect.top;
  const now = performance.now();
  let found: string | null = null;
  for (const drone of props.drones) {
    if (drone.state === "IDLE" || drone.state === "COMPLETED") continue;
    const rendered = renderedPosition(drone.id, now);
    const { x, y } = latLngToXY(rendered.lat, rendered.lon, rect.width, rect.height);
    if (Math.hypot(x - mx, y - my) < 16) found = drone.id;
  }
  emit("select", found);
}
</script>

<template>
  <div class="ds-map-wrapper">
    <canvas ref="canvasRef" class="ds-map-canvas" @click="handleClick" />
    <div class="ds-map-legend">
      <div class="ds-map-legend-title">States</div>
      <div v-for="[key, style] in legendStates" :key="key" class="ds-map-legend-row">
        <span
          class="inline-block h-2 w-2 rounded-full"
          :style="{ background: style.color, boxShadow: `0 0 6px ${style.color}` }"
        />
        <span :style="{ color: style.color }">{{ style.label }}</span>
      </div>
    </div>
  </div>
</template>
