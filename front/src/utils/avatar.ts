import type { AvatarAsset } from "../services/types";

const DEFAULT_USER_AVATAR_NAME = "user-default.png";
const DEFAULT_BOT_AVATAR_NAME = "bot-default.png";
const USER_AVATAR_STORAGE_KEY = "web-user-avatar-name";

export const DEFAULT_AVATAR_ASSETS: AvatarAsset[] = [
  { name: "user-default.png", url: "/assets/avatars/user-default.png" },
  { name: "bot-default.png", url: "/assets/avatars/bot-default.png" },
  { name: "claude-blue.png", url: "/assets/avatars/claude-blue.png" },
  { name: "kimi-teal.png", url: "/assets/avatars/kimi-teal.png" },
  { name: "codex-slate.png", url: "/assets/avatars/codex-slate.png" },
];

export function resolveAvatarName(avatarName: string | undefined, kind: "user" | "bot") {
  const fallback = kind === "user" ? DEFAULT_USER_AVATAR_NAME : DEFAULT_BOT_AVATAR_NAME;
  return avatarName?.trim() || fallback;
}

export function buildAvatarUrl(avatarName: string | undefined, kind: "user" | "bot") {
  return `/assets/avatars/${resolveAvatarName(avatarName, kind)}`;
}

export function pickAvailableAvatarName(
  avatarName: string | undefined,
  assets: AvatarAsset[],
  kind: "user" | "bot",
) {
  const resolvedName = resolveAvatarName(avatarName, kind);
  if (assets.some((asset) => asset.name === resolvedName)) {
    return resolvedName;
  }

  const preferredFallback = assets.find((asset) =>
    kind === "user" ? asset.name.includes("user") : asset.name.includes("bot"),
  );
  return preferredFallback?.name || assets[0]?.name || resolvedName;
}

export function readStoredUserAvatarName() {
  if (typeof window === "undefined") {
    return DEFAULT_USER_AVATAR_NAME;
  }
  try {
    return resolveAvatarName(localStorage.getItem(USER_AVATAR_STORAGE_KEY) || undefined, "user");
  } catch {
    return DEFAULT_USER_AVATAR_NAME;
  }
}

export function storeUserAvatarName(avatarName: string) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    localStorage.setItem(USER_AVATAR_STORAGE_KEY, resolveAvatarName(avatarName, "user"));
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}
