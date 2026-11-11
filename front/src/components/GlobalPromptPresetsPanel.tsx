import { Check, Info, MessageSquareQuote, Plus, RotateCcw, Save, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { PromptPreset } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { getErrorMessage } from "../utils/errorMessage";
import "./GlobalSettingsPanels.css";

const MAX_PRESETS = 50;

type Props = {
  client: WebBotClient;
  botAlias: string;
  canManage?: boolean;
};

function clonePresets(value: PromptPreset[] = []) {
  return value.map((preset) => ({ ...preset }));
}

export function GlobalPromptPresetsPanel({ client, botAlias, canManage = true }: Props) {
  const uid = useId();
  const listRef = useRef<HTMLOListElement>(null);
  const focusNewPreset = useRef(false);
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

  // A new preset lands at the end of the list; move the caret into its title.
  useEffect(() => {
    if (!focusNewPreset.current) return;
    focusNewPreset.current = false;
    listRef.current?.querySelector<HTMLInputElement>("li:last-child .global-preset-title")?.focus();
  }, [draft.length]);

  function addPreset() {
    if (draft.length >= MAX_PRESETS) return;
    focusNewPreset.current = true;
    setDraft((current) => [...current, { id: `global-${Date.now().toString(36)}`, title: "", content: "" }]);
  }

  function removePreset(index: number) {
    setDraft((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function save() {
    const normalized = draft.map((preset) => ({ id: preset.id.trim(), title: preset.title.trim(), content: preset.content }));
    if (normalized.some((preset) => !preset.id || !preset.title || !preset.content.trim())) {
      setError("每条全局预设都需要填写标题和内容");
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

  const dirty = JSON.stringify(draft) !== JSON.stringify(presets);

  return (
    <section aria-labelledby={`${uid}-title`} className="global-settings-island">
      <header className="global-settings-head">
        <span className="global-settings-head-icon" aria-hidden="true"><MessageSquareQuote className="h-4 w-4" /></span>
        <h2 id={`${uid}-title`}>全局提示词预设</h2>
        {loading ? null : <span className="orbit-chip">{draft.length} / {MAX_PRESETS}</span>}
      </header>

      {loading ? <p role="status" className="global-settings-empty">加载中...</p> : null}
      {!loading && !canManage && draft.length === 0 ? <p className="global-settings-empty">暂无全局预设</p> : null}

      {draft.length > 0 ? (
        <ol ref={listRef} className="global-presets">
          {draft.map((preset, index) => (
            <li key={`${preset.id}-${index}`} className="global-preset">
              <div className="global-preset-head">
                <span className="global-preset-index" aria-hidden="true">{index + 1}</span>
                <input
                  aria-label={`全局预设标题 ${index + 1}`}
                  className="global-preset-title"
                  value={preset.title}
                  maxLength={80}
                  placeholder="预设标题"
                  disabled={!canManage || saving}
                  onChange={(event) => updatePreset(index, { title: event.currentTarget.value })}
                />
                {canManage ? (
                  <button
                    type="button"
                    aria-label={`删除全局预设 ${preset.title || index + 1}`}
                    onClick={() => removePreset(index)}
                    disabled={saving}
                    className="orbit-btn orbit-btn--icon global-preset-remove"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                ) : null}
              </div>
              <textarea
                aria-label={`全局预设内容 ${index + 1}`}
                className="global-preset-content"
                value={preset.content}
                maxLength={12000}
                rows={4}
                placeholder="预设内容"
                disabled={!canManage || saving}
                onChange={(event) => updatePreset(index, { content: event.currentTarget.value })}
              />
            </li>
          ))}
        </ol>
      ) : null}

      {canManage && !loading ? (
        <button type="button" onClick={addPreset} disabled={saving || draft.length >= MAX_PRESETS} className="global-presets-add">
          <Plus className="h-4 w-4" aria-hidden="true" />
          新增预设
        </button>
      ) : null}

      {error ? (
        <div role="alert" className="admin-callout" data-tone="danger">
          <TriangleAlert className="h-4 w-4 flex-none" aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      {canManage && !loading ? (
        <footer className="global-settings-foot">
          <p role="status" className="global-settings-foot-note" data-tone={!dirty && notice ? "success" : undefined}>
            {dirty ? (
              <>
                <Info className="h-3.5 w-3.5" aria-hidden="true" />
                有尚未保存的更改
              </>
            ) : notice ? (
              <>
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                {notice}
              </>
            ) : null}
          </p>
          <div className="global-settings-foot-actions">
            <button type="button" onClick={cancel} disabled={saving || !dirty} className="orbit-btn orbit-btn--ghost">
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              放弃更改
            </button>
            <button type="button" onClick={() => void save()} disabled={saving || !dirty} className="orbit-btn orbit-btn--primary">
              <Save className="h-4 w-4" aria-hidden="true" />
              {saving ? "保存中..." : "保存全局预设"}
            </button>
          </div>
        </footer>
      ) : null}
    </section>
  );
}
