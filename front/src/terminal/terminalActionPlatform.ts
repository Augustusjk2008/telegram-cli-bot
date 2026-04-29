import type { TerminalAction, TerminalRuntimePlatform } from "../services/types";

export function resolveTerminalActionCommand(
  action: TerminalAction,
  runtimePlatform: TerminalRuntimePlatform,
) {
  return (runtimePlatform === "windows" ? action.windowsCommand : action.linuxCommand).trim();
}

export function isTerminalActionVisible(
  action: TerminalAction,
  runtimePlatform: TerminalRuntimePlatform,
) {
  return action.enabled && Boolean(resolveTerminalActionCommand(action, runtimePlatform));
}
