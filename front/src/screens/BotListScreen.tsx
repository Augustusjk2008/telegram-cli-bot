import { useState, useEffect } from "react";
import { BotSummary } from "../services/types";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { BotCard } from "../components/BotCard";

export function BotListScreen({ onSelect }: { onSelect: (alias: string) => void }) {
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const client = new MockWebBotClient();
    client.listBots().then((data) => {
      setBots(data);
      setLoading(false);
    });
  }, []);

  return (
    <main className="flex-1 overflow-y-auto p-4 bg-[var(--bg)]">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Bots</h1>
      </header>
      
      {loading ? (
        <div className="text-center text-[var(--muted)]">加载中...</div>
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
