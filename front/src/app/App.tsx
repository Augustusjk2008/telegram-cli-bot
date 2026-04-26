/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { MobileShell, type AppTab } from "./MobileShell";
import {
  readStoredViewMode,
  readViewportWidth,
  resolveEffectiveLayoutMode,
  storeViewMode,
  type ViewMode,
} from "./layoutMode";
import { BotSwitcherSheet } from "../components/BotSwitcherSheet";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { BotStatus, BotSummary, PublicHostInfo, SessionState } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { BotListScreen } from "../screens/BotListScreen";
import { ChatScreen } from "../screens/ChatScreen";
import { FilesScreen } from "../screens/FilesScreen";
import { GitScreen } from "../screens/GitScreen";
import { InviteCodeManagementScreen } from "../screens/InviteCodeManagementScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { MobileDebugScreen } from "../screens/MobileDebugScreen";
import { PluginsScreen } from "../screens/PluginsScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";
import type { ChatWorkbenchStatus } from "../workbench/workbenchTypes";
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
import { hasCapability, isGuest } from "../utils/capabilities";
import "../styles/tokens.css";
import "../styles/global.css";

const SESSION_TOKEN_STORAGE_KEY = "web-session-token";
const LEGACY_TOKEN_STORAGE_KEY = "web-api-token";
const BOT_STORAGE_KEY = "web-current-bot";
const UNREAD_STORAGE_KEY = "web-unread-bots";
const MAX_CACHED_CHAT_SCREENS = 3;
const TerminalScreen = lazy(() =>
  import("../screens/TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

function readStoredToken() {
  try {
    return (
      sessionStorage.getItem(SESSION_TOKEN_STORAGE_KEY)?.trim()
      || sessionStorage.getItem(LEGACY_TOKEN_STORAGE_KEY)?.trim()
      || ""
    );
  } catch {
    return "";
  }
}

function storeToken(token: string) {
  const trimmed = token.trim();
  if (!trimmed) {
    try {
      sessionStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
      sessionStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
    } catch {
      // Ignore storage failures and keep the in-memory state.
    }
    return;
  }
  try {
    sessionStorage.setItem(SESSION_TOKEN_STORAGE_KEY, trimmed);
    sessionStorage.setItem(LEGACY_TOKEN_STORAGE_KEY, trimmed);
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function clearStoredToken() {
  try {
    sessionStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
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

const BOT_SWITCHER_STATUS_PRIORITY: Record<BotStatus, number> = {
  unread: 0,
  running: 1,
  busy: 2,
  offline: 3,
};

function isMainBot(bot: BotSummary) {
  return Boolean(bot.isMain || bot.alias === "main");
}

function sortBotsForSwitcher(bots: BotSummary[]) {
  return [...bots].sort((left, right) => {
    const leftIsMain = isMainBot(left);
    const rightIsMain = isMainBot(right);
    if (leftIsMain !== rightIsMain) {
      return leftIsMain ? -1 : 1;
    }

    const statusDelta = BOT_SWITCHER_STATUS_PRIORITY[left.status] - BOT_SWITCHER_STATUS_PRIORITY[right.status];
    if (statusDelta !== 0) {
      return statusDelta;
    }

    return left.alias.localeCompare(right.alias, "zh-CN", {
      numeric: true,
      sensitivity: "base",
    });
  });
}

function buildDisplayBots(bots: BotSummary[], unreadBots: string[]) {
  return sortBotsForSwitcher(applyUnreadStatus(bots, unreadBots));
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
  const [viewMode, setViewMode] = useState<ViewMode>(() => readStoredViewMode());
  const [viewportWidth, setViewportWidth] = useState(() => readViewportWidth());
  const [session, setSession] = useState<SessionState | null>(null);
  const [currentTab, setCurrentTab] = useState<AppTab>("chat");
  const [currentBot, setCurrentBot] = useState<string | null>(null);
  const [showBotManager, setShowBotManager] = useState(false);
  const [showInviteCodeManager, setShowInviteCodeManager] = useState(false);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [desktopHasDirtyTabs, setDesktopHasDirtyTabs] = useState(false);
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [unreadBots, setUnreadBots] = useState<string[]>(() => readUnreadBots());
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [publicHostInfo, setPublicHostInfo] = useState<PublicHostInfo | null>(null);
  const [mountedChatBots, setMountedChatBots] = useState<string[]>([]);
  const [desktopChatStatusByBot, setDesktopChatStatusByBot] = useState<Record<string, ChatWorkbenchStatus>>({});
  const [desktopChatPaneVisible, setDesktopChatPaneVisible] = useState(true);
  const [isChatImmersive, setIsChatImmersive] = useState(false);
  const [isTerminalImmersive, setIsTerminalImmersive] = useState(false);
  const [userAvatarName, setUserAvatarName] = useState(() => readStoredUserAvatarName());
  const isLoggedIn = Boolean(session?.isLoggedIn);
  const chatReadOnly = !hasCapability(session, "chat_send");
  const allowTrace = hasCapability(session, "view_chat_trace");
  const structureOnly = !hasCapability(session, "read_file_content");
  const canUseTerminal = hasCapability(session, "terminal_exec");
  const canUseDebug = hasCapability(session, "debug_exec");
  const canUseGit = hasCapability(session, "git_ops");
  const canViewPlugins = hasCapability(session, "view_plugins");
  const canUseSettings = hasCapability(session, "admin_ops");
  const canManageBots = hasCapability(session, "admin_ops");
  const canManageRegisterCodes = hasCapability(session, "manage_register_codes");
  const displayBots = useMemo(() => buildDisplayBots(bots, unreadBots), [bots, unreadBots]);
  const botSummaryByAlias = useMemo(() => new Map(displayBots.map((bot) => [bot.alias, bot] as const)), [displayBots]);
  const hasUnreadOtherBots = useMemo(() => {
    if (unreadBots.length === 0) {
      return false;
    }
    const knownAliases = new Set(bots.map((bot) => bot.alias));
    return unreadBots.some((alias) => alias !== currentBot && knownAliases.has(alias));
  }, [bots, currentBot, unreadBots]);
  const effectiveLayoutMode = resolveEffectiveLayoutMode(viewMode, viewportWidth);
  const currentBotSummary = useMemo(() => {
    if (!currentBot) {
      return null;
    }
    return botSummaryByAlias.get(currentBot) || bots.find((bot) => bot.alias === currentBot) || null;
  }, [botSummaryByAlias, bots, currentBot]);

  function handleSelectBot(alias: string | null) {
    setCurrentBot(alias);
    setShowBotManager(false);
    setShowInviteCodeManager(false);
    storeBotAlias(alias);
    setIsChatImmersive(false);
    setIsTerminalImmersive(false);
  }

  function commitBotSelection(alias: string | null) {
    handleSelectBot(alias);
  }

  function requestBotSelection(alias: string | null) {
    if (effectiveLayoutMode === "desktop" && desktopHasDirtyTabs) {
      const confirmed = window.confirm("当前桌面工作台有未保存文件，切换智能体会丢失这些修改。确定继续吗？");
      if (!confirmed) {
        return false;
      }
    }
    commitBotSelection(alias);
    setCurrentTab("chat");
    return true;
  }

  async function openBotSwitcher() {
    setShowSwitcher(true);
    try {
      const nextBots = await client.listBots();
      setBots(nextBots);
    } catch {
      // Keep the current list so the switcher can open immediately even if refresh fails.
    }
  }

  function openInviteCodeManager() {
    setShowInviteCodeManager(true);
    setShowBotManager(false);
    setShowSwitcher(false);
    setIsChatImmersive(false);
    setIsTerminalImmersive(false);
  }

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    client.listBots().then(setBots).catch(() => setBots([]));
  }, [client, isLoggedIn]);

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    const allowedTabs: AppTab[] = ["chat", "files"];
    if (canUseDebug) {
      allowedTabs.push("debug");
    }
    if (canUseTerminal) {
      allowedTabs.push("terminal");
    }
    if (canUseGit) {
      allowedTabs.push("git");
    }
    if (canViewPlugins) {
      allowedTabs.push("plugins");
    }
    if (canUseSettings) {
      allowedTabs.push("settings");
    }
    if (!allowedTabs.includes(currentTab)) {
      setCurrentTab("chat");
      setIsChatImmersive(false);
      setIsTerminalImmersive(false);
    }
  }, [canUseDebug, canUseGit, canUseSettings, canUseTerminal, canViewPlugins, currentTab, isLoggedIn]);

  useEffect(() => {
    storeViewMode(viewMode);
  }, [viewMode]);

  useEffect(() => {
    const handleResize = () => {
      setViewportWidth(readViewportWidth());
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

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
    if (showInviteCodeManager) {
      document.title = `邀请码管理 - ${APP_NAME}`;
      return;
    }
    if (showBotManager || !currentBot) {
      document.title = `智能体管理 - ${APP_NAME}`;
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
  }, [currentBot, currentTab, isLoggedIn, showBotManager, showInviteCodeManager]);

  useEffect(() => {
    if (canManageRegisterCodes || !showInviteCodeManager) {
      return;
    }
    setShowInviteCodeManager(false);
  }, [canManageRegisterCodes, showInviteCodeManager]);

  useEffect(() => {
    storeUnreadBots(unreadBots);
  }, [unreadBots]);

  useEffect(() => {
    if (!isLoggedIn || bots.length === 0) {
      return;
    }

    if (showBotManager || showInviteCodeManager) {
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
  }, [bots, currentBot, isLoggedIn, showBotManager, showInviteCodeManager]);

  useEffect(() => {
    const storedToken = readStoredToken();
    if (!storedToken && useMockClient) {
      return;
    }
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    nextClient.restoreSession(storedToken)
      .then((nextSession) => {
        const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
        setClient(nextClient);
        setSession(nextSession);
        setCurrentBot(restoredAlias || null);
        setShowBotManager(false);
        setShowInviteCodeManager(false);
        setMountedChatBots(restoredAlias ? [restoredAlias] : []);
        setDesktopChatStatusByBot({});
        setLoginError("");
        setIsTerminalImmersive(false);
      })
      .catch(() => {
        if (storedToken) {
          clearStoredToken();
          setLoginError("本地登录已失效，请重登");
        }
      })
      .finally(() => {
        setLoginLoading(false);
      });
  }, [useMockClient]);

  async function handleLogin(input: { username: string; password: string }) {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const nextSession = await nextClient.login(input);
      const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
      storeToken(nextSession.token || "");
      setClient(nextClient);
      setSession(nextSession);
      setCurrentBot(restoredAlias || null);
      setShowBotManager(false);
      setShowInviteCodeManager(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setDesktopChatStatusByBot({});
      setIsTerminalImmersive(false);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleRegister(input: { username: string; password: string; registerCode: string }) {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const nextSession = await nextClient.register(input);
      const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
      storeToken(nextSession.token || "");
      setClient(nextClient);
      setSession(nextSession);
      setCurrentBot(restoredAlias || null);
      setShowBotManager(false);
      setShowInviteCodeManager(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setDesktopChatStatusByBot({});
      setIsTerminalImmersive(false);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleGuestLogin() {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const nextSession = await nextClient.loginGuest();
      const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
      storeToken(nextSession.token || "");
      setClient(nextClient);
      setSession(nextSession);
      setCurrentBot(restoredAlias || null);
      setShowBotManager(false);
      setShowInviteCodeManager(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setDesktopChatStatusByBot({});
      setIsTerminalImmersive(false);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "进入失败");
    } finally {
      setLoginLoading(false);
    }
  }

  function handleLogout() {
    void client.logout().catch(() => undefined);
    clearStoredToken();
    storeUnreadBots([]);
    setClient(useMockClient ? new MockWebBotClient() : new RealWebBotClient());
    setSession(null);
    setCurrentBot(null);
    setShowBotManager(false);
    setShowInviteCodeManager(false);
    setCurrentTab("chat");
    setBots([]);
    setUnreadBots([]);
    setMountedChatBots([]);
    setDesktopChatStatusByBot({});
    setDesktopChatPaneVisible(true);
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
    return (
      <LoginScreen
        onLogin={handleLogin}
        onRegister={handleRegister}
        onGuestLogin={handleGuestLogin}
        isLoading={loginLoading}
        error={loginError}
        hostInfo={publicHostInfo}
      />
    );
  }

  if (showInviteCodeManager && canManageRegisterCodes) {
    return (
      <InviteCodeManagementScreen
        client={client}
        onClose={() => setShowInviteCodeManager(false)}
      />
    );
  }

  if (showBotManager || !currentBot) {
    return <BotListScreen client={client} onSelect={handleSelectBot} onBotsChange={setBots} canManage={canManageBots} />;
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
              readOnly={chatReadOnly}
              allowTrace={allowTrace}
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
          structureOnly={structureOnly}
        />
      </div>
    );
  } else if (currentTab === "debug" && canUseDebug) {
    activeScreen = (
      <div className="absolute inset-0">
        <MobileDebugScreen
          authToken={readStoredToken()}
          botAlias={currentBot}
          client={client}
        />
      </div>
    );
  } else if (currentTab === "terminal" && canUseTerminal) {
    activeScreen = (
      <div className="absolute inset-0">
        <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">加载终端...</div>}>
          <TerminalScreen
            authToken={readStoredToken()}
            isVisible
            preferredWorkingDir={currentBotSummary?.workingDir || ""}
            themeName={themeName}
            isImmersive={isTerminalImmersive}
            onToggleImmersive={() => setIsTerminalImmersive((prev) => !prev)}
          />
        </Suspense>
      </div>
    );
  } else if (currentTab === "git" && canUseGit) {
    activeScreen = (
      <div className="absolute inset-0">
        <GitScreen key={`git-${currentBot}`} botAlias={currentBot} botAvatarName={currentBotSummary?.avatarName} client={client} />
      </div>
    );
  } else if (currentTab === "plugins" && canViewPlugins) {
    activeScreen = (
      <div className="absolute inset-0">
        <PluginsScreen
          key={`plugins-${currentBot}`}
          client={client}
          botAlias={currentBot}
        />
      </div>
    );
  } else if (currentTab === "settings" && canUseSettings) {
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
          sessionCapabilities={session?.capabilities}
        />
      </div>
    );
  }

  const switcher = showSwitcher ? (
    <BotSwitcherSheet
      bots={displayBots}
      currentAlias={currentBot}
      onSelect={(alias) => {
        return requestBotSelection(alias);
      }}
      onManage={() => {
        setShowBotManager(true);
        setShowInviteCodeManager(false);
        setShowSwitcher(false);
        setIsChatImmersive(false);
        setIsTerminalImmersive(false);
      }}
      showInviteManager={canManageRegisterCodes}
      inviteManagerActive={showInviteCodeManager}
      onOpenInviteManager={() => {
        openInviteCodeManager();
      }}
      onClose={() => setShowSwitcher(false)}
    />
  ) : null;

  if (effectiveLayoutMode === "desktop") {
    return (
      <>
        <PersistentTerminalProvider client={client}>
          <DesktopWorkbench
            authToken={readStoredToken()}
            botAlias={currentBot}
            botAvatarName={currentBotSummary?.avatarName}
            userAvatarName={userAvatarName}
            client={client}
            structureOnly={structureOnly}
            chatReadOnly={chatReadOnly}
            allowTrace={allowTrace}
            allowCodeJump={!structureOnly && !isGuest(session)}
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
            onUserAvatarChange={handleUserAvatarChange}
            sessionCapabilities={session?.capabilities}
            viewMode={viewMode}
            hasUnreadOtherBots={hasUnreadOtherBots}
            chatStatus={currentBot ? desktopChatStatusByBot[currentBot] : undefined}
            chatPaneContent={({ requestPreview }) => (
              <div className="h-full">
                {mountedChatBots.map((alias) => (
                  <div key={`desktop-chat-${alias}`} className={clsx("h-full", alias === currentBot ? "block" : "hidden")}>
                    <ChatScreen
                      botAlias={alias}
                      client={client}
                      botAvatarName={botSummaryByAlias.get(alias)?.avatarName || bots.find((bot) => bot.alias === alias)?.avatarName}
                      userAvatarName={userAvatarName}
                      isVisible={alias === currentBot && desktopChatPaneVisible}
                      readOnly={chatReadOnly}
                      allowTrace={allowTrace}
                      embedded
                      onRequestDesktopPreview={requestPreview}
                      onUnreadResult={markBotUnread}
                      onWorkbenchStatusChange={(status) => {
                        setDesktopChatStatusByBot((prev) => {
                          const currentStatus = prev[alias];
                          if (
                            currentStatus?.state === status.state
                            && currentStatus.processing === status.processing
                            && currentStatus.elapsedSeconds === status.elapsedSeconds
                            && currentStatus.lastError === status.lastError
                          ) {
                            return prev;
                          }
                          return {
                            ...prev,
                            [alias]: status,
                          };
                        });
                      }}
                    />
                  </div>
                ))}
              </div>
            )}
            onViewModeChange={setViewMode}
            onOpenBotSwitcher={() => {
              void openBotSwitcher();
            }}
            onDirtyTabsChange={setDesktopHasDirtyTabs}
            onChatPaneVisibilityChange={setDesktopChatPaneVisible}
          />
        </PersistentTerminalProvider>
        {switcher}
      </>
    );
  }

  return (
    <>
      <PersistentTerminalProvider client={client}>
        <MobileShell
          session={session}
          currentBot={currentBot}
          currentTab={currentTab}
          hideOuterChrome={hideOuterChrome}
          activeScreen={activeScreen}
          viewMode={viewMode}
          hasUnreadOtherBots={hasUnreadOtherBots}
          onOpenBotSwitcher={() => {
            void openBotSwitcher();
          }}
          onViewModeChange={setViewMode}
          onTabChange={(tab) => {
            setCurrentTab(tab);
            if (tab !== "chat") {
              setIsChatImmersive(false);
            }
            if (tab !== "terminal") {
              setIsTerminalImmersive(false);
            }
          }}
        />
      </PersistentTerminalProvider>
      {switcher}
    </>
  );
}
