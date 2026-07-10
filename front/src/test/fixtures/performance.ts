import type { ChatMessage, GitOverview, PluginRenderResult } from "../../services/types";

export function createChatHistoryFixture(options: { messageCount: number; traceCountPerAssistant?: number; markdownCharacters?: number }): ChatMessage[] {
  const traceCount = options.traceCountPerAssistant || 0;
  const markdown = "x".repeat(options.markdownCharacters || 0);
  return Array.from({ length: options.messageCount }, (_, index) => ({
    id: `fixture-${index}`,
    role: index % 2 === 0 ? "user" : "assistant",
    text: markdown || `消息 ${index}`,
    createdAt: new Date(index * 1000).toISOString(),
    state: "done",
    meta: traceCount && index % 2 ? { trace: Array.from({ length: traceCount }, (_, traceIndex) => ({ kind: "commentary", summary: `trace-${traceIndex}` })) } : undefined,
  }));
}

export function createGitChangesFixture(count: number): GitOverview {
  return {
    repoFound: true,
    canInit: false,
    workingDir: "C:/fixture",
    repoPath: "C:/fixture",
    repoName: "fixture",
    currentBranch: "main",
    isClean: count === 0,
    aheadCount: 0,
    behindCount: 0,
    changedFiles: Array.from({ length: count }, (_, index) => ({ path: `src/file-${index}.ts`, status: "modified", staged: false, unstaged: true, untracked: false, additions: 1, deletions: 0, stagedAdditions: 0, stagedDeletions: 0, unstagedAdditions: 1, unstagedDeletions: 0 })),
    recentCommits: [],
  };
}

export function createPluginTableFixture(rowCount: number): PluginRenderResult {
  return { renderer: "table", pluginId: "fixture", viewId: "fixture-table", title: "性能表格", mode: "snapshot", payload: { columns: [{ id: "name", title: "名称" }], rows: Array.from({ length: rowCount }, (_, index) => ({ id: String(index), cells: { name: `row-${index}` } })), actions: [] } };
}
