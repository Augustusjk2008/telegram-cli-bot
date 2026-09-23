import type { BotSummary, RemoteConnectionInput, RemoteWorkspace } from "./types";

export type RawRemoteWorkspace = {
  platform?: RemoteWorkspace["platform"];
  connection_id: string;
  host: string;
  port: number;
  username: string;
  root: string;
  host_key_fingerprint: string;
  key_filename?: string;
};

export function mapRemoteWorkspace(raw: RawRemoteWorkspace): RemoteWorkspace {
  return {
    connectionId: raw.connection_id, host: raw.host, port: raw.port,
    username: raw.username, root: normalizeRemotePath(raw.root, raw.platform), hostKeyFingerprint: raw.host_key_fingerprint,
    ...(raw.platform ? { platform: raw.platform } : {}),
    ...(raw.key_filename ? { keyFilename: raw.key_filename } : {}),
  };
}

export function remoteConnectionBody(input: RemoteConnectionInput, reconnect = false) {
  return {
    ...(!reconnect ? { host: input.host, port: input.port, username: input.username } : {}),
    ...(!reconnect && input.platform ? { platform: input.platform } : {}),
    ...(input.password ? { password: input.password } : {}),
    ...(input.keyFilename ? { key_filename: input.keyFilename } : {}),
    ...(input.passphrase ? { passphrase: input.passphrase } : {}),
    ...(input.hostKeyFingerprint ? { host_key_fingerprint: input.hostKeyFingerprint } : {}),
  };
}

export function workspaceLabel(bot: Pick<BotSummary, "workingDir" | "remoteWorkspace">) {
  const remote = bot.remoteWorkspace;
  return remote ? `${remote.username}@${remote.host}:${remote.root}` : bot.workingDir;
}

export function normalizeRemotePath(path: string, platform?: RemoteWorkspace["platform"]) {
  // Backslashes and case are significant on POSIX targets.
  if (platform !== "windows") return path;
  const normalized = path.replace(/\\/g, "/");
  // Leave UNC/device and drive-relative paths intact for backend validation.
  if ((normalized.startsWith("/") && !/^\/[A-Za-z]:(?:\/|$)/.test(normalized))
    || /^[A-Za-z]:(?!\/)/.test(normalized)) return path;
  return normalized.replace(/\/+/g, "/")
    .replace(/^\/?([a-z]):(?:\/|$)/i, (_, drive: string) => `/${drive.toUpperCase()}:/`);
}

export function joinRemotePath(parent: string, name: string, platform?: RemoteWorkspace["platform"]) {
  return normalizeRemotePath(`${normalizeRemotePath(parent, platform).replace(/\/+$/, "")}/${name}`, platform);
}

export function parentRemotePath(path: string, platform?: RemoteWorkspace["platform"]) {
  const normalized = normalizeRemotePath(path, platform).replace(/\/+$/, "");
  if (platform === "windows" && /^\/[A-Z]:$/.test(normalized)) return `${normalized}/`;
  const parent = normalized.replace(/\/[^/]*$/, "") || "/";
  return normalizeRemotePath(parent, platform);
}

export function relativeRemotePath(path: string, root: string, platform?: RemoteWorkspace["platform"]) {
  const normalized = normalizeRemotePath(path, platform);
  const prefix = `${normalizeRemotePath(root, platform).replace(/\/+$/, "")}/`;
  return normalized.startsWith(prefix) ? normalized.slice(prefix.length) : normalized;
}
