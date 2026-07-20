import { BotSummary } from "../services/types";
import { clsx } from "clsx";
import { Settings2, ShieldCheck, X } from "lucide-react";
import { BotActivitySummary } from "./BotActivitySummary";
import { StatusPill } from "./StatusPill";
import { getBotRuntimeLabel } from "./botRuntimeLabel";
import { getBotAccentStyle } from "../utils/botVisual";

type Props = {
  bots: BotSummary[];
  currentAlias: string | null;
  onSelect: (alias: string) => boolean | Promise<boolean>;
  onManage: () => void;
  showManageButton?: boolean;
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
  showManageButton = true,
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
        data-testid="mobile-bot-switcher-sheet"
        className="relative flex max-h-[82dvh] flex-col rounded-t-xl bg-[var(--bg)] shadow-lg animate-in slide-in-from-bottom-full duration-200"
      >
        <div className="flex min-h-12 items-center justify-between border-b border-[var(--border)] px-3 py-1.5">
          <div className="flex min-w-0 items-baseline gap-2">
            <h2 className="text-base font-semibold">智能体切换</h2>
            <span className="text-xs text-[var(--muted)]">{bots.length} 个</span>
          </div>
          <button
            type="button"
            aria-label="关闭智能体切换"
            onClick={onClose}
            className="-mr-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg hover:bg-[var(--surface-strong)]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        {showManageButton || showInviteManager ? (
          <div
            className={clsx(
              "grid gap-2 border-b border-[var(--border)] px-3 py-2",
              showManageButton && showInviteManager ? "grid-cols-2" : "grid-cols-1",
            )}
          >
            {showManageButton ? (
              <button
                type="button"
                onClick={onManage}
                className="flex min-h-10 min-w-0 items-center justify-center gap-2 rounded-lg border border-[var(--border)] px-3 text-sm font-medium hover:bg-[var(--surface-strong)]"
              >
                <Settings2 className="h-4 w-4 shrink-0" />
                <span className="truncate">智能体管理</span>
              </button>
            ) : null}
            {showInviteManager ? (
              <button
                type="button"
                onClick={() => {
                  onOpenInviteManager?.();
                  onClose();
                }}
                className={clsx(
                  "flex min-h-10 min-w-0 items-center justify-center gap-2 rounded-lg border px-3 text-sm font-medium",
                  inviteManagerActive
                    ? "border-transparent tcb-selected-accent"
                    : "border-[var(--border)] hover:bg-[var(--surface-strong)]",
                )}
              >
                <ShieldCheck className="h-4 w-4 shrink-0" />
                <span className="truncate">管理中心</span>
              </button>
            ) : null}
          </div>
        ) : null}
        <div className="space-y-1.5 overflow-y-auto overscroll-contain px-3 py-2 pb-[calc(env(safe-area-inset-bottom)+0.5rem)]">
          {bots.length === 0 ? (
            <div className="py-8 text-center text-sm text-[var(--muted)]">暂无可用智能体</div>
          ) : null}
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
                  "relative min-h-16 w-full overflow-hidden rounded-lg border py-2.5 pl-4 pr-3 text-left transition active:scale-[0.99]",
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
                <span
                  aria-hidden="true"
                  className="absolute left-0 top-0 h-full w-[3px]"
                  style={getBotAccentStyle(bot.alias)}
                />
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <span className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
                    <span className="min-w-0 truncate text-sm font-semibold text-[var(--text)]">{bot.alias}</span>
                    {bot.isMain || bot.alias === "main" ? (
                      <span className="shrink-0 rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] leading-none text-[var(--muted)]">
                        主
                      </span>
                    ) : null}
                    {currentAlias === bot.alias ? (
                      <span className="shrink-0 rounded border border-transparent px-1.5 py-0.5 text-[10px] leading-none tcb-selected-accent">
                        当前
                      </span>
                    ) : null}
                    {noAccess ? (
                      <span className="shrink-0 rounded border border-zinc-500 bg-white px-1.5 py-0.5 text-[10px] font-semibold leading-none text-zinc-900">
                        无权限 · 只读
                      </span>
                    ) : null}
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    {bot.status === "unread" ? <StatusPill status="unread" className="px-1.5 text-[10px] leading-4" /> : null}
                    <StatusPill status={isOffline ? "offline" : "online"} className="px-1.5 text-[10px] leading-4" />
                  </span>
                </div>
                <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-[var(--muted)]">
                  <span
                    className={clsx(
                      "shrink-0 font-medium",
                      currentAlias === bot.alias ? "text-[var(--text)]" : "text-[var(--muted)]",
                    )}
                    title={getBotRuntimeLabel(bot)}
                  >
                    {getBotRuntimeLabel(bot)}
                  </span>
                  <span aria-hidden="true" className="shrink-0 text-[var(--border)]">·</span>
                  <span
                    className="min-w-0 flex-1 truncate"
                    title={bot.workingDir}
                  >
                    {bot.workingDir || "未设置"}
                  </span>
                  {!isOffline ? <BotActivitySummary bot={bot} className="min-h-0 shrink-0" showLatestAnswerTime /> : null}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
