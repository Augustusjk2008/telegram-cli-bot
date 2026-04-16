export const ASSISTANT_CRON_RUN_ENQUEUED_EVENT = "assistant-cron-run-enqueued";

export type AssistantCronRunEnqueuedDetail = {
  botAlias: string;
  runId: string;
  prompt: string;
  queuedAt: string;
};

export function dispatchAssistantCronRunEnqueued(detail: AssistantCronRunEnqueuedDetail) {
  window.dispatchEvent(new CustomEvent<AssistantCronRunEnqueuedDetail>(ASSISTANT_CRON_RUN_ENQUEUED_EVENT, {
    detail,
  }));
}

export function isAssistantCronRunEnqueuedEvent(
  event: Event,
): event is CustomEvent<AssistantCronRunEnqueuedDetail> {
  return event.type === ASSISTANT_CRON_RUN_ENQUEUED_EVENT;
}
