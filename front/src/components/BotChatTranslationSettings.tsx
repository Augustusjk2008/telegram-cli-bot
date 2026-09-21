import { useEffect, useState } from "react";
import type { BotChatTranslationConfig } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

export function BotChatTranslationSettings({ client, botAlias }: { client: WebBotClient; botAlias: string }) {
  const [config, setConfig] = useState<BotChatTranslationConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    client.getBotChatTranslationConfig(botAlias).then(
      (value) => { if (active) setConfig(value); },
      (err) => { if (active) setError(err instanceof Error ? err.message : "加载翻译设置失败"); },
    );
    return () => { active = false; };
  }, [client, botAlias]);

  async function update(enabled: boolean) {
    setSaving(true);
    setError("");
    try {
      setConfig(await client.updateBotChatTranslationConfig(botAlias, enabled));
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存翻译设置失败");
    } finally {
      setSaving(false);
    }
  }

  const globalEnabled = config?.global_translate_user_enabled || config?.global_translate_assistant_enabled;
  return (
    <section aria-label="Bot 聊天翻译设置" className="mt-3 rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] p-2.5">
      <label className="flex items-center justify-between gap-3 text-sm text-[var(--text)]">
        <span>本 Bot 启用聊天翻译</span>
        <input
          type="checkbox"
          role="switch"
          checked={config?.enabled ?? false}
          disabled={!config?.can_edit || saving}
          onChange={(event) => void update(event.target.checked)}
          className="h-4 w-4 shrink-0 accent-[var(--accent)]"
        />
      </label>
      <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
        {!config ? (error ? "翻译设置不可用" : "正在加载翻译设置…") : !globalEnabled
          ? "全局聊天翻译已关闭，此开关暂不生效。"
          : `遵循全局配置：${[config.global_translate_user_enabled && "翻译提问", config.global_translate_assistant_enabled && "翻译最终回答"].filter(Boolean).join("、")}。`}
      </p>
      <p className="text-xs leading-5 text-[var(--muted)]">适用于本 Bot 的所有会话，从下一条消息生效。</p>
      {saving ? <p role="status" className="text-xs text-[var(--muted)]">正在保存…</p> : null}
      {error ? <p role="alert" className="mt-1 text-xs text-red-600">{error}</p> : null}
    </section>
  );
}
