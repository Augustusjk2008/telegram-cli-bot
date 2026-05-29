/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { MobileShell, type AppTab } from "./MobileShell";
import { NotificationCenter } from "./NotificationCenter";
import {
  readStoredViewMode,
  readViewportWidth,
  resolveEffectiveLayoutMode,
  storeViewMode,
  type ViewMode,
} from "./layoutMode";
import {
  applyBotActivityOverrides,
  updateBotAgentActivityOverrides,
  type BotActivityChange,
  type BotAgentActivityOverrides,
} from "./botActivity";
import { BotSwitcherSheet } from "../components/BotSwitcherSheet";
import { DesktopBotSwitcherPopover } from "../components/DesktopBotSwitcherPopover";
import { AnnouncementButton } from "../components/AnnouncementButton";
import { AnnouncementDialog } from "../components/AnnouncementDialog";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";
import type { AnnouncementListResult, BotStatus, BotSummary, PublicHostInfo, SessionState } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { BotListScreen } from "../screens/BotListScreen";
import { ChatScreen } from "../screens/ChatScreen";
import { DesktopBotManagerScreen } from "../screens/DesktopBotManagerScreen";
import { FilesScreen } from "../screens/FilesScreen";
import { GitScreen } from "../screens/GitScreen";
import { AdminCenterScreen } from "../screens/AdminCenterScreen";
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
const EMPTY_ANNOUNCEMENT_STATE: AnnouncementListResult = {
  items: [],
  latestId: "",
  lastSeenId: "",
  hasUnseen: false,
};
const TerminalScreen = lazy(() =>
  import("../screens/TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

function readStoredToken() {
  try {
    return (
      sessionStorage.getItem(SESSION_TOKEN_STORAGE_KEY)?.trim()
      || sessionStorage.getItem(LEGACY_TOKEN_STORAGE_KEY)?.trim()
      || localStorage.getItem(SESSION_TOKEN_STORAGE_KEY)?.trim()
      || localStorage.getItem(LEGACY_TOKEN_STORAGE_KEY)?.trim()
      || ""
    );
  } catch {
    return "";
  }
}

function storeToken(token: string, remember = false) {
  const trimmed = token.trim();
  if (!trimmed) {
    try {
      sessionStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
      sessionStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
      localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
      localStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
    } catch {
      // Ignore storage failures and keep the in-memory state.
    }
    return;
  }
  try {
    sessionStorage.setItem(SESSION_TOKEN_STORAGE_KEY, trimmed);
    sessionStorage.setItem(LEGACY_TOKEN_STORAGE_KEY, trimmed);
    if (remember) {
      localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, trimmed);
      localStorage.setItem(LEGACY_TOKEN_STORAGE_KEY, trimmed);
    } else {
      localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
      localStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures and keep the in-memory state.
  }
}

function clearStoredToken() {
  try {
    sessionStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
    localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
    localStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
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
  busy: 1,
  running: 2,
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

function buildDisplayBots(
  bots: BotSummary[],
  unreadBots: string[],
  botActivityOverrides: BotAgentActivityOverrides,
) {
  return sortBotsForSwitcher(applyUnreadStatus(applyBotActivityOverrides(bots, botActivityOverrides), unreadBots));
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
  const [showAdminCenter, setShowAdminCenter] = useState(false);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [botSwitcherAnchorRect, setBotSwitcherAnchorRect] = useState<DOMRect | null>(null);
  const [desktopHasDirtyTabs, setDesktopHasDirtyTabs] = useState(false);
  const [bots, setBots] = useState<BotSummary[]>([]);
  const [unreadBots, setUnreadBots] = useState<string[]>(() => readUnreadBots());
  const [botActivityOverrides, setBotActivityOverrides] = useState<BotAgentActivityOverrides>({});
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [publicHostInfo, setPublicHostInfo] = useState<PublicHostInfo | null>(null);
  const [mountedChatBots, setMountedChatBots] = useState<string[]>([]);
  const [desktopChatStatusByBot, setDesktopChatStatusByBot] = useState<Record<string, ChatWorkbenchStatus>>({});
  const [desktopChatPaneVisible, setDesktopChatPaneVisible] = useState(true);
  const [isChatImmersive, setIsChatImmersive] = useState(false);
  const [isTerminalImmersive, setIsTerminalImmersive] = useState(false);
  const [userAvatarName, setUserAvatarName] = useState(() => readStoredUserAvatarName());
  const [announcementState, setAnnouncementState] = useState<AnnouncementListResult>(EMPTY_ANNOUNCEMENT_STATE);
  const [announcementOpen, setAnnouncementOpen] = useState(false);
  const announcementAutoOpenedRef = useRef(false);
  const isLoggedIn = Boolean(session?.isLoggedIn);
  const chatReadOnly = !hasCapability(session, "chat_send");
  const allowTrace = hasCapability(session, "view_chat_trace");
  const canUseTerminal = hasCapability(session, "terminal_exec");
  const canUseDebug = hasCapability(session, "debug_exec");
  const canUseGit = hasCapability(session, "git_ops");
  const canViewPlugins = hasCapability(session, "view_plugins");
  const canUseSettings = hasCapability(session, "admin_ops");
  const canManageBots = hasCapability(session, "admin_ops");
  const canOpenAdminCenter = hasCapability(session, "admin_ops");
  const canManageEnvConfig = hasCapability(session, "admin_ops");
  const canManageRegisterCodes = hasCapability(session, "manage_register_codes");
  const displayBots = useMemo(() => buildDisplayBots(bots, unreadBots, botActivityOverrides), [botActivityOverrides, bots, unreadBots]);
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
  const visibleChatBotAlias = currentBot
    && !showBotManager
    && !showAdminCenter
    && (
      effectiveLayoutMode === "desktop"
        ? desktopChatPaneVisible
        : currentTab === "chat"
    )
    ? currentBot
    : null;
  const canOperateCurrentBot = currentBotSummary?.canOperate !== false;
  const canReadCurrentBotFiles = canOperateCurrentBot && hasCapability(session, "read_file_content");
  const canWriteCurrentBotFiles = canOperateCurrentBot && hasCapability(session, "write_files");
  const structureOnly = !canReadCurrentBotFiles;
  const canUseCurrentBotTerminal = canUseTerminal && canOperateCurrentBot;
  const terminalDisabledReason = !canUseTerminal
    ? "你无权限使用终端"
    : canUseCurrentBotTerminal
      ? ""
      : "你无权限使用此智能体终端";
  const canViewAssistantOps = effectiveLayoutMode === "desktop"
    && currentBotSummary?.botMode === "assistant"
    && hasCapability(session, "admin_ops");

  function handleSelectBot(alias: string | null) {
    setCurrentBot(alias);
    setShowBotManager(false);
    setShowAdminCenter(false);
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

  async function openBotSwitcher(anchorRect?: DOMRect) {
    setBotSwitcherAnchorRect(anchorRect || null);
    setShowSwitcher(true);
    try {
      const nextBots = await client.listBots();
      setBots(nextBots);
    } catch {
      // Keep the current list so the switcher can open immediately even if refresh fails.
    }
  }

  function closeBotSwitcher() {
    setShowSwitcher(false);
    setBotSwitcherAnchorRect(null);
  }

  function openAdminCenter() {
    setShowAdminCenter(true);
    setShowBotManager(false);
    setShowSwitcher(false);
    setIsChatImmersive(false);
    setIsTerminalImmersive(false);
  }

  async function refreshAnnouncements(nextClient = client, autoOpen = false) {
    try {
      const result = await nextClient.listAnnouncements();
      setAnnouncementState(result);
      if (autoOpen && !announcementAutoOpenedRef.current && result.hasUnseen && result.items.length > 0) {
        announcementAutoOpenedRef.current = true;
        setAnnouncementOpen(true);
      }
    } catch {
      setAnnouncementState(EMPTY_ANNOUNCEMENT_STATE);
    }
  }

  async function handleCloseAnnouncements(latestId: string) {
    setAnnouncementOpen(false);
    if (!latestId) {
      return;
    }
    try {
      const result = await client.markAnnouncementsSeen(latestId);
      setAnnouncementState(result);
    } catch {
      setAnnouncementState((current) => ({
        ...current,
        hasUnseen: false,
        lastSeenId: latestId,
      }));
    }
  }

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    client.listBots().then(setBots).catch(() => setBots([]));
  }, [client, isLoggedIn]);

  const allowedTabs = useMemo(() => {
    const nextTabs: AppTab[] = ["chat", "files"];
    if (canUseDebug) {
      nextTabs.push("debug");
    }
    if (canUseTerminal) {
      nextTabs.push("terminal");
    }
    if (canUseGit) {
      nextTabs.push("git");
    }
    if (canViewPlugins) {
      nextTabs.push("plugins");
    }
    if (canUseSettings) {
      nextTabs.push("settings");
    }
    return nextTabs;
  }, [canUseDebug, canUseGit, canUseSettings, canUseTerminal, canViewPlugins]);

  useEffect(() => {
    if (!isLoggedIn) {
      return;
    }
    if (!allowedTabs.includes(currentTab)) {
      setCurrentTab("chat");
      setIsChatImmersive(false);
      setIsTerminalImmersive(false);
    }
  }, [allowedTabs, currentTab, isLoggedIn]);

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
    if (showAdminCenter) {
      document.title = `管理中心 - ${APP_NAME}`;
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
  }, [currentBot, currentTab, isLoggedIn, showAdminCenter, showBotManager]);

  useEffect(() => {
    if (canOpenAdminCenter || !showAdminCenter) {
      return;
    }
    setShowAdminCenter(false);
  }, [canOpenAdminCenter, showAdminCenter]);

  useEffect(() => {
    storeUnreadBots(unreadBots);
  }, [unreadBots]);

  useEffect(() => {
    if (!isLoggedIn || bots.length === 0) {
      return;
    }

    if (showBotManager || showAdminCenter) {
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
  }, [bots, currentBot, isLoggedIn, showAdminCenter, showBotManager]);

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
        setShowAdminCenter(false);
        setMountedChatBots(restoredAlias ? [restoredAlias] : []);
        setDesktopChatStatusByBot({});
        setLoginError("");
        setIsTerminalImmersive(false);
        void refreshAnnouncements(nextClient, true);
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

  async function handleLogin(input: { username: string; password: string; remember?: boolean }) {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const nextSession = await nextClient.login(input);
      const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
      storeToken(nextSession.token || "", Boolean(input.remember));
      setClient(nextClient);
      setSession(nextSession);
      setCurrentBot(restoredAlias || null);
      setShowBotManager(false);
      setShowAdminCenter(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setDesktopChatStatusByBot({});
      setIsTerminalImmersive(false);
      void refreshAnnouncements(nextClient, true);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleRegister(input: { username: string; password: string; registerCode: string; remember?: boolean }) {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const nextSession = await nextClient.register(input);
      const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
      storeToken(nextSession.token || "", Boolean(input.remember));
      setClient(nextClient);
      setSession(nextSession);
      setCurrentBot(restoredAlias || null);
      setShowBotManager(false);
      setShowAdminCenter(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setDesktopChatStatusByBot({});
      setIsTerminalImmersive(false);
      void refreshAnnouncements(nextClient, true);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoginLoading(false);
    }
  }

  async function handleGuestLogin(input?: { remember?: boolean }) {
    const nextClient = useMockClient ? new MockWebBotClient() : new RealWebBotClient();
    setLoginLoading(true);
    setLoginError("");
    try {
      const nextSession = await nextClient.loginGuest();
      const restoredAlias = readStoredBotAlias() || nextSession.currentBotAlias || "";
      storeToken(nextSession.token || "", Boolean(input?.remember));
      setClient(nextClient);
      setSession(nextSession);
      setCurrentBot(restoredAlias || null);
      setShowBotManager(false);
      setShowAdminCenter(false);
      setMountedChatBots(restoredAlias ? [restoredAlias] : []);
      setDesktopChatStatusByBot({});
      setIsTerminalImmersive(false);
      void refreshAnnouncements(nextClient, true);
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
    setShowAdminCenter(false);
    setCurrentTab("chat");
    setBots([]);
    setBotActivityOverrides({});
    setUnreadBots([]);
    setMountedChatBots([]);
    setDesktopChatStatusByBot({});
    setDesktopChatPaneVisible(true);
    setLoginError("");
    setIsChatImmersive(false);
    setIsTerminalImmersive(false);
    setAnnouncementState(EMPTY_ANNOUNCEMENT_STATE);
    setAnnouncementOpen(false);
    announcementAutoOpenedRef.current = false;
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

  function handleBotActivityChange(alias: string, activity: BotActivityChange) {
    setBotActivityOverrides((prev) => updateBotAgentActivityOverrides(prev, alias, activity));
  }

  const announcementButton = (
    <AnnouncementButton
      hasUnseen={announcementState.hasUnseen}
      onClick={() => {
        void refreshAnnouncements(client, false);
        setAnnouncementOpen(true);
      }}
    />
  );
  const announcementDialog = (
    <AnnouncementDialog
      open={announcementOpen}
      items={announcementState.items}
      latestId={announcementState.latestId}
      onClose={handleCloseAnnouncements}
    />
  );
  const notificationCenter = (
    <NotificationCenter
      client={client}
      enabled={isLoggedIn}
      currentBotAlias={currentBot}
      visibleChatBotAlias={visibleChatBotAlias}
      onUnreadBot={markBotUnread}
    />
  );

  if (!isLoggedIn) {
    return (
      <LoginScreen
        onLogin={handleLogin}
        onRegister={handleRegister}
        onGuestLogin={handleGuestLogin}
        isLoading={loginLoading}
        error={loginError}
        hostInfo={publicHostInfo}
        themeName={themeName}
        onThemeChange={handleThemeChange}
      />
    );
  }

  if (showAdminCenter && canOpenAdminCenter) {
    return (
      <>
        <AdminCenterScreen
          client={client}
          onClose={() => setShowAdminCenter(false)}
          initialBots={bots}
          onBotsChange={setBots}
          canManageRegisterCodes={canManageRegisterCodes}
          canManageEnvConfig={canManageEnvConfig}
        />
        {notificationCenter}
        {announcementDialog}
      </>
    );
  }

  if (showBotManager || !currentBot) {
    if (effectiveLayoutMode === "desktop") {
      return (
        <>
          <DesktopBotManagerScreen
            client={client}
            currentAlias={currentBot}
            onSelect={handleSelectBot}
            onBotsChange={setBots}
            canManage={canManageBots}
          />
          {notificationCenter}
          {announcementDialog}
        </>
      );
    }
    return (
      <>
        <BotListScreen client={client} onSelect={handleSelectBot} onBotsChange={setBots} canManage={canManageBots} />
        {notificationCenter}
        {announcementDialog}
      </>
    );
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
              readOnly={chatReadOnly || !canOperateCurrentBot}
              allowTrace={allowTrace}
              isImmersive={alias === currentBot ? isChatImmersive : false}
              onToggleImmersive={alias === currentBot
                ? () => setIsChatImmersive((prev) => !prev)
                : undefined}
              onUnreadResult={markBotUnread}
              onBotActivityChange={handleBotActivityChange}
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
          canWriteFiles={canWriteCurrentBotFiles}
          canOpenSystemFolder={Boolean(session?.isLocalAdmin) && hasCapability(session, "admin_ops") && canOperateCurrentBot}
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
            botAlias={currentBot}
            client={client}
            isVisible
            preferredWorkingDir={currentBotSummary?.workingDir || ""}
            themeName={themeName}
            isImmersive={isTerminalImmersive}
            disabledReason={terminalDisabledReason}
            onToggleImmersive={() => setIsTerminalImmersive((prev) => !prev)}
          />
        </Suspense>
      </div>
    );
  } else if (currentTab === "git" && canUseGit) {
    activeScreen = (
      <div className="absolute inset-0">
        <GitScreen
          key={`git-${currentBot}`}
          botAlias={currentBot}
          botAvatarName={currentBotSummary?.avatarName}
          client={client}
          sessionCapabilities={session?.capabilities}
        />
      </div>
    );
  } else if (currentTab === "plugins" && canViewPlugins) {
    activeScreen = (
      <div className="absolute inset-0">
        <PluginsScreen
          key={`plugins-${currentBot}`}
          client={client}
          botAlias={currentBot}
          canOperate={canOperateCurrentBot}
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
    effectiveLayoutMode === "desktop" ? (
      <DesktopBotSwitcherPopover
        bots={displayBots}
        currentAlias={currentBot}
        anchorRect={botSwitcherAnchorRect}
        onSelect={(alias) => {
          return requestBotSelection(alias);
        }}
        onManage={() => {
          setShowBotManager(true);
          setShowAdminCenter(false);
          closeBotSwitcher();
          setIsChatImmersive(false);
          setIsTerminalImmersive(false);
        }}
        showInviteManager={canOpenAdminCenter}
        inviteManagerActive={showAdminCenter}
        onOpenInviteManager={() => {
          openAdminCenter();
        }}
        onClose={closeBotSwitcher}
      />
    ) : (
      <BotSwitcherSheet
        bots={displayBots}
        currentAlias={currentBot}
        onSelect={(alias) => {
          return requestBotSelection(alias);
        }}
        onManage={() => {
          setShowBotManager(true);
          setShowAdminCenter(false);
          closeBotSwitcher();
          setIsChatImmersive(false);
          setIsTerminalImmersive(false);
        }}
        showInviteManager={canOpenAdminCenter}
        inviteManagerActive={showAdminCenter}
        onOpenInviteManager={() => {
          openAdminCenter();
        }}
        onClose={closeBotSwitcher}
      />
    )
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
            canWriteFiles={canWriteCurrentBotFiles}
            canOpenSystemFolder={Boolean(session?.isLocalAdmin) && hasCapability(session, "admin_ops") && canOperateCurrentBot}
            chatReadOnly={chatReadOnly || !canOperateCurrentBot}
            botCanOperate={canOperateCurrentBot}
            terminalDisabledReason={terminalDisabledReason}
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
            canViewAssistantOps={canViewAssistantOps}
            viewMode={viewMode}
            hasUnreadOtherBots={hasUnreadOtherBots}
            announcementAction={announcementButton}
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
                      readOnly={chatReadOnly || !canOperateCurrentBot}
                      allowTrace={allowTrace}
                      embedded
                      onRequestDesktopPreview={requestPreview}
                      onUnreadResult={markBotUnread}
                      onBotActivityChange={handleBotActivityChange}
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
            onOpenBotSwitcher={(anchorRect) => {
              void openBotSwitcher(anchorRect);
            }}
            onOpenBotManager={() => {
              setShowBotManager(true);
              setShowAdminCenter(false);
              setShowSwitcher(false);
              setIsChatImmersive(false);
              setIsTerminalImmersive(false);
            }}
            onDirtyTabsChange={setDesktopHasDirtyTabs}
            onChatPaneVisibilityChange={setDesktopChatPaneVisible}
          />
        </PersistentTerminalProvider>
        {switcher}
        {notificationCenter}
        {announcementDialog}
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
          allowedTabs={allowedTabs}
          hideOuterChrome={hideOuterChrome}
          activeScreen={activeScreen}
          viewMode={viewMode}
          hasUnreadOtherBots={hasUnreadOtherBots}
          announcementAction={announcementButton}
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
      {notificationCenter}
      {announcementDialog}
    </>
  );
}
