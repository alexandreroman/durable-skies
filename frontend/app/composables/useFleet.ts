import { onMounted, onUnmounted, ref } from "vue";
import type { Base, DeliveryPoint, Drone, FleetEvent, FleetState } from "../types/fleet";

const POLL_INTERVAL_MS = 500;

export function useFleet() {
  const drones = ref<Drone[]>([]);
  const bases = ref<Base[]>([]);
  const deliveryPoints = ref<DeliveryPoint[]>([]);
  const events = ref<FleetEvent[]>([]);
  const pendingOrdersCount = ref(0);
  const dispatching = ref(false);
  const selectedDrone = ref<string | null>(null);
  const hoveredDrone = ref<string | null>(null);

  const config = useRuntimeConfig();
  let stopped = false;
  let timerId: ReturnType<typeof setTimeout> | null = null;

  async function fetchOnce(): Promise<void> {
    try {
      const state = await $fetch<FleetState>(`${config.public.apiBase}/fleet`);
      drones.value = state.drones;
      bases.value = state.bases;
      deliveryPoints.value = state.delivery_points;
      events.value = state.events;
      pendingOrdersCount.value = state.pending_orders_count ?? 0;
      dispatching.value = state.dispatching ?? false;
    } catch {
      // swallow: next poll will retry
    }
  }

  async function loop(): Promise<void> {
    if (stopped) return;
    await fetchOnce();
    if (stopped) return;
    timerId = setTimeout(loop, POLL_INTERVAL_MS);
  }

  function selectDrone(id: string | null): void {
    selectedDrone.value = selectedDrone.value === id ? null : id;
  }

  function setHoveredDrone(id: string | null): void {
    hoveredDrone.value = id;
  }

  async function submitOrder(): Promise<void> {
    const pickupBase = bases.value[0];

    const requests = Array.from({ length: 10 }, () => {
      const dropoff =
        deliveryPoints.value.length > 0
          ? deliveryPoints.value[Math.floor(Math.random() * deliveryPoints.value.length)]
          : undefined;

      const order = {
        id: crypto.randomUUID(),
        pickup_base_id: pickupBase?.id ?? "base-north",
        dropoff_point_id: dropoff?.id ?? "dp-1",
        payload_kg: 1.2,
        created_at: new Date().toISOString(),
      };

      return $fetch(`${config.public.apiBase}/orders`, { method: "POST", body: order });
    });

    try {
      await Promise.all(requests);
    } catch {
      // swallow: next poll will retry
    }
  }

  onMounted(() => {
    stopped = false;
    void loop();
  });

  onUnmounted(() => {
    stopped = true;
    if (timerId !== null) {
      clearTimeout(timerId);
      timerId = null;
    }
  });

  return {
    drones,
    bases,
    deliveryPoints,
    events,
    pendingOrdersCount,
    dispatching,
    selectedDrone,
    hoveredDrone,
    selectDrone,
    setHoveredDrone,
    submitOrder,
  };
}
