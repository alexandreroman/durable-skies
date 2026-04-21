<script setup lang="ts">
import { useFleet } from "./composables/useFleet";

const {
  drones,
  bases,
  deliveryPoints,
  events,
  pendingOrdersCount,
  selectedDrone,
  selectDrone,
  submitOrder,
} = useFleet();
</script>

<template>
  <div class="flex h-screen flex-col">
    <header class="ds-header flex items-center gap-4 pl-5 pr-3">
      <div class="flex items-center gap-3">
        <!-- Hexagonal drone badge -->
        <svg
          width="28"
          height="28"
          viewBox="0 0 28 28"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <path
            d="M14 2.5 L24 8 L24 20 L14 25.5 L4 20 L4 8 Z"
            fill="var(--ds-violet-soft)"
            stroke="var(--ds-violet)"
            stroke-width="1.25"
            stroke-linejoin="round"
          />
          <!-- Cross-quadcopter glyph -->
          <g stroke="var(--ds-violet)" stroke-width="1.25" stroke-linecap="round">
            <line x1="14" y1="9" x2="14" y2="19" />
            <line x1="9" y1="14" x2="19" y2="14" />
            <circle cx="14" cy="9" r="1.5" fill="var(--ds-violet)" stroke="none" />
            <circle cx="14" cy="19" r="1.5" fill="var(--ds-violet)" stroke="none" />
            <circle cx="9" cy="14" r="1.5" fill="var(--ds-violet)" stroke="none" />
            <circle cx="19" cy="14" r="1.5" fill="var(--ds-violet)" stroke="none" />
          </g>
        </svg>

        <div class="flex flex-col leading-tight">
          <span class="ds-brand">Durable Skies</span>
          <span class="ds-subtitle">Temporal · Drone Fleet Orchestrator</span>
        </div>
      </div>

      <div class="ml-auto flex items-center gap-3">
        <span
          v-if="pendingOrdersCount > 0"
          class="ds-queue-pill"
          :title="`${pendingOrdersCount} order${pendingOrdersCount === 1 ? '' : 's'} waiting for a drone`"
        >
          <span aria-hidden="true">📦</span>
          <span class="ds-queue-num">{{ pendingOrdersCount }}</span>
          <span>queued</span>
        </span>
        <button class="ds-submit-button" @click="submitOrder()">
          <span class="ds-submit-plus">+</span>
          <span>Submit order</span>
        </button>
      </div>
    </header>

    <div class="flex flex-1 overflow-hidden">
      <FleetMap
        :drones="drones"
        :bases="bases"
        :delivery-points="deliveryPoints"
        :selected-drone="selectedDrone"
        @select="(id) => selectDrone(id)"
      />
      <div class="ds-right-rail flex flex-col">
        <WorkflowRegistry
          class="flex-1 min-h-0"
          :drones="drones"
          :bases="bases"
          :selected-drone="selectedDrone"
          @select="(id) => selectDrone(id)"
        />
        <EventLog class="max-h-[200px]" :events="events" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.ds-queue-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--ds-divider);
  background: rgba(255, 255, 255, 0.03);
  color: var(--ds-text);
  font-size: 12px;
  line-height: 1;
  letter-spacing: 0.02em;
  user-select: none;
  transition: color 150ms ease, border-color 150ms ease, background 150ms ease;
}
.ds-queue-num {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ds-violet);
}
</style>
