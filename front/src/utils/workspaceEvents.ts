export const WORKSPACE_DELETED_EVENT = "tcb-workspace-deleted";

export type WorkspaceDeletedDetail = {
  botAlias: string;
  workspacePath: string;
};

export function isWorkspaceDeletedEvent(event: Event): event is CustomEvent<WorkspaceDeletedDetail> {
  return event instanceof CustomEvent && event.type === WORKSPACE_DELETED_EVENT;
}
