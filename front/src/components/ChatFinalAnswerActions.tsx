import { useEffect, useRef, useState } from "react";
import { CheckCheck, ClipboardList, Copy, Gauge } from "lucide-react";
import type { ChatMessageContextUsage } from "../services/types";
import { copyText } from "../utils/clipboard";
import { ChatContextUsageBadge, formatContextUsageDetails } from "./ChatContextUsageBadge";

type Props = {
  contextUsage?: ChatMessageContextUsage;
  fullAnswerText?: string;
  onCopyFinalAnswer?: () => boolean | void | Promise<boolean | void>;
};

export function ChatFinalAnswerActions({ contextUsage, fullAnswerText, onCopyFinalAnswer }: Props) {
  const [copiedFinalAnswer, setCopiedFinalAnswer] = useState(false);
  const [copiedContextUsage, setCopiedContextUsage] = useState(false);
  const [copiedFullAnswer, setCopiedFullAnswer] = useState(false);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const contextCopyFeedbackTimerRef = useRef<number | null>(null);
  const fullAnswerCopyFeedbackTimerRef = useRef<number | null>(null);
  const contextDetails = formatContextUsageDetails(contextUsage);
  const fullAnswer = (fullAnswerText || "").trim();

  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
    if (contextCopyFeedbackTimerRef.current !== null) {
      window.clearTimeout(contextCopyFeedbackTimerRef.current);
    }
    if (fullAnswerCopyFeedbackTimerRef.current !== null) {
      window.clearTimeout(fullAnswerCopyFeedbackTimerRef.current);
    }
  }, []);

  if (!onCopyFinalAnswer && !contextDetails && !fullAnswer) {
    return null;
  }

  const copyFinalAnswer = async () => {
    if (!onCopyFinalAnswer || copiedFinalAnswer) {
      return;
    }
    const result = await onCopyFinalAnswer();
    if (result === false) {
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

  const copyContextUsage = async () => {
    if (!contextDetails || copiedContextUsage) {
      return;
    }
    const ok = await copyText(contextDetails);
    if (!ok) {
      return;
    }
    setCopiedContextUsage(true);
    if (contextCopyFeedbackTimerRef.current !== null) {
      window.clearTimeout(contextCopyFeedbackTimerRef.current);
    }
    contextCopyFeedbackTimerRef.current = window.setTimeout(() => {
      setCopiedContextUsage(false);
      contextCopyFeedbackTimerRef.current = null;
    }, 2000);
  };

  const copyFullAnswer = async () => {
    if (!fullAnswer || copiedFullAnswer) {
      return;
    }
    const ok = await copyText(fullAnswer);
    if (!ok) {
      return;
    }
    setCopiedFullAnswer(true);
    if (fullAnswerCopyFeedbackTimerRef.current !== null) {
      window.clearTimeout(fullAnswerCopyFeedbackTimerRef.current);
    }
    fullAnswerCopyFeedbackTimerRef.current = window.setTimeout(() => {
      setCopiedFullAnswer(false);
      fullAnswerCopyFeedbackTimerRef.current = null;
    }, 2000);
  };

  return (
    <div className="mt-2 flex flex-wrap items-center justify-end gap-1.5">
      <ChatContextUsageBadge
        contextUsage={contextUsage}
        preferLeft
        testId="chat-message-context-usage-bottom"
        className="max-w-full truncate text-[11px]"
      />
      {contextDetails ? (
        <button
          type="button"
          aria-label={copiedContextUsage ? "已复制上下文详情" : "复制上下文详情"}
          title={copiedContextUsage ? "已复制上下文详情" : "复制上下文详情"}
          disabled={copiedContextUsage}
          onClick={() => void copyContextUsage()}
          className={copiedContextUsage
            ? "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] disabled:cursor-not-allowed"
            : "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}
        >
          {copiedContextUsage ? <CheckCheck className="h-3.5 w-3.5" /> : <Gauge className="h-3.5 w-3.5" />}
        </button>
      ) : null}
      {fullAnswer ? (
        <button
          type="button"
          aria-label={copiedFullAnswer ? "已复制完整回答" : "复制完整回答"}
          title={copiedFullAnswer ? "已复制完整回答" : "复制完整回答"}
          disabled={copiedFullAnswer}
          onClick={() => void copyFullAnswer()}
          className={copiedFullAnswer
            ? "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] disabled:cursor-not-allowed"
            : "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}
        >
          {copiedFullAnswer ? <CheckCheck className="h-3.5 w-3.5" /> : <ClipboardList className="h-3.5 w-3.5" />}
        </button>
      ) : null}
      {onCopyFinalAnswer ? (
        <button
          type="button"
          aria-label={copiedFinalAnswer ? "已复制最终回答" : "复制最终回答"}
          title={copiedFinalAnswer ? "已复制最终回答" : "复制最终回答"}
          disabled={copiedFinalAnswer}
          onClick={() => void copyFinalAnswer()}
          className={copiedFinalAnswer
            ? "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] disabled:cursor-not-allowed"
            : "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"}
        >
          {copiedFinalAnswer ? <CheckCheck className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      ) : null}
    </div>
  );
}
