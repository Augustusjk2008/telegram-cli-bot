import type { ChatTraceEvent } from "../services/types";

export type ToolGroupState = "pending" | "completed" | "orphan_result";

export type ProcessChatTraceEntry = {
  kind: "process";
  event: ChatTraceEvent;
};

export type ToolGroupChatTraceEntry = {
  kind: "tool_group";
  toolIndex: number;
  state: ToolGroupState;
  call: ChatTraceEvent | null;
  results: ChatTraceEvent[];
};

export type ChatTraceEntry = ProcessChatTraceEntry | ToolGroupChatTraceEntry;

export type ParsedToolResultStatus = {
  exitCode?: number;
  wallTime?: string;
  tone: "neutral" | "success" | "error";
};

function parseNumber(value: string | undefined) {
  if (!value) {
    return undefined;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function extractExitCode(text: string) {
  const patterns = [
    /(?:^|\n)\s*Exit code:\s*(-?\d+)/i,
    /\bExit code:\s*(-?\d+)/i,
    /["']?exit[_\s-]*code["']?\s*[:=]\s*(-?\d+)/i,
  ];

  for (const pattern of patterns) {
    const matched = text.match(pattern);
    const parsed = parseNumber(matched?.[1]);
    if (typeof parsed === "number") {
      return parsed;
    }
  }

  return undefined;
}

export function parseToolResultStatus(text: string): ParsedToolResultStatus {
  const normalized = String(text || "");
  const exitCode = extractExitCode(normalized);
  const wallTimeMatch = normalized.match(/(?:^|\n)Wall time:\s*([^\n]+)/i);

  return {
    exitCode,
    wallTime: wallTimeMatch?.[1]?.trim(),
    tone: typeof exitCode !== "number" ? "neutral" : exitCode === 0 ? "success" : "error",
  };
}

export function groupChatTraceEntries(trace: ChatTraceEvent[] | undefined): ChatTraceEntry[] {
  const entries: ChatTraceEntry[] = [];
  const openGroups = new Map<string, number>();
  let toolIndex = 0;

  for (const event of trace || []) {
    if (event.kind === "tool_call") {
      toolIndex += 1;
      const entryIndex = entries.push({
        kind: "tool_group",
        toolIndex,
        state: "pending",
        call: event,
        results: [],
      }) - 1;
      if (event.callId) {
        openGroups.set(event.callId, entryIndex);
      }
      continue;
    }

    if (event.kind === "tool_result") {
      const matchedIndex = event.callId ? openGroups.get(event.callId) : undefined;
      if (typeof matchedIndex === "number") {
        const matchedEntry = entries[matchedIndex];
        if (matchedEntry?.kind === "tool_group") {
          entries[matchedIndex] = {
            ...matchedEntry,
            state: "completed",
            results: [...matchedEntry.results, event],
          };
          continue;
        }
      }

      entries.push({
        kind: "tool_group",
        toolIndex: 0,
        state: "orphan_result",
        call: null,
        results: [event],
      });
      continue;
    }

    entries.push({
      kind: "process",
      event,
    });
  }

  return entries;
}
