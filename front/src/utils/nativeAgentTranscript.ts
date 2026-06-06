import type { ChatMessageMetaInfo, ChatTraceEvent } from "../services/types";
import type { AgUiRunState, NativeAgentTranscriptEntry } from "./agUiRunReducer";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asString(value: unknown) {
  return typeof value === "string" ? value : "";
}

function stringifyValue(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "undefined" || value === null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function payloadText(trace: ChatTraceEvent) {
  const payload = asRecord(trace.payload);
  return (
    stringifyValue(payload.arguments).trim()
    || stringifyValue(payload.raw_arguments).trim()
    || stringifyValue(payload.output).trim()
    || stringifyValue(payload.content).trim()
  );
}

function permissionId(trace: ChatTraceEvent) {
  const payload = asRecord(trace.payload);
  return asString(payload.permissionId || payload.id || payload.permissionID || payload.permission_id).trim();
}

function isPermissionPending(trace: ChatTraceEvent) {
  const payload = asRecord(trace.payload);
  const state = asString(payload.state || payload.status).trim().toLowerCase();
  return !state || (
    !state.includes("replied")
    && !state.includes("approved")
    && !state.includes("reject")
    && !state.includes("denied")
    && !state.includes("allow")
  );
}

function entryKind(trace: ChatTraceEvent): NativeAgentTranscriptEntry["kind"] {
  if (trace.kind === "commentary" || trace.kind === "reasoning" || trace.kind === "status") return "process";
  if (trace.kind === "tool_call") return "tool";
  if (trace.kind === "permission") return "permission";
  if (trace.kind === "error") return "error";
  if (trace.kind === "cancelled") return "cancelled";
  return "event";
}

function entryLabel(kind: NativeAgentTranscriptEntry["kind"], trace: ChatTraceEvent) {
  if (kind === "process") return trace.kind === "reasoning" ? "思考" : "过程";
  if (kind === "tool") return trace.toolName || trace.title || "工具";
  if (kind === "permission") return "权限";
  if (kind === "error") return "错误";
  if (kind === "cancelled") return "已取消";
  return trace.kind === "tool_result" ? "工具结果" : "事件";
}

function traceOrder(trace: ChatTraceEvent, index: number) {
  if (typeof trace.ordinal === "number") return trace.ordinal;
  if (typeof trace.sequence === "number") return trace.sequence;
  return index + 1;
}

function traceToEntry(trace: ChatTraceEvent, index: number): NativeAgentTranscriptEntry {
  const seq = traceOrder(trace, index);
  const kind = entryKind(trace);
  const body = kind === "tool" || trace.kind === "tool_result" ? payloadText(trace) : undefined;
  return {
    id: trace.id || `${trace.kind || "trace"}-${seq}-${index}`,
    seq,
    kind,
    label: entryLabel(kind, trace),
    summary: trace.summary || trace.title || trace.toolName || "",
    body,
    collapsedByDefault: !["process", "permission", "error", "cancelled"].includes(kind),
    trace,
    ...(kind === "permission" ? { permissionId: permissionId(trace), pending: isPermissionPending(trace) } : {}),
  };
}

export function isNativeAgentMessage(meta?: ChatMessageMetaInfo): boolean {
  const provider = String(meta?.nativeSource?.provider || "").trim().toLowerCase();
  return (
    meta?.tracePresentation === "native_agent_flat"
    || provider === "native_agent"
    || provider === "原生 agent"
  );
}

export function buildNativeAgentTranscriptEntries(input: {
  trace?: ChatTraceEvent[];
  agUiState?: AgUiRunState | null;
}): NativeAgentTranscriptEntry[] {
  if (input.agUiState?.entries?.length) {
    return [...input.agUiState.entries].sort((left, right) => left.seq - right.seq);
  }
  return (input.trace || [])
    .map(traceToEntry)
    .sort((left, right) => left.seq - right.seq);
}
