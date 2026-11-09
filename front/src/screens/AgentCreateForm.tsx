import { useEffect, useId, useMemo, useState, type CSSProperties } from "react";
import { FolderOpen, HardDrive, Plus, Server, ShieldAlert, Sparkles, SquareTerminal, X } from "lucide-react";
import { DirectoryPickerDialog } from "../components/DirectoryPickerDialog";
import { RemoteWorkspacePicker } from "../components/RemoteWorkspacePicker";
import type { BotSummary, CliType } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getBotAccentColor, getBotIdentityTextStyle } from "../utils/botVisual";
import { cliTypeLabel } from "../utils/cliType";
import { buildExecutionConfig, DEFAULT_NATIVE_AGENT_DRAFT, isMainBot } from "./botManagerModel";
import { buildCreateDraft, defaultCliPathForType, type CreateDraft } from "./useBotManager";

const CLI_TYPE_CHOICES: CliType[] = ["codex", "codex_server", "claude", "antigravity", "deepseek"];

type Props = {
  client: WebBotClient;
  bots: BotSummary[];
  /** The manager's in-flight action; any non-empty value locks the form. */
  savingAction: string;
  onCreate: (draft: CreateDraft) => Promise<BotSummary | null>;
  canManage: boolean;
  canCreateWorkdirDirectory: boolean;
  canRunUnsafeCli: boolean;
  nativeAgentFeatureEnabled: boolean | null;
  /** `panel` sits in the desktop inspector; `card` stacks inside the narrow list. */
  layout: "panel" | "card";
  description: string;
  onCreated?: (alias: string) => void;
  onCancel?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function normalizeCreateDraft(draft: CreateDraft): CreateDraft {
  const executionConfig = buildExecutionConfig(draft.runtimeBackend);
  const providerInput = draft.nativeAgent?.provider?.trim() || "";
  const providerLooksLikeUrl = /^https?:\/\//i.test(providerInput);
  const baseUrlInput = draft.nativeAgent?.baseUrl?.trim() || "";
  const nativeAgent = {
    ...DEFAULT_NATIVE_AGENT_DRAFT,
    ...(draft.nativeAgent || {}),
    provider: providerLooksLikeUrl ? "codeflow" : providerInput,
    model: draft.nativeAgent?.model?.trim() || "",
    piAgent: draft.nativeAgent?.piAgent?.trim() || "",
    baseUrl: providerLooksLikeUrl && !baseUrlInput ? providerInput.replace(/\/+$/, "") : baseUrlInput.replace(/\/+$/, ""),
    apiKey: draft.nativeAgent?.apiKey?.trim() || "",
    clearApiKey: Boolean(draft.nativeAgent?.clearApiKey),
  };
  return {
    alias: draft.alias.trim(),
    cliType: draft.cliType,
    cliPath: draft.cliPath.trim(),
    workingDir: draft.workingDir.trim(),
    remoteWorkspace: draft.remoteWorkspace,
    bypassApprovalAndSandbox: draft.runtimeBackend === "cli" ? Boolean(draft.bypassApprovalAndSandbox) : false,
    runtimeBackend: draft.runtimeBackend,
    supportedExecutionModes: executionConfig.supportedExecutionModes,
    defaultExecutionMode: executionConfig.defaultExecutionMode,
    nativeAgent,
  };
}

function createDraftEquals(left: CreateDraft, right: CreateDraft) {
  return JSON.stringify(normalizeCreateDraft(left)) === JSON.stringify(normalizeCreateDraft(right));
}

/** Suggest a path in the host's own style, judged from the directories existing agents use. */
function workdirPlaceholder(bots: BotSummary[]) {
  const sample = bots.find((bot) => isMainBot(bot))?.workingDir || bots[0]?.workingDir || "";
  return /^[A-Za-z]:[\\/]/.test(sample) || sample.includes("\\") ? "C:\\workspace\\team3" : "/srv/workspace/team3";
}

/** The "新增智能体" form shared by the desktop inspector and the narrow agent list. */
export function AgentCreateForm({
  client,
  bots,
  savingAction,
  onCreate,
  canManage,
  canCreateWorkdirDirectory,
  canRunUnsafeCli,
  nativeAgentFeatureEnabled,
  layout,
  description,
  onCreated,
  onCancel,
  onDirtyChange,
}: Props) {
  const ids = useId();
  const titleId = `${ids}-title`;
  const aliasId = `${ids}-alias`;
  const cliPathId = `${ids}-cli-path`;
  const piAgentId = `${ids}-pi-agent`;
  const workdirId = `${ids}-workdir`;
  const baseDraft = useMemo(() => buildCreateDraft("codex", bots), [bots]);
  const [draft, setDraft] = useState<CreateDraft>(() => buildCreateDraft());
  const [remoteCreate, setRemoteCreate] = useState(false);
  const [showWorkdirPicker, setShowWorkdirPicker] = useState(false);
  const dirty = !createDraftEquals(draft, baseDraft);
  const busy = savingAction !== "";
  const directoryBrowserAlias = bots.find((bot) => isMainBot(bot))?.alias || bots[0]?.alias || "main";

  useEffect(() => {
    if (bots.length === 0) {
      return;
    }
    setDraft((prev) => {
      const userEditedPath = prev.cliPath.trim() && prev.cliPath.trim() !== defaultCliPathForType(prev.cliType);
      if (prev.alias.trim() || prev.workingDir.trim() || userEditedPath) {
        return prev;
      }
      return { ...prev, cliPath: buildCreateDraft(prev.cliType, bots).cliPath };
    });
  }, [bots]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (nativeAgentFeatureEnabled === false && draft.runtimeBackend === "native_agent") {
      setDraft((prev) => ({
        ...prev,
        runtimeBackend: "cli",
        supportedExecutionModes: ["cli"],
        defaultExecutionMode: "cli",
      }));
    }
  }, [draft.runtimeBackend, nativeAgentFeatureEnabled]);

  useEffect(() => {
    if (!canRunUnsafeCli && draft.bypassApprovalAndSandbox) {
      setDraft((prev) => ({ ...prev, bypassApprovalAndSandbox: false }));
    }
  }, [canRunUnsafeCli, draft.bypassApprovalAndSandbox]);

  const alias = draft.alias.trim();
  const isCli = draft.runtimeBackend === "cli";
  const isDeepSeek = draft.cliType === "deepseek";
  const nativeUnavailableReason = nativeAgentFeatureEnabled === false
    ? "原生 agent 全局未启用"
    : isDeepSeek ? "DeepSeek Harness 仅支持 CLI 运行" : "";
  const missing = [
    !alias && "别名",
    remoteCreate && !draft.remoteWorkspace && "远程工作目录",
  ].filter(Boolean);
  const canSubmit = canManage && !busy && missing.length === 0;
  const footHint = missing.length > 0
    ? `还需填写：${missing.join("、")}`
    : `将创建 ${alias.toLowerCase()} · ${isCli ? `CLI / ${cliTypeLabel(draft.cliType)}` : "原生 agent"} · ${remoteCreate ? "远程 SSH" : "本地"}`;

  // Segmented buttons, unlike the selects they replace, also fire for the active choice.
  function selectRuntimeBackend(runtimeBackend: CreateDraft["runtimeBackend"]) {
    if (runtimeBackend === draft.runtimeBackend) return;
    setDraft((prev) => ({
      ...prev,
      runtimeBackend,
      supportedExecutionModes: [runtimeBackend],
      defaultExecutionMode: runtimeBackend,
    }));
  }

  function selectCliType(cliType: CliType) {
    if (cliType === "deepseek") setRemoteCreate(false);
    setDraft((prev) => ({
      ...prev,
      cliType,
      cliPath: buildCreateDraft(cliType, bots).cliPath,
      ...(cliType === "deepseek" ? { remoteWorkspace: undefined, bypassApprovalAndSandbox: false } : {}),
    }));
  }

  function selectLocation(remote: boolean) {
    if (remote === remoteCreate) return;
    setRemoteCreate(remote);
    setDraft((prev) => ({ ...prev, remoteWorkspace: undefined }));
  }

  async function submit() {
    const created = await onCreate(draft);
    if (created) {
      setDraft(buildCreateDraft(draft.cliType, bots));
      setRemoteCreate(false);
      onCreated?.(created.alias);
    }
  }

  return (
    <div className="am-create" data-layout={layout}>
      <header className="am-create-head">
        <span
          aria-hidden="true"
          className="am-avatar am-avatar--lg am-create-avatar"
          data-empty={alias ? undefined : "true"}
          style={alias ? ({ "--am-identity": getBotAccentColor(alias) } as CSSProperties) : undefined}
        >
          {alias ? Array.from(alias)[0] : <Plus className="h-5 w-5" />}
        </span>
        <div className="am-create-head-copy">
          <h2 id={titleId} className="am-create-title">新增智能体</h2>
          <p className="am-create-description">{description}</p>
        </div>
        {onCancel ? (
          <button
            type="button"
            aria-label="取消新增智能体"
            title="取消"
            onClick={onCancel}
            disabled={busy}
            className="orbit-btn orbit-btn--ghost orbit-btn--icon orbit-btn--sm am-create-close"
          >
            <X aria-hidden="true" className="h-4 w-4" />
          </button>
        ) : null}
      </header>

      <fieldset aria-labelledby={titleId} disabled={!canManage || busy} className="am-create-body">
        <div className="am-create-col">
          <div className="am-create-row">
            <label htmlFor={aliasId} className="am-create-label">别名<em aria-hidden="true">*</em></label>
            <input
              id={aliasId}
              aria-label="新智能体别名"
              value={draft.alias}
              onChange={(event) => setDraft((prev) => ({ ...prev, alias: event.target.value }))}
              className="orbit-field am-create-input"
              placeholder="例如 team3"
              autoComplete="off"
              spellCheck={false}
            />
            <p className="am-create-hint">字母、数字、_ 或 -，2–32 位，保存时转为小写</p>
          </div>

          <section aria-labelledby={`${ids}-runtime`} className="am-create-group">
            <h3 id={`${ids}-runtime`} className="am-create-caption">运行方式</h3>
            <div className="am-create-row am-create-row--inline">
              <span id={`${ids}-backend`} className="am-create-label">运行后端</span>
              <div role="group" aria-labelledby={`${ids}-backend`} className="orbit-segmented orbit-segmented--accent am-create-segmented">
                <button type="button" aria-pressed={isCli} onClick={() => selectRuntimeBackend("cli")}>
                  <SquareTerminal aria-hidden="true" className="h-3.5 w-3.5" />
                  CLI
                </button>
                <button
                  type="button"
                  aria-pressed={!isCli}
                  disabled={isCli && Boolean(nativeUnavailableReason)}
                  title={nativeUnavailableReason || undefined}
                  onClick={() => selectRuntimeBackend("native_agent")}
                >
                  <Sparkles aria-hidden="true" className="h-3.5 w-3.5" />
                  原生 agent
                </button>
              </div>
              {nativeUnavailableReason ? <p className="am-create-hint">{nativeUnavailableReason}</p> : null}
            </div>

            {isCli ? (
              <>
                <div className="am-create-row">
                  <span id={`${ids}-cli-type`} className="am-create-label">CLI 类型</span>
                  <div role="radiogroup" aria-labelledby={`${ids}-cli-type`} className="am-create-choices">
                    {CLI_TYPE_CHOICES.map((cliType) => (
                      <label key={cliType} className="am-create-choice">
                        <input
                          type="radio"
                          name={`${ids}-cli-type`}
                          value={cliType}
                          checked={draft.cliType === cliType}
                          onChange={() => selectCliType(cliType)}
                        />
                        <span aria-hidden="true" className="am-create-choice-dot" style={getBotIdentityTextStyle(cliType)} />
                        {cliTypeLabel(cliType)}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="am-create-row">
                  <label htmlFor={cliPathId} className="am-create-label">CLI 路径</label>
                  <input
                    id={cliPathId}
                    aria-label="新智能体 CLI 路径"
                    value={draft.cliPath}
                    onChange={(event) => setDraft((prev) => ({ ...prev, cliPath: event.target.value }))}
                    className="orbit-field am-create-input am-create-mono"
                    placeholder={defaultCliPathForType(draft.cliType)}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <p className="am-create-hint">命令名或可执行文件的完整路径；留空使用默认命令 {defaultCliPathForType(draft.cliType)}</p>
                </div>
                {!isDeepSeek ? (
                  <label className="am-create-toggle" data-locked={canRunUnsafeCli ? undefined : "true"}>
                    <span aria-hidden="true" className="am-create-toggle-icon">
                      <ShieldAlert className="h-4 w-4" />
                    </span>
                    <span className="am-create-toggle-copy">
                      <span className="am-create-toggle-title">默认绕过审批和沙箱</span>
                      <span className="am-create-hint">
                        {canRunUnsafeCli ? "仅建议在可信工作区开启" : "当前账号无权开启此项"}
                      </span>
                    </span>
                    <input
                      type="checkbox"
                      aria-label="新智能体默认绕过审批和沙箱"
                      checked={canRunUnsafeCli ? Boolean(draft.bypassApprovalAndSandbox) : false}
                      onChange={(event) => setDraft((prev) => ({
                        ...prev,
                        bypassApprovalAndSandbox: canRunUnsafeCli ? event.target.checked : false,
                      }))}
                      disabled={!canRunUnsafeCli}
                      className="settings-switch"
                    />
                  </label>
                ) : null}
              </>
            ) : (
              <div className="am-create-row">
                <label htmlFor={piAgentId} className="am-create-label">Pi agent</label>
                <input
                  id={piAgentId}
                  aria-label="Pi agent"
                  value={draft.nativeAgent?.piAgent || DEFAULT_NATIVE_AGENT_DRAFT.piAgent}
                  onChange={(event) => setDraft((prev) => ({
                    ...prev,
                    nativeAgent: {
                      ...DEFAULT_NATIVE_AGENT_DRAFT,
                      ...(prev.nativeAgent || {}),
                      piAgent: event.target.value,
                    },
                  }))}
                  className="orbit-field am-create-input am-create-mono"
                  placeholder="main"
                  autoComplete="off"
                  spellCheck={false}
                />
                <p className="am-create-hint">Provider、模型、Base URL、API Key 和推理参数在全局环境配置中设置</p>
              </div>
            )}
          </section>
        </div>

        <div className="am-create-col">
          <section aria-labelledby={`${ids}-workspace`} className="am-create-group">
            <h3 id={`${ids}-workspace`} className="am-create-caption">工作区</h3>
            <div className="am-create-row am-create-row--inline">
              <span className="am-create-label">位置</span>
              <div role="group" aria-label="工作区位置" className="orbit-segmented orbit-segmented--accent am-create-segmented">
                <button type="button" aria-pressed={!remoteCreate} onClick={() => selectLocation(false)}>
                  <HardDrive aria-hidden="true" className="h-3.5 w-3.5" />
                  本地
                </button>
                <button
                  type="button"
                  aria-pressed={remoteCreate}
                  disabled={isDeepSeek}
                  title={isDeepSeek ? "DeepSeek Harness 仅支持本地工作区" : undefined}
                  onClick={() => selectLocation(true)}
                >
                  <Server aria-hidden="true" className="h-3.5 w-3.5" />
                  远程 SSH
                </button>
              </div>
              {isDeepSeek || remoteCreate ? (
                <p className="am-create-hint">
                  {isDeepSeek ? "DeepSeek Harness 仅支持本地工作区" : "智能体在本机运行，经 SSH 读写 Linux / Windows 远程目录"}
                </p>
              ) : null}
            </div>

            {remoteCreate ? (
              <div className="am-create-remote">
                <RemoteWorkspacePicker
                  client={client}
                  onPick={(remote) => setDraft((prev) => ({ ...prev, remoteWorkspace: { connectionId: remote.connectionId, root: remote.root } }))}
                />
              </div>
            ) : (
              <div className="am-create-row">
                <label htmlFor={workdirId} className="am-create-label">工作目录</label>
                <div className="am-create-inline">
                  <input
                    id={workdirId}
                    aria-label="新智能体工作目录"
                    value={draft.workingDir}
                    onChange={(event) => setDraft((prev) => ({ ...prev, workingDir: event.target.value }))}
                    className="orbit-field am-create-input am-create-mono"
                    placeholder={workdirPlaceholder(bots)}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <button
                    type="button"
                    aria-label="浏览新智能体工作目录"
                    onClick={() => setShowWorkdirPicker(true)}
                    className="orbit-btn orbit-btn--secondary"
                  >
                    <FolderOpen aria-hidden="true" className="h-4 w-4" />
                    浏览目录
                  </button>
                </div>
                <p className="am-create-hint">需为已存在的目录；留空使用服务的默认工作目录</p>
              </div>
            )}
          </section>
        </div>
      </fieldset>

      <footer className="am-create-foot">
        <p className="am-create-foot-hint">{footHint}</p>
        <div className="am-create-foot-actions">
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSubmit}
            className="orbit-btn orbit-btn--primary"
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            {savingAction === "create" ? "创建中..." : "创建智能体"}
          </button>
        </div>
      </footer>

      {showWorkdirPicker ? (
        <DirectoryPickerDialog
          title="选择工作目录"
          botAlias={directoryBrowserAlias}
          client={client}
          initialPath={draft.workingDir}
          mutateBrowseState={false}
          mode="workdir"
          canCreateDirectory={canCreateWorkdirDirectory}
          onPick={(workingDir) => setDraft((prev) => ({ ...prev, workingDir }))}
          onClose={() => setShowWorkdirPicker(false)}
        />
      ) : null}
    </div>
  );
}
