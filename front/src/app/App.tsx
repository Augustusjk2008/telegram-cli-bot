/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { Folder, GitBranch, Menu, MessageSquare, Settings, SquareTerminal } from "lucide-react";
import { clsx } from "clsx";
import { BotSwitcherSheet } from "../components/BotSwitcherSheet";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { BotSummary, PublicHostInfo } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { BotListScreen } from "../screens/BotListScreen";
import { ChatScreen } from "../screens/ChatScreen";
import { FilesScreen } from "../screens/FilesScreen";
import { GitScreen } from "../screens/GitScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import { readStoredUserAvatarName, storeUserAvatarName } from "../utils/avatar";
import {
  APP_NAME,
  applyChatReadingPreferences,
  applyUiTheme,
  persistChatBodyFontFamily,
  persistChatBodyFontSize,
  persistChatBodyLineHeight,
  persistChatBodyParagraphSpacing,
  persistUiTheme,
  readStoredChatBodyFontFamily,
  readStoredChatBodyFontSize,
  readStoredChatBodyLineHeight,
  readStoredChatBodyParagraphSpacing,
  readStoredUiTheme,
  type ChatBodyFontFamilyName,
  type ChatBodyFontSizeName,
  type ChatBodyLineHeightName,
  type ChatBodyParagraphSpacingName,
  type UiThemeName,
} from "../theme";
import "../styles/tokens.css";
import "../styles/global.css";

const TOKEN_STORAGE_KEY = "web-api-token";
const BOT_STORAGE_KEY = "web-current-bot";
const UNREAD_STORAGE_KEY = "web-unread-bots";
const MAX_CACHED_CHAT_SCREENS = 3;
const TerminalScreen = lazy(() =>
  import("../screens/TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

function readStoredToken() {
  try {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY)?.trim() || "";
  } catch {
    return "";
  }
}

function storeToken(token: string) {
  const trimmed = token.trim();
  if (!trimmed) {
    try {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch {
      // Ignore storage failures and keep the in-memory state.
    }
    return;
  }
  try {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, trimmed);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function clearStoredToken() {
  try {
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function readStoredBotAlias() {
  try {
    return localStorage.getItem(BOT_STORAGE_KEY)?.trim() || "";
  } catch {
    return "";
  }
}

function storeBotAlias(alias: string | null) {
  const trimmed = alias?.trim() || "";
  if (!trimmed) {
    return;
  }
  try {
    localStorage.setItem(BOT_STORAGE_KEY, trimmed);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function readUnreadBots() {
  try {
    const raw = localStorage.getItem(UNREAD_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
  } catch {
    return [];
  }
}

function storeUnreadBots(items: string[]) {
  try {
    if (items.length === 0) {
      localStorage.removeItem(UNREAD_STORAGE_KEY);
      return;
    }
    localStorage.setItem(UNREAD_STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function applyUnreadStatus(bots: BotSummary[], unreadBots: string[]) {
  const unreadSet = new Set(unreadBots);
  return bots.map((bot) => {
    if (bot.status === "busy") {
      return bot;
    }
    if (!unreadSet.has(bot.alias)) {
      return bot;
    }
    return {
      ...bot,
      status: "unread" as const,
      lastActiveText: "未读",
    };
  });
}

function updateMountedChatBots(prev: string[], currentBot: string | null) {
  if (!currentBot) {
    return prev;
  }

  const next = [...prev.filter((alias) => alias !== currentBot), currentBot].slice(-MAX_CACHED_CHAT_SCREENS);
  if (next.length === prev.length && next.every((alias, index) => alias === prev[index])) {
    return prev;
  }
  return next;
}

export function App() {
  const useMockClient = import.meta.env.MODE === "test" || import.meta.env.VITE_USE_MOCK === "true";
  const [client, setClient] = useState<WebBotClient>(() => useMockClient ? new MockWebBotClient() : new RealWebBotClient());
  const [themeName, setThemeName] = useState<UiThemeName>(() => readStoredUiTheme());
  const [chatBodyFontFamily, setChatBodyFontFamily] = useState<ChatBodyFontFamilyName>(() => readStoredChatBodyFontFamily());
  const [chatBodyFontSize, setChatBodyFontSize] = useState<ChatBodyFontSizeName>(() => readStoredChatBodyFontSize());
  const [chatBodyLineHeight, setChatBodyLineHeight] = useState<ChatBodyLineHeightName>(() => readStoredChatBodyLineHeight());
  const [chatBodyParagraphSpacing, setChatBodyParagraphSpacing] = useState<ChatBodyParagraphSpacingName>(() => readStoredChatBodyParagraphSpacing());
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentTab, setCurrentTab] = useState<"chat" | "files" | "terminal" | "git" | "settings">("chat");
  const [currentBot, setCurrentBot] = useState<string | null>(null);
  const [showBotManager, setShowBotManager] = useState(false);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [unreadBots, setUnreadBots] = useState<string[]>(() => readUnreadBots());
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [publicHostInfo, setPublicHostInfo] = useState<PublicHostInfo | null>(null);
  const [mountedChatBots, setMountedChatBots] = useState<string[]>([]);
  const [isChatImmersive, setIsChatImmersive] = useState(false);
  const [isTerminalImmersive, setIsTerminalImmersive] = useState(false);
  const [userAvatarName, setUserAvatarName] = useState(() => readStoredUserAvatarName());
  const displayBots = useMemo(() => applyUnreadStatus(bots, unreadBots), [bots, unreadBots]);
  const botSummaryByAlias = useMemo(() => new Map(displayBots.map((bot) => [bot.alias, bot] as const)), [displayBots]);
  const currentBotSummary = useMemo(() => {
    if (!currentBot) {
      return null;
    }
    return botSummaryByAlias.get(currentBot) || bots.find((bot) => bot.alias === currentBot) || null;
  }, [botSummaryByAlias, bots, currentBot]);

  function handleSelectBot(alias: string | null) {
    setCurrentBot(alias);
    setShowBotManager(false);
    storeBotAlias(alias);
    setIsChatImmersive(false);
    setIsTerminalImmersive(false);
  }

  async function openBotSwitcher() {
    try {
      const nextBots = await client.listBots();
      setBots(nextBots);
    } catch {
      setBots([]);
    } finally {
      setShowSwitcher(true);
    }
  }

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    client.listBots().then(setBots).catch(() => setBots([]));
  }, [client, isLoggedIn]);

  useEffect(() => {
    let cancelled = false;

    client.getPublicHostInfo()
      .then((hostInfo) => {
        if (cancelled) {
          return;
        }
        setPublicHostInfo(hostInfo);
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        setPublicHostInfo(null);
      });

    return () => {
      cancelled = true;
    };
  }, [client]);

  useLayoutEffect(() => {
    applyUiTheme(themeName);
    persistUiTheme(themeName);
  }, [themeName]);

  useLayoutEffect(() => {
    applyChatReadingPreferences(
      chatBodyFontFamily,
      chatBodyFontSize,
      chatBodyLineHeight,
      chatBodyParagraphSpacing,
    );
    persistChatBodyFontFamily(chatBodyFontFamily);
    persistChatBodyFontSize(chatBodyFontSize);
    persistChatBodyLineHeight(chatBodyLineHeight);
    persistChatBodyParagraphSpacing(chatBodyParagraphSpacing);
  }, [chatBodyFontFamily, chatBodyFontSize, chatBodyLineHeight, chatBodyParagraphSpacing]);

  useEffect(() => {
    if (!isLoggedIn) {
      document.title = APP_NAME;
      return;
    }
    if (showBotManager || !currentBot) {
      document.title = `Bot 管理 - ${APP_NAME}`;
      return;
    }
    if (currentTab === "terminal") {
      document.title = `终端 - ${APP_NAME}`;
      return;
    }
    if (currentBot) {
      document.title = `${currentBot} - ${APP_NAME}`;
      return;
    }
    document.title = APP_NAME;
  }, [currentBot, currentTab, isLoggedIn, showBotManager]);

  useEffect(() => {
    storeUnreadBots(unreadBots);
  }, [unreadBots]);

  useEffect(() => {
    if (!isLoggedIn || bots.length === 0) {
      return;
    }

    if (showBotManager) {
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
  }, [bots, currentBot, isLoggedIn, showBotManager]);

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
        setShowBotManager(false);
        setMountedChatBots(restoredAlias ? [restoredAlias] : []);
        setLoginError("");
        setIsTerminalImmersive(false);
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
      setShowBotManager(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setIsTerminalImmersive(false);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoginLoading(false);
    }
  }

  function handleLogout() {
    clearStoredToken();
    storeUnreadBots([]);
    setClient(useMockClient ? new MockWebBotClient() : new RealWebBotClient());
    setIsLoggedIn(false);
    setCurrentBot(null);
    setShowBotManager(false);
    setCurrentTab("chat");
    setBots([]);
    setUnreadBots([]);
    setMountedChatBots([]);
    setLoginError("");
    setIsChatImmersive(false);
    setIsTerminalImmersive(false);
  }

  function handleThemeChange(nextTheme: UiThemeName) {
    setThemeName(nextTheme);
  }

  function handleChatBodyFontFamilyChange(nextFontFamily: ChatBodyFontFamilyName) {
    setChatBodyFontFamily(nextFontFamily);
  }

  function handleChatBodyFontSizeChange(nextFontSize: ChatBodyFontSizeName) {
    setChatBodyFontSize(nextFontSize);
  }

  function handleChatBodyLineHeightChange(nextLineHeight: ChatBodyLineHeightName) {
    setChatBodyLineHeight(nextLineHeight);
  }

  function handleChatBodyParagraphSpacingChange(nextParagraphSpacing: ChatBodyParagraphSpacingName) {
    setChatBodyParagraphSpacing(nextParagraphSpacing);
  }

  function handleUserAvatarChange(nextAvatarName: string) {
    setUserAvatarName(nextAvatarName);
    storeUserAvatarName(nextAvatarName);
  }

  useEffect(() => {
    if (!currentBot) {
      return;
    }
    setMountedChatBots((prev) => updateMountedChatBots(prev, currentBot));
  }, [currentBot]);

  useEffect(() => {
    if (currentTab !== "chat" || !currentBot) {
      return;
    }
    setUnreadBots((prev) => prev.filter((alias) => alias !== currentBot));
  }, [currentBot, currentTab]);

  function markBotUnread(alias: string) {
    setUnreadBots((prev) => (prev.includes(alias) ? prev : [...prev, alias]));
  }

  if (!isLoggedIn) {
    return <LoginScreen onLogin={handleLogin} isLoading={loginLoading} error={loginError} hostInfo={publicHostInfo} />;
  }

  if (showBotManager || !currentBot) {
    return <BotListScreen client={client} onSelect={handleSelectBot} />;
  }

  const hideOuterChrome = (currentTab === "chat" && isChatImmersive)
    || (currentTab === "terminal" && isTerminalImmersive);
  let activeScreen: ReactNode = null;

  if (currentTab === "chat") {
    activeScreen = (
      <div className="absolute inset-0">
        {mountedChatBots.map((alias) => (
          <div key={`chat-${alias}`} className={clsx("h-full", alias === currentBot ? "block" : "hidden")}>
            <ChatScreen
              botAlias={alias}
              client={client}
              botAvatarName={botSummaryByAlias.get(alias)?.avatarName || bots.find((bot) => bot.alias === alias)?.avatarName}
              userAvatarName={userAvatarName}
              isVisible={alias === currentBot}
              isImmersive={alias === currentBot ? isChatImmersive : false}
              onToggleImmersive={alias === currentBot
                ? () => setIsChatImmersive((prev) => !prev)
                : undefined}
              onUnreadResult={markBotUnread}
            />
          </div>
        ))}
      </div>
    );
  } else if (currentTab === "files") {
    activeScreen = (
      <div className="absolute inset-0">
        <FilesScreen
          key={`files-${currentBot}`}
          botAlias={currentBot}
          botAvatarName={currentBotSummary?.avatarName}
          client={client}
        />
      </div>
    );
  } else if (currentTab === "terminal") {
    activeScreen = (
      <div className="absolute inset-0">
        <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">加载终端...</div>}>
          <TerminalScreen
            authToken={readStoredToken()}
            botAlias={currentBot}
            client={client}
            isVisible
            preferredWorkingDir={currentBotSummary?.workingDir || ""}
            themeName={themeName}
            isImmersive={isTerminalImmersive}
            onToggleImmersive={() => setIsTerminalImmersive((prev) => !prev)}
          />
        </Suspense>
      </div>
    );
  } else if (currentTab === "git") {
    activeScreen = (
      <div className="absolute inset-0">
        <GitScreen key={`git-${currentBot}`} botAlias={currentBot} botAvatarName={currentBotSummary?.avatarName} client={client} />
      </div>
    );
  } else if (currentTab === "settings") {
    activeScreen = (
      <div className="absolute inset-0">
        <SettingsScreen
          key={`settings-${currentBot}`}
          botAlias={currentBot}
          botAvatarName={currentBotSummary?.avatarName}
          client={client}
          onLogout={handleLogout}
          themeName={themeName}
          onThemeChange={handleThemeChange}
          chatBodyFontFamily={chatBodyFontFamily}
          onChatBodyFontFamilyChange={handleChatBodyFontFamilyChange}
          chatBodyFontSize={chatBodyFontSize}
          onChatBodyFontSizeChange={handleChatBodyFontSizeChange}
          chatBodyLineHeight={chatBodyLineHeight}
          onChatBodyLineHeightChange={handleChatBodyLineHeightChange}
          chatBodyParagraphSpacing={chatBodyParagraphSpacing}
          onChatBodyParagraphSpacingChange={handleChatBodyParagraphSpacingChange}
          userAvatarName={userAvatarName}
          onUserAvatarChange={handleUserAvatarChange}
        />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col h-[100dvh] w-full bg-[var(--bg)] shadow-xl overflow-hidden relative">
      {!hideOuterChrome ? (
        <header className="flex items-center justify-between p-3 bg-[var(--surface-strong)] border-b border-[var(--border)] shrink-0">
          <button
            onClick={() => {
              void openBotSwitcher();
            }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-[var(--border)] transition-colors"
          >
            <Menu className="w-5 h-5" />
            <span className="font-semibold">{currentBot}</span>
          </button>
        </header>
      ) : null}

      <div className="flex-1 overflow-hidden relative">
        {activeScreen}
      </div>

      {!hideOuterChrome ? (
        <nav className="flex items-center justify-around p-2 bg-[var(--surface-strong)] border-t border-[var(--border)] shrink-0 pb-safe">
          <button
            onClick={() => {
              setCurrentTab("chat");
              setIsTerminalImmersive(false);
            }}
            className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "chat" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
          >
            <MessageSquare className="w-6 h-6 mb-1" />
            <span className="text-[10px] font-medium">聊天</span>
          </button>
          <button
            onClick={() => {
              setCurrentTab("files");
              setIsChatImmersive(false);
              setIsTerminalImmersive(false);
            }}
            className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "files" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
          >
            <Folder className="w-6 h-6 mb-1" />
            <span className="text-[10px] font-medium">文件</span>
          </button>
          <button
            onClick={() => {
              setCurrentTab("terminal");
              setIsChatImmersive(false);
            }}
            className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "terminal" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
          >
            <SquareTerminal className="w-6 h-6 mb-1" />
            <span className="text-[10px] font-medium">终端</span>
          </button>
          <button
            onClick={() => {
              setCurrentTab("git");
              setIsChatImmersive(false);
              setIsTerminalImmersive(false);
            }}
            className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "git" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
          >
            <GitBranch className="w-6 h-6 mb-1" />
            <span className="text-[10px] font-medium">Git</span>
          </button>
          <button
            onClick={() => {
              setCurrentTab("settings");
              setIsChatImmersive(false);
              setIsTerminalImmersive(false);
            }}
            className={clsx("flex flex-col items-center p-2 rounded-xl min-w-[64px]", currentTab === "settings" ? "text-[var(--accent)]" : "text-[var(--muted)]")}
          >
            <Settings className="w-6 h-6 mb-1" />
            <span className="text-[10px] font-medium">设置</span>
          </button>
        </nav>
      ) : null}

      {showSwitcher ? (
        <BotSwitcherSheet
          bots={displayBots}
          currentAlias={currentBot}
          onSelect={(alias) => {
            handleSelectBot(alias);
            setCurrentTab("chat");
            setIsTerminalImmersive(false);
          }}
          onManage={() => {
            setShowBotManager(true);
            setShowSwitcher(false);
            setIsChatImmersive(false);
            setIsTerminalImmersive(false);
          }}
          onClose={() => setShowSwitcher(false)}
        />
      ) : null}
    </div>
  );
}
