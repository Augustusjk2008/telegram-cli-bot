import { useState } from "react";
import { ChatComposer } from "../components/ChatComposer";
import { streamAssistantReply } from "../services/mockWebBotClient";

export function ChatScreen({ botAlias }: { botAlias: string }) {
  const [items, setItems] = useState<string[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  async function handleSend(text: string) {
    setItems((prev) => [...prev, text]);
    setIsStreaming(true);
    setStreamingText("");
    await streamAssistantReply((chunk) => {
      setStreamingText((prev) => prev + chunk);
    });
    setIsStreaming(false);
  }

  return (
    <main className="flex flex-col h-full">
      <header className="p-4 border-b border-[var(--border)] bg-[var(--surface-strong)]">
        <h1 className="text-lg font-semibold">{botAlias}</h1>
      </header>
      <section className="flex-1 overflow-y-auto p-4 space-y-4">
        {items.length === 0 && !isStreaming && (
          <div className="text-center text-[var(--muted)] mt-10">
            暂无消息，开始聊天吧
          </div>
        )}
        {items.map((item, index) => (
          <div key={index} className="flex justify-end">
            <div className="bg-[var(--accent)] text-white px-4 py-2 rounded-2xl max-w-[80%]">
              {item}
            </div>
          </div>
        ))}
        {isStreaming && (
          <div className="flex justify-start">
            <div className="bg-[var(--surface)] text-[var(--text)] px-4 py-2 rounded-2xl max-w-[80%] border border-[var(--border)]">
              {streamingText || "正在生成..."}
            </div>
          </div>
        )}
      </section>
      <ChatComposer onSend={handleSend} disabled={isStreaming} />
    </main>
  );
}
