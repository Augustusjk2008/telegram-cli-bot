import { useEffect, useRef } from "react";
import { FRONTEND_FEATURE_FLAGS } from "../app/featureFlags";

type Options = {
  enabled: boolean;
  isStreaming: boolean;
  isSseHealthy: () => boolean;
  sync: () => boolean | void | Promise<boolean | void>;
  initialDelayMs?: number;
  idleIntervalMs?: number;
  maxBackoffMs?: number;
  incrementalEnabled?: boolean;
};

/** Schedules low-frequency delta sync without polling while healthy SSE is streaming. */
export function useChatHistorySync({
  enabled,
  isStreaming,
  isSseHealthy,
  sync,
  initialDelayMs = 5_000,
  idleIntervalMs = 10_000,
  maxBackoffMs = 60_000,
  incrementalEnabled = FRONTEND_FEATURE_FLAGS.historyRevisionSync,
}: Options) {
  const syncRef = useRef(sync);
  syncRef.current = sync;
  const healthyRef = useRef(isSseHealthy);
  healthyRef.current = isSseHealthy;

  useEffect(() => {
    if (!incrementalEnabled) {
      if (!enabled) {
        return;
      }
      const timer = window.setInterval(() => {
        void syncRef.current();
      }, idleIntervalMs);
      return () => window.clearInterval(timer);
    }
    if (!enabled || (isStreaming && healthyRef.current())) {
      return;
    }
    let disposed = false;
    let timer: number | null = null;
    let delay = initialDelayMs;
    const cancelTimer = () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };
    const schedule = () => {
      cancelTimer();
      if (disposed || document.visibilityState === "hidden") {
        return;
      }
      timer = window.setTimeout(async () => {
        timer = null;
        try {
          const result = await syncRef.current();
          if (result === false) {
            throw new Error("history sync failed");
          }
          delay = idleIntervalMs;
        } catch {
          delay = Math.min(maxBackoffMs, delay * 2);
        }
        schedule();
      }, delay);
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        cancelTimer();
        return;
      }
      delay = initialDelayMs;
      schedule();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    schedule();
    return () => {
      disposed = true;
      cancelTimer();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, idleIntervalMs, incrementalEnabled, initialDelayMs, isStreaming, maxBackoffMs]);
}
