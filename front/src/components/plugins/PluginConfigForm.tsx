import { useEffect, useMemo, useState } from "react";
import type { PluginConfigField, PluginSummary, PluginUpdateInput } from "../../services/types";

type Props = {
  plugin: PluginSummary;
  disabled?: boolean;
  onSubmit: (input: PluginUpdateInput) => void;
};

function fieldDefault(field: PluginConfigField) {
  if (typeof field.default !== "undefined") {
    return field.default;
  }
  if (field.type === "boolean") {
    return false;
  }
  return "";
}

function buildInitialDraft(plugin: PluginSummary) {
  const draft: Record<string, unknown> = {};
  for (const section of plugin.configSchema?.sections || []) {
    for (const field of section.fields) {
      draft[field.key] = plugin.config?.[field.key] ?? fieldDefault(field);
    }
  }
  return draft;
}

function validateField(field: PluginConfigField, value: unknown) {
  if (field.type === "boolean") {
    return { ok: true as const, value: Boolean(value) };
  }
  if (field.type === "string") {
    return { ok: true as const, value: String(value ?? "") };
  }
  if (field.type === "select") {
    const options = new Set(field.options.map((option) => option.value));
    const next = String(value ?? "");
    if (!options.has(next)) {
      return { ok: false as const, message: `${field.label} 选项无效` };
    }
    return { ok: true as const, value: next };
  }
  const raw = String(value ?? "").trim();
  const numeric = raw === "" ? Number.NaN : Number(raw);
  if (!Number.isFinite(numeric)) {
    return { ok: false as const, message: `${field.label} 必须是数字` };
  }
  if (typeof field.minimum === "number" && numeric < field.minimum) {
    return { ok: false as const, message: `${field.label} 不能小于 ${field.minimum}` };
  }
  if (typeof field.maximum === "number" && numeric > field.maximum) {
    return { ok: false as const, message: `${field.label} 不能大于 ${field.maximum}` };
  }
  return { ok: true as const, value: field.type === "integer" ? Math.trunc(numeric) : numeric };
}

export function PluginConfigForm({ plugin, disabled = false, onSubmit }: Props) {
  const [draft, setDraft] = useState<Record<string, unknown>>(() => buildInitialDraft(plugin));
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(buildInitialDraft(plugin));
    setError("");
  }, [plugin]);

  const sections = useMemo(() => plugin.configSchema?.sections || [], [plugin.configSchema]);
  if (!plugin.configSchema || sections.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface-strong)] p-3">
      {plugin.configSchema.title ? (
        <div className="text-sm font-medium text-[var(--text)]">{plugin.configSchema.title}</div>
      ) : null}

      {sections.map((section) => (
        <div key={section.id} className="space-y-3">
          {section.title ? <div className="text-sm text-[var(--text)]">{section.title}</div> : null}
          {section.description ? <div className="text-xs text-[var(--muted)]">{section.description}</div> : null}
          {section.fields.map((field) => (
            <label key={field.key} className="flex flex-col gap-1 text-sm text-[var(--text)]">
              <span>{field.label}</span>
              {field.type === "boolean" ? (
                <input
                  type="checkbox"
                  checked={Boolean(draft[field.key])}
                  disabled={disabled}
                  onChange={(event) => {
                    const nextValue = event.currentTarget.checked;
                    setDraft((current) => ({ ...current, [field.key]: nextValue }));
                  }}
                  aria-label={field.label}
                />
              ) : field.type === "select" ? (
                <select
                  value={String(draft[field.key] ?? "")}
                  disabled={disabled}
                  onChange={(event) => {
                    const nextValue = event.currentTarget.value;
                    setDraft((current) => ({ ...current, [field.key]: nextValue }));
                  }}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
                  aria-label={field.label}
                >
                  {field.options.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === "string" ? "text" : "number"}
                  value={String(draft[field.key] ?? "")}
                  disabled={disabled}
                  min={field.type === "string" ? undefined : field.minimum}
                  max={field.type === "string" ? undefined : field.maximum}
                  step={field.type === "string" ? undefined : field.step}
                  placeholder={field.placeholder}
                  onChange={(event) => {
                    const nextValue = event.currentTarget.value;
                    setDraft((current) => ({ ...current, [field.key]: nextValue }));
                  }}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
                  aria-label={field.label}
                />
              )}
              {field.description ? <span className="text-xs text-[var(--muted)]">{field.description}</span> : null}
            </label>
          ))}
        </div>
      ))}

      {error ? <div className="text-sm text-[var(--danger)]">{error}</div> : null}

      <div className="flex justify-end">
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            const nextConfig: Record<string, unknown> = {};
            for (const section of sections) {
              for (const field of section.fields) {
                const result = validateField(field, draft[field.key]);
                if (!result.ok) {
                  setError(result.message);
                  return;
                }
                nextConfig[field.key] = result.value;
              }
            }
            setError("");
            onSubmit({ config: nextConfig });
          }}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text)] hover:bg-[var(--surface)] disabled:opacity-60"
          aria-label={`保存 ${plugin.name} 设置`}
        >
          保存
        </button>
      </div>
    </div>
  );
}
