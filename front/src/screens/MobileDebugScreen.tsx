import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  BugPlay,
  FileCode2,
  ListTree,
  Pause,
  Play,
  ScrollText,
  Square,
  StepForward,
  TableProperties,
  type LucideIcon,
} from "lucide-react";
import { FileEditorSurface } from "../components/FileEditorSurface";
import type { DebugLaunchField, DebugState, DebugVariable, FileReadResult } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { fieldsForProfile, launchFormPatch, type DebugLaunchFormValue } from "../workbench/debugLaunchSchema";
import { toWorkspaceRelativeSourcePath } from "../workbench/debugSourcePath";
import { useDebugSession } from "../workbench/useDebugSession";

type Props = {
  authToken?: string;
  botAlias: string;
  client: WebBotClient;
};

type MobileDebugView = "source" | "stack" | "variables" | "logs";

type ActiveSource = {
  path: string;
  line?: number;
};

const VIEW_ITEMS: Array<{ value: MobileDebugView; label: string; Icon: LucideIcon }> = [
  { value: "source", label: "源码", Icon: FileCode2 },
  { value: "stack", label: "栈", Icon: ListTree },
  { value: "variables", label: "变量", Icon: TableProperties },
  { value: "logs", label: "日志", Icon: ScrollText },
];

function phaseText(state: DebugState) {
  if (state.phase === "starting") return "连接中";
  if (state.phase === "paused") return "已暂停";
  if (state.phase === "running") return "运行中";
  if (state.phase === "stopping") return "停止中";
  if (state.phase === "error") return "错误";
  return "未启动";
}

function currentFrame(state: DebugState) {
  return state.frames.find((item) => item.id === state.currentFrameId) || state.frames[0] || null;
}

function DebugIconButton({
  label,
  Icon,
  onClick,
  disabled,
  primary = false,
  danger = false,
}: {
  label: string;
  Icon: LucideIcon;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  danger?: boolean;
}) {
  const tone = primary
    ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-foreground)]"
    : danger
      ? "border-red-400/60 text-red-500"
      : "border-[var(--border)] text-[var(--text)]";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border ${tone} disabled:opacity-40`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

function MobileLaunchField({
  field,
  value,
  onChange,
}: {
  field: DebugLaunchField;
  value: unknown;
  onChange: (value: DebugLaunchFormValue) => void;
}) {
  if (field.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm text-[var(--text)]">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <label className="block text-xs">
      <span className="mb-1 block text-[var(--muted)]">{field.label}</span>
      <input
        aria-label={field.label}
        type={field.secret ? "password" : "text"}
        inputMode={field.type === "number" ? "numeric" : undefined}
        value={Array.isArray(value) ? value.join(" ") : String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1 font-mono text-[var(--text)]"
      />
    </label>
  );
}

function VariableTree({
  items,
  variables,
  onRequestVariables,
}: {
  items: DebugVariable[];
  variables: Record<string, DebugVariable[]>;
  onRequestVariables: (variablesReference: string) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (items.length === 0) {
    return <p className="p-3 text-xs text-[var(--muted)]">暂无变量</p>;
  }

  return (
    <div className="space-y-2 p-3">
      {items.map((item) => {
        const reference = item.variablesReference || "";
        const children = reference ? variables[reference] || [] : [];
        const isExpanded = Boolean(reference && expanded[reference]);

        return (
          <div key={`${item.name}:${item.value}:${reference}`} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2">
            <button
              type="button"
              disabled={!reference}
              onClick={() => {
                if (!isExpanded && reference && !variables[reference]) {
                  onRequestVariables(reference);
                }
                setExpanded((current) => ({ ...current, [reference]: !current[reference] }));
              }}
              className="flex w-full items-start gap-2 text-left disabled:cursor-default"
            >
              <span className="mt-0.5 w-4 shrink-0 text-xs text-[var(--muted)]">{reference ? (isExpanded ? "▾" : "▸") : "·"}</span>
              <span className="min-w-0 flex-1">
                <span className="block break-all font-mono text-xs text-[var(--text)]">{item.name}</span>
                <span className="block break-all font-mono text-xs text-[var(--muted)]">{item.value}</span>
                {item.type ? <span className="block text-[11px] text-[var(--muted)]">{item.type}</span> : null}
              </span>
            </button>
            {isExpanded && children.length > 0 ? (
              <div className="mt-2 border-l border-[var(--border)] pl-2">
                <VariableTree items={children} variables={variables} onRequestVariables={onRequestVariables} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function MobileDebugScreen({ authToken = "", botAlias, client }: Props) {
  const [view, setView] = useState<MobileDebugView>("source");
  const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);
  const [sourceContent, setSourceContent] = useState("");
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [remoteExpanded, setRemoteExpanded] = useState(false);
  const [workspaceRoot, setWorkspaceRoot] = useState("");

  function displaySourcePath(path: string) {
    return toWorkspaceRelativeSourcePath(path, workspaceRoot);
  }

  const debug = useDebugSession({
    authToken,
    botAlias,
    client,
    enabled: true,
    onRevealLocation: ({ sourcePath, line }) => {
      setActiveSource({ path: displaySourcePath(sourcePath), ...(line ? { line } : {}) });
      setView("source");
    },
  });

  const frame = currentFrame(debug.state);
  const launchFields = fieldsForProfile(debug.profile);
  const isBusy = debug.state.phase === "starting" || debug.state.phase === "stopping";
  const targetLabel = useMemo(() => {
    if (!debug.profile) {
      return "";
    }
    if (debug.profile.providerId === "cpp-gdb") {
      const host = String(debug.launchForm.remoteHost || debug.profile.remoteHost || "");
      const port = String(debug.launchForm.remotePort || debug.profile.remotePort || "");
      return host && port ? `${host}:${port}` : host;
    }
    return debug.profile.providerLabel;
  }, [debug.launchForm, debug.profile]);

  useEffect(() => {
    setWorkspaceRoot(debug.profile?.workspace || debug.profile?.cwd || "");
  }, [debug.profile]);

  useEffect(() => {
    if (!frame?.source || !frame.line) {
      return;
    }
    const sourcePath = displaySourcePath(frame.source);
    setActiveSource((current) => (
      current?.path === sourcePath && current.line === frame.line
        ? current
        : { path: sourcePath, line: frame.line }
    ));
  }, [frame?.source, frame?.line, workspaceRoot]);

  useEffect(() => {
    if (!activeSource?.path) {
      setSourceContent("");
      setSourceError("");
      return;
    }
    let cancelled = false;
    setSourceLoading(true);
    setSourceError("");
    client.readFileFull(botAlias, activeSource.path)
      .then((result: FileReadResult) => {
        if (!cancelled) {
          setSourceContent(result.content);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSourceError(error instanceof Error ? error.message : "读取源码失败");
          setSourceContent("");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSourceLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeSource?.path, botAlias, client]);

  if (debug.profileLoading && !debug.profile) {
    return (
      <main data-testid="mobile-debug-screen" className="flex h-full items-center justify-center bg-[var(--bg)] text-sm text-[var(--muted)]">
        读取调试配置中...
      </main>
    );
  }

  if (!debug.profile) {
    return (
      <main data-testid="mobile-debug-screen" className="flex h-full items-center justify-center bg-[var(--bg)] p-4 text-center text-sm text-[var(--muted)]">
        当前工作目录无可用调试配置
      </main>
    );
  }

  return (
    <main data-testid="mobile-debug-screen" className="flex h-full min-h-0 flex-col bg-[var(--bg)]">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--surface-strong)] p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-[var(--text)]">{debug.profile.providerLabel}</h1>
            <p className="truncate text-xs text-[var(--muted)]">{debug.profile.configName}</p>
          </div>
          <div className="shrink-0 rounded-full bg-[var(--accent-soft)] px-2 py-1 text-xs text-[var(--text)]">{phaseText(debug.state)}</div>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 text-xs text-[var(--muted)]">
          <span className="min-w-0 truncate font-mono">{targetLabel || "未配置目标"}</span>
          {frame?.source ? <span className="max-w-[45%] truncate font-mono">{frame.source}:{frame.line}</span> : null}
        </div>
      </header>

      <section className="shrink-0 border-b border-[var(--border)] bg-[var(--surface)] p-2">
        <div role="toolbar" aria-label="调试控制" className="flex items-center gap-1 overflow-x-auto">
          <DebugIconButton label="启动调试" Icon={BugPlay} onClick={() => void debug.launch()} disabled={isBusy} primary />
          <DebugIconButton label="继续" Icon={Play} onClick={() => void debug.continueExecution()} disabled={!debug.canContinue || debug.state.phase !== "paused"} />
          <DebugIconButton label="暂停" Icon={Pause} onClick={() => void debug.pauseExecution()} disabled={!debug.canPause || debug.state.phase !== "running"} />
          <DebugIconButton label="下一步" Icon={StepForward} onClick={() => void debug.next()} disabled={!debug.canNext || debug.state.phase !== "paused"} />
          <DebugIconButton label="进入函数" Icon={ArrowDownToLine} onClick={() => void debug.stepIn()} disabled={!debug.canStepIn || debug.state.phase !== "paused"} />
          <DebugIconButton label="跳出函数" Icon={ArrowUpFromLine} onClick={() => void debug.stepOut()} disabled={!debug.canStepOut || debug.state.phase !== "paused"} />
          <DebugIconButton label="停止调试" Icon={Square} onClick={() => void debug.stop()} disabled={debug.state.phase === "idle"} danger />
        </div>
        {launchFields.length > 0 ? (
          <div className="mt-2 rounded-lg border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-xs text-[var(--text)]">
            <button
              type="button"
              onClick={() => setRemoteExpanded((current) => !current)}
              className="w-full text-left text-[var(--muted)]"
            >
              启动参数
            </button>
            {remoteExpanded ? (
              <div className="mt-3 space-y-2">
                {launchFields.map((field) => (
                  <MobileLaunchField
                    key={field.key}
                    field={field}
                    value={debug.launchForm[field.key]}
                    onChange={(value) => debug.updateLaunchForm(launchFormPatch(field.key, value))}
                  />
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <nav className="grid shrink-0 grid-cols-4 border-b border-[var(--border)] bg-[var(--surface-strong)] p-1">
        {VIEW_ITEMS.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            onClick={() => setView(value)}
            className={`flex items-center justify-center gap-1 rounded-md px-2 py-2 text-xs ${
              view === value ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-[var(--muted)]"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <section className="min-h-0 flex-1 overflow-hidden">
        {view === "source" ? (
          activeSource ? (
            sourceError ? (
              <div className="p-3 text-sm text-red-500">{sourceError}</div>
            ) : (
              <FileEditorSurface
                path={activeSource.path}
                value={sourceContent}
                loading={sourceLoading}
                dirty={false}
                canSave={false}
                breakpointLines={debug.breakpointLinesForPath(activeSource.path)}
                currentLine={activeSource.line || debug.currentLineForPath(activeSource.path)}
                statusText={sourceLoading ? "读取源码中" : "只读调试视图"}
                onToggleBreakpoint={(line) => void debug.toggleBreakpoint(activeSource.path, line)}
                onChange={() => undefined}
                onSave={() => undefined}
                onClose={() => setActiveSource(null)}
              />
            )
          ) : (
            <div className="flex h-full items-center justify-center p-4 text-center text-sm text-[var(--muted)]">启动调试后显示当前位置</div>
          )
        ) : null}

        {view === "stack" ? (
          <div className="h-full overflow-auto p-3">
            {debug.state.frames.length > 0 ? debug.state.frames.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  if (item.sourceResolved !== false && item.source && item.source !== "??") {
                    setActiveSource({ path: displaySourcePath(item.source), line: item.line });
                    setView("source");
                  }
                  void debug.selectFrame(item.id);
                }}
                className={`mb-2 w-full rounded-lg border px-3 py-2 text-left text-xs ${
                  item.id === debug.state.currentFrameId ? "border-[var(--accent-outline)] bg-[var(--accent-soft)]" : "border-[var(--border)] bg-[var(--surface)]"
                }`}
              >
                <span className="block break-all font-mono text-[var(--text)]">{item.name || "??"}</span>
                <span className="mt-1 block break-all text-[var(--muted)]">{item.source || "?"}:{item.line || 0}</span>
              </button>
            )) : <p className="text-sm text-[var(--muted)]">暂无调用栈</p>}
          </div>
        ) : null}

        {view === "variables" ? (
          <div className="h-full overflow-auto">
            {debug.state.scopes.length > 0 ? debug.state.scopes.map((scope) => (
              <div key={scope.name}>
                <div className="border-b border-[var(--border)] px-3 py-2 text-xs font-semibold text-[var(--muted)]">{scope.name}</div>
                <VariableTree
                  items={debug.state.variables[scope.variablesReference] || []}
                  variables={debug.state.variables}
                  onRequestVariables={debug.requestVariables}
                />
              </div>
            )) : <p className="p-3 text-sm text-[var(--muted)]">暂无变量</p>}
          </div>
        ) : null}

        {view === "logs" ? (
          <pre className="h-full overflow-auto bg-[var(--surface)] p-3 text-xs text-[var(--text)]">
            {(debug.prepareLogs.length > 0 ? debug.prepareLogs.join("\n") : debug.state.message || "暂无日志")}
          </pre>
        ) : null}
      </section>
    </main>
  );
}
