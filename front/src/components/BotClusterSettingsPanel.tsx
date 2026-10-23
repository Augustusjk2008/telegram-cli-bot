import { useEffect, useState } from "react";
import { ClusterModelTiersPanel } from "./ClusterModelTiersPanel";
import { ClusterSetupPanel } from "./ClusterSetupPanel";
import type {
  BotClusterConfig,
  BotOverview,
  CliParamsPayload,
  ClusterStatus,
  NativeAgentModelsPayload,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  overview?: BotOverview | null;
  canManage?: boolean;
};

const DEFAULT_CLUSTER: BotClusterConfig = {
  enabled: false,
  writePolicy: "main_only",
  maxParallelAgents: 1,
  defaultTimeoutSeconds: 600,
  modelTiers: { low: "", medium: "", high: "" },
  reasoningEfforts: { low: "", medium: "", high: "" },
};

function cloneCluster(value?: BotClusterConfig | null): BotClusterConfig {
  return {
    ...(value || DEFAULT_CLUSTER),
    modelTiers: { ...(value?.modelTiers || DEFAULT_CLUSTER.modelTiers) },
    reasoningEfforts: { ...(value?.reasoningEfforts || DEFAULT_CLUSTER.reasoningEfforts) },
  };
}

export function BotClusterSettingsPanel({ botAlias, client, overview, canManage = true }: Props) {
  const [cluster, setCluster] = useState<BotClusterConfig>(() => cloneCluster(overview?.cluster));
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [cliParams, setCliParams] = useState<CliParamsPayload | null>(null);
  const [nativeModels, setNativeModels] = useState<NativeAgentModelsPayload | null>(null);
  const [timeoutDraft, setTimeoutDraft] = useState(String(cluster.defaultTimeoutSeconds));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const nativeRuntime = overview?.defaultExecutionMode === "native_agent" || overview?.executionMode === "native_agent";

  async function load() {
    setError("");
    const results = await Promise.allSettled([
      client.getClusterStatus(botAlias),
      nativeRuntime ? client.getNativeAgentModels(botAlias) : Promise.resolve(null),
      nativeRuntime ? Promise.resolve(null) : client.getCliParams(botAlias),
    ]);
    const [statusResult, modelsResult, cliResult] = results;
    if (statusResult.status === "fulfilled") {
      setStatus(statusResult.value);
      setCluster((current) => ({
        ...current,
        enabled: statusResult.value.enabled,
        modelTiers: { ...current.modelTiers, ...statusResult.value.modelTiers },
        reasoningEfforts: { ...current.reasoningEfforts, ...statusResult.value.reasoningEfforts },
      }));
    } else {
      setError(statusResult.reason instanceof Error ? statusResult.reason.message : "加载集群状态失败");
    }
    if (modelsResult.status === "fulfilled" && modelsResult.value) setNativeModels(modelsResult.value);
    if (cliResult.status === "fulfilled" && cliResult.value) setCliParams(cliResult.value);
  }

  useEffect(() => {
    setCluster(cloneCluster(overview?.cluster));
    setTimeoutDraft(String(overview?.cluster?.defaultTimeoutSeconds || DEFAULT_CLUSTER.defaultTimeoutSeconds));
    void load();
  }, [botAlias, client, nativeRuntime, overview?.alias, overview?.cluster]);

  async function save(patch: Partial<BotClusterConfig>) {
    if (!canManage) return;
    const next: BotClusterConfig = {
      ...cluster,
      ...patch,
      modelTiers: { ...cluster.modelTiers, ...(patch.modelTiers || {}) },
      reasoningEfforts: { ...cluster.reasoningEfforts, ...(patch.reasoningEfforts || {}) },
    };
    if (nativeRuntime) {
      for (const tier of ["low", "medium", "high"] as const) {
        if (next.reasoningEfforts[tier] && !reasoningOptions(next.modelTiers[tier]).includes(next.reasoningEfforts[tier])) {
          next.reasoningEfforts[tier] = "";
        }
      }
    }
    setSaving(true);
    setError("");
    try {
      const result = await client.updateClusterConfig(botAlias, next);
      setCluster(cloneCluster(result.cluster));
      setStatus(result.status);
      setTimeoutDraft(String(result.cluster.defaultTimeoutSeconds));
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

  function reasoningOptions(model: string) {
    if (nativeRuntime) {
      const selected = model || nativeModels?.selectedModel || overview?.nativeAgent?.model || "";
      return nativeModels?.items.find((item) => item.id === selected)?.reasoningEfforts || [];
    }
    return cliParams?.schema.reasoning_effort?.enum || cliParams?.schema.effort?.enum || [];
  }

  return (
    <section aria-labelledby="bot-cluster-settings-title" className="space-y-5 border-t border-[var(--border)] pt-5 text-sm">
      <div className="space-y-1">
        <h2 id="bot-cluster-settings-title" className="text-base font-semibold text-[var(--text)]">集群模式</h2>
        <p className="text-sm text-[var(--muted)]">子智能体由主 agent 按当前会话动态编组；这里配置并发、写入策略、超时和模型档位。</p>
      </div>
      {overview?.cliType === "deepseek" ? <p className="text-xs text-[var(--muted)]">DeepSeek Harness：集群轮次自动注入 MCP。</p> : null}
      {error ? <p role="alert" className="text-sm text-[var(--feedback-error-text-deep)]">{error}</p> : null}
      <label className="flex items-center justify-between gap-3 border-y border-[var(--border)] py-3 font-medium text-[var(--text)]">
        <span>启用集群模式</span>
        <input type="checkbox" checked={cluster.enabled} disabled={!canManage || saving || !status} onChange={(event) => void save({ enabled: event.target.checked })} className="h-4 w-4" />
      </label>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="grid gap-1"><span className="font-medium text-[var(--text)]">并发规模</span><select aria-label="集群规模" value={cluster.maxParallelAgents} disabled={!canManage || saving} onChange={(event) => void save({ maxParallelAgents: Number(event.target.value) })} className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3"><option value={1}>1</option>{[2, 3, 4, 5, 6, 7, 8].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="grid gap-1"><span className="font-medium text-[var(--text)]">子 Agent 写入策略</span><select aria-label="子 Agent 写入策略" value={cluster.writePolicy} disabled={!canManage || saving} onChange={(event) => void save({ writePolicy: event.target.value as BotClusterConfig["writePolicy"] })} className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3"><option value="main_only">仅主 Agent 可写</option><option value="all_agents">允许子 Agent 写入</option></select></label>
        <label className="grid gap-1"><span className="font-medium text-[var(--text)]">默认超时（秒）</span><input aria-label="任务超时（秒）" type="number" min={60} max={3600} value={timeoutDraft} disabled={!canManage || saving} onChange={(event) => setTimeoutDraft(event.target.value)} onBlur={() => void saveTimeout()} className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3" /></label>
      </div>
      <ClusterModelTiersPanel value={cluster.modelTiers} reasoningEfforts={cluster.reasoningEfforts} modelOptions={nativeRuntime ? nativeModels?.items.map((item) => item.id) || [] : cliParams?.schema.model?.enum || []} reasoningOptions={reasoningOptions} disabled={!canManage || saving} onChange={(value) => void save({ modelTiers: value })} onReasoningChange={(value) => void save({ reasoningEfforts: value })} />
      <ClusterSetupPanel botAlias={botAlias} client={client} canManage={canManage} />
    </section>
  );
}
