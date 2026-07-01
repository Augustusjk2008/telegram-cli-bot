export const WORKSPACE_DELETED_EVENT = "tcb-workspace-deleted";

export type WorkspaceDeletedDetail = {
  botAlias: string;
  workspacePath: string;
};

export function dispatchWorkspaceDeleted(detail: WorkspaceDeletedDetail) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<WorkspaceDeletedDetail>(WORKSPACE_DELETED_EVENT, { detail }));
}

export function isWorkspaceDeletedEvent(event: Event): event is CustomEvent<WorkspaceDeletedDetail> {
  return event instanceof CustomEvent && event.type === WORKSPACE_DELETED_EVENT;
}
