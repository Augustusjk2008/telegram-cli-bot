import type { HostEffect, PluginAction, PluginOpenTarget } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";

export type ApplyPluginHostEffects = (effects: HostEffect[], pluginId?: string) => Promise<void | false> | void | false;

export type PluginActionExecutionContext = {
  client: WebBotClient;
  botAlias: string;
  pluginId: string;
  viewId: string;
  title: string;
  sessionId?: string;
  inputPayload: Record<string, unknown>;
  payload?: Record<string, unknown>;
  applyHostEffects?: ApplyPluginHostEffects;
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
    if (await context.applyHostEffects?.(result.hostEffects, context.pluginId) === false) {
      // The service already released the session when it returned closeSession or a view refresh.
      if (context.sessionId && (result.closeSession || result.refresh === "view")) {
        await context.refreshSession?.(context.pluginId, context.sessionId);
      }
      return;
    }
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

export function pluginViewTabPath(target: PluginOpenTarget) {
  const sourcePath = typeof target.input.path === "string" ? target.input.path : "";
  const viewInput = { ...target.input };
  if (typeof target.input.path === "string") delete viewInput.path;
  const identity = Object.keys(viewInput).length
    ? JSON.stringify(viewInput, (_key, value) => (
        value && typeof value === "object" && !Array.isArray(value)
          ? Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)))
          : value
      ))
    : "";
  return `plugin://${target.pluginId}/${target.viewId}/${sourcePath || target.title}${identity ? `?input=${encodeURIComponent(identity)}` : ""}`;
}

type PluginUtilityEffect = Exclude<HostEffect, { type: "open_file" | "reveal_in_files" | "open_plugin_view" }>;

export async function applyPluginUtilityEffect(
  effect: PluginUtilityEffect, client: WebBotClient, botAlias: string, pluginId: string,
) {
  if (effect.type === "copy_text") {
    await navigator.clipboard?.writeText(effect.text);
  } else if (effect.type === "download_artifact") {
    await client.downloadPluginArtifact(botAlias, effect.artifactId, effect.filename);
  } else {
    if (Object.keys(effect).some(key => key !== "type")) throw new Error("运行时安装不接受插件提供的运行时参数");
    if (!pluginId) throw new Error("运行时安装缺少插件来源");
    await client.installPluginRuntime(botAlias, pluginId);
  }
}
