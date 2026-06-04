import { memo, useEffect, useMemo, useRef, useState } from "react";
import { CheckCheck, ChevronDown, ChevronRight, Copy, ListTree, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { delightMotion, delightMotionStagger, premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import type { ChatTraceEvent } from "../services/types";
import { groupChatTraceEntries } from "../utils/chatTraceGrouping";
import { ChatToolTraceCard } from "./ChatToolTraceCard";

type Props = {
  messageId: string;
  trace?: ChatTraceEvent[];
  traceCount?: number;
  toolCallCount?: number;
  processCount?: number;
  expanded: boolean;
  onToggleExpanded: () => void;
  isLoading?: boolean;
  loadError?: string;
  onLoadTrace?: () => void;
  onCopyFinalAnswer?: () => boolean | void | Promise<boolean | void>;
  onReplyNativePermission?: (permissionId: string, approved: boolean) => Promise<void>;
};

function getPayloadRecord(event: ChatTraceEvent): Record<string, unknown> {
  return event.payload && typeof event.payload === "object"
    ? event.payload as Record<string, unknown>
    : {};
}

function getNativePermissionId(event: ChatTraceEvent) {
  if (event.kind !== "permission") {
    return "";
  }
  const payload = getPayloadRecord(event);
  const permissionId = String(payload.id || payload.permissionID || payload.permission_id || "").trim();
  const state = String(payload.state || payload.status || "").trim().toLowerCase();
  if (!permissionId || state.includes("replied")) {
    return "";
  }
  return permissionId;
}

function describeProcessEvent(event: ChatTraceEvent) {
  if (event.kind === "commentary") {
    return "过程";
  }
  if (event.kind === "cancelled") {
    return "已终止";
  }
  if (event.kind === "error") {
    return "异常";
  }
  return "事件";
}

function isGenericProcessEvent(event: ChatTraceEvent) {
  return event.kind !== "commentary" && event.kind !== "cancelled" && event.kind !== "error";
}

function ChatTracePanelInner({
  messageId,
  trace,
  traceCount,
  toolCallCount,
  processCount,
  expanded,
  onToggleExpanded,
  isLoading = false,
  loadError = "",
  onLoadTrace,
  onCopyFinalAnswer,
  onReplyNativePermission,
}: Props) {
  const reduceMotion = useReducedMotion();
  const [copiedFinalAnswer, setCopiedFinalAnswer] = useState(false);
  const [replyingPermissionId, setReplyingPermissionId] = useState("");
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const events = trace || [];
  const summary = useMemo(() => ({
    traceCount: typeof traceCount === "number" ? traceCount : events.length,
    toolCallCount: typeof toolCallCount === "number" ? toolCallCount : events.filter((item) => item.kind === "tool_call").length,
    processCount: typeof processCount === "number" ? processCount : events.filter((item) => item.kind !== "tool_call" && item.kind !== "tool_result").length,
  }), [events, processCount, toolCallCount, traceCount]);
  const groupedEntries = useMemo(() => groupChatTraceEntries(events), [events]);

  useEffect(() => {
    const hasCompleteTrace = events.length > 0 && events.length >= summary.traceCount;
    if (!expanded || hasCompleteTrace || summary.traceCount <= 0 || isLoading || Boolean(loadError) || !onLoadTrace) {
      return;
    }
    onLoadTrace();
  }, [expanded, events.length, isLoading, loadError, onLoadTrace, summary.traceCount]);

  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
  }, []);

  if (summary.traceCount <= 0) {
    return null;
  }

  const buttonLabel = `${expanded ? "收起" : "展开"}过程详情`;
  const copyButtonLabel = copiedFinalAnswer ? "已复制最终回答" : "复制最终回答";
  const handleCopyFinalAnswer = async () => {
    if (!onCopyFinalAnswer || copiedFinalAnswer) {
      return;
    }
    const copyResult = await onCopyFinalAnswer();
    if (copyResult === false) {
      return;
    }
    setCopiedFinalAnswer(true);
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
    copyFeedbackTimerRef.current = window.setTimeout(() => {
      setCopiedFinalAnswer(false);
      copyFeedbackTimerRef.current = null;
    }, 2000);
  };
  const handleReplyNativePermission = async (permissionId: string, approved: boolean) => {
    if (!onReplyNativePermission || replyingPermissionId) {
      return;
    }
    setReplyingPermissionId(permissionId);
    try {
      await onReplyNativePermission(permissionId, approved);
    } finally {
      setReplyingPermissionId("");
    }
  };

  return (
    <section
      data-testid={`chat-trace-panel-${messageId}`}
      className="mt-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-2 shadow-[var(--shadow-soft)]"
    >
      <div className="flex w-full items-center justify-between gap-3">
        <button
          type="button"
          aria-label={buttonLabel}
          aria-expanded={expanded}
          onClick={onToggleExpanded}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          {expanded ? <ChevronDown className="h-4 w-4 shrink-0 text-[var(--muted)]" /> : <ChevronRight className="h-4 w-4 shrink-0 text-[var(--muted)]" />}
          <ListTree className="h-4 w-4 shrink-0 text-[var(--muted)]" />
          <span className="truncate text-sm font-medium text-[var(--text)]">{buttonLabel}</span>
        </button>
        <span className="flex shrink-0 items-center gap-1.5">
          {onCopyFinalAnswer ? (
            <button
              type="button"
              aria-label={copyButtonLabel}
              title={copyButtonLabel}
              disabled={copiedFinalAnswer}
              onClick={(event) => {
                event.stopPropagation();
                void handleCopyFinalAnswer();
              }}
              className={copiedFinalAnswer
                ? "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] transition-colors disabled:cursor-not-allowed"
                : "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] transition-colors hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}
            >
              {copiedFinalAnswer ? <CheckCheck className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
          ) : null}
          <span className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
            {summary.processCount} 条过程
            {summary.toolCallCount > 0 ? ` · ${summary.toolCallCount} 次工具` : ""}
          </span>
        </span>
      </div>
      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.div
            className="mt-3 space-y-3 overflow-hidden"
            {...resolveMotionProps(premiumMotion.tracePanel, reduceMotion)}
          >
            {isLoading && events.length === 0 ? (
              <div className="flex items-center gap-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3 text-sm text-[var(--text)]">
                <LoaderCircle className="h-4 w-4 animate-spin" />
                <span>正在加载过程详情...</span>
              </div>
            ) : null}
            {!isLoading && loadError && events.length === 0 ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-700">
                <div>{loadError}</div>
                {onLoadTrace ? (
                  <button
                    type="button"
                    onClick={onLoadTrace}
                    className="mt-2 inline-flex rounded-md border border-red-200 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
                  >
                    重试
                  </button>
                ) : null}
              </div>
            ) : null}
            {groupedEntries.map((entry, index) => {
              const animateIndex = Math.min(index, delightMotionStagger.maxAnimatedItems - 1);
              const traceItemMotion = resolveMotionProps({
                ...delightMotion.traceItem,
                transition: {
                  ...delightMotion.traceItem.transition,
                  delay: index < delightMotionStagger.maxAnimatedItems ? animateIndex * delightMotionStagger.itemDelaySeconds : 0,
                },
              }, reduceMotion);

              if (entry.kind === "tool_group") {
                return (
                  <motion.div
                    key={`tool-group-${entry.call?.callId || entry.results[0]?.callId || `orphan-${index}`}`}
                    data-trace-seq={index}
                    {...traceItemMotion}
                  >
                    <ChatToolTraceCard entry={entry} />
                  </motion.div>
                );
              }

              const event = entry.event;
              const isGenericEvent = isGenericProcessEvent(event);
              const nativePermissionId = getNativePermissionId(event);
              return (
                <motion.div
                  key={`${event.kind}-${event.rawType || "process"}-${event.summary}-${index}`}
                  data-trace-seq={index}
                  className={isGenericEvent
                    ? "rounded-lg border border-[var(--accent-outline)] bg-[var(--accent-soft)] px-3 py-2"
                    : "rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-2"}
                  {...traceItemMotion}
                >
                  <div
                    className={isGenericEvent
                      ? "text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--accent)]"
                      : "text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--muted)]"}
                  >
                    {describeProcessEvent(event)}
                  </div>
                  <div
                    className={isGenericEvent
                      ? "mt-1 whitespace-pre-wrap break-all text-sm text-[var(--text)]"
                      : "mt-1 whitespace-pre-wrap break-all text-sm text-[var(--text)]"}
                  >
                    {event.summary || "无摘要"}
                  </div>
                  {nativePermissionId && onReplyNativePermission ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={Boolean(replyingPermissionId)}
                        onClick={() => void handleReplyNativePermission(nativePermissionId, true)}
                        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] px-2.5 text-xs font-medium text-[var(--accent)] hover:bg-[var(--workbench-hover-bg)] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {replyingPermissionId === nativePermissionId ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
                        允许一次
                      </button>
                      <button
                        type="button"
                        disabled={Boolean(replyingPermissionId)}
                        onClick={() => void handleReplyNativePermission(nativePermissionId, false)}
                        className="inline-flex h-7 items-center rounded-md border border-red-200 bg-red-50 px-2.5 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        拒绝
                      </button>
                    </div>
                  ) : null}
                </motion.div>
              );
            })}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}

export const ChatTracePanel = memo(ChatTracePanelInner);
