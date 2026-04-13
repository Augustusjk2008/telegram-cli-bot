function previewTail(previewText: string | undefined) {
  const normalized = (previewText || "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "（无预览）";
  }
  return normalized.slice(-48);
}

export function buildResumePrompt(botMode: string | undefined, previewText: string | undefined) {
  const tail = previewTail(previewText);
  if (botMode === "assistant") {
    return `上次异常中断了。你先确认你最后有没有说到这句附近：${tail}。如果没有，请去看 assistant 历史记录和 assistant 相关保存记录，然后继续工作。`;
  }
  return `上次异常中断了。你先确认你最后有没有说到这句附近：${tail}。如果没有，请去看当前这个 CLI 对话的聊天记录，然后继续工作。`;
}

