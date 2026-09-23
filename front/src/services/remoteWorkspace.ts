import type { BotSummary, RemoteConnectionInput, RemoteWorkspace } from "./types";

export type RawRemoteWorkspace = {
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
    username: raw.username, root: raw.root, hostKeyFingerprint: raw.host_key_fingerprint,
    ...(raw.key_filename ? { keyFilename: raw.key_filename } : {}),
  };
}

export function remoteConnectionBody(input: RemoteConnectionInput, reconnect = false) {
  return {
    ...(!reconnect ? { host: input.host, port: input.port, username: input.username } : {}),
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

// Backslashes are valid filename characters on POSIX targets.
export function joinRemotePath(parent: string, name: string) {
  return `${parent.replace(/\/+$/, "")}/${name}`;
}

export function parentRemotePath(path: string) {
  return path.replace(/\/+$/, "").replace(/\/[^/]*$/, "") || "/";
}
