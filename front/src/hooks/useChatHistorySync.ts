import { useEffect, useRef } from "react";
import { FRONTEND_FEATURE_FLAGS } from "../app/featureFlags";

type Options = {
  enabled: boolean;
  isStreaming: boolean;
  isSseHealthy: () => boolean;
  sync: (translationsOnly?: boolean) => boolean | void | Promise<boolean | void>;
  pendingTranslationKeys?: string[];
  initialDelayMs?: number;
  idleIntervalMs?: number;
  maxBackoffMs?: number;
  incrementalEnabled?: boolean;
};

/** Schedules idle delta sync and a bounded translation refresh window during SSE. */
export function useChatHistorySync({
  enabled,
  isStreaming,
  isSseHealthy,
  sync,
  pendingTranslationKeys = [],
  initialDelayMs = 5_000,
  idleIntervalMs = 10_000,
  maxBackoffMs = 60_000,
  incrementalEnabled = FRONTEND_FEATURE_FLAGS.historyRevisionSync,
}: Options) {
  const syncRef = useRef(sync);
  syncRef.current = sync;
  const healthyRef = useRef(isSseHealthy);
  healthyRef.current = isSseHealthy;
  const translationAttemptsRef = useRef(new Map<string, number>());
  const pendingKey = JSON.stringify(pendingTranslationKeys);

  useEffect(() => {
    const pendingKeys: string[] = JSON.parse(pendingKey);
    const pendingSet = new Set(pendingKeys);
    for (const key of translationAttemptsRef.current.keys()) {
      if (!pendingSet.has(key)) translationAttemptsRef.current.delete(key);
    }
    const remainingTranslations = () => pendingKeys.filter((key) => (translationAttemptsRef.current.get(key) || 0) < 40);
    if (!incrementalEnabled && pendingKeys.length === 0) {
      if (!enabled) {
        return;
      }
      const timer = window.setInterval(() => {
        void syncRef.current();
      }, idleIntervalMs);
      return () => window.clearInterval(timer);
    }
    if (!enabled) {
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
      if (disposed) {
        return;
      }
      const translations = remainingTranslations();
      if (translations.length === 0 && isStreaming && healthyRef.current()) return;
      timer = window.setTimeout(async () => {
        timer = null;
        const translationsOnly = translations.length > 0;
        for (const key of translations) {
          translationAttemptsRef.current.set(key, (translationAttemptsRef.current.get(key) || 0) + 1);
        }
        try {
          const result = await syncRef.current(translationsOnly);
          if (result === false) {
            throw new Error("history sync failed");
          }
          delay = idleIntervalMs;
        } catch {
          delay = Math.min(maxBackoffMs, delay * 2);
        }
        schedule();
      }, translations.length > 0 ? 1_500 : delay);
    };
    schedule();
    return () => {
      disposed = true;
      cancelTimer();
    };
  }, [enabled, idleIntervalMs, incrementalEnabled, initialDelayMs, isStreaming, maxBackoffMs, pendingKey]);
}
