import { useMemo, useState } from "react";
import { ChatMessageMeta } from "../../components/ChatMessageMeta";
import { ChatPlainTextMessage } from "../../components/ChatPlainTextMessage";
import { ChatTracePanel } from "../../components/ChatTracePanel";
import type { AssistantPatchGenerationStatus, ChatTraceEvent } from "../../services/types";

type Props = {
  proposalId: string;
  createdAt: string;
  status: AssistantPatchGenerationStatus;
  logs: string[];
  trace: ChatTraceEvent[];
  running: boolean;
  error?: string;
};

function joinTranscriptLines(status: AssistantPatchGenerationStatus, logs: string[], error?: string) {
  const blocks: string[] = [];
  if (status.message) {
    blocks.push(status.message);
  }
  if (logs.length > 0) {
    blocks.push(logs.join("\n\n"));
  }
  if (error) {
    blocks.push(error);
  }
  return blocks.join("\n\n").trim();
}

export function PatchGenerationTranscript({
  proposalId,
  createdAt,
  status,
  logs,
  trace,
  running,
  error = "",
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const content = useMemo(() => joinTranscriptLines(status, logs, error), [error, logs, status]);
  const traceCount = trace.length;

  if (!content && traceCount <= 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-start">
        <div className="min-w-0 max-w-[96%] sm:max-w-[90%]">
          <ChatMessageMeta
            name="Patch 生成"
            createdAt={createdAt}
          />
          <div className={error
            ? "min-w-0 overflow-hidden rounded-2xl border border-red-200 bg-red-50 px-4 py-2 text-red-700"
            : "min-w-0 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[var(--text)]"}
          >
            <ChatPlainTextMessage
              content={content || (running ? "正在生成 patch..." : "")}
              className={error ? "text-red-700" : "text-[var(--text)]"}
            />
          </div>
          <ChatTracePanel
            messageId={`assistant-patch-${proposalId}`}
            trace={trace}
            traceCount={traceCount}
            toolCallCount={trace.filter((item) => item.kind === "tool_call").length}
            processCount={trace.filter((item) => item.kind !== "tool_call" && item.kind !== "tool_result").length}
            expanded={expanded}
            onToggleExpanded={() => setExpanded((current) => !current)}
          />
        </div>
      </div>
    </div>
  );
}
