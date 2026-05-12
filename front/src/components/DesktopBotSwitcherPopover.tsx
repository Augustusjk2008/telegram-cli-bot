import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { clsx } from "clsx";
import { CheckCircle2, Copy, LogIn, Search, Settings, ShieldCheck, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { BotStatus, BotSummary } from "../services/types";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import { BotActivitySummary, getBotActivityText } from "./BotActivitySummary";
import { ChatAvatar } from "./ChatAvatar";
import { StatusPill } from "./StatusPill";

type StatusFilter = "all" | BotStatus;

type Props = {
  bots: BotSummary[];
  currentAlias: string | null;
  anchorRect?: DOMRect | null;
  onSelect: (alias: string) => boolean | Promise<boolean>;
  onManage: () => void;
  showInviteManager?: boolean;
  inviteManagerActive?: boolean;
  onOpenInviteManager?: () => void;
  onClose: () => void;
};

const STATUS_FILTERS: Array<{ id: StatusFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "unread", label: "未读" },
  { id: "running", label: "运行中" },
  { id: "busy", label: "处理中" },
  { id: "offline", label: "离线" },
];

function isOffline(bot: BotSummary) {
  return bot.serviceStatus === "offline" || bot.status === "offline";
}

function effectiveStatus(bot: BotSummary): BotStatus {
  if (isOffline(bot)) {
    return "offline";
  }
  if (bot.status === "unread") {
    return "unread";
  }
  if (bot.status === "busy" || bot.activityStatus === "busy" || (bot.busyAgentCount || 0) > 0) {
    return "busy";
  }
  return "running";
}

function botMatchesQuery(bot: BotSummary, query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  const haystack = [
    bot.alias,
    bot.workingDir,
    bot.cliType,
    bot.botMode || "",
    ...(bot.busyAgentNames || []),
  ].join(" ").toLowerCase();
  return haystack.includes(normalized);
}

function resolvePopoverStyle(anchorRect?: DOMRect | null): CSSProperties {
  const viewportWidth = window.innerWidth || 1024;
  const viewportHeight = window.innerHeight || 768;
  const margin = 12;
  const width = Math.min(960, Math.max(520, viewportWidth - margin * 2));
  const preferredLeft = anchorRect?.left ?? margin;
  const preferredTop = (anchorRect?.bottom ?? 44) + 8;
  const left = Math.min(Math.max(margin, preferredLeft), Math.max(margin, viewportWidth - width - margin));
  const top = Math.min(Math.max(margin, preferredTop), Math.max(margin, viewportHeight - 140));
  return {
    left,
    top,
    width,
    maxHeight: "min(72vh, 680px)",
  };
}

function busyNames(bot: BotSummary) {
  const names = bot.busyAgentNames || [];
  if (names.length > 0) {
    return names;
  }
  if ((bot.busyAgentCount || 0) > 0 || bot.activityStatus === "busy" || bot.status === "busy") {
    return ["主 agent"];
  }
  return [];
}

export function DesktopBotSwitcherPopover({
  bots,
  currentAlias,
  anchorRect,
  onSelect,
  onManage,
  showInviteManager = false,
  inviteManagerActive = false,
  onOpenInviteManager,
  onClose,
}: Props) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [focusedAlias, setFocusedAlias] = useState(currentAlias || bots[0]?.alias || "");
  const searchRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());
  const style = useMemo(() => resolvePopoverStyle(anchorRect), [anchorRect]);
  const reduceMotion = useReducedMotion();
  const backdropMotion = resolveMotionProps(premiumMotion.popoverBackdrop, reduceMotion);
  const panelMotion = resolveMotionProps(premiumMotion.anchoredPopover, reduceMotion);
  const detailMotion = resolveMotionProps(premiumMotion.detailSwap, reduceMotion);

  const filteredBots = useMemo(() => bots.filter((bot) => {
    const status = effectiveStatus(bot);
    return (statusFilter === "all" || status === statusFilter) && botMatchesQuery(bot, query);
  }), [bots, query, statusFilter]);

  const focusedBot = filteredBots.find((bot) => bot.alias === focusedAlias)
    || filteredBots.find((bot) => bot.alias === currentAlias)
    || filteredBots[0]
    || null;

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    if (filteredBots.length === 0) {
      setFocusedAlias("");
      return;
    }
    if (!filteredBots.some((bot) => bot.alias === focusedAlias)) {
      setFocusedAlias(
        filteredBots.find((bot) => bot.alias === currentAlias)?.alias
        || filteredBots[0].alias,
      );
    }
  }, [currentAlias, filteredBots, focusedAlias]);

  function focusBot(alias: string) {
    setFocusedAlias(alias);
    window.requestAnimationFrame(() => {
      itemRefs.current.get(alias)?.focus();
    });
  }

  async function selectBot(bot: BotSummary | null) {
    if (!bot || isOffline(bot)) {
      return;
    }
    const shouldClose = await onSelect(bot.alias);
    if (shouldClose !== false) {
      onClose();
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (filteredBots.length === 0) {
        return;
      }
      event.preventDefault();
      const currentIndex = Math.max(0, filteredBots.findIndex((bot) => bot.alias === focusedAlias));
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = (currentIndex + delta + filteredBots.length) % filteredBots.length;
      focusBot(filteredBots[nextIndex].alias);
      return;
    }
    if (event.key === "Enter" && document.activeElement === searchRef.current) {
      event.preventDefault();
      void selectBot(focusedBot);
    }
  }

  function setItemRef(alias: string) {
    return (node: HTMLButtonElement | null) => {
      if (node) {
        itemRefs.current.set(alias, node);
      } else {
        itemRefs.current.delete(alias);
      }
    };
  }

  function copyWorkdir() {
    if (!focusedBot?.workingDir) {
      return;
    }
    void navigator.clipboard?.writeText(focusedBot.workingDir);
  }

  const filteredCountText = query || statusFilter !== "all"
    ? `${filteredBots.length} / ${bots.length}`
    : `${bots.length}`;

  return (
    <div className="fixed inset-0 z-50" onKeyDown={handleKeyDown}>
      <motion.div className="absolute inset-0 bg-black/20" onClick={onClose} {...backdropMotion} />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="智能体切换"
        data-testid="desktop-bot-switcher-popover"
        className="absolute flex min-h-[360px] origin-top-left flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl"
        style={style}
        {...panelMotion}
      >
        <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted)]" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索智能体、目录、agent"
              aria-label="搜索智能体"
              className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--bg)] pl-8 pr-3 text-sm outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div className="inline-flex shrink-0 rounded-md border border-[var(--border)] bg-[var(--surface-strong)] p-0.5">
            {STATUS_FILTERS.map((filter) => (
              <button
                key={filter.id}
                type="button"
                aria-pressed={statusFilter === filter.id}
                onClick={() => setStatusFilter(filter.id)}
                className={clsx(
                  "h-8 rounded px-2 text-xs",
                  statusFilter === filter.id
                    ? "bg-[var(--accent)] text-white"
                    : "text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--text)]",
                )}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <span className="w-12 text-right text-xs text-[var(--muted)]">{filteredCountText}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭智能体切换"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-[var(--surface-strong)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
          <div className="min-h-0 overflow-y-auto border-r border-[var(--border)] p-2">
            {filteredBots.length === 0 ? (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
                没有匹配的智能体
              </div>
            ) : filteredBots.map((bot) => {
              const offline = isOffline(bot);
              const status = effectiveStatus(bot);
              const current = bot.alias === currentAlias;
              return (
                <button
                  key={bot.alias}
                  ref={setItemRef(bot.alias)}
                  type="button"
                  aria-current={current ? "true" : undefined}
                  aria-disabled={offline}
                  onFocus={() => setFocusedAlias(bot.alias)}
                  onMouseEnter={() => setFocusedAlias(bot.alias)}
                  onClick={() => void selectBot(bot)}
                  className={clsx(
                    "mb-1 grid w-full grid-cols-[32px_minmax(0,1fr)_auto] items-center gap-3 rounded-md border px-2.5 py-2 text-left",
                    "focus:outline-none focus:ring-2 focus:ring-[var(--accent)]",
                    current ? "border-[var(--accent)] bg-[var(--accent)]/5" : "border-transparent hover:bg-[var(--surface-strong)]",
                    focusedAlias === bot.alias && !current ? "bg-[var(--surface-strong)]" : "",
                    offline ? "cursor-not-allowed opacity-70" : "",
                  )}
                >
                  <ChatAvatar alt={`${bot.alias} 头像`} avatarName={bot.avatarName} kind="bot" size={32} />
                  <span className="min-w-0">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-sm font-semibold text-[var(--text)]">{bot.alias}</span>
                      {bot.isMain || bot.alias === "main" ? (
                        <span className="rounded border border-[var(--border)] px-1 text-[10px] text-[var(--muted)]">主</span>
                      ) : null}
                      {current ? (
                        <span className="rounded border border-[var(--accent)] px-1 text-[10px] text-[var(--accent)]">当前</span>
                      ) : null}
                      {bot.canOperate === false ? (
                        <span className="rounded border border-[var(--border)] px-1 text-[10px] text-[var(--muted)]">只读</span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-[var(--muted)]">
                      <span className="shrink-0">{bot.botMode || "cli"} · {bot.cliType}</span>
                      <span className="truncate" title={bot.workingDir}>{bot.workingDir}</span>
                    </span>
                    <BotActivitySummary bot={bot} className="mt-0.5" />
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    {status === "unread" ? <StatusPill status="unread" /> : null}
                    <StatusPill status={status === "unread" ? "online" : status} />
                  </span>
                </button>
              );
            })}
          </div>

          <aside className="min-h-0 overflow-y-auto bg-[var(--surface-strong)] p-3">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={focusedBot?.alias || "empty"}
                data-testid="desktop-bot-switcher-detail"
                className="min-h-0"
                {...detailMotion}
              >
                {focusedBot ? (
                  <div className="space-y-3">
                    <div className="flex items-start gap-3">
                      <ChatAvatar alt={`${focusedBot.alias} 头像`} avatarName={focusedBot.avatarName} kind="bot" size={40} />
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <h2 className="truncate text-base font-semibold text-[var(--text)]">智能体切换</h2>
                          <StatusPill status={effectiveStatus(focusedBot) === "unread" ? "online" : effectiveStatus(focusedBot)} />
                        </div>
                        <div className="mt-1 truncate text-sm font-medium text-[var(--text)]">{focusedBot.alias}</div>
                        <div className="text-xs text-[var(--muted)]">{focusedBot.botMode || "cli"} · {focusedBot.cliType}</div>
                      </div>
                    </div>

                    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-2">
                      <div className="text-xs font-medium text-[var(--muted)]">工作目录</div>
                      <div className="mt-1 break-all font-mono text-xs text-[var(--text)]">{focusedBot.workingDir}</div>
                    </div>

                    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-2">
                      <div className="text-xs font-medium text-[var(--muted)]">状态</div>
                      <div className="mt-1 text-sm text-[var(--text)]">{getBotActivityText(focusedBot)}</div>
                      {busyNames(focusedBot).length > 0 ? (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {busyNames(focusedBot).slice(0, 3).map((name) => (
                            <span key={name} className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                              {name}
                            </span>
                          ))}
                          {busyNames(focusedBot).length > 3 ? (
                            <span className="rounded border border-[var(--border)] px-1.5 py-0.5 text-xs text-[var(--muted)]">
                              +{busyNames(focusedBot).length - 3}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </div>

                    {isOffline(focusedBot) ? (
                      <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-xs font-medium text-red-700">
                        离线中，暂不可切换
                      </div>
                    ) : null}

                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        aria-disabled={isOffline(focusedBot)}
                        onClick={() => void selectBot(focusedBot)}
                        className={clsx(
                          "inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white",
                          isOffline(focusedBot) ? "cursor-not-allowed opacity-60" : "",
                        )}
                      >
                        {focusedBot.alias === currentAlias ? <CheckCircle2 className="h-4 w-4" /> : <LogIn className="h-4 w-4" />}
                        {focusedBot.alias === currentAlias ? "当前" : "进入"}
                      </button>
                      <button
                        type="button"
                        onClick={copyWorkdir}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm font-medium hover:bg-[var(--surface-strong)]"
                      >
                        <Copy className="h-4 w-4" />
                        复制目录
                      </button>
                      <button
                        type="button"
                        onClick={onManage}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm font-medium hover:bg-[var(--surface-strong)]"
                      >
                        <Settings className="h-4 w-4" />
                        智能体管理
                      </button>
                      {showInviteManager ? (
                        <button
                          type="button"
                          onClick={onOpenInviteManager}
                          className={clsx(
                            "inline-flex h-9 items-center justify-center gap-1.5 rounded-md border px-3 text-sm font-medium hover:bg-[var(--surface-strong)]",
                            inviteManagerActive ? "border-[var(--accent)] bg-[var(--accent)]/5" : "border-[var(--border)] bg-[var(--surface)]",
                          )}
                        >
                          <ShieldCheck className="h-4 w-4" />
                          管理中心
                        </button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </motion.div>
            </AnimatePresence>
          </aside>
        </div>
      </motion.div>
    </div>
  );
}
