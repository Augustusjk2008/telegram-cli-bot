import { Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { EnvConfigItem } from "../../services/types";
import type { WebBotClient } from "../../services/webBotClient";
import { getErrorMessage } from "../../utils/errorMessage";
import { buildEnvFieldPatch, createEnvFieldDraft, EnvFieldList, type EnvFieldDraft } from "./EnvFieldList";

type Props = {
  client: WebBotClient;
  onSaved?: (message: string) => void | Promise<void>;
  onError?: (message: string) => void;
};

/** Notification keys live in .env but are edited here; Environment Config no longer lists them. */
export const NOTIFICATION_ENV_CATEGORY = "notifications";

export function NotificationSettingsForm({ client, onSaved, onError }: Props) {
  const [items, setItems] = useState<EnvConfigItem[]>([]);
  const [draft, setDraft] = useState<EnvFieldDraft>({ values: {}, secrets: {} });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const pendingValues = useMemo(() => buildEnvFieldPatch(items, draft), [items, draft]);
  const hasChanges = Object.keys(pendingValues).length > 0;

  async function load() {
    const config = await client.getEnvConfig();
    const next = config.items.filter((item) => item.category === NOTIFICATION_ENV_CATEGORY);
    setItems(next);
    setDraft(createEnvFieldDraft(next));
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    void load()
      .catch((nextError) => {
        if (active) onError?.(getErrorMessage(nextError, "加载通知配置失败"));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [client]);

  async function save() {
    if (!hasChanges) return;
    setSaving(true);
    try {
      await client.updateEnvConfig({ values: pendingValues });
      // Notification keys are hot-reloadable; apply only them so other unsaved-to-runtime .env edits stay put.
      await client.reloadEnvConfig(items.map((item) => item.key));
      await load();
      await onSaved?.("通知配置已保存并生效");
    } catch (nextError) {
      onError?.(getErrorMessage(nextError, "保存通知配置失败"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-[var(--muted)]">正在加载通知配置…</p>;
  }
  if (!items.length) return null;

  return (
    <div className="space-y-3 border-t border-[var(--border)] pt-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">通知配置</h3>
      <EnvFieldList items={items} draft={draft} onDraftChange={setDraft} disabled={saving} />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || !hasChanges}
          className="orbit-btn orbit-btn--primary"
        >
          <Save className="h-4 w-4" />
          {saving ? "保存中..." : "保存通知配置"}
        </button>
        {hasChanges && !saving ? (
          <button type="button" onClick={() => setDraft(createEnvFieldDraft(items))} className="orbit-btn orbit-btn--ghost">
            放弃修改
          </button>
        ) : null}
      </div>
    </div>
  );
}
