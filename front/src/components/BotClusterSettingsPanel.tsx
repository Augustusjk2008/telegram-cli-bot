import { clsx } from "clsx";
import { LoaderCircle, Network, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clusterDraftEquals } from "../utils/clusterDraft";
import { ClusterModelTiersPanel } from "./ClusterModelTiersPanel";
import { ClusterSetupPanel } from "./ClusterSetupPanel";
import {
  SettingsDirtyBadge,
  SettingsField,
  SettingsSection,
  SettingsSwitch,
  settingsButtonClassName,
  settingsControlClassName,
  settingsPrimaryButtonClassName,
} from "./SettingsSection";
import type {
  BotClusterConfig,
  BotOverview,
  CliParamsPayload,
  CliType,
  ClusterModelTier,
  ClusterStatus,
  ClusterTierConfig,
  ClusterTierConfigs,
  NativeAgentModelsPayload,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  overview?: BotOverview | null;
  canManage?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
};

const TIERS: ClusterModelTier[] = ["low", "medium", "high", "professional"];

const EMPTY_TIER_CONFIG: ClusterTierConfig = {
  cliType: "",
  cliPath: "",
  provider: "",
  model: "",
  reasoningEffort: "",
};

const DEFAULT_CLUSTER: BotClusterConfig = {
  enabled: false,
  writePolicy: "main_only",
  maxParallelAgents: 1,
  defaultTimeoutSeconds: 600,
  modelTiers: { low: "", medium: "", high: "", professional: "" },
  reasoningEfforts: { low: "", medium: "", high: "", professional: "" },
  tierConfigs: {
    low: { ...EMPTY_TIER_CONFIG },
    medium: { ...EMPTY_TIER_CONFIG },
    high: { ...EMPTY_TIER_CONFIG },
    professional: { ...EMPTY_TIER_CONFIG },
  },
};

function cloneTierConfigs(
  value: Partial<ClusterTierConfigs> | undefined,
  modelTiers: BotClusterConfig["modelTiers"],
  reasoningEfforts: BotClusterConfig["reasoningEfforts"],
): ClusterTierConfigs {
  return Object.fromEntries(TIERS.map((tier) => [
    tier,
    {
      ...EMPTY_TIER_CONFIG,
      model: modelTiers[tier],
      reasoningEffort: reasoningEfforts[tier],
      ...(value?.[tier] || {}),
    },
  ])) as ClusterTierConfigs;
}

function cloneCluster(value?: BotClusterConfig | null): BotClusterConfig {
  const modelTiers = { ...(value?.modelTiers || DEFAULT_CLUSTER.modelTiers) };
  const reasoningEfforts = { ...(value?.reasoningEfforts || DEFAULT_CLUSTER.reasoningEfforts) };
  return {
    ...(value || DEFAULT_CLUSTER),
    modelTiers,
    reasoningEfforts,
    tierConfigs: cloneTierConfigs(value?.tierConfigs, modelTiers, reasoningEfforts),
  };
}

function tierConfigTypes(configs: ClusterTierConfigs | undefined, inheritedCliType: string) {
  return Array.from(new Set([
    inheritedCliType,
    ...TIERS.map((tier) => String(configs?.[tier]?.cliType || "").trim()).filter(Boolean),
  ].filter(Boolean)));
}

export function BotClusterSettingsPanel({ botAlias, client, overview, canManage = true, onDirtyChange }: Props) {
  // `cluster` mirrors the persisted config; `draft` holds edits until the user saves them together.
  const [cluster, setCluster] = useState<BotClusterConfig>(() => cloneCluster(overview?.cluster));
  const [draft, setDraft] = useState<BotClusterConfig>(() => cloneCluster(overview?.cluster));
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [cliParamsByType, setCliParamsByType] = useState<Partial<Record<string, CliParamsPayload>>>({});
  const [nativeModels, setNativeModels] = useState<NativeAgentModelsPayload | null>(null);
  const [timeoutDraft, setTimeoutDraft] = useState(String(cluster.defaultTimeoutSeconds));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const cliParamsScopeRef = useRef(0);
  const requestedCliTypesRef = useRef<Set<string>>(new Set());
  const [cliParamsScope, setCliParamsScope] = useState(0);

  const nativeRuntime = overview?.defaultExecutionMode === "native_agent" || overview?.executionMode === "native_agent";
  const inheritedCliType = String(overview?.cliType || "codex");
  const mainCliParams = cliParamsByType[inheritedCliType];
  const dirty = !clusterDraftEquals(draft, cluster) || timeoutDraft.trim() !== String(cluster.defaultTimeoutSeconds);
  const draftCliTypesKey = nativeRuntime ? "" : tierConfigTypes(draft.tierConfigs, inheritedCliType).join("\n");

  const onDirtyChangeRef = useRef(onDirtyChange);
  useEffect(() => {
    onDirtyChangeRef.current = onDirtyChange;
  }, [onDirtyChange]);

  useEffect(() => {
    onDirtyChangeRef.current?.(dirty);
  }, [dirty]);

  useEffect(() => () => onDirtyChangeRef.current?.(false), []);

  async function load() {
    setError("");
    const statusResult = await Promise.allSettled([client.getClusterStatus(botAlias)]);
    const statusValue = statusResult[0];
    if (statusValue.status !== "fulfilled") {
      setError(statusValue.reason instanceof Error ? statusValue.reason.message : "加载集群状态失败");
      return;
    }

    const nextStatus = statusValue.value;
    setStatus(nextStatus);
    const nextCluster = cloneCluster({
      ...(overview?.cluster || DEFAULT_CLUSTER),
      enabled: nextStatus.enabled,
      modelTiers: { ...(overview?.cluster?.modelTiers || {}), ...nextStatus.modelTiers },
      reasoningEfforts: { ...(overview?.cluster?.reasoningEfforts || {}), ...nextStatus.reasoningEfforts },
      tierConfigs: nextStatus.tierConfigs || overview?.cluster?.tierConfigs,
    });
    setCluster(nextCluster);
    setDraft(nextCluster);
    setTimeoutDraft(String(nextCluster.defaultTimeoutSeconds));

    if (nativeRuntime) {
      const modelsResult = await Promise.allSettled([client.getNativeAgentModels(botAlias)]);
      const modelValue = modelsResult[0];
      if (modelValue.status === "fulfilled") setNativeModels(modelValue.value);
    }
  }

  useEffect(() => {
    const nextCluster = cloneCluster(overview?.cluster);
    setCluster(nextCluster);
    setDraft(nextCluster);
    setTimeoutDraft(String(overview?.cluster?.defaultTimeoutSeconds || DEFAULT_CLUSTER.defaultTimeoutSeconds));
    // CLI params are per Bot and may change with its runtime, so reload them for the new scope.
    cliParamsScopeRef.current += 1;
    requestedCliTypesRef.current = new Set();
    setCliParamsByType({});
    setCliParamsScope(cliParamsScopeRef.current);
    void load();
  }, [botAlias, client, nativeRuntime, overview?.alias, overview?.cluster]);

  useEffect(() => {
    // Draft tiers can pick a CLI that has not been loaded yet; fetch its options before saving.
    if (nativeRuntime || !draftCliTypesKey) return;
    const missing = draftCliTypesKey.split("\n").filter((cliType) => !requestedCliTypesRef.current.has(cliType));
    if (!missing.length) return;
    missing.forEach((cliType) => requestedCliTypesRef.current.add(cliType));
    const scope = cliParamsScopeRef.current;
    void Promise.allSettled(missing.map((cliType) => client.getCliParams(botAlias, cliType as CliType))).then((results) => {
      if (scope !== cliParamsScopeRef.current) return;
      setCliParamsByType((current) => {
        const next = { ...current };
        results.forEach((result, index) => {
          if (result.status === "fulfilled") next[missing[index]] = result.value;
          else requestedCliTypesRef.current.delete(missing[index]);
        });
        return next;
      });
    });
  }, [botAlias, client, nativeRuntime, draftCliTypesKey, cliParamsScope]);

  async function persist(next: BotClusterConfig, options: { replaceDraft: boolean }) {
    setSaving(true);
    setError("");
    try {
      const result = await client.updateClusterConfig(botAlias, next);
      const saved = cloneCluster(result.cluster);
      setCluster(saved);
      setStatus(result.status);
      if (options.replaceDraft) {
        setDraft(saved);
        setTimeoutDraft(String(saved.defaultTimeoutSeconds));
      } else {
        setDraft((current) => ({ ...current, enabled: saved.enabled }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存集群配置失败");
    } finally {
      setSaving(false);
    }
  }

  // The switch applies immediately and leaves unsaved field edits in the draft.
  async function toggleEnabled(enabled: boolean) {
    if (!canManage) return;
    await persist({ ...cluster, enabled }, { replaceDraft: false });
  }

  async function saveDraft() {
    if (!canManage || saving || !dirty) return;
    const timeout = Number(timeoutDraft.trim());
    if (!Number.isInteger(timeout) || timeout < 60 || timeout > 3600) {
      setError("任务超时必须是 60 到 3600 之间的整数");
      return;
    }
    await persist({
      ...draft,
      enabled: cluster.enabled,
      defaultTimeoutSeconds: timeout,
      tierConfigs: cloneTierConfigs(draft.tierConfigs, draft.modelTiers, draft.reasoningEfforts),
    }, { replaceDraft: true });
  }

  function resetDraft() {
    setDraft(cluster);
    setTimeoutDraft(String(cluster.defaultTimeoutSeconds));
    setError("");
  }

  function updateDraftTier(tier: ClusterModelTier, next: ClusterTierConfig) {
    setDraft((current) => ({
      ...current,
      modelTiers: { ...current.modelTiers, [tier]: next.model },
      reasoningEfforts: { ...current.reasoningEfforts, [tier]: next.reasoningEffort },
      tierConfigs: { ...current.tierConfigs, [tier]: next } as ClusterTierConfigs,
    }));
  }

  const fallbackModelOptions = nativeRuntime
    ? nativeModels?.items.map((item) => item.id) || []
    : mainCliParams?.schema.model?.enum || [];
  const fallbackReasoningOptions = nativeRuntime
    ? (model: string) => {
      const selected = model || nativeModels?.selectedModel || overview?.nativeAgent?.model || "";
      return nativeModels?.items.find((item) => item.id === selected)?.reasoningEfforts || [];
    }
    : mainCliParams?.schema.reasoning_effort?.enum || mainCliParams?.schema.effort?.enum || [];

  return (
    <SettingsSection
      id="settings-section-cluster"
      titleId="bot-cluster-settings-title"
      icon={<Network className="h-3.5 w-3.5" />}
      title="集群模式"
      description="子智能体由主 agent 按当前会话动态编组；这里配置并发、写入策略、超时和模型档位。"
      badge={(
        <>
        <span
          className={clsx(
            "inline-flex h-4 items-center rounded-full px-1.5 text-[10px] font-medium",
            cluster.enabled
              ? "bg-[var(--status-success-bg)] text-[var(--status-success)]"
              : "bg-[var(--workbench-active-bg)] text-[var(--muted)]",
          )}
        >
          {cluster.enabled ? "已启用" : "未启用"}
        </span>
        {dirty ? <SettingsDirtyBadge /> : null}
        </>
      )}
      actions={(
        <>
          {saving ? <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin text-[var(--muted)]" /> : null}
          <SettingsSwitch
            aria-label="启用集群模式"
            title="启用集群模式"
            checked={cluster.enabled}
            disabled={!canManage || saving || !status}
            onChange={(event) => void toggleEnabled(event.target.checked)}
          />
        </>
      )}
    >
      <div className="space-y-2.5">
        {inheritedCliType === "deepseek" || nativeRuntime ? (
          <div className="space-y-0.5 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2.5 py-1.5 text-[11px] leading-4 text-[var(--muted)]">
            {inheritedCliType === "deepseek" ? <p>DeepSeek Harness：集群轮次自动注入 MCP。</p> : null}
            {inheritedCliType === "deepseek" ? <p>集群档位继承主 Bot 的 Provider：DeepSeek。</p> : null}
            {nativeRuntime ? <p>当前 Bot 使用原生 Agent/Pi 执行。模型档位沿用原生模型配置；为档位选择 CLI 会在保存时被拒绝。</p> : null}
          </div>
        ) : null}
        {error ? <p role="alert" className="text-xs text-[var(--feedback-error-text-deep)]">{error}</p> : null}
        <div className="grid gap-2 @sm:grid-cols-2 @xl:grid-cols-3">
          <SettingsField label="并发规模">
            <select aria-label="集群规模" value={draft.maxParallelAgents} disabled={!canManage || saving} onChange={(event) => setDraft((current) => ({ ...current, maxParallelAgents: Number(event.target.value) }))} className={settingsControlClassName}>
              {Array.from({ length: 20 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </SettingsField>
          <SettingsField label="子 Agent 写入策略">
            <select aria-label="子 Agent 写入策略" value={draft.writePolicy} disabled={!canManage || saving} onChange={(event) => setDraft((current) => ({ ...current, writePolicy: event.target.value as BotClusterConfig["writePolicy"] }))} className={settingsControlClassName}>
              <option value="main_only">仅主 Agent 可写</option>
              <option value="all_agents">允许子 Agent 写入</option>
            </select>
          </SettingsField>
          <SettingsField label="默认超时（秒）">
            <input aria-label="任务超时（秒）" type="number" min={60} max={3600} value={timeoutDraft} disabled={!canManage || saving} onChange={(event) => setTimeoutDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); void saveDraft(); } }} className={settingsControlClassName} />
          </SettingsField>
        </div>
        <ClusterModelTiersPanel
          value={draft.modelTiers}
          reasoningEfforts={draft.reasoningEfforts}
          tierConfigs={draft.tierConfigs}
          cliParamsByType={cliParamsByType}
          inheritedCliType={inheritedCliType}
          nativeRuntime={nativeRuntime}
          modelOptions={fallbackModelOptions}
          reasoningOptions={fallbackReasoningOptions}
          disabled={!canManage || saving}
          onTierConfigChange={updateDraftTier}
          onChange={(modelTiers) => setDraft((current) => ({ ...current, modelTiers }))}
          onReasoningChange={(reasoningEfforts) => setDraft((current) => ({ ...current, reasoningEfforts }))}
        />
        <div className="flex items-center justify-end gap-2">
          {dirty ? (
            <button type="button" onClick={resetDraft} disabled={saving} className={settingsButtonClassName}>
              还原
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void saveDraft()}
            disabled={!canManage || saving || !dirty}
            className={settingsPrimaryButtonClassName}
          >
            {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            {saving ? "保存中..." : "保存集群配置"}
          </button>
        </div>
        <ClusterSetupPanel botAlias={botAlias} client={client} canManage={canManage} />
      </div>
    </SettingsSection>
  );
}
