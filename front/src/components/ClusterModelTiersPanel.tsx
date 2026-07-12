import type { ClusterModelTiers, ClusterReasoningEfforts } from "../services/types";

type Props = {
  value: ClusterModelTiers;
  reasoningEfforts: ClusterReasoningEfforts;
  modelOptions: string[];
  reasoningOptions: string[];
  disabled?: boolean;
  onChange: (next: ClusterModelTiers) => void;
  onReasoningChange: (next: ClusterReasoningEfforts) => void;
};

const TIER_LABELS: Array<{ key: keyof ClusterModelTiers; label: string; hint: string }> = [
  { key: "low", label: "低档", hint: "快、省 token" },
  { key: "medium", label: "中档", hint: "均衡" },
  { key: "high", label: "高档", hint: "复杂任务" },
];

export function ClusterModelTiersPanel({
  value,
  reasoningEfforts,
  modelOptions,
  reasoningOptions,
  disabled,
  onChange,
  onReasoningChange,
}: Props) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <h2 className="text-base font-semibold text-[var(--text)]">集群模型档位</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">每档可独立选择模型和思考深度；留空时继承主 agent。</p>
      <div className="mt-4 divide-y divide-[var(--border)]">
        {TIER_LABELS.map((tier) => (
          <div key={tier.key} className="grid gap-3 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(90px,0.6fr)_minmax(0,1.4fr)_minmax(0,1fr)] sm:items-end">
            <div className="text-sm font-medium text-[var(--text)] sm:pb-2">
              {tier.label} <span className="text-xs font-normal text-[var(--muted)]">{tier.hint}</span>
            </div>
            <label className="grid gap-1 text-sm">
              <span className="text-xs text-[var(--muted)]">模型</span>
              <select
                aria-label={`${tier.label}模型`}
                value={value[tier.key]}
                disabled={disabled}
                onChange={(event) => onChange({ ...value, [tier.key]: event.target.value })}
                className="h-9 min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
              >
                <option value="">继承主 agent 模型</option>
                {modelOptions.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm">
              <span className="text-xs text-[var(--muted)]">思考深度</span>
              <select
                aria-label={`${tier.label}思考深度`}
                value={reasoningEfforts[tier.key]}
                disabled={disabled}
                onChange={(event) => onReasoningChange({ ...reasoningEfforts, [tier.key]: event.target.value })}
                className="h-9 min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
              >
                <option value="">继承主 agent 思考深度</option>
                {reasoningOptions.map((effort) => (
                  <option key={effort} value={effort}>{effort}</option>
                ))}
              </select>
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}
