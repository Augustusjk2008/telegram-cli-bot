import { useFrameBatchedQueue } from "./useFrameBatchedQueue";
import { FRONTEND_FEATURE_FLAGS } from "../app/featureFlags";
import { useCallback, useMemo } from "react";
import { isChatStreamBarrier, type ChatStreamInputEvent } from "../stream/chatStreamBatch";

export function useChatStreamBatcher(
  consume: (events: readonly ChatStreamInputEvent[]) => void,
) {
  const queue = useFrameBatchedQueue(consume, FRONTEND_FEATURE_FLAGS.chatFrameBatching);
  const enqueue = useCallback((event: ChatStreamInputEvent) => {
    if (isChatStreamBarrier(event)) {
      queue.flush();
      queue.enqueue(event);
      queue.flush();
      return;
    }
    queue.enqueue(event);
  }, [queue]);
  return useMemo(() => ({ ...queue, enqueue }), [enqueue, queue]);
}
