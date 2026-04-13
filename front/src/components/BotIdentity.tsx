import type { ReactNode } from "react";
import { ChatAvatar } from "./ChatAvatar";

type Props = {
  alias: string;
  avatarName?: string;
  size?: number;
  className?: string;
  nameClassName?: string;
  subtitle?: ReactNode;
};

export function BotIdentity({
  alias,
  avatarName,
  size = 28,
  className = "flex min-w-0 items-center gap-2",
  nameClassName = "truncate font-semibold text-[var(--text)]",
  subtitle,
}: Props) {
  return (
    <div className={className}>
      <ChatAvatar alt={`${alias} 头像`} avatarName={avatarName} kind="bot" size={size} />
      <div className="min-w-0">
        <div className={nameClassName}>{alias}</div>
        {subtitle}
      </div>
    </div>
  );
}
