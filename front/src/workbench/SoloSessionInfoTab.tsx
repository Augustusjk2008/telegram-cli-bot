import type { SoloSessionSnapshot } from "./soloTypes";

type Props = {
  snapshot: SoloSessionSnapshot | null;
};

function shortId(value: string) {
  const normalized = value.trim();
  if (!normalized) return "无";
  return normalized.length > 12 ? `${normalized.slice(0, 8)}...${normalized.slice(-4)}` : normalized;
}

function basename(path: string) {
  const parts = path.trim().split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path || "无";
}

function looksLikePath(value: string) {
  const normalized = value.trim();
  if (!/[\\/]/.test(normalized)) {
    return false;
  }
  return (
    /[A-Za-z]:[\\/]/.test(normalized)
    || /(^|\s|["'`])\.{1,2}[\\/]/.test(normalized)
    || /(^|\s|["'`])[~/][^ \t\r\n]+[\\/]/.test(normalized)
    || /[^ \t\r\n]+[\\/][^ \t\r\n]+/.test(normalized)
  );
}

function sanitizeDegradedReason(reason: string) {
  if (looksLikePath(reason)) {
    return "会话历史降级，详情见后端诊断";
  }
  return reason || "未知";
}

function field(label: string, value: string) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3 border-b border-[var(--workbench-hairline)] px-4 py-3 text-sm last:border-b-0">
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd className="min-w-0 truncate font-medium text-[var(--text)]" title={value}>{value || "无"}</dd>
    </div>
  );
}

export function SoloSessionInfoTab({ snapshot }: Props) {
  if (!snapshot) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-sm text-[var(--muted)]">
        会话信息加载中...
      </div>
    );
  }

  return (
    <div data-testid="solo-session-info-tab" className="h-full min-h-0 overflow-y-auto">
      <dl>
        {field("Bot", snapshot.botAlias)}
        {field("会话", `${snapshot.conversationTitle || "当前会话"} (${shortId(snapshot.conversationId)})`)}
        {field("工作区", basename(snapshot.workingDir))}
        {field("模型", snapshot.model)}
        {field("原生会话", shortId(snapshot.nativeSessionId))}
        {field("线性序号", String(snapshot.linearIndex || 0))}
        {field("历史 Head", shortId(snapshot.workspaceHistoryHead))}
        {field("上下文", snapshot.contextStatusText)}
        {field("回滚", snapshot.rollbackSupported ? "可用" : "不可用")}
        {snapshot.degraded ? field("降级原因", sanitizeDegradedReason(snapshot.degradedReason)) : null}
      </dl>
    </div>
  );
}
