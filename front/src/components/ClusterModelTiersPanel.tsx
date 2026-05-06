import type { ClusterModelTiers } from "../services/types";

type Props = {
  value: ClusterModelTiers;
  modelOptions: string[];
  disabled?: boolean;
  onChange: (next: ClusterModelTiers) => void;
};

const TIER_LABELS: Array<{ key: keyof ClusterModelTiers; label: string; hint: string }> = [
  { key: "low", label: "低档", hint: "快、省 token" },
  { key: "medium", label: "中档", hint: "均衡" },
  { key: "high", label: "高档", hint: "复杂任务" },
];

export function ClusterModelTiersPanel({ value, modelOptions, disabled, onChange }: Props) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <h2 className="text-base font-semibold text-[var(--text)]">集群模型档位</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">主 agent 调子 agent 时选低/中/高档；effort/reasoning 继承主 agent。</p>
      <div className="mt-4 grid gap-3">
        {TIER_LABELS.map((tier) => (
          <label key={tier.key} className="grid gap-1 text-sm">
            <span className="font-medium text-[var(--text)]">
              {tier.label} <span className="text-xs font-normal text-[var(--muted)]">{tier.hint}</span>
            </span>
            <select
              value={value[tier.key]}
              disabled={disabled}
              onChange={(event) => onChange({ ...value, [tier.key]: event.target.value })}
              className="h-9 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
            >
              <option value="">继承主 agent 模型</option>
              {modelOptions.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </section>
  );
}
