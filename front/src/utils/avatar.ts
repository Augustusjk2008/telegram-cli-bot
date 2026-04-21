import type { AvatarAsset } from "../services/types";

const USER_AVATAR_STORAGE_KEY = "web-user-avatar-name";

export const DEFAULT_AVATAR_ASSETS: AvatarAsset[] = Array.from({ length: 12 }, (_, index) => {
  const name = `avatar_${String(index + 1).padStart(2, "0")}.png`;
  return { name, url: `/assets/avatars/${name}` };
});

export function resolveAvatarName(avatarName: string | undefined, _kind: "user" | "bot") {
  return avatarName?.trim() || "";
}

export function buildAvatarUrl(avatarName: string | undefined, kind: "user" | "bot") {
  const resolvedName = resolveAvatarName(avatarName, kind);
  return resolvedName ? `/assets/avatars/${resolvedName}` : "";
}

export function pickAvailableAvatarName(
  avatarName: string | undefined,
  assets: AvatarAsset[],
  kind: "user" | "bot",
) {
  const resolvedName = resolveAvatarName(avatarName, kind);
  if (resolvedName && assets.some((asset) => asset.name === resolvedName)) {
    return resolvedName;
  }

  return assets[0]?.name || resolvedName;
}

export function readStoredUserAvatarName() {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    return resolveAvatarName(localStorage.getItem(USER_AVATAR_STORAGE_KEY) || undefined, "user");
  } catch {
    return "";
  }
}

export function storeUserAvatarName(avatarName: string) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    const resolvedName = resolveAvatarName(avatarName, "user");
    if (resolvedName) {
      localStorage.setItem(USER_AVATAR_STORAGE_KEY, resolvedName);
    } else {
      localStorage.removeItem(USER_AVATAR_STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}
