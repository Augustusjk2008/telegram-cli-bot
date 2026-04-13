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

  useEffect(() => {
    setCurrentName(resolveAvatarName(avatarName, kind));
  }, [avatarName, kind]);

  return (
    <img
      src={buildAvatarUrl(currentName, kind)}
      alt={alt}
      width={size}
      height={size}
      className="shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface-strong)] object-cover"
      onError={() => {
        const fallbackName = resolveAvatarName(undefined, kind);
        if (currentName !== fallbackName) {
          setCurrentName(fallbackName);
        }
      }}
    />
  );
}
