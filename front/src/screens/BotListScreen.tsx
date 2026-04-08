import { useEffect, useState } from "react";
import { BotCard } from "../components/BotCard";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { BotSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client?: WebBotClient;
  onSelect: (alias: string) => void;
};

export function BotListScreen({ client = new MockWebBotClient(), onSelect }: Props) {
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    client.listBots()
      .then((data) => {
        if (cancelled) return;
        setBots(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "加载 Bot 失败");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <main className="flex-1 overflow-y-auto p-4 bg-[var(--bg)]">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">选择 Bot</h1>
      </header>

      {loading ? (
        <div className="text-center text-[var(--muted)]">加载中...</div>
      ) : error ? (
        <div className="text-center text-red-600">{error}</div>
      ) : bots.length === 0 ? (
        <div className="text-center text-[var(--muted)]">暂无 Bot</div>
      ) : (
        <div className="space-y-4">
          {bots.map((bot) => (
            <BotCard key={bot.alias} bot={bot} onClick={() => onSelect(bot.alias)} />
          ))}
        </div>
      )}
    </main>
  );
}
