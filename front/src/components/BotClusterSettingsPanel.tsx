import { clsx } from "clsx";
import { LoaderCircle, Network } from "lucide-react";
import { useEffect, useState } from "react";
import { ClusterModelTiersPanel } from "./ClusterModelTiersPanel";
import { ClusterSetupPanel } from "./ClusterSetupPanel";
import { SettingsField, SettingsSection, SettingsSwitch, settingsControlClassName } from "./SettingsSection";
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

export function BotClusterSettingsPanel({ botAlias, client, overview, canManage = true }: Props) {
  const [cluster, setCluster] = useState<BotClusterConfig>(() => cloneCluster(overview?.cluster));
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [cliParamsByType, setCliParamsByType] = useState<Partial<Record<string, CliParamsPayload>>>({});
  const [nativeModels, setNativeModels] = useState<NativeAgentModelsPayload | null>(null);
  const [timeoutDraft, setTimeoutDraft] = useState(String(cluster.defaultTimeoutSeconds));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const nativeRuntime = overview?.defaultExecutionMode === "native_agent" || overview?.executionMode === "native_agent";
  const inheritedCliType = String(overview?.cliType || "codex");
  const mainCliParams = cliParamsByType[inheritedCliType];

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
    setTimeoutDraft(String(nextCluster.defaultTimeoutSeconds));

    if (nativeRuntime) {
      const modelsResult = await Promise.allSettled([client.getNativeAgentModels(botAlias)]);
      const modelValue = modelsResult[0];
      if (modelValue.status === "fulfilled") setNativeModels(modelValue.value);
      return;
    }

    const types = tierConfigTypes(nextCluster.tierConfigs, inheritedCliType);
    const paramsResults = await Promise.allSettled(types.map((cliType) => client.getCliParams(botAlias, cliType as CliType)));
    const paramsByType: Partial<Record<string, CliParamsPayload>> = {};
    paramsResults.forEach((result, index) => {
      if (result.status === "fulfilled") paramsByType[types[index]] = result.value;
    });
    setCliParamsByType(paramsByType);
  }

  useEffect(() => {
    setCluster(cloneCluster(overview?.cluster));
    setTimeoutDraft(String(overview?.cluster?.defaultTimeoutSeconds || DEFAULT_CLUSTER.defaultTimeoutSeconds));
    void load();
  }, [botAlias, client, nativeRuntime, overview?.alias, overview?.cluster]);

  async function save(patch: Partial<BotClusterConfig>) {
    if (!canManage) return;
    const mergedTierConfigs = cloneTierConfigs(
      patch.tierConfigs || cluster.tierConfigs,
      cluster.modelTiers,
      cluster.reasoningEfforts,
    );
    const nextModelTiers = { ...cluster.modelTiers };
    const nextReasoningEfforts = { ...cluster.reasoningEfforts };
    for (const tier of TIERS) {
      if (patch.tierConfigs?.[tier]) {
        nextModelTiers[tier] = mergedTierConfigs[tier].model;
        nextReasoningEfforts[tier] = mergedTierConfigs[tier].reasoningEffort;
      }
    }
    const next: BotClusterConfig = {
      ...cluster,
      ...patch,
      modelTiers: { ...nextModelTiers, ...(patch.modelTiers || {}) },
      reasoningEfforts: { ...nextReasoningEfforts, ...(patch.reasoningEfforts || {}) },
      tierConfigs: mergedTierConfigs,
    };
    setSaving(true);
    setError("");
    try {
      const result = await client.updateClusterConfig(botAlias, next);
      setCluster(cloneCluster(result.cluster));
      setStatus(result.status);
      setTimeoutDraft(String(result.cluster.defaultTimeoutSeconds));
      if (!nativeRuntime) {
        const types = tierConfigTypes(result.cluster.tierConfigs, inheritedCliType);
        const paramsResults = await Promise.allSettled(types.map((cliType) => client.getCliParams(botAlias, cliType as CliType)));
        setCliParamsByType((current) => {
          const next = { ...current };
          paramsResults.forEach((paramsResult, index) => {
            if (paramsResult.status === "fulfilled") next[types[index]] = paramsResult.value;
          });
          return next;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存集群配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveTimeout() {
    const value = Number(timeoutDraft);
    if (!Number.isInteger(value) || value < 60 || value > 3600) {
      setTimeoutDraft(String(cluster.defaultTimeoutSeconds));
      setError("任务超时必须是 60 到 3600 之间的整数");
      return;
    }
    if (value !== cluster.defaultTimeoutSeconds) await save({ defaultTimeoutSeconds: value });
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
      )}
      actions={(
        <>
          {saving ? <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin text-[var(--muted)]" /> : null}
          <SettingsSwitch
            aria-label="启用集群模式"
            title="启用集群模式"
            checked={cluster.enabled}
            disabled={!canManage || saving || !status}
            onChange={(event) => void save({ enabled: event.target.checked })}
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
            <select aria-label="集群规模" value={cluster.maxParallelAgents} disabled={!canManage || saving} onChange={(event) => void save({ maxParallelAgents: Number(event.target.value) })} className={settingsControlClassName}>
              {Array.from({ length: 20 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </SettingsField>
          <SettingsField label="子 Agent 写入策略">
            <select aria-label="子 Agent 写入策略" value={cluster.writePolicy} disabled={!canManage || saving} onChange={(event) => void save({ writePolicy: event.target.value as BotClusterConfig["writePolicy"] })} className={settingsControlClassName}>
              <option value="main_only">仅主 Agent 可写</option>
              <option value="all_agents">允许子 Agent 写入</option>
            </select>
          </SettingsField>
          <SettingsField label="默认超时（秒）">
            <input aria-label="任务超时（秒）" type="number" min={60} max={3600} value={timeoutDraft} disabled={!canManage || saving} onChange={(event) => setTimeoutDraft(event.target.value)} onBlur={() => void saveTimeout()} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} className={settingsControlClassName} />
          </SettingsField>
        </div>
        <ClusterModelTiersPanel
          value={cluster.modelTiers}
          reasoningEfforts={cluster.reasoningEfforts}
          tierConfigs={cluster.tierConfigs}
          cliParamsByType={cliParamsByType}
          inheritedCliType={inheritedCliType}
          nativeRuntime={nativeRuntime}
          modelOptions={fallbackModelOptions}
          reasoningOptions={fallbackReasoningOptions}
          disabled={!canManage || saving}
          onTierConfigChange={(tier, next) => void save({ tierConfigs: { ...cluster.tierConfigs, [tier]: next } as ClusterTierConfigs })}
          onChange={(modelTiers) => void save({ modelTiers })}
          onReasoningChange={(reasoningEfforts) => void save({ reasoningEfforts })}
        />
        <ClusterSetupPanel botAlias={botAlias} client={client} canManage={canManage} />
      </div>
    </SettingsSection>
  );
}
