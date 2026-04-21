<script setup lang="ts">
import { computed } from "vue";
import type { Base, Drone, FlightLegKind } from "../types/fleet";
import { SIGNAL_COLORS, WORKFLOW_STATES } from "../composables/fleetConstants";

const LEG_LABELS: Record<FlightLegKind, string> = {
  takeoff: "Takeoff",
  to_pickup: "→ Pickup",
  pickup: "Pickup package",
  to_dropoff: "→ Dropoff",
  dropoff: "Deliver",
  return: "Return",
  land: "Land",
  divert_to_base: "Divert to base",
};

const props = defineProps<{
  drones: Drone[];
  bases: Base[];
  selectedDrone: string | null;
}>();

const emit = defineEmits<{ select: [id: string | null]; hover: [id: string | null] }>();

const baseById = computed(() => new Map(props.bases.map((b) => [b.id, b])));

function batteryColor(battery: number): string {
  if (battery > 40) return "#00D4A0";
  if (battery > 20) return "#FFB547";
  return "#FF6B6B";
}

function signalColor(signal: string): string {
  return SIGNAL_COLORS[signal] ?? "var(--ds-text-dim)";
}

function workflowUrl(workflowId: string): string {
  return `http://localhost:8233/namespaces/default/workflows/${encodeURIComponent(workflowId)}`;
}

function baseName(baseId: string): string {
  return baseById.value.get(baseId)?.name ?? baseId;
}

function orderLabel(orderId: string): string {
  return orderId.length > 6 ? orderId.slice(-6) : orderId;
}
</script>

<template>
  <div class="flex flex-col" @click.self="emit('select', null)">
    <div
      class="flex items-center justify-between px-3 py-2"
      style="border-bottom: 1px solid var(--ds-divider)"
      @click.self="emit('select', null)"
    >
      <span class="ds-section-label">Drones</span>
      <span class="ds-count-pill">
        <span class="ds-count-num">{{ drones.length }}</span>
        <span>active</span>
      </span>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto" @click.self="emit('select', null)">
      <div
        v-for="drone in drones"
        :key="drone.id"
        class="ds-wf-row"
        :class="{ 'is-selected': selectedDrone === drone.id }"
        :style="{
          borderLeft:
            selectedDrone === drone.id
              ? `2px solid ${WORKFLOW_STATES[drone.state].color}`
              : '2px solid transparent',
        }"
        @click="emit('select', drone.id)"
        @mouseenter="emit('hover', drone.id)"
        @mouseleave="emit('hover', null)"
      >
        <div class="mb-1 flex items-center justify-between gap-2">
          <div class="flex min-w-0 items-center gap-2">
            <span
              class="ds-state-dot"
              :style="{
                background: WORKFLOW_STATES[drone.state].color,
                color: WORKFLOW_STATES[drone.state].color,
              }"
            />
            <span class="ds-wf-name truncate">{{ drone.name }}</span>
          </div>
          <div class="flex items-center gap-2">
            <template v-if="drone.current_order_id">
              <a
                v-if="drone.workflow_id"
                class="ds-order-chip"
                :href="workflowUrl(drone.workflow_id)"
                target="_blank"
                rel="noopener noreferrer"
                @click.stop
              >
                order #{{ orderLabel(drone.current_order_id) }}
              </a>
              <span v-else class="ds-order-chip">
                order #{{ orderLabel(drone.current_order_id) }}
              </span>
            </template>
            <span
              class="ds-state-pill"
              :style="{
                background: WORKFLOW_STATES[drone.state].bg,
                color: WORKFLOW_STATES[drone.state].color,
                border: `1px solid ${WORKFLOW_STATES[drone.state].color}55`,
              }"
            >
              {{ WORKFLOW_STATES[drone.state].label }}
            </span>
          </div>
        </div>

        <div class="mb-1.5 flex items-center justify-between gap-2">
          <span class="ds-home-chip truncate">⌂ {{ baseName(drone.home_base_id) }}</span>
        </div>

        <div class="flex items-center gap-1">
          <div class="ds-battery-track">
            <div
              class="ds-battery-fill"
              :style="{
                width: `${drone.battery_pct}%`,
                background: batteryColor(drone.battery_pct),
              }"
            />
          </div>
          <svg
            class="ds-battery-icon"
            width="14"
            height="14"
            viewBox="0 0 16 16"
            aria-hidden="true"
            :style="{ color: batteryColor(drone.battery_pct) }"
          >
            <rect
              x="1.5"
              y="5"
              width="11"
              height="6"
              rx="1.25"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linejoin="round"
            />
            <rect
              x="13"
              y="6.75"
              width="1.5"
              height="2.5"
              rx="0.5"
              fill="currentColor"
            />
            <rect
              x="3"
              y="6.5"
              :width="(Math.max(0, Math.min(100, drone.battery_pct)) / 100) * 8"
              height="3"
              fill="currentColor"
            />
          </svg>
          <span class="ds-battery-pct">{{ drone.battery_pct.toFixed(0) }}%</span>
        </div>

        <div class="mt-1.5 ds-chip-row">
          <span
            v-for="(signal, i) in drone.signals.slice(-2)"
            :key="i"
            class="ds-signal-chip"
            :style="{
              border: `1px solid ${signalColor(signal)}66`,
              color: signalColor(signal),
            }"
          >
            ⚡ {{ signal }}
          </span>
        </div>

        <div class="ds-plan-track mt-1.5">
          <template v-if="drone.flight_plan">
            <template v-for="(leg, i) in drone.flight_plan.legs" :key="i">
              <span
                class="ds-plan-step"
                :class="[
                  `is-${leg.status}`,
                  { 'is-divert': leg.kind === 'divert_to_base' },
                ]"
                :style="
                  leg.status === 'active'
                    ? {
                        background:
                          leg.kind === 'divert_to_base'
                            ? WORKFLOW_STATES.INCIDENT.color
                            : WORKFLOW_STATES[drone.state].color,
                        borderColor:
                          leg.kind === 'divert_to_base'
                            ? WORKFLOW_STATES.INCIDENT.color
                            : WORKFLOW_STATES[drone.state].color,
                      }
                    : leg.kind === 'divert_to_base'
                      ? { borderColor: WORKFLOW_STATES.INCIDENT.color, color: WORKFLOW_STATES.INCIDENT.color }
                      : {}
                "
                :title="LEG_LABELS[leg.kind]"
              />
              <span
                v-if="i < drone.flight_plan.legs.length - 1"
                class="ds-plan-link"
                :class="{ 'is-done': leg.status === 'done' }"
              />
            </template>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ds-battery-icon {
  flex-shrink: 0;
  display: inline-block;
  vertical-align: middle;
}

.ds-plan-track {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: nowrap;
  min-height: 16px;
}

.ds-chip-row {
  min-height: 18px;
}

.ds-plan-step {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.35);
  background: transparent;
  flex-shrink: 0;
  transition:
    background 120ms ease,
    border-color 120ms ease;
}

.ds-plan-step.is-done {
  background: rgba(255, 255, 255, 0.35);
  border-color: rgba(255, 255, 255, 0.35);
}

.ds-plan-step.is-active {
  width: 8px;
  height: 8px;
  transform-origin: center;
  animation: ds-plan-glow 1.6s ease-in-out infinite;
}

.ds-plan-step.is-pending {
  background: transparent;
}

.ds-plan-step.is-divert.is-done {
  background: #ff6b6b;
  border-color: #ff6b6b;
}

.ds-plan-link {
  width: 6px;
  height: 1px;
  background: rgba(255, 255, 255, 0.18);
  flex-shrink: 0;
}

.ds-plan-link.is-done {
  background: rgba(255, 255, 255, 0.35);
}

@keyframes ds-plan-glow {
  0%,
  100% {
    box-shadow: 0 0 2px 0 color-mix(in srgb, currentColor 60%, transparent);
    transform: scale(1);
  }
  50% {
    box-shadow: 0 0 5px 0 color-mix(in srgb, currentColor 60%, transparent);
    transform: scale(1.35);
  }
}
</style>
