import type { HostEffect, PluginAction } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";

export type PluginActionExecutionContext = {
  client: WebBotClient;
  botAlias: string;
  pluginId: string;
  viewId: string;
  title: string;
  sessionId?: string;
  inputPayload: Record<string, unknown>;
  payload?: Record<string, unknown>;
  applyHostEffects?: (effects: HostEffect[]) => Promise<void> | void;
  closeSession?: (pluginId: string, sessionId: string) => Promise<void> | void;
  refreshSession?: (pluginId: string, sessionId: string) => Promise<void> | void;
  reopenView?: (target: {
    pluginId: string;
    viewId: string;
    title: string;
    input: Record<string, unknown>;
  }) => Promise<void> | void;
  pushToast?: (message: string) => void;
};

function confirmAction(action: PluginAction) {
  if (!action.confirm) {
    return true;
  }
  const title = action.confirm.title?.trim();
  const message = action.confirm.message?.trim();
  return window.confirm([title, message].filter(Boolean).join("\n\n") || `确认执行 ${action.label}？`);
}

export async function runPluginAction(
  action: PluginAction,
  context: PluginActionExecutionContext,
) {
  if (action.disabled) {
    return;
  }
  if (!confirmAction(action)) {
    return;
  }

  const payload = {
    ...(action.payload || {}),
    ...(context.payload || {}),
  };
  const result = action.target === "host"
    ? { hostEffects: action.hostAction ? [action.hostAction] : [] }
    : await context.client.invokePluginAction(context.botAlias, context.pluginId, {
        viewId: context.viewId,
        sessionId: context.sessionId,
        actionId: action.id,
        payload,
      });

  if (result.message) {
    context.pushToast?.(result.message);
  }
  if (result.hostEffects?.length) {
    await context.applyHostEffects?.(result.hostEffects);
  }
  if (result.closeSession && context.sessionId) {
    await context.closeSession?.(context.pluginId, context.sessionId);
    return;
  }
  if (result.refresh === "session" && context.sessionId) {
    if (context.refreshSession) {
      await context.refreshSession(context.pluginId, context.sessionId);
      return;
    }
    await context.reopenView?.({
      pluginId: context.pluginId,
      viewId: context.viewId,
      title: context.title,
      input: context.inputPayload,
    });
    return;
  }
  if (result.refresh === "view") {
    await context.reopenView?.({
      pluginId: context.pluginId,
      viewId: context.viewId,
      title: context.title,
      input: context.inputPayload,
    });
  }
}
