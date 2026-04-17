import { BotSummary } from "../services/types";
import { X } from "lucide-react";
import { ChatAvatar } from "./ChatAvatar";
import { StatusPill } from "./StatusPill";

type Props = {
  bots: BotSummary[];
  currentAlias: string;
  onSelect: (alias: string) => boolean | Promise<boolean>;
  onManage: () => void;
  onClose: () => void;
};

export function BotSwitcherSheet({ bots, currentAlias, onSelect, onManage, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-[var(--surface)] rounded-t-2xl shadow-lg max-h-[80vh] flex flex-col animate-in slide-in-from-bottom-full duration-200">
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <h2 className="text-lg font-bold">切换 Bot</h2>
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
            Bot 管理
          </button>
        </div>
        <div className="overflow-y-auto p-4 space-y-2">
          {bots.map((bot) => {
            const isOffline = bot.status === "offline";
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
                className={`w-full flex items-center justify-between p-4 rounded-xl border ${
                  isOffline
                    ? "cursor-not-allowed border-red-200 bg-red-50/80 opacity-95"
                    : currentAlias === bot.alias
                      ? "border-[var(--accent)] bg-[var(--accent)]/5"
                      : "border-[var(--border)] hover:bg-[var(--surface-strong)]"
                }`}
              >
                <div className="flex min-w-0 items-start gap-3">
                  <ChatAvatar alt={`${bot.alias} 头像`} avatarName={bot.avatarName} kind="bot" size={32} />
                  <div className="flex min-w-0 flex-col items-start">
                    <span className="font-semibold">{bot.alias}</span>
                    <span className="max-w-full truncate text-xs text-[var(--muted)]" title={`${bot.cliType}: ${bot.workingDir}`}>
                      {bot.cliType}: {bot.workingDir}
                    </span>
                    {isOffline ? (
                      <span className="mt-1 text-xs font-medium text-red-700">离线中，暂不可切换</span>
                    ) : null}
                  </div>
                </div>
                <StatusPill status={bot.status} />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
