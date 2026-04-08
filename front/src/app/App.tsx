/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useEffect, useState } from "react";
import { Folder, Menu, MessageSquare, Settings } from "lucide-react";
import { clsx } from "clsx";
import { BotSwitcherSheet } from "../components/BotSwitcherSheet";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { BotSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { BotListScreen } from "../screens/BotListScreen";
import { ChatScreen } from "../screens/ChatScreen";
import { FilesScreen } from "../screens/FilesScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import "../styles/tokens.css";
import "../styles/global.css";

export function App() {
  const useMockClient = import.meta.env.MODE === "test" || import.meta.env.VITE_USE_MOCK === "true";
  const [client, setClient] = useState<WebBotClient>(() => useMockClient ? new MockWebBotClient() : new RealWebBotClient());
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentTab, setCurrentTab] = useState<"chat" | "files" | "settings">("chat");
  const [currentBot, setCurrentBot] = useState<string | null>(null);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    client.listBots().then(setBots).catch(() => setBots([]));
  }, [client, isLoggedIn]);

  useEffect(() => {
    if (useMockClient) {
      return;
    }
    const storedToken = localStorage.getItem("web-api-token");
    if (!storedToken) {
      return;
    }

    const nextClient = new RealWebBotClient();
    setLoginLoading(true);
    nextClient.login(storedToken)
      .then((session) => {
        setClient(nextClient);
        setIsLoggedIn(true);
        setCurrentBot(session.currentBotAlias || null);
        setLoginError("");
      })
      .catch(() => {
        localStorage.removeItem("web-api-token");
        setLoginError("本地保存的访问口令已失效，请重新登录");
      })
      .finally(() => {
        setLoginLoading(false);
      });
  }, [useMockClient]);

  async function handleLogin(token: string) {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const session = await nextClient.login(token);
      if (!useMockClient) {
        localStorage.setItem("web-api-token", token);
      }
      setClient(nextClient);
      setIsLoggedIn(true);
      setCurrentBot(session.currentBotAlias || null);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoginLoading(false);
    }
  }

  function handleLogout() {
    localStorage.removeItem("web-api-token");
    setClient(useMockClient ? new MockWebBotClient() : new RealWebBotClient());
    setIsLoggedIn(false);
    setCurrentBot(null);
    setCurrentTab("chat");
    setBots([]);
    setLoginError("");
  }

  if (!isLoggedIn) {
    return <LoginScreen onLogin={handleLogin} isLoading={loginLoading} error={loginError} />;
  }

  if (!currentBot) {
    return <BotListScreen client={client} onSelect={setCurrentBot} />;
  }

  return (
    <div className="flex flex-col h-[100dvh] w-full max-w-md mx-auto bg-[var(--bg)] shadow-xl overflow-hidden relative">
      <header className="flex items-center justify-between p-3 bg-[var(--surface-strong)] border-b border-[var(--border)] shrink-0">
        <button
          onClick={() => setShowSwitcher(true)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-[var(--border)] transition-colors"
        >
          <Menu className="w-5 h-5" />
          <span className="font-semibold">{currentBot}</span>
        </button>
      </header>

      <div className="flex-1 overflow-hidden relative">
        {currentTab === "chat" ? <ChatScreen key={`chat-${currentBot}`} botAlias={currentBot} client={client} /> : null}
        {currentTab === "files" ? <FilesScreen key={`files-${currentBot}`} botAlias={currentBot} client={client} /> : null}
        {currentTab === "settings" ? <SettingsScreen key={`settings-${currentBot}`} botAlias={currentBot} client={client} onLogout={handleLogout} /> : null}
      </div>

      <nav className="flex items-center justify-around p-2 bg-[var(--surface-strong)] border-t border-[var(--border)] shrink-0 pb-safe">
        <button
          onClick={() => setCurrentTab("chat")}
          className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "chat" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
        >
          <MessageSquare className="w-6 h-6 mb-1" />
          <span className="text-[10px] font-medium">聊天</span>
        </button>
        <button
          onClick={() => setCurrentTab("files")}
          className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "files" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
        >
          <Folder className="w-6 h-6 mb-1" />
          <span className="text-[10px] font-medium">文件</span>
        </button>
        <button
          onClick={() => setCurrentTab("settings")}
          className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "settings" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
        >
          <Settings className="w-6 h-6 mb-1" />
          <span className="text-[10px] font-medium">设置</span>
        </button>
      </nav>

      {showSwitcher ? (
        <BotSwitcherSheet
          bots={bots}
          currentAlias={currentBot}
          onSelect={(alias) => {
            setCurrentBot(alias);
            setCurrentTab("chat");
          }}
          onClose={() => setShowSwitcher(false)}
        />
      ) : null}
    </div>
  );
}
