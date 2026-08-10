import { clsx } from "clsx";
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Maximize2, Minimize2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { FileEditorSurface } from "../components/FileEditorSurface";
import { FilePreviewPane } from "../components/FilePreviewPane";
import { GitDiffViewer } from "../components/GitDiffViewer";
import { PluginViewSurface } from "../components/plugin-renderers/PluginViewSurface";
import type { CodeNavigationIntent, HostEffect, InlineCompletionConfig, PluginOpenTarget } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { inferFileEditorLanguageId } from "../utils/fileEditorLanguage";
import { isFilePreviewFullyLoaded } from "../utils/filePreview";
import type { EditorRevealLocation, EditorTab } from "./workbenchTypes";

type Props = {
  botAlias: string;
  client: WebBotClient;
  tabs: EditorTab[];
  activeTab: EditorTab | null;
  activeTabPath: string;
  breakpointLines?: number[];
  currentLine?: number | null;
  editorReveal?: EditorRevealLocation | null;
  navigationCommand?: { kind: "definition" | "implementation"; requestId: string } | null;
  canNavigateBack?: boolean;
  canNavigateForward?: boolean;
  allowCodeJump?: boolean;
  canNavigateImplementation?: boolean;
  canUseInlineCompletion?: boolean;
  onToggleBreakpoint?: (line: number) => void;
  onResolveCodeNavigation?: (input: CodeNavigationIntent) => void;
  onNavigateBack?: () => void | Promise<void>;
  onNavigateForward?: () => void | Promise<void>;
  onActivateTab: (path: string) => void | Promise<void>;
  onCloseTab: (path: string) => boolean;
  onChangeActiveContent: (content: string) => void;
  onSaveActiveTab: () => void;
  onCloseAll: () => void;
  onCloseOthers: (path: string) => void;
  onCloseTabsToRight: (path: string) => void;
  onReopenLastClosed: () => void | Promise<void>;
  onRevealInTree: (path: string) => void | Promise<void>;
  onApplyHostEffects?: (effects: HostEffect[]) => Promise<void> | void;
  onClosePluginTab?: (path: string) => void | Promise<void>;
  onReopenPluginView?: (target: PluginOpenTarget) => Promise<void> | void;
  onLoadFullPreview?: (path: string) => void | Promise<void>;
  onNotice?: (message: string) => void;
  focused: boolean;
  onToggleFocus: () => void;
};

function pluginTargetLabel(target: PluginOpenTarget) {
  return target.title.trim() || "Mermaid 转 Visio";
}

function splitBreadcrumbPath(path: string) {
  return path.split(/[\\/]+/).map((part) => part.trim()).filter(Boolean);
}

export function buildEditorBreadcrumb(tab: EditorTab) {
  if (tab.kind === "plugin-view") {
    return tab.sourcePath
      ? [...splitBreadcrumbPath(tab.sourcePath), tab.basename]
      : ["插件", tab.basename];
  }
  if (tab.kind === "git-diff") {
    return splitBreadcrumbPath(tab.sourcePath || tab.path);
  }
  if (tab.kind === "external-source") {
    return ["外部依赖 · 只读", ...splitBreadcrumbPath(tab.displayPath || tab.basename)];
  }
  if (tab.kind === "file-preview") {
    return [...splitBreadcrumbPath(tab.sourcePath || tab.basename), "预览"];
  }
  return splitBreadcrumbPath(tab.path);
}

function PluginViewLoading() {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="space-y-2 text-center text-sm text-[var(--muted)]">
      <p>正在加载插件视图</p>
      {elapsedSeconds > 0 ? (
        <p>已等待 {elapsedSeconds} 秒，首次启动插件或目录较大时可能更久。</p>
      ) : null}
    </div>
  );
}

export function EditorPane({
  botAlias,
  client,
  tabs,
  activeTab,
  activeTabPath,
  breakpointLines = [],
  currentLine = null,
  editorReveal = null,
  navigationCommand = null,
  canNavigateBack = false,
  canNavigateForward = false,
  allowCodeJump = true,
  canNavigateImplementation = true,
  canUseInlineCompletion = false,
  onToggleBreakpoint,
  onResolveCodeNavigation,
  onNavigateBack,
  onNavigateForward,
  onActivateTab,
  onCloseTab,
  onChangeActiveContent,
  onSaveActiveTab,
  onCloseAll,
  onCloseOthers,
  onCloseTabsToRight,
  onReopenLastClosed,
  onRevealInTree,
  onApplyHostEffects,
  onClosePluginTab,
  onReopenPluginView,
  onLoadFullPreview,
  onNotice,
  focused,
  onToggleFocus,
}: Props) {
  const [inlineCompletionConfig, setInlineCompletionConfig] = useState<InlineCompletionConfig | null>(null);
  const codeNavigationHoverRequestSeqRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    if (!canUseInlineCompletion) {
      setInlineCompletionConfig(null);
      return () => {
        cancelled = true;
      };
    }
    void client.getInlineCompletionRuntimeConfig(botAlias)
      .then((config) => {
        if (!cancelled) {
          setInlineCompletionConfig(config);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setInlineCompletionConfig(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, canUseInlineCompletion, client]);

  const inlineCompletion = useMemo(() => {
    if (!activeTab || !canUseInlineCompletion || activeTab.kind !== "file" || !inlineCompletionConfig?.configured) {
      return undefined;
    }
    return {
      editorId: `workbench:${botAlias}:${activeTab.path}`,
      path: activeTab.path,
      languageId: inferFileEditorLanguageId(activeTab.path),
      lastModifiedNs: activeTab.lastModifiedNs,
      disabled: activeTab.loading || activeTab.saving || Boolean(activeTab.readOnly),
      autoTriggerEnabled: inlineCompletionConfig.autoTriggerEnabled,
      manualTriggerEnabled: inlineCompletionConfig.manualTriggerEnabled,
      autoTriggerDelayMs: Math.max(700, inlineCompletionConfig.autoTriggerDelayMs),
      request: (input, signal) => client.requestInlineCompletion(botAlias, input, signal),
    };
  }, [activeTab, botAlias, canUseInlineCompletion, client, inlineCompletionConfig]);

  const codeNavigationHoverContextKey = useMemo(() => {
    if (!activeTab) {
      return null;
    }
    return {
      botAlias,
      client,
      kind: activeTab.kind,
      path: activeTab.path,
      sourceId: activeTab.sourceId,
      displayPath: activeTab.displayPath,
      documentVersion: activeTab.documentVersion,
      content: activeTab.content,
    };
  }, [
    activeTab?.content,
    activeTab?.displayPath,
    activeTab?.documentVersion,
    activeTab?.kind,
    activeTab?.path,
    activeTab?.sourceId,
    botAlias,
    client,
  ]);

  const codeNavigationHover = useMemo(() => {
    if (
      !allowCodeJump
      || !onResolveCodeNavigation
      || !activeTab
      || (activeTab.kind !== "file" && activeTab.kind !== "external-source")
    ) {
      return undefined;
    }
    return {
      contextKey: codeNavigationHoverContextKey,
      request: async (input: CodeNavigationIntent, signal: AbortSignal) => {
        if (input.path !== activeTab.path) {
          return false;
        }
        const requestId = `code-navigation-hover-${Date.now()}-${++codeNavigationHoverRequestSeqRef.current}`;
        const result = await client.resolveCodeNavigation(botAlias, {
          kind: "definition",
          requestId,
          document: {
            ...(activeTab.kind === "external-source" && activeTab.sourceId
              ? { sourceId: activeTab.sourceId }
              : { path: activeTab.path }),
            languageId: inferFileEditorLanguageId(activeTab.displayPath || activeTab.path),
            version: Math.max(1, Math.trunc(activeTab.documentVersion || 1)),
            content: activeTab.content,
          },
          position: { line: input.line, column: input.column },
        }, signal);
        return !signal.aborted && result.items.some((item) => (
          (item.targetType === "workspace" && Boolean(item.path))
          || (item.targetType === "external" && Boolean(item.sourceId))
        ));
      },
    };
  }, [activeTab, allowCodeJump, botAlias, client, codeNavigationHoverContextKey, onResolveCodeNavigation]);

  const [menuPath, setMenuPath] = useState("");
  const [pluginMenuOpen, setPluginMenuOpen] = useState(false);

  useEffect(() => {
    setPluginMenuOpen(false);
  }, [activeTabPath]);

  if (tabs.length === 0 || !activeTab) {
    return (
      <div
        data-testid="editor-empty-state"
        className="editor-empty-state flex h-full min-h-0 items-center justify-center p-6 text-center text-sm text-[var(--muted)]"
      >
        <div className="relative z-10 space-y-2">
          <p>未打开文件</p>
          <p><kbd className="font-mono text-[var(--text)]">Ctrl+P</kbd> 快速打开文件</p>
          <p><kbd className="font-mono text-[var(--text)]">Ctrl+Shift+F</kbd> 全文搜索</p>
        </div>
      </div>
    );
  }

  const visibleStatusText = activeTab.statusText === "语言服务同步失败"
    ? ""
    : activeTab.statusText;
  const visibleError = activeTab.error === "文档缺少语言标识"
    ? ""
    : activeTab.error;

  const activePluginTargets = activeTab.kind === "file" ? activeTab.pluginTargets || [] : [];
  const hasPluginMenu = activePluginTargets.length > 1;
  const singlePluginTarget = activePluginTargets.length === 1 ? activePluginTargets[0] : null;
  const breadcrumbParts = buildEditorBreadcrumb(activeTab);
  const activePreviewPath = activeTab.kind === "file-preview" ? activeTab.sourcePath || "" : "";
  const activePreviewResult = activeTab.kind === "file-preview" ? activeTab.filePreview || null : null;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="editor-tab-strip flex h-[34px] shrink-0 items-stretch justify-between border-b border-[var(--border)] bg-[var(--workbench-panel-elevated-bg)]">
        <div role="tablist" aria-label="打开的编辑器" className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
          {tabs.map((tab) => {
            const isActive = activeTabPath === tab.path;
            const isFilePreview = tab.kind === "file-preview";
            const tabLabel = isFilePreview ? `${tab.basename} 预览` : tab.basename;
            const displayPath = isFilePreview ? tab.sourcePath || tab.basename : tab.displayPath || tab.path;
            return (
              <div
                key={tab.path}
                data-editor-tab-active={isActive ? "true" : "false"}
                onContextMenu={(event) => {
                  event.preventDefault();
                  setMenuPath((current) => current === tab.path ? "" : tab.path);
                }}
                className={clsx(
                  "editor-tab group relative flex h-full shrink-0 items-center gap-1 border-r border-[var(--border)] px-2",
                  isActive
                    ? "bg-[var(--editor-bg)]"
                    : "bg-transparent hover:bg-[var(--workbench-hover-bg)]",
                )}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-label={tabLabel}
                  title={displayPath}
                  onClick={() => {
                    setMenuPath("");
                    void onActivateTab(tab.path);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                      event.preventDefault();
                      setMenuPath(tab.path);
                    }
                  }}
                  className="inline-flex max-w-52 min-w-0 items-center gap-1.5 text-[13px] text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--workbench-focus-ring)]"
                >
                  <span className="truncate">{tab.basename}</span>
                  {isFilePreview ? (
                    <span className="shrink-0 text-[10px] text-[var(--muted)]">预览</span>
                  ) : null}
                </button>
                {tab.kind === "external-source" ? (
                  <span className="max-w-44 truncate text-[10px] text-[var(--muted)]" aria-label="外部依赖 · 只读">
                    外部依赖 · 只读
                  </span>
                ) : null}
                {tab.dirty ? (
                  <span
                    data-testid={`editor-tab-dirty-dot-${tab.path}`}
                    className="h-2 w-2 rounded-full bg-[var(--accent)]"
                  />
                ) : null}
                <button
                  type="button"
                  aria-label={`关闭 ${isFilePreview ? tabLabel : tab.displayPath || tab.path}`}
                  onClick={() => {
                    if (onCloseTab(tab.path)) {
                      setMenuPath((current) => current === tab.path ? "" : current);
                    }
                  }}
                  className="editor-tab-close inline-flex h-5 w-5 items-center justify-center rounded text-xs text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
                >
                  ×
                </button>
                {menuPath === tab.path ? (
                  <div className="absolute right-0 top-full z-20 w-44 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]">
                    <button
                      type="button"
                      onClick={() => {
                        onCloseTab(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      关闭
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        onCloseOthers(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      关闭其他标签页
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        onCloseTabsToRight(tab.path);
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      关闭右侧标签页
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void onReopenLastClosed();
                        setMenuPath("");
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      重新打开刚关闭的标签页
                    </button>
                    {tab.kind !== "external-source" ? (
                      <button
                        type="button"
                        onClick={() => {
                          void onRevealInTree(tab.sourcePath || tab.path);
                          setMenuPath("");
                        }}
                        className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                      >
                        在文件树中定位
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="relative flex shrink-0 items-center gap-1 px-1">
          <button
            type="button"
            aria-label="导航后退"
            title="导航后退 (Alt+Left)"
            disabled={!canNavigateBack || !onNavigateBack}
            onClick={() => void onNavigateBack?.()}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-35"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label="导航前进"
            title="导航前进 (Alt+Right)"
            disabled={!canNavigateForward || !onNavigateForward}
            onClick={() => void onNavigateForward?.()}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-35"
          >
            <ArrowRight className="h-4 w-4" />
          </button>
          {tabs.length > 1 ? (
            <button
              type="button"
              aria-label="关闭全部标签页"
              title="关闭全部标签页"
              onClick={onCloseAll}
              className="inline-flex h-7 w-7 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
          {singlePluginTarget ? (
            <button
              type="button"
              onClick={() => {
                void onReopenPluginView?.(singlePluginTarget);
              }}
              disabled={!onReopenPluginView}
              className="inline-flex h-7 items-center rounded border border-[var(--accent-outline)] bg-[var(--surface)] px-2 text-[12px] text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {pluginTargetLabel(singlePluginTarget)}
            </button>
          ) : null}
          {hasPluginMenu ? (
            <div className="relative">
              <button
                type="button"
                aria-expanded={pluginMenuOpen}
                aria-haspopup="menu"
                aria-label="插件入口"
                onClick={() => {
                  setPluginMenuOpen((current) => !current);
                }}
                className="inline-flex h-7 items-center gap-1 rounded border border-[var(--accent-outline)] bg-[var(--surface)] px-2 text-[12px] text-[var(--text)] hover:bg-[var(--surface-strong)]"
              >
                插件入口
                <ChevronDown className="h-4 w-4" />
              </button>
              {pluginMenuOpen ? (
                <div
                  role="menu"
                  aria-label="插件入口"
                  className="absolute right-0 top-full z-20 mt-2 min-w-40 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-1 shadow-[var(--shadow-card)]"
                >
                  {activePluginTargets.map((target) => (
                    <button
                      key={`${target.pluginId}:${target.viewId}:${target.title}`}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setPluginMenuOpen(false);
                        void onReopenPluginView?.(target);
                      }}
                      className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-[var(--surface-strong)]"
                    >
                      {pluginTargetLabel(target)}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            aria-label={focused ? "退出聚焦编辑器" : "聚焦编辑器"}
            title={focused ? "退出聚焦编辑器" : "聚焦编辑器"}
            onClick={onToggleFocus}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--workbench-focus-ring)]"
          >
            {focused ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <nav aria-label="文件路径" className="editor-breadcrumb flex h-[22px] shrink-0 items-center overflow-x-auto border-b border-[var(--border)] bg-[var(--editor-bg)] px-2 text-[11px]">
        <ol className="flex min-w-max items-center whitespace-nowrap">
          {breadcrumbParts.map((part, index) => {
            const isCurrent = index === breadcrumbParts.length - 1;
            return (
              <li key={`${part}-${index}`} className="flex items-center">
                {index > 0 ? (
                  <ChevronRight aria-hidden="true" className="mx-0.5 h-3 w-3 shrink-0 text-[var(--muted)]" />
                ) : null}
                <span
                  aria-current={isCurrent ? "page" : undefined}
                  className={isCurrent ? "text-[var(--editor-text)]" : "text-[var(--muted)]"}
                >
                  {part}
                </span>
              </li>
            );
          })}
        </ol>
      </nav>

      {activeTab.kind !== "file-preview" && visibleStatusText ? (
        <div className="border-b border-[var(--border)] px-4 py-2 text-sm text-[var(--muted)]">
          {visibleStatusText}
        </div>
      ) : null}
      {activeTab.kind !== "file-preview" && visibleError ? (
        <div className="border-b border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] px-4 py-2 text-sm text-[var(--status-danger)]">
          {visibleError}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab.kind === "file-preview" ? (
          <FilePreviewPane
            title={activePreviewPath || activeTab.basename}
            result={activePreviewResult}
            loading={activeTab.loading}
            botAlias={botAlias}
            statusText={visibleStatusText}
            error={visibleError}
            onLoadFull={
              activePreviewPath
              && activePreviewResult
              && !isFilePreviewFullyLoaded(activePreviewResult)
              && onLoadFullPreview
                ? () => void onLoadFullPreview(activePreviewPath)
                : undefined
            }
          />
        ) : activeTab.kind === "git-diff" ? (
          <GitDiffViewer
            content={activeTab.content}
            testId="desktop-git-diff-viewer"
            className="h-full min-h-0 p-3 text-xs leading-6"
          />
        ) : activeTab.kind === "plugin-view" ? (
          <div data-testid="desktop-plugin-view" className="h-full min-h-0">
            {activeTab.pluginView ? (
              <PluginViewSurface
                botAlias={botAlias}
                client={client}
                view={activeTab.pluginView}
                inputPayload={activeTab.pluginInput || {}}
                onApplyHostEffects={onApplyHostEffects}
                onClosePluginSession={() => onClosePluginTab?.(activeTab.path)}
                onRefreshPluginSession={() => activeTab.pluginInput
                  ? onReopenPluginView?.({
                      pluginId: activeTab.pluginView?.pluginId || "",
                      viewId: activeTab.pluginView?.viewId || "",
                      title: activeTab.pluginView?.title || activeTab.basename,
                      input: activeTab.pluginInput,
                    })
                  : undefined}
                onReopenPluginView={onReopenPluginView}
                onNotice={onNotice}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">
                <PluginViewLoading />
              </div>
            )}
          </div>
        ) : (
          <FileEditorSurface
            path={activeTab.path}
            value={activeTab.content}
            loading={activeTab.loading}
            saving={activeTab.saving}
            dirty={activeTab.dirty}
            canSave={activeTab.dirty && !activeTab.missing && !activeTab.readOnly}
            readOnly={Boolean(activeTab.readOnly)}
            breakpointLines={breakpointLines}
            currentLine={currentLine}
            reveal={editorReveal?.path === activeTab.path ? editorReveal : null}
            navigationCommand={navigationCommand}
            canNavigateImplementation={canNavigateImplementation}
            statusText=""
            error=""
            hideHeader
            inlineCompletion={inlineCompletion}
            codeNavigationHover={codeNavigationHover}
            onToggleBreakpoint={onToggleBreakpoint}
            onResolveCodeNavigation={allowCodeJump ? onResolveCodeNavigation : undefined}
            onChange={onChangeActiveContent}
            onSave={onSaveActiveTab}
            onClose={() => {
              onCloseTab(activeTab.path);
            }}
          />
        )}
      </div>
    </div>
  );
}
