import { useFrameBatchedQueue } from "./useFrameBatchedQueue";
import { FRONTEND_FEATURE_FLAGS } from "../app/featureFlags";

export function useChatStreamBatcher<T>(
  consume: (events: readonly T[]) => void,
) {
  return useFrameBatchedQueue(consume, FRONTEND_FEATURE_FLAGS.chatFrameBatching);
}
