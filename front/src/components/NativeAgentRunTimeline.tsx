import { useMemo, useState } from "react";
import { AlertTriangle, Brain, Check, ChevronDown, ChevronRight, LoaderCircle, ShieldQuestion, Wrench, X } from "lucide-react";
import type { AgUiPermissionRequest, AgUiRunState, AgUiToolCallItem } from "../utils/agUiRunReducer";

type Props = {
  state: AgUiRunState;
  onReplyPermission?: (permissionId: string, approved: boolean) => Promise<void>;
};

function isPendingPermission(permission: AgUiPermissionRequest) {
  const state = permission.state.trim().toLowerCase();
  return !state || (
    !state.includes("replied")
    && !state.includes("approved")
    && !state.includes("reject")
    && !state.includes("denied")
    && !state.includes("allow")
  );
}

function compactText(value: string, fallback = "") {
  const text = value.trim();
  if (!text) {
    return fallback;
  }
  return text.length > 1200 ? `${text.slice(0, 1200)}...` : text;
}

function ToolCallCard({ tool }: { tool: AgUiToolCallItem }) {
  const hasArgs = Boolean(tool.argsText.trim());
  const hasResult = Boolean(tool.resultText.trim());
  return (
    <section data-testid="native-agent-tool-call" className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2 text-sm font-medium text-[var(--text)]">
          <Wrench className="h-4 w-4 shrink-0 text-[var(--accent)]" />
          <span className="truncate">{tool.toolCallName || "tool"}</span>
        </div>
        <span className="shrink-0 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
          {tool.status === "completed" ? "完成" : "运行中"}
        </span>
      </div>
      {hasArgs ? (
        <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-950 px-3 py-2 text-xs leading-5 text-slate-100">
          {compactText(tool.argsText)}
        </pre>
      ) : null}
      {hasResult ? (
        <div className="mt-3 rounded-lg border border-[var(--accent-outline)] bg-[var(--accent-soft)] px-3 py-2 text-sm text-[var(--text)]">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--accent)]">返回</div>
          <div className="mt-1 whitespace-pre-wrap break-all">{compactText(tool.resultText)}</div>
        </div>
      ) : null}
    </section>
  );
}

export function NativeAgentRunTimeline({ state, onReplyPermission }: Props) {
  const [replyingPermissionId, setReplyingPermissionId] = useState("");
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const visibleActivities = useMemo(() => (
    state.activities.filter((activity) => activity.activityType !== "TCB_PERMISSION_REQUEST" && activity.summary.trim())
  ), [state.activities]);
  const pendingPermissions = state.permissionRequests.filter(isPendingPermission);
  const hasTimeline = (
    visibleActivities.length > 0
    || state.reasoning.some((item) => item.text.trim())
    || state.toolCalls.length > 0
    || state.permissionRequests.length > 0
    || Boolean(state.error)
  );

  if (!hasTimeline) {
    return null;
  }

  const replyPermission = async (permissionId: string, approved: boolean) => {
    if (!onReplyPermission || replyingPermissionId) {
      return;
    }
    setReplyingPermissionId(permissionId);
    try {
      await onReplyPermission(permissionId, approved);
    } finally {
      setReplyingPermissionId("");
    }
  };

  return (
    <section data-testid="native-agent-run-timeline" className="mt-2 space-y-2 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-3 py-3 shadow-[var(--shadow-soft)]">
      {visibleActivities.map((activity) => (
        <div key={`${activity.activityType}-${activity.id}`} className="flex items-center gap-2 text-sm text-[var(--muted)]">
          {state.running ? <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-[var(--accent)]" /> : <Check className="h-4 w-4 shrink-0 text-[var(--accent)]" />}
          <span className="min-w-0 truncate">{activity.summary}</span>
        </div>
      ))}

      {state.reasoning.some((item) => item.text.trim()) ? (
        <section className="rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] px-3 py-2">
          <button
            type="button"
            aria-expanded={reasoningOpen}
            onClick={() => setReasoningOpen((value) => !value)}
            className="flex w-full items-center gap-2 text-left text-sm font-medium text-[var(--text)]"
          >
            {reasoningOpen ? <ChevronDown className="h-4 w-4 text-[var(--muted)]" /> : <ChevronRight className="h-4 w-4 text-[var(--muted)]" />}
            <Brain className="h-4 w-4 text-[var(--accent)]" />
            <span>思考</span>
          </button>
          {reasoningOpen ? (
            <div className="mt-2 space-y-2 text-sm text-[var(--text)]">
              {state.reasoning.filter((item) => item.text.trim()).map((item) => (
                <div key={item.messageId} className="whitespace-pre-wrap break-all rounded-lg bg-[var(--workbench-panel-elevated-bg)] px-3 py-2">
                  {compactText(item.text)}
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {state.toolCalls.map((tool) => (
        <ToolCallCard key={tool.toolCallId} tool={tool} />
      ))}

      {state.permissionRequests.map((permission) => {
        const pending = isPendingPermission(permission);
        return (
          <section key={permission.permissionId} data-testid="native-agent-permission" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-amber-900">
            <div className="flex items-start gap-2">
              <ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{permission.summary || "权限请求"}</div>
                <div className="mt-1 text-xs text-amber-800">{pending ? "等待权限处理" : "权限已处理"}</div>
              </div>
            </div>
            {pending && onReplyPermission ? (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={Boolean(replyingPermissionId)}
                  onClick={() => void replyPermission(permission.permissionId, true)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--accent-outline)] bg-white px-2.5 text-xs font-medium text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {replyingPermissionId === permission.permissionId ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  允许一次
                </button>
                <button
                  type="button"
                  disabled={Boolean(replyingPermissionId)}
                  onClick={() => void replyPermission(permission.permissionId, false)}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-red-200 bg-white px-2.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <X className="h-3.5 w-3.5" />
                  拒绝
                </button>
              </div>
            ) : null}
          </section>
        );
      })}

      {state.error ? (
        <section className="rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-red-700">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0">
              <div className="text-sm font-medium">运行异常</div>
              <div className="mt-1 whitespace-pre-wrap break-all text-sm">{state.error.message}</div>
            </div>
          </div>
        </section>
      ) : null}

      {pendingPermissions.length > 0 ? (
        <div className="text-xs text-amber-700">等待权限处理</div>
      ) : null}
    </section>
  );
}
