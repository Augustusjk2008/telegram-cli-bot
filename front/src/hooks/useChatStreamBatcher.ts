import { useCallback, useRef } from "react";
import { useFrameBatchedQueue } from "./useFrameBatchedQueue";

export type ChatStreamPatch<T> = (current: T) => T;

/** Batches stream patches into one state update per animation frame. */
export function useChatStreamBatcher<T>(setState: (updater: (current: T) => T) => void) {
  const setStateRef = useRef(setState);
  setStateRef.current = setState;
  const queue = useFrameBatchedQueue<ChatStreamPatch<T>>((patches) => {
    setStateRef.current((current) => patches.reduce((next, patch) => patch(next), current));
  });

  return {
    enqueue: queue.enqueue,
    flush: queue.flush,
    cancel: queue.cancel,
    pendingCount: queue.pendingCount,
    applyNow: useCallback((patch: ChatStreamPatch<T>) => {
      queue.flush();
      setStateRef.current(patch);
    }, [queue]),
  };
}