import { useCallback, useEffect, useRef } from "react";

export type FrameBatchedQueue<T> = {
  enqueue: (item: T) => void;
  flush: () => void;
  cancel: () => void;
  pendingCount: () => number;
};

export function useFrameBatchedQueue<T>(
  consume: (items: readonly T[]) => void,
): FrameBatchedQueue<T> {
  const consumeRef = useRef(consume);
  const pendingRef = useRef<T[]>([]);
  const frameRef = useRef<number | null>(null);
  consumeRef.current = consume;

  const flush = useCallback(() => {
    if (frameRef.current !== null) {
      if (typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(frameRef.current);
      } else {
        window.clearTimeout(frameRef.current);
      }
      frameRef.current = null;
    }
    const pending = pendingRef.current;
    pendingRef.current = [];
    if (pending.length > 0) {
      consumeRef.current(pending);
    }
  }, []);

  const enqueue = useCallback((item: T) => {
    pendingRef.current.push(item);
    if (frameRef.current !== null) {
      return;
    }
    const consumePending = () => {
      frameRef.current = null;
      const pending = pendingRef.current;
      pendingRef.current = [];
      if (pending.length > 0) {
        consumeRef.current(pending);
      }
    };
    if (typeof window.requestAnimationFrame === "function") {
      frameRef.current = window.requestAnimationFrame(consumePending);
      return;
    }
    frameRef.current = window.setTimeout(consumePending, 0);
  }, []);

  const cancel = useCallback(() => {
    if (frameRef.current !== null) {
      if (typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(frameRef.current);
      } else {
        window.clearTimeout(frameRef.current);
      }
      frameRef.current = null;
    }
    pendingRef.current = [];
  }, []);

  useEffect(() => cancel, [cancel]);

  return {
    enqueue,
    flush,
    cancel,
    pendingCount: () => pendingRef.current.length,
  };
}