import { useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  BugPlay,
  ChevronDown,
  ChevronRight,
  Pause,
  Play,
  Square,
  StepForward,
  type LucideIcon,
} from "lucide-react";
import type { DebugProfile, DebugState, DebugVariable } from "../services/types";

type LaunchForm = {
  prepareCommand: string;
  remoteHost: string;
  remoteUser: string;
  remoteDir: string;
  remotePort: string;
  password: string;
  stopAtEntry: boolean;
};

type Props = {
  profile: DebugProfile | null;
  profileLoading?: boolean;
  state: DebugState;
  prepareLogs: string[];
  launchForm: LaunchForm;
  onLaunchFormChange: (patch: Partial<LaunchForm>) => void;
  onLaunch: () => void;
  onContinue: () => void;
  onPause: () => void;
  onNext: () => void;
  onStepIn: () => void;
  onStepOut: () => void;
  onStop: () => void;
  onSelectFrame: (frameId: string) => void;
  onRequestVariables: (variablesReference: string) => void;
};

function sysrootFromProfile(profile: DebugProfile | null) {
  if (!profile) {
    return "";
  }
  const matched = profile.setupCommands.find((item) => item.startsWith("set sysroot "));
  return matched ? matched.slice("set sysroot ".length).trim() : "";
}

function phaseText(state: DebugState) {
  if (state.phase === "preparing") {
    return "准备中";
  }
  if (state.phase === "deploying" || state.phase === "starting_gdb" || state.phase === "connecting_remote") {
    return "连接中";
  }
  if (state.phase === "paused") {
    return "已暂停";
  }
  if (state.phase === "running") {
    return "运行中";
  }
  if (state.phase === "terminating") {
    return "停止中";
  }
  if (state.phase === "error") {
    return "错误";
  }
  return "未启动";
}

function CollapseHeader({
  title,
  summary,
  expanded,
  onToggle,
}: {
  title: string;
  summary?: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-label={`${expanded ? "收起" : "展开"}${title}`}
      onClick={onToggle}
      className="flex w-full items-center gap-2 text-left"
    >
      <Icon className="h-4 w-4 shrink-0 text-[var(--muted)]" />
      <span className="shrink-0 text-sm font-semibold text-[var(--text)]">{title}</span>
      {summary ? <span className="min-w-0 truncate text-[11px] text-[var(--muted)]">{summary}</span> : null}
    </button>
  );
}

function DebugToolButton({
  label,
  icon: Icon,
  onClick,
  disabled,
  primary = false,
  danger = false,
}: {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  danger?: boolean;
}) {
  const tone = primary
    ? "border-[var(--accent)] bg-[var(--accent)] text-white hover:brightness-110"
    : danger
      ? "border-red-400/60 text-red-500 hover:bg-red-500/10"
      : "border-[var(--border)] text-[var(--text)] hover:bg-[var(--accent-soft)]";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${tone} disabled:cursor-not-allowed disabled:opacity-40`}
    >
      <Icon className="h-4 w-4" />
    </button>
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

  return (
    <div className="space-y-1">
      {items.map((item) => {
        const reference = item.variablesReference || "";
        const children = reference ? variables[reference] || [] : [];
        const isExpanded = Boolean(reference && expanded[reference]);
        const canExpand = Boolean(reference);

        return (
          <div key={`${item.name}:${item.value}:${reference}`} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2">
            <div className="flex items-start gap-2">
              {canExpand ? (
                <button
                  type="button"
                  onClick={() => {
                    if (!isExpanded && reference && !variables[reference]) {
                      onRequestVariables(reference);
                    }
                    setExpanded((current) => ({
                      ...current,
                      [reference]: !current[reference],
                    }));
                  }}
                  className="mt-0.5 text-xs text-[var(--muted)]"
                >
                  {isExpanded ? "▾" : "▸"}
                </button>
              ) : (
                <span className="mt-0.5 text-xs text-[var(--muted)]">·</span>
              )}
              <div className="min-w-0 flex-1">
                <div className="break-all font-mono text-xs text-[var(--text)]">{item.name}</div>
                <div className="break-all font-mono text-xs text-[var(--muted)]">{item.value}</div>
                {item.type ? <div className="text-[11px] text-[var(--muted)]">{item.type}</div> : null}
              </div>
            </div>
            {canExpand && isExpanded && children.length > 0 ? (
              <div className="mt-2 border-l border-[var(--border)] pl-3">
                <VariableTree items={children} variables={variables} onRequestVariables={onRequestVariables} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function DebugPane({
  profile,
  profileLoading = false,
  state,
  prepareLogs,
  launchForm,
  onLaunchFormChange,
  onLaunch,
  onContinue,
  onPause,
  onNext,
  onStepIn,
  onStepOut,
  onStop,
  onSelectFrame,
  onRequestVariables,
}: Props) {
  const sysroot = sysrootFromProfile(profile);
  const currentFrameId = state.currentFrameId || state.frames[0]?.id || "";
  const [sessionExpanded, setSessionExpanded] = useState(false);
  const [remoteExpanded, setRemoteExpanded] = useState(false);
  const isBusy = state.phase === "preparing"
    || state.phase === "starting_gdb"
    || state.phase === "connecting_remote"
    || state.phase === "terminating";
  const remoteSummary = [
    launchForm.remoteUser || profile?.remoteUser || "",
    launchForm.remoteHost || profile?.remoteHost || "",
    launchForm.remotePort || (profile?.remotePort ? String(profile.remotePort) : ""),
  ];
  const remoteLabel = remoteSummary[1]
    ? `${remoteSummary[0] ? `${remoteSummary[0]}@` : ""}${remoteSummary[1]}${remoteSummary[2] ? `:${remoteSummary[2]}` : ""}`
    : "";

  if (profileLoading && !profile) {
    return (
      <section data-testid="debug-pane" className="space-y-3 p-3 text-sm text-[var(--muted)]">
        读取调试配置中...
      </section>
    );
  }

  if (!profile) {
    return (
      <section data-testid="debug-pane" className="space-y-3 p-3 text-sm text-[var(--muted)]">
        当前工作目录不支持 C++ 调试
      </section>
    );
  }

  return (
    <section data-testid="debug-pane" className="space-y-3 p-3">
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--text)]">调试</h2>
            <p className="text-xs text-[var(--muted)]">{phaseText(state)}</p>
          </div>
          <span className="rounded-full bg-[var(--accent-soft)] px-2 py-1 text-xs text-[var(--text)]">{state.message || "就绪"}</span>
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <CollapseHeader
          title="会话配置"
          summary={profile.configName}
          expanded={sessionExpanded}
          onToggle={() => setSessionExpanded((current) => !current)}
        />
        {sessionExpanded ? (
          <dl className="mt-3 space-y-2 text-[12px]">
            <div>
              <dt className="text-[var(--muted)]">配置名</dt>
              <dd className="break-all text-[var(--text)]">{profile.configName}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">program</dt>
              <dd className="break-all text-[var(--text)]">{profile.program}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">miDebuggerPath</dt>
              <dd className="break-all text-[var(--text)]">{profile.miDebuggerPath}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">sysroot</dt>
              <dd className="break-all text-[var(--text)]">{sysroot || "-"}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">compile_commands.json</dt>
              <dd className="break-all text-[var(--text)]">{profile.compileCommands || "-"}</dd>
            </div>
          </dl>
        ) : null}
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <CollapseHeader
          title="远端参数"
          summary={remoteLabel}
          expanded={remoteExpanded}
          onToggle={() => setRemoteExpanded((current) => !current)}
        />
        {remoteExpanded ? (
        <div className="mt-3 space-y-3">
          <label className="block text-xs">
            <span className="mb-1 block text-[var(--muted)]">准备命令</span>
            <input
              value={launchForm.prepareCommand}
              onChange={(event) => onLaunchFormChange({ prepareCommand: event.target.value })}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-[12px] leading-5 text-[var(--text)]"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block text-[var(--muted)]">host</span>
            <input
              value={launchForm.remoteHost}
              onChange={(event) => onLaunchFormChange({ remoteHost: event.target.value })}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-[12px] leading-5 text-[var(--text)]"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block text-[var(--muted)]">user</span>
            <input
              value={launchForm.remoteUser}
              onChange={(event) => onLaunchFormChange({ remoteUser: event.target.value })}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-[12px] leading-5 text-[var(--text)]"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block text-[var(--muted)]">remoteDir</span>
            <input
              value={launchForm.remoteDir}
              onChange={(event) => onLaunchFormChange({ remoteDir: event.target.value })}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-[12px] leading-5 text-[var(--text)]"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block text-[var(--muted)]">port</span>
            <input
              value={launchForm.remotePort}
              inputMode="numeric"
              onChange={(event) => onLaunchFormChange({ remotePort: event.target.value })}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-[12px] leading-5 text-[var(--text)]"
            />
          </label>
          <label className="block text-xs">
            <span className="mb-1 block text-[var(--muted)]">password</span>
            <input
              type="password"
              value={launchForm.password}
              onChange={(event) => onLaunchFormChange({ password: event.target.value })}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-[12px] leading-5 text-[var(--text)]"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-[var(--text)]">
            <input
              type="checkbox"
              checked={launchForm.stopAtEntry}
              onChange={(event) => onLaunchFormChange({ stopAtEntry: event.target.checked })}
            />
            <span>入口暂停</span>
          </label>
        </div>
        ) : null}
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-[var(--text)]">控制</h3>
          <div role="toolbar" aria-label="调试控制" className="flex min-w-0 items-center gap-1 overflow-x-auto">
            <DebugToolButton label="启动调试" icon={BugPlay} onClick={onLaunch} disabled={isBusy} primary />
            <DebugToolButton label="继续" icon={Play} onClick={onContinue} disabled={state.phase !== "paused"} />
            <DebugToolButton label="暂停" icon={Pause} onClick={onPause} disabled={state.phase !== "running"} />
            <DebugToolButton label="下一步" icon={StepForward} onClick={onNext} disabled={state.phase !== "paused"} />
            <DebugToolButton label="进入函数" icon={ArrowDownToLine} onClick={onStepIn} disabled={state.phase !== "paused"} />
            <DebugToolButton label="跳出函数" icon={ArrowUpFromLine} onClick={onStepOut} disabled={state.phase !== "paused"} />
            <DebugToolButton label="停止调试" icon={Square} onClick={onStop} disabled={state.phase === "idle"} danger />
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <h3 className="text-sm font-semibold text-[var(--text)]">断点</h3>
        <div className="mt-3 space-y-2">
          {state.breakpoints.length > 0 ? state.breakpoints.map((item) => (
            <div key={`${item.source}:${item.line}`} className="rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-xs">
              <div className="break-all font-mono text-[var(--text)]">{item.source}</div>
              <div className="mt-1 text-[var(--muted)]">第 {item.line} 行 {item.status === "rejected" ? `已拒绝 ${item.message || ""}` : item.verified ? "已验证" : "待验证"}</div>
            </div>
          )) : <p className="text-xs text-[var(--muted)]">暂无断点</p>}
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <h3 className="text-sm font-semibold text-[var(--text)]">调用栈</h3>
        <div className="mt-3 space-y-2">
          {state.frames.length > 0 ? state.frames.map((frame) => (
            <button
              key={frame.id}
              type="button"
              onClick={() => onSelectFrame(frame.id)}
              className={`w-full rounded-xl border px-3 py-2 text-left text-xs ${
                frame.id === currentFrameId
                  ? "border-[var(--accent-outline)] bg-[var(--accent-soft)]"
                  : "border-[var(--border)] bg-[var(--surface-strong)]"
              }`}
            >
              <div className="break-all font-mono text-[var(--text)]">{frame.name}</div>
              <div className="mt-1 break-all text-[var(--muted)]">{frame.source || "??"}:{frame.line || 0}</div>
            </button>
          )) : <p className="text-xs text-[var(--muted)]">暂无调用栈</p>}
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <h3 className="text-sm font-semibold text-[var(--text)]">局部变量</h3>
        <div className="mt-3 space-y-3">
          {state.scopes.length > 0 ? state.scopes.map((scope) => (
            <div key={scope.name} className="space-y-2">
              <div className="text-xs font-semibold text-[var(--muted)]">{scope.name}</div>
              <VariableTree
                items={state.variables[scope.variablesReference] || []}
                variables={state.variables}
                onRequestVariables={onRequestVariables}
              />
            </div>
          )) : <p className="text-xs text-[var(--muted)]">暂无变量</p>}
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
        <h3 className="text-sm font-semibold text-[var(--text)]">日志</h3>
        <pre className="mt-3 max-h-64 overflow-auto rounded-xl bg-[var(--surface-strong)] p-3 text-xs text-[var(--text)]">
          {(prepareLogs.length > 0 ? prepareLogs.join("\n") : state.message || "暂无日志")}
        </pre>
      </div>
    </section>
  );
}
