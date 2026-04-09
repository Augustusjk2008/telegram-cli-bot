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

const TOKEN_STORAGE_KEY = "web-api-token";
const BOT_STORAGE_KEY = "web-current-bot";

function readStoredToken() {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY)?.trim() || "";
}

function storeToken(token: string) {
  const trimmed = token.trim();
  if (!trimmed) {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    return;
  }
  sessionStorage.setItem(TOKEN_STORAGE_KEY, trimmed);
}

function clearStoredToken() {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

function readStoredBotAlias() {
  return localStorage.getItem(BOT_STORAGE_KEY)?.trim() || "";
}

function storeBotAlias(alias: string | null) {
  const trimmed = alias?.trim() || "";
  if (!trimmed) {
    return;
  }
  localStorage.setItem(BOT_STORAGE_KEY, trimmed);
}

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
  const [mountedChatBots, setMountedChatBots] = useState<string[]>([]);

  function handleSelectBot(alias: string | null) {
    setCurrentBot(alias);
    storeBotAlias(alias);
  }

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    client.listBots().then(setBots).catch(() => setBots([]));
  }, [client, isLoggedIn]);

  useEffect(() => {
    if (!isLoggedIn || bots.length === 0) {
      return;
    }

    if (currentBot && bots.some((bot) => bot.alias === currentBot)) {
      return;
    }

    const storedAlias = readStoredBotAlias();
    if (storedAlias && bots.some((bot) => bot.alias === storedAlias)) {
      setCurrentBot(storedAlias);
      return;
    }

    setCurrentBot(null);
  }, [bots, currentBot, isLoggedIn]);

  useEffect(() => {
    const storedToken = readStoredToken();
    if (!storedToken) {
      return;
    }

    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    nextClient.login(storedToken)
      .then((session) => {
        const restoredAlias = readStoredBotAlias() || session.currentBotAlias || "";
        setClient(nextClient);
        setIsLoggedIn(true);
        setCurrentBot(restoredAlias || null);
        setMountedChatBots(restoredAlias ? [restoredAlias] : []);
        setLoginError("");
      })
      .catch(() => {
        clearStoredToken();
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
      const restoredAlias = readStoredBotAlias() || session.currentBotAlias || "";
      storeToken(token);
      setClient(nextClient);
      setIsLoggedIn(true);
      setCurrentBot(restoredAlias || null);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoginLoading(false);
    }
  }

  function handleLogout() {
    clearStoredToken();
    setClient(useMockClient ? new MockWebBotClient() : new RealWebBotClient());
    setIsLoggedIn(false);
    setCurrentBot(null);
    setCurrentTab("chat");
    setBots([]);
    setMountedChatBots([]);
    setLoginError("");
  }

  useEffect(() => {
    if (!currentBot) {
      return;
    }
    setMountedChatBots((prev) => (prev.includes(currentBot) ? prev : [...prev, currentBot]));
  }, [currentBot]);

  if (!isLoggedIn) {
    return <LoginScreen onLogin={handleLogin} isLoading={loginLoading} error={loginError} />;
  }

  if (!currentBot) {
    return <BotListScreen client={client} onSelect={handleSelectBot} />;
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
        <div className={clsx("absolute inset-0", currentTab === "chat" ? "block" : "hidden")}>
          {mountedChatBots.map((alias) => (
            <div key={`chat-${alias}`} className={clsx("h-full", alias === currentBot ? "block" : "hidden")}>
              <ChatScreen botAlias={alias} client={client} />
            </div>
          ))}
        </div>
        <div className={clsx("absolute inset-0", currentTab === "files" ? "block" : "hidden")}>
          <FilesScreen key={`files-${currentBot}`} botAlias={currentBot} client={client} />
        </div>
        <div className={clsx("absolute inset-0", currentTab === "settings" ? "block" : "hidden")}>
          <SettingsScreen key={`settings-${currentBot}`} botAlias={currentBot} client={client} onLogout={handleLogout} />
        </div>
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
            handleSelectBot(alias);
            setCurrentTab("chat");
          }}
          onClose={() => setShowSwitcher(false)}
        />
      ) : null}
    </div>
  );
}
