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

  onTierConfigChange?: (tier: TierKey, next: ClusterTierConfig) => void;
};

const TIER_LABELS: Array<{ key: TierKey; label: string; hint: string }> = [
  { key: "low", label: "低档", hint: "快、省 token" },
  { key: "medium", label: "中档", hint: "均衡" },
  { key: "high", label: "高档", hint: "复杂任务" },
  { key: "professional", label: "专业档", hint: "特殊工作" },
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
    <section className="@container space-y-1.5 rounded-md border border-[var(--workbench-hairline)] px-2.5 py-2">
      <h3 className="text-xs font-semibold text-[var(--text)]">集群模型档位</h3>
      <p className="text-[11px] leading-4 text-[var(--muted)]">
        每档可选择执行 CLI、模型和思考深度；留空时继承所选 CLI 配置。
      </p>

      <div className="divide-y divide-[var(--workbench-hairline)]">
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
            <div key={tier.key} className="grid grid-cols-2 gap-x-2 gap-y-1.5 py-2 last:pb-0 @lg:grid-cols-[minmax(84px,0.5fr)_minmax(0,1.2fr)_minmax(0,1.2fr)] @lg:items-end">
              <div className="col-span-2 text-xs font-semibold text-[var(--text)] @lg:col-span-1 @lg:pb-2">
                {tier.label} <span className="text-[11px] font-normal text-[var(--muted)]">{tier.hint}</span>
              </div>
              {hasTierCliConfig ? (
                <label className="grid min-w-0 gap-1 text-xs">
                  <span className="text-[11px] text-[var(--muted)]">执行 CLI</span>
                  <select
                    aria-label={`${tier.label}执行 CLI`}
                    value={config.cliType}
                    disabled={disabled}
                    onChange={(event) => updateTier(tier.key, {
                      cliType: event.target.value,
                      model: "",
                      reasoningEffort: "",
                      provider: "",
                    })}
                    className="h-8 min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
                  >
                    <option value="">继承主 Bot CLI（{String(inheritedCliType || "codex")}）</option>
                    {CLI_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  {cliStatus ? <span className="text-xs text-[var(--feedback-error-text-deep)]">{cliStatus}</span> : null}
                </label>
              ) : null}
              <label className="grid min-w-0 gap-1 text-xs">
                <span className="text-[11px] text-[var(--muted)]">模型</span>
                <select
                  aria-label={`${tier.label}模型`}
                  value={config.model}
                  disabled={disabled}
                  onChange={(event) => updateTier(tier.key, { model: event.target.value })}
                  className="h-8 min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
                >
                  <option value="">继承所选 CLI 模型</option>
                  {unavailableModel ? <option value={config.model} disabled>{config.model}（当前不可用）</option> : null}
                  {models.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              </label>
              <label className="grid min-w-0 gap-1 text-xs">
                <span className="text-[11px] text-[var(--muted)]">思考深度</span>
                <select
                  aria-label={`${tier.label}思考深度`}
                  value={config.reasoningEffort}
                  disabled={disabled}
                  onChange={(event) => updateTier(tier.key, { reasoningEffort: event.target.value })}
                  className="h-8 min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
                >
                  <option value="">继承所选 CLI 思考深度</option>
                  {unavailableEffort ? <option value={config.reasoningEffort} disabled>{config.reasoningEffort}（当前模型不支持）</option> : null}
                  {efforts.map((effort) => <option key={effort} value={effort}>{effort}</option>)}
                </select>
              </label>
              {providerOptions.length > 0 ? (
                <label className="grid min-w-0 gap-1 text-xs @lg:col-start-2">
                  <span className="text-[11px] text-[var(--muted)]">DeepSeek Provider</span>
                  <select
                    aria-label={`${tier.label}Provider`}
                    value={config.provider}
                    disabled={disabled}
                    onChange={(event) => updateTier(tier.key, { provider: event.target.value })}
                    className="h-8 min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
                  >
                    <option value="">继承所选 CLI Provider{providerId ? `（${providerId}）` : ""}</option>
                    {providerOptions.map((provider) => <option key={provider.id} value={provider.id}>{provider.label || provider.id}</option>)}
                  </select>
                </label>
              ) : null}
              {hasTierCliConfig ? (
                <details className="col-span-2 text-[11px] text-[var(--muted)] @lg:col-start-2">
                  <summary className="cursor-pointer">高级配置：CLI 路径</summary>
                  <input
                    aria-label={`${tier.label} CLI 路径`}
                    value={config.cliPath}
                    disabled={disabled}
                    placeholder="留空使用所选 CLI 默认路径"
                    onChange={(event) => updateTier(tier.key, { cliPath: event.target.value })}
                    className="mt-1.5 w-full h-8 min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:opacity-60"
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
