import { useEffect, useRef } from "react";

type Options = {
  enabled: boolean;
  isStreaming: boolean;
  isSseHealthy: () => boolean;
  sync: () => void | Promise<void>;
  idleIntervalMs?: number;
  maxBackoffMs?: number;
};

/** Schedules low-frequency delta sync without polling while healthy SSE is streaming. */
export function useChatHistorySync({
  enabled,
  isStreaming,
  isSseHealthy,
  sync,
  idleIntervalMs = 10_000,
  maxBackoffMs = 60_000,
}: Options) {
  const syncRef = useRef(sync);
  syncRef.current = sync;
  const healthyRef = useRef(isSseHealthy);
  healthyRef.current = isSseHealthy;

  useEffect(() => {
    if (!enabled || (isStreaming && healthyRef.current())) {
      return;
    }
    let disposed = false;
    let timer: number | null = null;
    let delay = idleIntervalMs;
    const schedule = () => {
      if (disposed || document.hidden) {
        return;
      }
      timer = window.setTimeout(async () => {
        try {
          await syncRef.current();
          delay = idleIntervalMs;
        } catch {
          delay = Math.min(maxBackoffMs, delay * 2);
        }
        schedule();
      }, delay);
    };
    schedule();
    return () => {
      disposed = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [enabled, idleIntervalMs, isStreaming, maxBackoffMs]);
}