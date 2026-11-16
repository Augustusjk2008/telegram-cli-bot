import { Pencil, RotateCcw, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import type { EnvConfigItem, EnvConfigPatchValue, EnvConfigValue } from "../../services/types";

/** A pending action on a sensitive value that is stored but never sent to the browser. */
export type EnvSecretAction = "edit" | "clear";

export type EnvFieldDraft = {
  values: Record<string, EnvConfigValue>;
  secrets: Record<string, EnvSecretAction>;
};

export function formatEnvFieldValue(value: EnvConfigValue | undefined) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  return value || "";
}

/** Booleans stay booleans; every other field keeps the raw text the user typed and the backend normalizes it. */
export function createEnvFieldDraft(items: EnvConfigItem[]): EnvFieldDraft {
  return {
    values: Object.fromEntries(items.map((item) => [
      item.key,
      item.type === "boolean" ? Boolean(item.value) : formatEnvFieldValue(item.value),
    ])),
    secrets: {},
  };
}

/** Only changed fields are sent, so saving one panel never rewrites values it did not touch. */
export function buildEnvFieldPatch(items: EnvConfigItem[], draft: EnvFieldDraft): Record<string, EnvConfigPatchValue> {
  const values: Record<string, EnvConfigPatchValue> = {};
  for (const item of items) {
    const value = draft.values[item.key] ?? item.value;
    if (item.sensitive) {
      const action = draft.secrets[item.key];
      if (action === "clear") {
        values[item.key] = { action: "clear" };
      } else if ((action === "edit" || !item.masked) && formatEnvFieldValue(value)) {
        values[item.key] = value;
      }
      continue;
    }
    if (formatEnvFieldValue(value) !== formatEnvFieldValue(item.value)) {
      values[item.key] = value;
    }
  }
  return values;
}

type Props = {
  items: EnvConfigItem[];
  draft: EnvFieldDraft;
  onDraftChange: Dispatch<SetStateAction<EnvFieldDraft>>;
  disabled?: boolean;
};

export function EnvFieldList({ items, draft, onDraftChange, disabled = false }: Props) {
  const setValue = (key: string, value: EnvConfigValue) => {
    onDraftChange((previous) => ({ ...previous, values: { ...previous.values, [key]: value } }));
  };
  const setSecretAction = (key: string, action: EnvSecretAction | null) => {
    onDraftChange((previous) => {
      const secrets = { ...previous.secrets };
      if (action) secrets[key] = action;
      else delete secrets[key];
      return { values: { ...previous.values, [key]: "" }, secrets };
    });
  };

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {items.map((item) => {
        const value = draft.values[item.key] ?? item.value;
        const secretAction = item.sensitive ? draft.secrets[item.key] : undefined;
        const secretLocked = item.sensitive && item.masked && !secretAction;
        const inputValue = secretLocked ? "********" : formatEnvFieldValue(value);
        return (
          <article key={item.key} className="space-y-2 admin-well p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h4 className="font-medium text-[var(--text)]">{item.label}</h4>
                <p className="text-xs text-[var(--muted)]">{item.description}</p>
                {item.processOverridden ? (
                  <p className="text-xs text-[var(--status-warning)]">当前值来自进程环境变量，保存到 .env 不会覆盖它。</p>
                ) : null}
              </div>
              {item.sensitive && item.masked ? (
                <div className="flex gap-2">
                  {secretAction ? (
                    <button
                      type="button"
                      onClick={() => setSecretAction(item.key, null)}
                      disabled={disabled}
                      className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      撤销
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => setSecretAction(item.key, "edit")}
                        disabled={disabled}
                        className="orbit-btn orbit-btn--ghost orbit-btn--sm"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        修改
                      </button>
                      <button
                        type="button"
                        onClick={() => setSecretAction(item.key, "clear")}
                        disabled={disabled}
                        className="orbit-btn orbit-btn--sm admin-btn--danger-quiet"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        清空
                      </button>
                    </>
                  )}
                </div>
              ) : null}
            </div>
            {item.type === "boolean" ? (
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  aria-label={item.label}
                  checked={Boolean(value)}
                  disabled={disabled}
                  onChange={(event) => setValue(item.key, event.target.checked)}
                />
                启用
              </label>
            ) : item.type === "select" && item.options?.length ? (
              <select
                aria-label={item.label}
                value={formatEnvFieldValue(value)}
                disabled={disabled}
                onChange={(event) => setValue(item.key, event.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
              >
                {item.options.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            ) : (
              <input
                aria-label={item.label}
                type={item.type === "password" ? "password" : item.type === "number" ? "number" : "text"}
                value={inputValue}
                placeholder={secretAction === "clear" ? "保存后清空" : secretAction === "edit" ? "输入新值；留空则保持不变" : undefined}
                disabled={disabled || secretLocked || secretAction === "clear"}
                autoComplete={item.sensitive ? "new-password" : undefined}
                onChange={(event) => setValue(item.key, event.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] disabled:opacity-70"
              />
            )}
          </article>
        );
      })}
    </div>
  );
}
