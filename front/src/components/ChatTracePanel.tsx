import { memo, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ListTree, LoaderCircle } from "lucide-react";
import type { ChatTraceEvent } from "../services/types";
import { ChatToolTraceCard } from "./ChatToolTraceCard";

type Props = {
  messageId: string;
  trace?: ChatTraceEvent[];
  traceCount?: number;
  toolCallCount?: number;
  processCount?: number;
  elapsedSeconds?: number;
  copyLabel?: string;
  onCopy?: () => void;
  isLoading?: boolean;
  loadError?: string;
  onLoadTrace?: () => void;
};

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

function ChatTracePanelInner({
  messageId,
  trace,
  traceCount,
  toolCallCount,
  processCount,
  elapsedSeconds,
  copyLabel,
  onCopy,
  isLoading = false,
  loadError = "",
  onLoadTrace,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const events = trace || [];
  const summary = useMemo(() => ({
    traceCount: typeof traceCount === "number" ? traceCount : events.length,
    toolCallCount: typeof toolCallCount === "number" ? toolCallCount : events.filter((item) => item.kind === "tool_call").length,
    processCount: typeof processCount === "number" ? processCount : events.filter((item) => item.kind !== "tool_call" && item.kind !== "tool_result").length,
  }), [events, processCount, toolCallCount, traceCount]);

  useEffect(() => {
    if (!expanded || events.length > 0 || summary.traceCount <= 0 || isLoading || Boolean(loadError) || !onLoadTrace) {
      return;
    }
    onLoadTrace();
  }, [expanded, events.length, isLoading, loadError, onLoadTrace, summary.traceCount]);

  if (summary.traceCount <= 0) {
    return null;
  }

  const buttonLabel = `${expanded ? "收起" : "展开"}过程详情`;
  const showActions = typeof elapsedSeconds === "number" || Boolean(copyLabel && onCopy);
  let toolIndex = 0;

  return (
    <section
      data-testid={`chat-trace-panel-${messageId}`}
      className="mt-2 rounded-2xl border border-slate-200 bg-slate-50/90 px-3 py-2"
    >
      <button
        type="button"
        aria-label={buttonLabel}
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="flex min-w-0 items-center gap-2">
          {expanded ? <ChevronDown className="h-4 w-4 text-slate-500" /> : <ChevronRight className="h-4 w-4 text-slate-500" />}
          <ListTree className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-medium text-slate-800">{buttonLabel}</span>
        </span>
        <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-[11px] text-slate-600">
          {summary.processCount} 条过程
          {summary.toolCallCount > 0 ? ` · ${summary.toolCallCount} 次工具` : ""}
        </span>
      </button>
      {expanded ? (
        <div className="mt-3 space-y-3">
          {isLoading && events.length === 0 ? (
            <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              <span>正在加载过程详情...</span>
            </div>
          ) : null}
          {!isLoading && loadError && events.length === 0 ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-700">
              <div>{loadError}</div>
              {onLoadTrace ? (
                <button
                  type="button"
                  onClick={onLoadTrace}
                  className="mt-2 inline-flex rounded-full border border-red-200 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
                >
                  重试
                </button>
              ) : null}
            </div>
          ) : null}
          {events.map((event, index) => {
            if (event.kind === "tool_call" || event.kind === "tool_result") {
              if (event.kind === "tool_call") {
                toolIndex += 1;
              }
              return (
                <div key={`${event.kind}-${event.callId || "tool"}-${index}`} data-trace-seq={index}>
                  <ChatToolTraceCard
                    event={event}
                    index={toolIndex}
                  />
                </div>
              );
            }

            return (
              <div
                key={`${event.kind}-${event.rawType || "process"}-${event.summary}-${index}`}
                data-trace-seq={index}
                className="rounded-2xl border border-slate-200 bg-white px-3 py-2"
              >
                <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
                  {describeProcessEvent(event)}
                </div>
                <div className="mt-1 whitespace-pre-wrap break-all text-sm text-slate-800">
                  {event.summary || "无摘要"}
                </div>
              </div>
            );
          })}
          {showActions ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-2">
              {typeof elapsedSeconds === "number" ? (
                <div className="text-xs text-slate-600">用时 {elapsedSeconds} 秒</div>
              ) : null}
              {copyLabel && onCopy ? (
                <button
                  type="button"
                  onClick={onCopy}
                  className="ml-auto inline-flex rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  {copyLabel}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export const ChatTracePanel = memo(ChatTracePanelInner);
