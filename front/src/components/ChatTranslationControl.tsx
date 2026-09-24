import { useState } from "react";
import { Languages, LoaderCircle, RotateCcw } from "lucide-react";
import type { ChatMessage } from "../services/types";

const translationFailureReasons: Record<string, string> = {
  timeout: "翻译请求超时",
  translation_skipped: "翻译模型跳过了本次翻译",
  translation_failed: "翻译模型报告翻译失败",
  cancelled: "翻译已取消",
  interrupted: "翻译任务已中断",
  service_closed: "翻译服务已关闭",
  invalid_config: "翻译服务配置不完整或无效",
  empty_source: "原文为空，无需翻译",
  authentication_error: "翻译服务认证失败",
  http_error: "翻译服务返回请求错误",
  network_error: "无法连接翻译服务",
  invalid_response: "翻译服务返回的内容格式无效",
  empty_response: "翻译服务未返回译文",
  truncated: "译文因长度限制被截断",
  protected_content_mismatch: "译文未完整保留代码、路径等受保护内容",
  translation_error: "翻译服务发生内部错误",
};

export function ChatTranslationControl({ item, onChange, onRetry }: {
  item: ChatMessage;
  onChange: (view: "original" | "translated") => void;
  onRetry?: () => Promise<void>;
}) {
  const [retrying, setRetrying] = useState(false);
  const translation = item.translation;
  if (!translation) return null;
  const available = translation.status === "completed" && Boolean(translation.text?.trim());
  const canRetry = item.role === "assistant" && translation.status === "failed" && Boolean(onRetry);
  const translated = available && item.translationView !== "original";
  const label = available
    ? translated ? "显示原文" : "显示译文"
    : translation.status === "pending" ? "译文待更新，当前为原文" : "翻译未完成，显示原文";
  const reason = translation.status === "pending"
    ? "翻译正在进行中"
    : translationFailureReasons[translation.error ?? ""]
      ?? (translation.status === "completed" ? "翻译服务未返回译文" : "未提供具体原因");
  const tooltip = canRetry ? `重试翻译：${reason}` : available ? label : `${label}：${reason}`;
  return (
    <span title={tooltip} className={`inline-flex ${available || canRetry ? "" : "cursor-not-allowed"}`}>
      <button
        type="button"
        aria-label={tooltip}
        title={tooltip}
        aria-pressed={translated}
        disabled={(!available && !canRetry) || retrying}
        onClick={() => {
          if (canRetry && onRetry) {
            setRetrying(true);
            void onRetry().finally(() => setRetrying(false));
          } else {
            onChange(translated ? "original" : "translated");
          }
        }}
        className={`inline-flex h-6 w-6 items-center justify-center rounded-md border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 ${translated
          ? "border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] hover:bg-[var(--workbench-hover-bg)]"
          : "border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}`}
      >
        {translation.status === "pending" || retrying
          ? <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
          : canRetry ? <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
          : <Languages aria-hidden="true" className="h-3.5 w-3.5" />}
      </button>
    </span>
  );
}
