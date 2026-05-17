import type { DebugLaunchField, DebugProfile } from "../services/types";

export type DebugLaunchFormValue = string | number | boolean | string[] | Record<string, string>;
export type DebugLaunchForm = Record<string, DebugLaunchFormValue>;

export function buildDebugLaunchForm(profile: DebugProfile | null): DebugLaunchForm {
  if (!profile) {
    return {};
  }
  const defaults = { ...profile.launchDefaults };
  if (profile.providerId === "cpp-gdb") {
    defaults.prepareCommand ??= profile.prepareCommand;
    defaults.remoteHost ??= profile.remoteHost;
    defaults.remoteUser ??= profile.remoteUser;
    defaults.remoteDir ??= profile.remoteDir;
    defaults.remotePort ??= profile.remotePort;
    defaults.stopAtEntry ??= profile.stopAtEntry;
    defaults.password ??= "";
  }
  return defaults as DebugLaunchForm;
}

export function fieldsForProfile(profile: DebugProfile | null): DebugLaunchField[] {
  if (!profile) {
    return [];
  }
  if (profile.launchSchema.fields.length > 0) {
    return profile.launchSchema.fields;
  }
  if (profile.providerId !== "cpp-gdb") {
    return [];
  }
  return [
    { key: "prepareCommand", label: "准备命令", type: "string" },
    { key: "remoteHost", label: "host", type: "string" },
    { key: "remoteUser", label: "user", type: "string" },
    { key: "remoteDir", label: "remoteDir", type: "string" },
    { key: "remotePort", label: "port", type: "number" },
    { key: "password", label: "password", type: "string", secret: true },
    { key: "stopAtEntry", label: "入口暂停", type: "boolean" },
  ];
}
