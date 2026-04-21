<script setup lang="ts">
import { useFleet } from "./composables/useFleet";

const { drones, bases, deliveryPoints, events, selectedDrone, selectDrone, submitOrder } =
  useFleet();
</script>

<template>
  <div class="flex h-screen flex-col">
    <header class="ds-header flex items-center gap-4 px-5">
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

      <button class="ds-submit-button ml-auto" @click="submitOrder()">
        <span class="ds-submit-plus">+</span>
        <span>Submit order</span>
      </button>
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
          class="flex-1 overflow-hidden"
          :drones="drones"
          :selected-drone="selectedDrone"
          @select="(id) => selectDrone(id)"
        />
        <EventLog :events="events" />
      </div>
    </div>
  </div>
</template>
