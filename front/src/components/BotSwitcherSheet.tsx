import { BotSummary } from "../services/types";
import { clsx } from "clsx";
import { X } from "lucide-react";
import { BotActivitySummary } from "./BotActivitySummary";
import { ChatAvatar } from "./ChatAvatar";
import { StatusPill } from "./StatusPill";
import { getBotRuntimeLabel } from "./botRuntimeLabel";

type Props = {
  bots: BotSummary[];
  currentAlias: string | null;
  onSelect: (alias: string) => boolean | Promise<boolean>;
  onManage: () => void;
  showInviteManager?: boolean;
  inviteManagerActive?: boolean;
  onOpenInviteManager?: () => void;
  onClose: () => void;
};

export function BotSwitcherSheet({
  bots,
  currentAlias,
  onSelect,
  onManage,
  showInviteManager = false,
  inviteManagerActive = false,
  onOpenInviteManager,
  onClose,
}: Props) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="智能体切换"
        className="relative bg-[var(--surface)] rounded-t-2xl shadow-lg max-h-[80vh] flex flex-col animate-in slide-in-from-bottom-full duration-200"
      >
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <h2 className="text-lg font-bold">智能体切换</h2>
          <button onClick={onClose} className="p-2 -mr-2 rounded-full hover:bg-[var(--border)]">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-4 pb-0">
          <button
            type="button"
            onClick={() => {
              onManage();
            }}
            className="w-full rounded-xl border border-[var(--border)] px-4 py-3 text-left font-medium hover:bg-[var(--surface-strong)]"
          >
            智能体管理
          </button>
        </div>
        <div className="overflow-y-auto p-4 space-y-2">
          {bots.map((bot) => {
            const isOffline = bot.serviceStatus === "offline" || bot.status === "offline";
            const noAccess = bot.canOperate === false;
            return (
              <button
                key={bot.alias}
                disabled={isOffline}
                onClick={async () => {
                  if (isOffline) {
                    return;
                  }
                  const shouldClose = await onSelect(bot.alias);
                  if (shouldClose !== false) {
                    onClose();
                  }
                }}
                className={clsx(
                  "w-full flex items-center justify-between p-4 rounded-xl border transition",
                  isOffline
                    ? "cursor-not-allowed border-red-200 bg-red-50/80 opacity-95"
                    : currentAlias === bot.alias
                      ? "tcb-soft-selected"
                      : "border-[var(--border)] hover:bg-[var(--surface-strong)]",
                  noAccess
                    ? "border-zinc-500 bg-zinc-100 text-zinc-950 shadow-inner grayscale saturate-0 contrast-125 blur-[0.2px]"
                    : "",
                )}
              >
                <div className="flex min-w-0 items-start gap-3">
                  <ChatAvatar alt={`${bot.alias} 头像`} avatarName={bot.avatarName} kind="bot" size={32} />
                  <div className="flex min-w-0 flex-col items-start">
                    <span className="font-semibold">{bot.alias}</span>
                    <span
                      className={clsx(
                        "max-w-full truncate text-xs",
                        currentAlias === bot.alias ? "text-[var(--text)]" : "text-[var(--muted)]",
                      )}
                      title={`${getBotRuntimeLabel(bot)}: ${bot.workingDir}`}
                    >
                      {getBotRuntimeLabel(bot)}: {bot.workingDir}
                    </span>
                    {isOffline ? (
                      <span className="mt-1 text-xs font-medium text-red-700">离线中，暂不可切换</span>
                    ) : null}
                    {noAccess ? (
                      <span className="mt-1 rounded border border-zinc-500 bg-white px-1.5 py-0.5 text-xs font-semibold text-zinc-900">
                        无权限 · 只读
                      </span>
                    ) : null}
                    {!isOffline ? <BotActivitySummary bot={bot} className="mt-1" /> : null}
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {bot.status === "unread" ? <StatusPill status="unread" /> : null}
                  <StatusPill status={isOffline ? "offline" : "online"} />
                </div>
              </button>
            );
          })}
          {showInviteManager ? (
            <div className="pt-3">
              <button
                type="button"
                onClick={() => {
                  onOpenInviteManager?.();
                  onClose();
                }}
                className={clsx(
                  "w-full rounded-xl border px-4 py-3 text-left font-medium",
                  inviteManagerActive
                    ? "border-transparent tcb-selected-accent"
                    : "border-[var(--border)] hover:bg-[var(--surface-strong)]",
                )}
              >
                管理中心
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
