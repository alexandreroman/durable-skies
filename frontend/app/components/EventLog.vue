<script setup lang="ts">
import type { FleetEvent } from "../types/fleet";
import { LOG_COLORS } from "../composables/fleetConstants";

defineProps<{ events: FleetEvent[] }>();

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function colorFor(type: FleetEvent["type"]): string {
  return LOG_COLORS[type] ?? "var(--ds-text-muted)";
}

// 90% mix toward --ds-text (#E8E9F3) to keep the type signal but soften the
// raw hue for easier scanning across dozens of rows.
function messageColor(type: FleetEvent["type"]): string {
  return `color-mix(in srgb, ${colorFor(type)} 90%, #E8E9F3)`;
}
</script>

<template>
  <div class="ds-event-log flex flex-col">
    <div class="ds-event-header">
      <span class="ds-section-label">Event Log</span>
    </div>
    <div class="flex-1 overflow-y-auto">
      <TransitionGroup name="ds-event-row" tag="div">
        <div v-for="event in events" :key="event.id" class="ds-event-row">
          <span class="ds-event-time">{{ formatTime(event.time) }}</span>
          <span class="ds-event-bar" :style="{ background: colorFor(event.type) }" />
          <span class="ds-event-message" :style="{ color: messageColor(event.type) }">
            {{ event.message }}
          </span>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.ds-event-row-enter-active {
  transition: opacity 200ms ease-out, transform 200ms ease-out;
}
.ds-event-row-leave-active {
  transition: opacity 120ms ease-in;
}
.ds-event-row-enter-from {
  opacity: 0;
  transform: translateY(-6px);
}
.ds-event-row-enter-to,
.ds-event-row-leave-from {
  opacity: 1;
  transform: translateY(0);
}
.ds-event-row-leave-to {
  opacity: 0;
}
</style>
