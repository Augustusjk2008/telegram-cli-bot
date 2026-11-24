import type {
  GitBranchList,
  GitCapabilities,
  GitCommitGraphPayload,
  GitGraphScope,
  GitIdentityConfig,
  GitOverview,
  GitStashList,
  GitWorkspaceIdentity,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

/** What the Git page shows for one workspace, kept so returning to the page is instant. */
export type GitScreenSnapshot = {
  overview: GitOverview;
  gitCapabilities: GitCapabilities | null;
  branches: GitBranchList;
  selectedBranch: string;
  stashes: GitStashList;
  graphScope: GitGraphScope;
  graphPayload: GitCommitGraphPayload | null;
  selectedGraphHash: string;
  identityConfig: GitIdentityConfig | null;
  commitMessage: string;
  /** A server operation this page was waiting for; its result is shown on return. */
  pendingOperationId: string;
};

export type GitScreenSections = {
  changes: boolean;
  graph: boolean;
  branches: boolean;
  stash: boolean;
  settings: boolean;
  remotes: boolean;
};

export const DEFAULT_GIT_SCREEN_SECTIONS: GitScreenSections = {
  changes: false,
  graph: false,
  branches: false,
  stash: false,
  settings: true,
  remotes: false,
};

const MAX_CACHED_WORKSPACES = 8;

type ClientCache = {
  sections: GitScreenSections;
  workspaces: Map<string, GitScreenSnapshot>;
};

// Keyed by client: signing in or out creates a new client, which drops the cache.
const caches = new WeakMap<WebBotClient, ClientCache>();

function clientCache(client: WebBotClient) {
  let cache = caches.get(client);
  if (!cache) {
    cache = { sections: DEFAULT_GIT_SCREEN_SECTIONS, workspaces: new Map() };
    caches.set(client, cache);
  }
  return cache;
}

export function gitWorkspaceKey(botAlias: string, identity?: GitWorkspaceIdentity) {
  return [
    identity?.accountId || "",
    identity?.botAlias || botAlias,
    identity?.root || "",
    identity?.connectionId || "",
    identity?.platform || "",
  ].join("\n");
}

export function readGitScreenSnapshot(client: WebBotClient, key: string) {
  return caches.get(client)?.workspaces.get(key) || null;
}

export function writeGitScreenSnapshot(client: WebBotClient, key: string, snapshot: GitScreenSnapshot) {
  const { workspaces } = clientCache(client);
  workspaces.delete(key);
  workspaces.set(key, snapshot);
  while (workspaces.size > MAX_CACHED_WORKSPACES) {
    workspaces.delete(workspaces.keys().next().value as string);
  }
}

export function readGitScreenSections(client: WebBotClient) {
  return caches.get(client)?.sections || DEFAULT_GIT_SCREEN_SECTIONS;
}

export function writeGitScreenSections(client: WebBotClient, sections: GitScreenSections) {
  clientCache(client).sections = sections;
}
