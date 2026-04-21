<script setup lang="ts">
import type { Drone } from "../types/fleet";
import { SIGNAL_COLORS, WORKFLOW_STATES } from "../composables/fleetConstants";

defineProps<{
  drones: Drone[];
  selectedDrone: string | null;
}>();

const emit = defineEmits<{ select: [id: string] }>();

function batteryColor(battery: number): string {
  if (battery > 40) return "#00D4A0";
  if (battery > 20) return "#FFB547";
  return "#FF6B6B";
}

function signalColor(signal: string): string {
  return SIGNAL_COLORS[signal] ?? "var(--ds-text-dim)";
}

function workflowLabel(workflowId: string | null): string {
  if (!workflowId) return "—";
  return workflowId.length > 12 ? workflowId.slice(-12) : workflowId;
}
</script>

<template>
  <div class="flex flex-col">
    <div
      class="flex items-center justify-between px-4 py-3"
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
        <div class="mb-1.5 flex items-center justify-between gap-2">
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

        <div class="ds-wf-meta mb-2 truncate">wf › {{ workflowLabel(drone.workflow_id) }}</div>

        <div class="flex items-center gap-2">
          <div class="ds-battery-track">
            <div
              class="ds-battery-fill"
              :style="{
                width: `${drone.battery_pct}%`,
                background: batteryColor(drone.battery_pct),
              }"
            />
          </div>
          <span class="ds-battery-pct">{{ drone.battery_pct.toFixed(0) }}%</span>
        </div>

        <div v-if="drone.signals.length > 0" class="mt-2 flex flex-wrap gap-1.5">
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
