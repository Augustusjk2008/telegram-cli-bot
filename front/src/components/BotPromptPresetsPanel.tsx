import { LoaderCircle, MessageSquareText, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { PromptPreset } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import {
  SettingsDirtyBadge,
  SettingsNotice,
  SettingsSection,
  settingsButtonClassName,
  settingsDangerIconButtonClassName,
  settingsPrimaryButtonClassName,
} from "./SettingsSection";

type Props = {
  botAlias: string;
  client: WebBotClient;
  canManage?: boolean;
};

function clonePresets(value: PromptPreset[] = []) {
  return value.map((preset) => ({ ...preset }));
}

export function BotPromptPresetsPanel({ botAlias, client, canManage = true }: Props) {
  const [presets, setPresets] = useState<PromptPreset[]>([]);
  const [draft, setDraft] = useState<PromptPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void client.getBotOverview(botAlias)
      .then((overview) => {
        if (cancelled) return;
        const next = clonePresets(overview.promptPresets || []);
        setPresets(next);
        setDraft(next);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err, "加载当前智能体提示词预设失败"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

  function updatePreset(index: number, patch: Partial<PromptPreset>) {
    setDraft((current) => current.map((preset, itemIndex) => itemIndex === index ? { ...preset, ...patch } : preset));
  }

  function addPreset() {
    if (draft.length >= 50) return;
    setDraft((current) => [...current, { id: `bot-${Date.now().toString(36)}`, title: "", content: "" }]);
  }

  function removePreset(index: number) {
    setDraft((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function save() {
    const normalized = draft.map((preset) => ({ id: preset.id.trim(), title: preset.title.trim(), content: preset.content }));
    if (normalized.some((preset) => !preset.id || !preset.title || !preset.content.trim())) {
      setError("每条当前智能体预设都需要填写 ID、标题和内容");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await client.updateBotPromptPresets(botAlias, normalized);
      const next = clonePresets(updated.promptPresets || normalized);
      setPresets(next);
      setDraft(next);
      setNotice("当前智能体提示词预设已保存");
    } catch (err) {
      setError(getErrorMessage(err, "保存当前智能体提示词预设失败"));
    } finally {
      setSaving(false);
    }
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(presets);

  return (
    <SettingsSection
      id="settings-section-presets"
      titleId="bot-prompt-presets-title"
      icon={<MessageSquareText className="h-3.5 w-3.5" />}
      title="提示词预设"
      description="只影响当前智能体；聊天输入框中的预设入口用于选择和插入。"
      badge={dirty ? <SettingsDirtyBadge /> : !loading ? (
        <span className="inline-flex h-4 items-center rounded-full bg-[var(--workbench-active-bg)] px-1.5 text-[10px] font-medium tabular-nums text-[var(--muted)]">{draft.length}</span>
      ) : null}
      actions={canManage ? (
        <button
          type="button"
          aria-label="新增预设"
          onClick={addPreset}
          disabled={saving || draft.length >= 50}
          className={settingsButtonClassName}
        >
          <Plus className="h-3.5 w-3.5" />
          新增
        </button>
      ) : null}
    >
      <div className="space-y-2">
        {loading ? (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            加载中...
          </div>
        ) : null}
        {!loading && draft.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--workbench-hairline)] px-3 py-4 text-center text-[11px] text-[var(--muted)]">
            暂无当前智能体预设
          </div>
        ) : null}
        {draft.map((preset, index) => (
          <div key={`${preset.id}-${index}`} className="group/preset overflow-hidden rounded-md border border-[var(--workbench-hairline)] bg-[var(--bg)] transition-colors focus-within:border-[var(--accent-outline)]">
            <div className="flex min-w-0 items-center gap-1 border-b border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] pl-2 pr-0.5">
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-[var(--muted)]">{String(index + 1).padStart(2, "0")}</span>
              <input
                aria-label={`当前智能体预设标题 ${index + 1}`}
                value={preset.title}
                maxLength={80}
                placeholder="预设标题"
                disabled={!canManage || saving}
                onChange={(event) => updatePreset(index, { title: event.currentTarget.value })}
                className="h-8 min-w-0 flex-1 bg-transparent px-1.5 text-xs font-medium text-[var(--text)] outline-none placeholder:font-normal placeholder:text-[var(--muted)] disabled:opacity-60"
              />
              {canManage ? (
                <button
                  type="button"
                  aria-label={`删除当前智能体预设 ${preset.title || index + 1}`}
                  onClick={() => removePreset(index)}
                  disabled={saving}
                  className={settingsDangerIconButtonClassName}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
            <textarea
              aria-label={`当前智能体预设内容 ${index + 1}`}
              value={preset.content}
              maxLength={12000}
              rows={3}
              placeholder="预设内容"
              disabled={!canManage || saving}
              onChange={(event) => updatePreset(index, { content: event.currentTarget.value })}
              className="block w-full resize-y bg-transparent px-2.5 py-1.5 text-xs leading-5 text-[var(--text)] outline-none placeholder:text-[var(--muted)] disabled:opacity-60"
            />
          </div>
        ))}
        {error ? <SettingsNotice tone="danger">{error}</SettingsNotice> : null}
        {notice ? <p role="status" className="text-[11px] text-[var(--feedback-success-text-deep)]">{notice}</p> : null}
        {canManage && (dirty || saving) ? (
          <div className="flex items-center justify-end gap-1.5 pt-0.5">
            <button
              type="button"
              onClick={() => { setDraft(clonePresets(presets)); setError(""); setNotice(""); }}
              disabled={saving}
              className={settingsButtonClassName}
            >
              取消
            </button>
            <button type="button" onClick={() => void save()} disabled={saving} className={settingsPrimaryButtonClassName}>
              {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {saving ? "保存中..." : "保存当前预设"}
            </button>
          </div>
        ) : null}
      </div>
    </SettingsSection>
  );
}
