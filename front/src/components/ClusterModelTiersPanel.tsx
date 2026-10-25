import type {
  CliParamsPayload,
  CliType,
  ClusterModelTiers,
  ClusterReasoningEfforts,
  ClusterTierConfig,
  ClusterTierConfigs,
} from "../services/types";

type TierKey = keyof ClusterModelTiers;

type Props = {
  value: ClusterModelTiers;
  reasoningEfforts: ClusterReasoningEfforts;
  modelOptions: string[];
  reasoningOptions: string[] | ((model: string) => string[]);
  disabled?: boolean;
  onChange: (next: ClusterModelTiers) => void;
  onReasoningChange: (next: ClusterReasoningEfforts) => void;
  tierConfigs?: ClusterTierConfigs;
  cliParamsByType?: Partial<Record<string, CliParamsPayload>>;
  inheritedCliType?: CliType | string;
  nativeRuntime?: boolean;
  onTierConfigChange?: (tier: TierKey, next: ClusterTierConfig) => void;
};

const TIER_LABELS: Array<{ key: TierKey; label: string; hint: string }> = [
  { key: "low", label: "低档", hint: "快、省 token" },
  { key: "medium", label: "中档", hint: "均衡" },
  { key: "high", label: "高档", hint: "复杂任务" },
];

const CLI_OPTIONS: Array<{ value: CliType; label: string }> = [
  { value: "codex", label: "Codex" },
  { value: "codex_server", label: "Codex Server" },
  { value: "claude", label: "Claude" },
  { value: "antigravity", label: "Antigravity" },
  { value: "deepseek", label: "DeepSeek Harness" },
];

const EMPTY_TIER_CONFIG: ClusterTierConfig = {
  cliType: "",
  cliPath: "",
  provider: "",
  model: "",
  reasoningEffort: "",
};

function uniqueOptions(values: string[]) {
  return Array.from(new Set(values.map((value) => String(value || "").trim()).filter(Boolean)));
}

function paramsForTier(
  config: ClusterTierConfig,
  inheritedCliType: string,
  cliParamsByType: Partial<Record<string, CliParamsPayload>>,
) {
  return cliParamsByType[config.cliType || inheritedCliType];
}

function modelOptionsForTier(config: ClusterTierConfig, params: CliParamsPayload | undefined, fallback: string[]) {
  if (params?.cliType === "deepseek") {
    const providerId = config.provider || params.selectedProvider || String(params.params.provider || "");
    const providerModels = params.modelOptionsByProvider?.[providerId] || [];
    if (providerModels.length) return providerModels.map((model) => model.id);
  }
  return params?.schema.model?.enum?.length ? params.schema.model.enum : fallback;
}

function reasoningOptionsForTier(
  config: ClusterTierConfig,
  params: CliParamsPayload | undefined,
  fallback: string[] | ((model: string) => string[]),
) {
  if (!params) return typeof fallback === "function" ? fallback(config.model) : fallback;
  if (params.cliType === "deepseek") {
    const providerId = config.provider || params.selectedProvider || String(params.params.provider || "");
    const model = params.modelOptionsByProvider?.[providerId]?.find((item) => item.id === config.model);
    if (model?.reasoningEfforts?.length) return model.reasoningEfforts;
    const provider = params.providerOptions?.find((item) => item.id === providerId);
    if (provider?.reasoningEfforts?.length) return provider.reasoningEfforts;
  }
  return params.schema.reasoning_effort?.enum || params.schema.effort?.enum || [];
}

export function ClusterModelTiersPanel({
  value,
  reasoningEfforts,
  modelOptions,
  reasoningOptions,
  disabled,
  onChange,
  onReasoningChange,
  tierConfigs,
  cliParamsByType = {},
  inheritedCliType = "codex",
  nativeRuntime = false,
  onTierConfigChange,
}: Props) {
  const hasTierCliConfig = Boolean(onTierConfigChange || tierConfigs);

  function updateTier(tier: TierKey, patch: Partial<ClusterTierConfig>) {
    const current: ClusterTierConfig = {
      ...EMPTY_TIER_CONFIG,
      model: value[tier],
      reasoningEffort: reasoningEfforts[tier],
      ...(tierConfigs?.[tier] || {}),
    };
    const next = { ...current, ...patch };
    if (typeof patch.provider === "string" && patch.provider !== current.provider) {
      next.model = "";
      next.reasoningEffort = "";
    }
    if (onTierConfigChange) {
      onTierConfigChange(tier, next);
      return;
    }
    if (typeof patch.model === "string") onChange({ ...value, [tier]: patch.model });
    if (typeof patch.reasoningEffort === "string") {
      onReasoningChange({ ...reasoningEfforts, [tier]: patch.reasoningEffort });
    }
  }

  return (
    <section className="space-y-3 border-t border-[var(--border)] pt-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">集群模型档位</h3>
      <p className="mt-1 text-sm text-[var(--muted)]">
        每档可选择执行 CLI、模型和思考深度；留空时继承所选 CLI 配置。
      </p>
      {nativeRuntime && hasTierCliConfig ? (
        <p role="alert" className="text-xs text-[var(--feedback-error-text-deep)]">
          原生 Agent/Pi Bot 不支持为集群档位配置 CLI。请清空已有的执行 CLI 后再保存。
        </p>
      ) : null}
      <div className="divide-y divide-[var(--border)]">
        {TIER_LABELS.map((tier) => {
          const config: ClusterTierConfig = {
            ...EMPTY_TIER_CONFIG,
            model: value[tier.key],
            reasoningEffort: reasoningEfforts[tier.key],
            ...(tierConfigs?.[tier.key] || {}),
          };
          const selectedCliType = config.cliType || String(inheritedCliType || "codex");
          const params = paramsForTier(config, String(inheritedCliType || "codex"), cliParamsByType);
          const models = uniqueOptions(modelOptionsForTier(config, params, modelOptions));
          const efforts = uniqueOptions(reasoningOptionsForTier(config, params, reasoningOptions));
          const providerOptions = params?.cliType === "deepseek" ? params.providerOptions || [] : [];
          const providerId = config.provider || params?.selectedProvider || String(params?.params.provider || "");
          const unavailableModel = Boolean(config.model && !models.includes(config.model));
          const unavailableEffort = Boolean(config.reasoningEffort && !efforts.includes(config.reasoningEffort));
          const cliStatus = params?.availability && params.availability !== "available"
            ? params.diagnostic || `CLI 状态：${params.availability}`
            : "";
          return (
            <div key={tier.key} className="grid gap-3 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(90px,0.55fr)_minmax(0,1.2fr)_minmax(0,1.2fr)] sm:items-end">
              <div className="text-sm font-medium text-[var(--text)] sm:pb-2">
                {tier.label} <span className="text-xs font-normal text-[var(--muted)]">{tier.hint}</span>
              </div>
              {hasTierCliConfig ? (
                <label className="grid gap-1 text-sm">
                  <span className="text-xs text-[var(--muted)]">执行 CLI</span>
                  <select
                    aria-label={`${tier.label}执行 CLI`}
                    value={config.cliType}
                    disabled={disabled || nativeRuntime}
                    onChange={(event) => updateTier(tier.key, {
                      cliType: event.target.value,
                      model: "",
                      reasoningEffort: "",
                      provider: "",
                    })}
                    className="h-9 min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  >
                    <option value="">继承主 Bot CLI（{String(inheritedCliType || "codex")}）</option>
                    {CLI_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  {cliStatus ? <span className="text-xs text-[var(--feedback-error-text-deep)]">{cliStatus}</span> : null}
                </label>
              ) : null}
              <label className="grid gap-1 text-sm">
                <span className="text-xs text-[var(--muted)]">模型</span>
                <select
                  aria-label={`${tier.label}模型`}
                  value={config.model}
                  disabled={disabled}
                  onChange={(event) => updateTier(tier.key, { model: event.target.value })}
                  className="h-9 min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                >
                  <option value="">继承所选 CLI 模型</option>
                  {unavailableModel ? <option value={config.model} disabled>{config.model}（当前不可用）</option> : null}
                  {models.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-xs text-[var(--muted)]">思考深度</span>
                <select
                  aria-label={`${tier.label}思考深度`}
                  value={config.reasoningEffort}
                  disabled={disabled}
                  onChange={(event) => updateTier(tier.key, { reasoningEffort: event.target.value })}
                  className="h-9 min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                >
                  <option value="">继承所选 CLI 思考深度</option>
                  {unavailableEffort ? <option value={config.reasoningEffort} disabled>{config.reasoningEffort}（当前模型不支持）</option> : null}
                  {efforts.map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                </select>
              </label>
              {providerOptions.length > 0 ? (
                <label className="grid gap-1 text-sm sm:col-start-2">
                  <span className="text-xs text-[var(--muted)]">DeepSeek Provider</span>
                  <select
                    aria-label={`${tier.label}Provider`}
                    value={config.provider}
                    disabled={disabled}
                    onChange={(event) => updateTier(tier.key, { provider: event.target.value })}
                    className="h-9 min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  >
                    <option value="">继承所选 CLI Provider{providerId ? `（${providerId}）` : ""}</option>
                    {providerOptions.map((provider) => <option key={provider.id} value={provider.id}>{provider.label || provider.id}</option>)}
                  </select>
                </label>
              ) : null}
              {hasTierCliConfig ? (
                <details className="text-xs text-[var(--muted)] sm:col-span-2">
                  <summary className="cursor-pointer">高级配置：CLI 路径</summary>
                  <input
                    aria-label={`${tier.label} CLI 路径`}
                    value={config.cliPath}
                    disabled={disabled || nativeRuntime}
                    placeholder="留空使用所选 CLI 默认路径"
                    onChange={(event) => updateTier(tier.key, { cliPath: event.target.value })}
                    className="mt-2 h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                  />
                </details>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
