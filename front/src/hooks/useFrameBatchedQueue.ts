import { useCallback, useEffect, useMemo, useRef } from "react";

export type FrameBatchedQueue<T> = {
  enqueue: (item: T) => void;
  flush: () => void;
  cancel: () => void;
  pendingCount: () => number;
};

export function useFrameBatchedQueue<T>(
  consume: (items: readonly T[]) => void,
  enabled = true,
): FrameBatchedQueue<T> {
  const consumeRef = useRef(consume);
  const pendingRef = useRef<T[]>([]);
  const frameRef = useRef<number | null>(null);
  const fallbackTimerRef = useRef<number | null>(null);
  consumeRef.current = consume;

  const cancelScheduledFlush = useCallback(() => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    if (fallbackTimerRef.current !== null) {
      window.clearTimeout(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  const flush = useCallback(() => {
    cancelScheduledFlush();
    const pending = pendingRef.current;
    pendingRef.current = [];
    if (pending.length > 0) {
      consumeRef.current(pending);
    }
  }, [cancelScheduledFlush]);

  const enqueue = useCallback((item: T) => {
    if (!enabled) {
      consumeRef.current([item]);
      return;
    }
    pendingRef.current.push(item);
    if (frameRef.current !== null || fallbackTimerRef.current !== null) {
      return;
    }
    const consumePending = () => {
      cancelScheduledFlush();
      const pending = pendingRef.current;
      pendingRef.current = [];
      if (pending.length > 0) {
        consumeRef.current(pending);
      }
    };
    frameRef.current = window.requestAnimationFrame(consumePending);
    fallbackTimerRef.current = window.setTimeout(consumePending, 50);
  }, [cancelScheduledFlush, enabled]);

  const cancel = useCallback(() => {
    cancelScheduledFlush();
    pendingRef.current = [];
  }, [cancelScheduledFlush]);

  useEffect(() => cancel, [cancel]);

  return useMemo(() => ({
    enqueue,
    flush,
    cancel,
    pendingCount: () => pendingRef.current.length,
  }), [cancel, enqueue, flush]);
}
