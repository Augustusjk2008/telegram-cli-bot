export const ASSISTANT_PROPOSAL_PATCH_REQUESTED_EVENT = "assistant-proposal-patch-requested";
export const ASSISTANT_PROPOSAL_PATCH_COMPLETED_EVENT = "assistant-proposal-patch-completed";

export type AssistantProposalPatchRequestedDetail = {
  botAlias: string;
  proposalId: string;
  proposalTitle: string;
  targetAlias: string;
  regenerate?: boolean;
  visibleText: string;
};

export type AssistantProposalPatchCompletedDetail = {
  botAlias: string;
  proposalId: string;
  ok: boolean;
  targetAlias: string;
  summary: string;
  error?: string;
};

export function dispatchAssistantProposalPatchRequested(detail: AssistantProposalPatchRequestedDetail) {
  window.dispatchEvent(new CustomEvent<AssistantProposalPatchRequestedDetail>(
    ASSISTANT_PROPOSAL_PATCH_REQUESTED_EVENT,
    { detail },
  ));
}

export function dispatchAssistantProposalPatchCompleted(detail: AssistantProposalPatchCompletedDetail) {
  window.dispatchEvent(new CustomEvent<AssistantProposalPatchCompletedDetail>(
    ASSISTANT_PROPOSAL_PATCH_COMPLETED_EVENT,
    { detail },
  ));
}

export function isAssistantProposalPatchRequestedEvent(
  event: Event,
): event is CustomEvent<AssistantProposalPatchRequestedDetail> {
  return event.type === ASSISTANT_PROPOSAL_PATCH_REQUESTED_EVENT;
}

export function isAssistantProposalPatchCompletedEvent(
  event: Event,
): event is CustomEvent<AssistantProposalPatchCompletedDetail> {
  return event.type === ASSISTANT_PROPOSAL_PATCH_COMPLETED_EVENT;
}
