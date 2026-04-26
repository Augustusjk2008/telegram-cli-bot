import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import type { ChatTraceEvent } from "../services/types";
import { type ToolGroupChatTraceEntry, parseToolResultStatus } from "../utils/chatTraceGrouping";
import { CHAT_TRACE_PREVIEW_CONFIG } from "../utils/chatTracePreview";

type Props = {
  entry: ToolGroupChatTraceEntry;
};

const EMPTY_RENDERED_VALUES = new Set(["", "{}", "[]", "\"\"", "null", "undefined"]);
const MAX_PREVIEW_LINES = CHAT_TRACE_PREVIEW_CONFIG.maxLines;
const MAX_PREVIEW_CHARS = CHAT_TRACE_PREVIEW_CONFIG.maxChars;

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

function collapseText(value: string, maxLines = MAX_PREVIEW_LINES, maxChars = MAX_PREVIEW_CHARS) {
  const lines = value.split(/\r?\n/);
  let truncated = false;
  let preview = value;

  if (lines.length > maxLines) {
    preview = lines.slice(0, maxLines).join("\n");
    truncated = true;
  }

  if (preview.length > maxChars) {
    preview = preview.slice(0, maxChars);
    truncated = true;
  }

  if (!truncated) {
    return { text: value, truncated: false };
  }

  return { text: `${preview}...`, truncated: true };
}

function toneClasses(tone: "neutral" | "success" | "error") {
  if (tone === "success") {
    return {
      container: "border-emerald-200 bg-emerald-50/80",
      badge: "border-emerald-200 bg-emerald-100 text-emerald-700",
      text: "text-emerald-900",
    };
  }
  if (tone === "error") {
    return {
      container: "border-red-200 bg-red-50/80",
      badge: "border-red-200 bg-red-100 text-red-700",
      text: "text-red-900",
    };
  }
  return {
    container: "border-sky-200 bg-sky-50/80",
    badge: "border-sky-200 bg-sky-100 text-sky-700",
    text: "text-sky-900",
  };
}

function ToolResultSection({ event, index, total }: { event: ChatTraceEvent; index: number; total: number }) {
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [rawExpanded, setRawExpanded] = useState(false);
  const payloadText = useMemo(() => renderPayload(event.payload), [event.payload]);
  const summary = useMemo(() => resolveSummary(event, payloadText), [event, payloadText]);
  const collapsedSummary = useMemo(() => collapseText(summary), [summary]);
  const renderedSummary = summaryExpanded || !collapsedSummary.truncated ? summary : collapsedSummary.text;
  const showRawPayload = isMeaningfulRenderedValue(payloadText) && payloadText.trim() !== summary.trim();
  const parsedStatus = useMemo(() => parseToolResultStatus(`${summary}\n${payloadText}`), [payloadText, summary]);
  const tones = toneClasses(parsedStatus.tone);
  const label = total > 1 ? `返回 ${index + 1}` : "返回";

  return (
    <div className={`rounded-xl border px-3 py-3 ${tones.container}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">{label}</div>
        <div className="flex flex-wrap items-center gap-2">
          {typeof parsedStatus.exitCode === "number" ? (
            <span className={`rounded-full border px-2 py-0.5 text-[11px] ${tones.badge}`}>
              Exit {parsedStatus.exitCode}
            </span>
          ) : typeof parsedStatus.success === "boolean" ? (
            <span className={`rounded-full border px-2 py-0.5 text-[11px] ${tones.badge}`}>
              {parsedStatus.success ? "成功" : "失败"}
            </span>
          ) : null}
          {parsedStatus.wallTime ? (
            <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600">
              {parsedStatus.wallTime}
            </span>
          ) : null}
        </div>
      </div>
      <div className={`mt-2 whitespace-pre-wrap break-all text-sm ${tones.text}`}>
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
      {showRawPayload ? (
        <div className="mt-3">
          <button
            type="button"
            aria-label={`${rawExpanded ? "收起" : "展开"}${label}原始内容`}
            aria-expanded={rawExpanded}
            onClick={() => setRawExpanded((prev) => !prev)}
            className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900"
          >
            {rawExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <span>{rawExpanded ? "收起原始内容" : "展开原始内容"}</span>
          </button>
          {rawExpanded ? (
            <pre className="mt-2 overflow-x-auto rounded-xl bg-slate-950 px-3 py-2 text-xs leading-5 text-slate-100">
              {payloadText}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function ChatToolTraceCard({ entry }: Props) {
  const [callSummaryExpanded, setCallSummaryExpanded] = useState(false);
  const [callRawExpanded, setCallRawExpanded] = useState(false);
  const callPayloadText = useMemo(() => (entry.call ? renderPayload(entry.call.payload) : ""), [entry.call]);
  const callSummary = useMemo(() => (entry.call ? resolveSummary(entry.call, callPayloadText) : ""), [callPayloadText, entry.call]);
  const collapsedCallSummary = useMemo(() => collapseText(callSummary), [callSummary]);
  const renderedCallSummary = callSummaryExpanded || !collapsedCallSummary.truncated ? callSummary : collapsedCallSummary.text;
  const showCallRawPayload = Boolean(entry.call) && isMeaningfulRenderedValue(callPayloadText) && callPayloadText.trim() !== callSummary.trim();
  const toolName = entry.call?.toolName || entry.call?.title || entry.results[0]?.toolName || entry.results[0]?.title || "";
  const label = entry.call ? `工具调用 ${entry.toolIndex}` : "工具返回（未匹配）";

  return (
    <section className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
            <Wrench className="h-3.5 w-3.5" />
            <span>{label}</span>
          </div>
        </div>
        {toolName ? (
          <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
            {toolName}
          </span>
        ) : null}
      </div>

      {entry.call ? (
        <div className="mt-3 rounded-xl border border-b-0 border-slate-200 bg-slate-50/70 px-3 py-3">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">调用</div>
          <div className="mt-2 whitespace-pre-wrap break-all text-sm text-slate-900">{renderedCallSummary}</div>
          {collapsedCallSummary.truncated ? (
            <button
              type="button"
              onClick={() => setCallSummaryExpanded((prev) => !prev)}
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900"
            >
              {callSummaryExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              <span>{callSummaryExpanded ? "收起完整内容" : "展开完整内容"}</span>
            </button>
          ) : null}
          {showCallRawPayload ? (
            <div className="mt-3">
              <button
                type="button"
                aria-label={`${callRawExpanded ? "收起" : "展开"}调用原始内容`}
                aria-expanded={callRawExpanded}
                onClick={() => setCallRawExpanded((prev) => !prev)}
                className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900"
              >
                {callRawExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                <span>{callRawExpanded ? "收起原始内容" : "展开原始内容"}</span>
              </button>
              {callRawExpanded ? (
                <pre className="mt-2 overflow-x-auto rounded-xl bg-slate-950 px-3 py-2 text-xs leading-5 text-slate-100">
                  {callPayloadText}
                </pre>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        {entry.results.length > 0 ? (
          entry.results.map((result, index) => (
            <ToolResultSection
              key={`${result.callId || "result"}-${index}-${result.summary}`}
              event={result}
              index={index}
              total={entry.results.length}
            />
          ))
        ) : (
          <div className="rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-3 text-sm text-amber-800">
            <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-amber-700">返回</div>
            <div className="mt-2 font-medium">等待返回</div>
            <div className="mt-1">尚无返回；若工具未完成、会话被终止，或原始 trace 缺失，此处保持 pending。</div>
          </div>
        )}
      </div>
    </section>
  );
}
