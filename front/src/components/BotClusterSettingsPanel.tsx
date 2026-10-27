import { useEffect, useState } from "react";
import { ClusterModelTiersPanel } from "./ClusterModelTiersPanel";
import { ClusterSetupPanel } from "./ClusterSetupPanel";
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

const TIERS: ClusterModelTier[] = ["low", "medium", "high"];

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
  modelTiers: { low: "", medium: "", high: "" },
  reasoningEfforts: { low: "", medium: "", high: "" },
  tierConfigs: {
    low: { ...EMPTY_TIER_CONFIG },
    medium: { ...EMPTY_TIER_CONFIG },
    high: { ...EMPTY_TIER_CONFIG },
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
    <section aria-labelledby="bot-cluster-settings-title" className="space-y-5 border-t border-[var(--border)] pt-5 text-sm">
      <div className="space-y-1">
        <h2 id="bot-cluster-settings-title" className="text-base font-semibold text-[var(--text)]">集群模式</h2>
        <p className="text-sm text-[var(--muted)]">子智能体由主 agent 按当前会话动态编组；这里配置并发、写入策略、超时和模型档位。</p>
      </div>
      {inheritedCliType === "deepseek" ? <p className="text-xs text-[var(--muted)]">DeepSeek Harness：集群轮次自动注入 MCP。</p> : null}
      {inheritedCliType === "deepseek" ? <p className="text-xs text-[var(--muted)]">集群档位继承主 Bot 的 Provider：DeepSeek。</p> : null}
      {nativeRuntime ? (
        <p className="text-xs text-[var(--muted)]">当前 Bot 使用原生 Agent/Pi 执行。模型档位沿用原生模型配置；为档位选择 CLI 会在保存时被拒绝。</p>
      ) : null}
      {error ? <p role="alert" className="text-sm text-[var(--feedback-error-text-deep)]">{error}</p> : null}
      <label className="flex items-center justify-between gap-3 border-y border-[var(--border)] py-3 font-medium text-[var(--text)]">
        <span>启用集群模式</span>
        <input type="checkbox" checked={cluster.enabled} disabled={!canManage || saving || !status} onChange={(event) => void save({ enabled: event.target.checked })} className="h-4 w-4" />
      </label>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="grid gap-1"><span className="font-medium text-[var(--text)]">并发规模</span><select aria-label="集群规模" value={cluster.maxParallelAgents} disabled={!canManage || saving} onChange={(event) => void save({ maxParallelAgents: Number(event.target.value) })} className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3">{Array.from({ length: 20 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="grid gap-1"><span className="font-medium text-[var(--text)]">子 Agent 写入策略</span><select aria-label="子 Agent 写入策略" value={cluster.writePolicy} disabled={!canManage || saving} onChange={(event) => void save({ writePolicy: event.target.value as BotClusterConfig["writePolicy"] })} className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3"><option value="main_only">仅主 Agent 可写</option><option value="all_agents">允许子 Agent 写入</option></select></label>
        <label className="grid gap-1"><span className="font-medium text-[var(--text)]">默认超时（秒）</span><input aria-label="任务超时（秒）" type="number" min={60} max={3600} value={timeoutDraft} disabled={!canManage || saving} onChange={(event) => setTimeoutDraft(event.target.value)} onBlur={() => void saveTimeout()} className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3" /></label>
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
    </section>
  );
}
