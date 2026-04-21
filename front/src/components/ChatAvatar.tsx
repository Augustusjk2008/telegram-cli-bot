import { useEffect, useState } from "react";
import { buildAvatarUrl, resolveAvatarName } from "../utils/avatar";

type Props = {
  alt: string;
  avatarName?: string;
  kind: "user" | "bot";
  size?: number;
};

export function ChatAvatar({ alt, avatarName, kind, size = 32 }: Props) {
  const [currentName, setCurrentName] = useState(resolveAvatarName(avatarName, kind));
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setCurrentName(resolveAvatarName(avatarName, kind));
    setFailed(false);
  }, [avatarName, kind]);

  const imageUrl = buildAvatarUrl(currentName, kind);
  if (failed || !imageUrl) {
    return (
      <div
        role="img"
        aria-label={alt}
        style={{ width: size, height: size }}
        className="flex shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-strong)] text-xs font-semibold uppercase text-[var(--muted)]"
      >
        {kind === "user" ? "我" : alt.trim().charAt(0) || "B"}
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={alt}
      width={size}
      height={size}
      className="shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface-strong)] object-cover"
      onError={() => {
        const fallbackName = resolveAvatarName(undefined, kind);
        if (currentName !== fallbackName) {
          setCurrentName(fallbackName);
          return;
        }
        setFailed(true);
      }}
    />
  );
}
