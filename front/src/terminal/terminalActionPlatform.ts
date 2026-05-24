import type { TerminalAction, TerminalRuntimePlatform } from "../services/types";

export function resolveTerminalActionCommand(
  action: TerminalAction,
  runtimePlatform: TerminalRuntimePlatform,
) {
  if (runtimePlatform === "windows") {
    return (action.windowsCommand || "").trim();
  }
  if (runtimePlatform === "macos") {
    return ((action.macosCommand || "").trim() || (action.linuxCommand || "").trim());
  }
  return (action.linuxCommand || "").trim();
}

export function isTerminalActionVisible(
  action: TerminalAction,
  runtimePlatform: TerminalRuntimePlatform,
) {
  return action.enabled && Boolean(resolveTerminalActionCommand(action, runtimePlatform));
}
