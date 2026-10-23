import { Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { PromptPreset } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";

type Props = {
  client: WebBotClient;
  botAlias: string;
  canManage?: boolean;
};

function clonePresets(value: PromptPreset[] = []) {
  return value.map((preset) => ({ ...preset }));
}

export function GlobalPromptPresetsPanel({ client, botAlias, canManage = true }: Props) {
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
    void client.getBotOverview(botAlias || "main")
      .then((overview) => {
        if (cancelled) return;
        const next = clonePresets(overview.globalPromptPresets || []);
        setPresets(next);
        setDraft(next);
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err, "加载全局提示词预设失败"));
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
    setDraft((current) => [...current, { id: `global-${Date.now().toString(36)}`, title: "", content: "" }]);
  }

  function removePreset(index: number) {
    setDraft((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function save() {
    const normalized = draft.map((preset) => ({ id: preset.id.trim(), title: preset.title.trim(), content: preset.content }));
    if (normalized.some((preset) => !preset.id || !preset.title || !preset.content.trim())) {
      setError("每条全局预设都需要填写 ID、标题和内容");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await client.updateGlobalPromptPresets(normalized);
      setPresets(clonePresets(next));
      setDraft(clonePresets(next));
      setNotice("全局提示词预设已保存");
    } catch (err) {
      setError(getErrorMessage(err, "保存全局提示词预设失败"));
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setDraft(clonePresets(presets));
    setError("");
    setNotice("");
  }

  return (
    <section aria-labelledby="global-prompt-presets-title" className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div>
        <h2 id="global-prompt-presets-title" className="text-base font-semibold text-[var(--text)]">全局提示词预设</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">影响所有智能体；聊天输入框只负责选择和插入。</p>
      </div>
      {loading ? <p className="text-sm text-[var(--muted)]">加载中...</p> : null}
      {!loading && draft.length === 0 ? <p className="rounded-lg border border-dashed border-[var(--border)] px-3 py-5 text-center text-sm text-[var(--muted)]">暂无全局预设</p> : null}
      <div className="space-y-3">
        {draft.map((preset, index) => (
          <div key={`${preset.id}-${index}`} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1 space-y-2">
                <label className="block text-sm font-medium text-[var(--text)]">预设标题 {index + 1}
                  <input aria-label={`全局预设标题 ${index + 1}`} value={preset.title} maxLength={80} disabled={!canManage || saving} onChange={(event) => updatePreset(index, { title: event.currentTarget.value })} className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-normal text-[var(--text)] disabled:opacity-60" />
                </label>
                <label className="block text-sm font-medium text-[var(--text)]">预设内容 {index + 1}
                  <textarea aria-label={`全局预设内容 ${index + 1}`} value={preset.content} maxLength={12000} rows={4} disabled={!canManage || saving} onChange={(event) => updatePreset(index, { content: event.currentTarget.value })} className="mt-1 w-full resize-y rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-normal text-[var(--text)] disabled:opacity-60" />
                </label>
              </div>
              {canManage ? <button type="button" aria-label={`删除全局预设 ${preset.title || index + 1}`} onClick={() => removePreset(index)} disabled={saving} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--muted)] hover:bg-[var(--feedback-error-background-subtle)] hover:text-[var(--feedback-error-text-strong)] disabled:opacity-50"><Trash2 className="h-4 w-4" /></button> : null}
            </div>
          </div>
        ))}
      </div>
      {error ? <p className="rounded-lg border border-[var(--feedback-error-border-light)] bg-[var(--feedback-error-background-subtle)] px-3 py-2 text-sm text-[var(--feedback-error-text-deep)]">{error}</p> : null}
      {notice ? <p role="status" className="text-sm text-[var(--feedback-success-text-deep)]">{notice}</p> : null}
      {canManage ? <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-3">
        <button type="button" onClick={addPreset} disabled={saving || draft.length >= 50} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-50"><Plus className="h-4 w-4" />新增预设</button>
        <div className="flex items-center gap-2">
          <button type="button" onClick={cancel} disabled={saving} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)] disabled:opacity-50">取消</button>
          <button type="button" onClick={() => void save()} disabled={saving} className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent disabled:opacity-50"><Save className="h-4 w-4" />{saving ? "保存中..." : "保存全局预设"}</button>
        </div>
      </div> : null}
    </section>
  );
}
