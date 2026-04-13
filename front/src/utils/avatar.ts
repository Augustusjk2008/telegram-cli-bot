const DEFAULT_USER_AVATAR_NAME = "user-default.png";
const DEFAULT_BOT_AVATAR_NAME = "bot-default.png";

export function resolveAvatarName(avatarName: string | undefined, kind: "user" | "bot") {
  const fallback = kind === "user" ? DEFAULT_USER_AVATAR_NAME : DEFAULT_BOT_AVATAR_NAME;
  return avatarName?.trim() || fallback;
}

export function buildAvatarUrl(avatarName: string | undefined, kind: "user" | "bot") {
  return `/assets/avatars/${resolveAvatarName(avatarName, kind)}`;
}

