import { useEffect, useState } from "react";
import { toolbarButtonClass } from "./ToolbarButton";
import type { ChatTranslationConfigInput } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_CHAT_TRANSLATION_CONFIG } from "../utils/chatTranslation";
import { getErrorMessage } from "../utils/errorMessage";

export function ChatTranslationSettingsPanel({ client, onSaved }: { client: WebBotClient; onSaved?: () => void }) {
  const [config, setConfig] = useState(DEFAULT_CHAT_TRANSLATION_CONFIG);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoaded(false);
    void client.getChatTranslationConfig().then((next) => {
      if (active) { setConfig(next); setLoaded(true); setApiKey(""); setClearApiKey(false); }
    }).catch((err: unknown) => {
      if (active) setError(getErrorMessage(err, "加载聊天翻译配置失败"));
    });
    return () => { active = false; };
  }, [client]);

  const enabled = config.translate_user_enabled || config.translate_assistant_enabled;
  const save = async () => {
    setError("");
    if (enabled && (!config.base_url.trim() || !config.model.trim()
      || !(apiKey.trim() || (config.api_key_configured && !clearApiKey)))) {
      setError("启用翻译时，请填写服务地址、模型和 API 密钥。");
      return;
    }
    if (!Number.isFinite(config.request_timeout_seconds) || config.request_timeout_seconds <= 0) {
      setError("超时秒数必须大于 0。");
      return;
    }
    const input: ChatTranslationConfigInput = {
      user_prompt: config.user_prompt,
      assistant_prompt: config.assistant_prompt,
      translate_user_enabled: config.translate_user_enabled,
      translate_assistant_enabled: config.translate_assistant_enabled,
      base_url: config.base_url.trim(),
      model: config.model.trim(),
      request_timeout_seconds: config.request_timeout_seconds,
      api_key: clearApiKey ? "" : apiKey.trim(),
      ...(clearApiKey ? { clear_api_key: true } : {}),
    };
    setSaving(true);
    try {
      setConfig(await client.updateChatTranslationConfig(input));
      setApiKey("");
      setClearApiKey(false);
      onSaved?.();
    } catch (err) {
      setError(getErrorMessage(err, "保存聊天翻译配置失败"));
    } finally {
      setSaving(false);
    }
  };

  const inputClass = "w-full min-w-0 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)]";
  return (
    <section aria-label="聊天翻译配置" className="space-y-3 rounded-lg border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-3">
      <h2 className="text-base font-semibold">聊天翻译（全局生效）</h2>
      {!loaded && !error ? <p className="text-sm text-[var(--muted)]">加载中...</p> : null}
      {error ? <p role="alert" className="text-sm text-[var(--status-danger)]">{error}</p> : null}
      <fieldset disabled={!loaded || saving} className="min-w-0 space-y-3 disabled:opacity-60">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {([
            ["translate_user_enabled", "翻译提问"],
            ["translate_assistant_enabled", "翻译最终回答"],
          ] as const).map(([key, label]) => (
            <label key={key} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] p-3 text-sm">
              {label}<input type="checkbox" checked={config[key]} onChange={(event) => setConfig({ ...config, [key]: event.target.checked })} />
            </label>
          ))}
          {([
            ["base_url", "翻译服务地址", "https://api.example.com/v1"],
            ["model", "翻译模型", ""],
          ] as const).map(([key, label, placeholder]) => (
            <label key={key} className="min-w-0 space-y-1 text-sm">
              <span>{label}</span>
              <input className={inputClass} value={config[key]} placeholder={placeholder} onChange={(event) => setConfig({ ...config, [key]: event.target.value })} />
            </label>
          ))}
          <label className="min-w-0 space-y-1 text-sm">
            <span>翻译 API 密钥</span>
            <input className={inputClass} type="password" autoComplete="new-password" value={apiKey} disabled={clearApiKey}
              placeholder={config.api_key_configured ? "已保存，留空保留" : "尚未配置"} onChange={(event) => setApiKey(event.target.value)} />
          </label>
          <label className="min-w-0 space-y-1 text-sm">
            <span>翻译超时（秒）</span>
            <input className={inputClass} type="number" min="0.1" step="any" value={config.request_timeout_seconds || ""}
              onChange={(event) => setConfig({ ...config, request_timeout_seconds: Number(event.target.value) })} />
          </label>
        </div>
        {([
          ["user_prompt", "用户消息翻译提示词"],
          ["assistant_prompt", "Bot 回答翻译提示词"],
        ] as const).map(([key, label]) => (
          <label key={key} className="block min-w-0 space-y-1 text-sm">
            <span>{label}</span>
            <textarea className={inputClass} rows={10} value={config[key] ?? ""}
              placeholder="留空并保存可恢复此方向的初版提示词"
              onChange={(event) => setConfig({ ...config, [key]: event.target.value })} />
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={clearApiKey} onChange={(event) => { setClearApiKey(event.target.checked); setApiKey(""); }} />
          清除已保存的翻译 API 密钥
        </label>
        <button type="button" className={toolbarButtonClass("primary", "md")} onClick={() => void save()}>
          {saving ? "保存中..." : "保存聊天翻译配置"}
        </button>
      </fieldset>
    </section>
  );
}
