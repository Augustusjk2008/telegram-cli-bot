import { clsx } from "clsx";
import { FileText, GitBranch, GitCompare, Info, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ViewMode } from "../app/layoutMode";
import { FilePreviewSurface } from "../components/FilePreviewSurface";
import { GitScreen } from "../screens/GitScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { FileReadResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getFilePreviewStatusText, withDetectedPreviewKind } from "../utils/filePreview";
import { PaneResizer } from "./PaneResizer";
import { SoloSessionInfoTab } from "./SoloSessionInfoTab";
import type { SoloSessionSnapshot, SoloTab } from "./soloTypes";
import { PANE_RESIZER_SIZE_PX, type ChatWorkbenchStatus, type WorkbenchProductMode } from "./workbenchTypes";
import { WorkbenchHeader } from "./WorkbenchHeader";

type Props = {
  botAlias: string;
  client?: WebBotClient;
  workspaceName: string;
  branchName?: string;
  viewMode: ViewMode;
  hasUnreadOtherBots?: boolean;
  announcementAction?: ReactNode;
  chatPaneContent: ReactNode | ((actions: { requestPreview: (path: string) => void }) => ReactNode);
  sessionSnapshot: SoloSessionSnapshot | null;
  chatStatus?: ChatWorkbenchStatus;
  productMode?: WorkbenchProductMode;
  soloAvailable?: boolean;
  onProductModeChange?: (mode: WorkbenchProductMode) => void;
  onViewModeChange: (viewMode: ViewMode) => void;
  onOpenBotSwitcher: (anchorRect?: DOMRect) => void;
  onLogout: () => void;
};

type PreviewState = {
  loading: boolean;
  error: string;
  result: FileReadResult | null;
};

const MIN_CHAT_WIDTH_PX = 360;
const MIN_TABS_WIDTH_PX = 420;
const DEFAULT_COLUMNS = `minmax(${MIN_CHAT_WIDTH_PX}px, 44%) ${PANE_RESIZER_SIZE_PX}px minmax(${MIN_TABS_WIDTH_PX}px, 1fr)`;

function basename(path: string) {
  const parts = path.trim().split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path || "预览";
}

function clampChatWidth(value: number, containerWidth: number) {
  const maxChatWidth = Math.max(MIN_CHAT_WIDTH_PX, containerWidth - PANE_RESIZER_SIZE_PX - MIN_TABS_WIDTH_PX);
  return Math.min(Math.max(MIN_CHAT_WIDTH_PX, value), maxChatWidth);
}

export function SoloWorkbench({
  botAlias,
  client = new MockWebBotClient(),
  workspaceName,
  branchName = "",
  viewMode,
  hasUnreadOtherBots = false,
  announcementAction,
  chatPaneContent,
  sessionSnapshot,
  chatStatus,
  productMode = "solo",
  soloAvailable = true,
  onProductModeChange,
  onViewModeChange,
  onOpenBotSwitcher,
  onLogout,
}: Props) {
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const resizeStartWidthRef = useRef(0);
  const previewRequestSeqRef = useRef<Record<string, number>>({});
  const [chatWidthPx, setChatWidthPx] = useState<number | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [tabs, setTabs] = useState<SoloTab[]>([
    { id: "session", kind: "session", title: "会话信息" },
    { id: "git", kind: "git-status", title: "Git" },
  ]);
  const [activeTabId, setActiveTabId] = useState("session");
  const [previews, setPreviews] = useState<Record<string, PreviewState>>({});

  const requestPreview = useCallback((path: string) => {
    const nextPath = path.trim();
    if (!nextPath) return;
    const id = `file:${nextPath}`;
    const title = basename(nextPath);
    setTabs((current) => (
      current.some((tab) => tab.id === id)
        ? current
        : [...current, { id, kind: "file-preview", title, path: nextPath, readonly: true }]
    ));
    setActiveTabId(id);
    setPreviews((current) => ({
      ...current,
      [nextPath]: { loading: true, error: "", result: current[nextPath]?.result || null },
    }));
    const requestId = (previewRequestSeqRef.current[nextPath] || 0) + 1;
    previewRequestSeqRef.current[nextPath] = requestId;
    void client.readFile(botAlias, nextPath)
      .then((result) => {
        if (previewRequestSeqRef.current[nextPath] !== requestId) return;
        setPreviews((current) => ({
          ...current,
          [nextPath]: { loading: false, error: "", result: withDetectedPreviewKind(nextPath, result) },
        }));
      })
      .catch((err) => {
        if (previewRequestSeqRef.current[nextPath] !== requestId) return;
        setPreviews((current) => ({
          ...current,
          [nextPath]: {
            loading: false,
            error: err instanceof Error ? err.message : "读取文件失败",
            result: null,
          },
        }));
      });
  }, [botAlias, client]);

  const openGitDiffTab = useCallback(async (path: string, staged: boolean) => {
    const diff = await client.getGitDiff(botAlias, path, staged);
    const id = `git-diff:${staged ? "staged" : "worktree"}:${path}`;
    const title = `${basename(path)}.diff`;
    const diffText = diff.truncated && diff.diff
      ? `${diff.diff}\n\n...[diff truncated]`
      : (diff.diff || "当前没有可显示的差异");
    setTabs((current) => {
      const nextTab: SoloTab = {
        id,
        kind: "git-diff",
        title,
        path,
        staged,
        diffText,
        readonly: true,
        truncated: diff.truncated,
      };
      const index = current.findIndex((tab) => tab.id === id);
      if (index === -1) {
        return [...current, nextTab];
      }
      return current.map((tab) => (tab.id === id ? nextTab : tab));
    });
    setActiveTabId(id);
  }, [botAlias, client]);

  useEffect(() => {
    setTabs([
      { id: "session", kind: "session", title: "会话信息" },
      { id: "git", kind: "git-status", title: "Git" },
    ]);
    setActiveTabId("session");
    setPreviews({});
    previewRequestSeqRef.current = {};
    setChatWidthPx(null);
  }, [botAlias]);

  const columnTemplate = chatWidthPx === null
    ? DEFAULT_COLUMNS
    : `${chatWidthPx}px ${PANE_RESIZER_SIZE_PX}px minmax(${MIN_TABS_WIDTH_PX}px, 1fr)`;
  const activeTab = tabs.find((tab) => tab.id === activeTabId) || tabs[0];
  const resolvedChatPaneContent = useMemo(
    () => (typeof chatPaneContent === "function" ? chatPaneContent({ requestPreview }) : chatPaneContent),
    [chatPaneContent, requestPreview],
  );

  return (
    <div
      data-testid="solo-workbench-root"
      data-resizing={isResizing ? "true" : "false"}
      className="desktop-workbench-root solo-workbench-root grid h-[100dvh] min-h-0 w-full grid-rows-[auto_minmax(0,1fr)_auto]"
    >
      <WorkbenchHeader
        currentBot={botAlias}
        workspaceName={workspaceName}
        branchName={branchName}
        viewMode={viewMode}
        hasUnreadOtherBots={hasUnreadOtherBots}
        announcementAction={announcementAction}
        sidebarVisible
        terminalVisible={false}
        chatVisible
        availableLayoutControls={[]}
        productMode={productMode}
        soloAvailable={soloAvailable}
        onProductModeChange={onProductModeChange}
        onToggleSidebar={() => {}}
        onToggleTerminal={() => {}}
        onToggleChat={() => {}}
        onViewModeChange={onViewModeChange}
        onOpenBotSwitcher={onOpenBotSwitcher}
        onLogout={onLogout}
      />

      <div data-testid="solo-workbench-shell" className="min-h-0 overflow-hidden bg-[var(--workbench-titlebar-bg)]">
        <div
          ref={columnsRef}
          className="grid h-full min-h-0 p-0.5"
          style={{ gridTemplateColumns: columnTemplate }}
        >
          <section data-testid="solo-chat-pane" className="desktop-workbench-pane min-h-0 overflow-hidden">
            {resolvedChatPaneContent}
          </section>

          <PaneResizer
            ariaLabel="调整 Solo 分栏宽度"
            axis="x"
            onResizeStart={() => {
              setIsResizing(true);
              resizeStartWidthRef.current = chatWidthPx
                ?? Math.round((columnsRef.current?.getBoundingClientRect().width || 1200) * 0.44);
            }}
            onResizeEnd={() => setIsResizing(false)}
            onResizeDelta={(deltaPx) => {
              const containerWidth = columnsRef.current?.getBoundingClientRect().width || 1200;
              setChatWidthPx(clampChatWidth(resizeStartWidthRef.current + deltaPx, containerWidth));
            }}
          />

          <section data-testid="solo-tabs-pane" className="desktop-workbench-pane grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
            <div className="flex min-w-0 items-center gap-1 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 py-1.5" role="tablist" aria-label="Solo 标签">
              {tabs.map((tab) => {
                const active = tab.id === activeTab.id;
                const Icon = tab.kind === "session" ? Info : tab.kind === "git-status" ? GitBranch : tab.kind === "git-diff" ? GitCompare : FileText;
                return (
                  <div key={tab.id} className="flex min-w-0 items-center">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={active}
                      aria-label={tab.title}
                      onClick={() => setActiveTabId(tab.id)}
                      className={clsx(
                        "inline-flex h-8 min-w-0 items-center gap-1.5 px-2 text-xs font-medium transition-colors",
                        active ? "tcb-selected-accent" : "text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5 shrink-0" />
                      <span className="max-w-36 truncate">{tab.title}</span>
                    </button>
                    {tab.kind !== "session" && tab.kind !== "git-status" ? (
                      <button
                        type="button"
                        aria-label={`关闭 ${tab.title}`}
                        title={`关闭 ${tab.title}`}
                        onClick={() => {
                          setTabs((current) => current.filter((item) => item.id !== tab.id));
                          setActiveTabId((current) => current === tab.id ? "session" : current);
                        }}
                        className="inline-flex h-8 w-7 items-center justify-center text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <div className="min-h-0 overflow-hidden">
              {activeTab.kind === "session" ? (
                <SoloSessionInfoTab snapshot={sessionSnapshot} />
              ) : activeTab.kind === "git-status" ? (
                <GitScreen
                  botAlias={botAlias}
                  client={client}
                  embedded
                  onOpenDiff={openGitDiffTab}
                />
              ) : activeTab.kind === "file-preview" ? (
                <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]">
                  <div className="flex min-w-0 items-center justify-between gap-3 border-b border-[var(--workbench-hairline)] px-4 py-2 text-xs text-[var(--muted)]">
                    <span className="min-w-0 truncate" title={activeTab.path}>{activeTab.path}</span>
                    <span className="shrink-0">{getFilePreviewStatusText(previews[activeTab.path]?.result || null) || "只读"}</span>
                  </div>
                  <div className="min-h-0 overflow-hidden">
                    {previews[activeTab.path]?.error ? (
                      <div className="p-4 text-sm text-red-600">{previews[activeTab.path]?.error}</div>
                    ) : (
                      <FilePreviewSurface
                        title={activeTab.path}
                        result={previews[activeTab.path]?.result || null}
                        loading={previews[activeTab.path]?.loading}
                        botAlias={botAlias}
                        desktop
                        onFileLinkClick={requestPreview}
                      />
                    )}
                  </div>
                </div>
              ) : (
                <pre className="h-full overflow-auto p-4 font-mono text-xs leading-5 text-[var(--text)] whitespace-pre-wrap">
                  {activeTab.diffText}
                </pre>
              )}
            </div>
          </section>
        </div>
      </div>

      <div className="desktop-workbench-statusbar flex min-h-6 items-center justify-between gap-3 border-t border-[var(--workbench-hairline)] bg-[var(--workbench-titlebar-bg)] px-2 text-[11px] text-[var(--muted)]">
        <span className="truncate">Solo · {sessionSnapshot?.conversationTitle || "当前会话"}</span>
        <span data-workbench-status={chatStatus?.processing ? "active" : undefined}>
          {chatStatus?.processing ? "运行中" : "空闲"}
        </span>
      </div>
    </div>
  );
}
