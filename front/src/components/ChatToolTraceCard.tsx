import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import type { ChatTraceEvent } from "../services/types";

type Props = {
  event: ChatTraceEvent;
  index: number;
};

const EMPTY_RENDERED_VALUES = new Set(["", "{}", "[]", "\"\"", "null", "undefined"]);
const MAX_PREVIEW_LINES = 5;

function isMeaningfulRenderedValue(value: string) {
  return !EMPTY_RENDERED_VALUES.has(value.trim());
}

function unwrapPayload(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return value;
  }

  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length === 0) {
    return undefined;
  }

  if (keys.every((key) => key === "arguments" || key === "raw_arguments")) {
    return record.arguments;
  }
  if (keys.every((key) => key === "output" || key === "is_error")) {
    return record.output;
  }
  if (keys.every((key) => key === "content" || key === "is_error")) {
    return record.content;
  }

  return value;
}

function renderPayload(value: unknown) {
  const normalized = unwrapPayload(value);
  if (typeof normalized === "undefined" || normalized === null) {
    return "";
  }
  if (typeof normalized === "string") {
    return normalized;
  }
  try {
    return JSON.stringify(normalized, null, 2);
  } catch {
    return String(normalized);
  }
}

function resolveSummary(event: ChatTraceEvent, payloadText = "") {
  const summary = String(event.summary || "").trim();
  if (isMeaningfulRenderedValue(summary)) {
    return summary;
  }
  if (isMeaningfulRenderedValue(payloadText)) {
    return payloadText;
  }
  return event.kind === "tool_call" ? "无参数" : "已返回，无可显示内容";
}

function collapseText(value: string, maxLines = MAX_PREVIEW_LINES) {
  const lines = value.split(/\r?\n/);
  if (lines.length <= maxLines) {
    return { text: value, truncated: false };
  }
  return {
    text: `${lines.slice(0, maxLines).join("\n")}\n...`,
    truncated: true,
  };
}

export function ChatToolTraceCard({ event, index }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const title = event.title || event.toolName || (event.kind === "tool_result" ? "工具返回" : "工具调用");
  const payloadText = useMemo(() => renderPayload(event.payload), [event.payload]);
  const summary = useMemo(() => resolveSummary(event, payloadText), [event, payloadText]);
  const collapsedSummary = useMemo(() => collapseText(summary), [summary]);
  const showPayload = isMeaningfulRenderedValue(payloadText) && payloadText.trim() !== summary.trim();
  const label = event.kind === "tool_call" ? `工具调用 ${index}` : "工具返回";
  const buttonLabel = `${expanded ? "收起" : "展开"}${label}原始内容`;
  const renderedSummary = summaryExpanded || !collapsedSummary.truncated ? summary : collapsedSummary.text;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
            <Wrench className="h-3.5 w-3.5" />
            <span>{label}</span>
          </div>
          <div className="mt-1 text-sm font-medium text-slate-800">{title}</div>
        </div>
        {event.toolName ? (
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
            {event.toolName}
          </span>
        ) : null}
      </div>
      <div className="mt-2 whitespace-pre-wrap break-all text-sm text-slate-800">
        {renderedSummary}
      </div>
      {collapsedSummary.truncated ? (
        <button
          type="button"
          onClick={() => setSummaryExpanded((prev) => !prev)}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900"
        >
          {summaryExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <span>{summaryExpanded ? "收起完整内容" : "展开完整内容"}</span>
        </button>
      ) : null}
      {showPayload ? (
        <div className="mt-3">
          <button
            type="button"
            aria-label={buttonLabel}
            aria-expanded={expanded}
            onClick={() => setExpanded((prev) => !prev)}
            className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900"
          >
            {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <span>{expanded ? "收起原始内容" : "展开原始内容"}</span>
          </button>
          {expanded ? (
            <pre className="mt-2 overflow-x-auto rounded-xl bg-slate-950 px-3 py-2 text-xs leading-5 text-slate-100">
              {payloadText}
            </pre>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
