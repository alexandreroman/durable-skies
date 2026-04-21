<script setup lang="ts">
import { computed } from "vue";
import type { Base, DeliveryPoint, Drone } from "../types/fleet";
import { SIGNAL_COLORS, WORKFLOW_STATES } from "../composables/fleetConstants";

const props = defineProps<{
  drones: Drone[];
  bases: Base[];
  deliveryPoints: DeliveryPoint[];
  selectedDrone: string | null;
}>();

const emit = defineEmits<{ select: [id: string] }>();

const baseById = computed(() => new Map(props.bases.map((b) => [b.id, b])));
const deliveryPointById = computed(() => new Map(props.deliveryPoints.map((p) => [p.id, p])));

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

function deliveryPointName(pointId: string): string {
  return deliveryPointById.value.get(pointId)?.name ?? pointId;
}

function orderLabel(orderId: string): string {
  return orderId.length > 6 ? orderId.slice(-6) : orderId;
}
</script>

<template>
  <div class="flex flex-col">
    <div
      class="flex items-center justify-between px-3 py-2"
      style="border-bottom: 1px solid var(--ds-divider)"
    >
      <span class="ds-section-label">Workflow Registry</span>
      <span class="ds-count-pill">
        <span class="ds-count-num">{{ drones.length }}</span>
        <span>active</span>
      </span>
    </div>

    <div class="flex-1 overflow-y-auto">
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

        <div class="mb-1.5 flex items-center justify-between gap-2">
          <span v-if="drone.target_point_id" class="ds-wf-meta min-w-0 truncate">
            → {{ deliveryPointName(drone.target_point_id) }}
          </span>
          <span class="ds-home-chip ml-auto truncate">⌂ {{ baseName(drone.home_base_id) }}</span>
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
</style>
