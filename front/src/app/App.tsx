/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect } from "react";
import { LoginScreen } from "../screens/LoginScreen";
import { BotListScreen } from "../screens/BotListScreen";
import { ChatScreen } from "../screens/ChatScreen";
import { FilesScreen } from "../screens/FilesScreen";
import { SettingsScreen } from "../screens/SettingsScreen";
import { MessageSquare, Folder, Settings, Menu } from "lucide-react";
import { BotSwitcherSheet } from "../components/BotSwitcherSheet";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { BotSummary } from "../services/types";
import { clsx } from "clsx";
import "../styles/tokens.css";
import "../styles/global.css";

export function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentTab, setCurrentTab] = useState<"chat" | "files" | "settings">("chat");
  const [currentBot, setCurrentBot] = useState<string | null>(null);
  const [showSwitcher, setShowSwitcher] = useState(false);
  const [bots, setBots] = useState<BotSummary[]>([]);

  useEffect(() => {
    if (isLoggedIn) {
      new MockWebBotClient().listBots().then(setBots);
    }
  }, [isLoggedIn]);

  if (!isLoggedIn) {
    return <LoginScreen onLogin={() => setIsLoggedIn(true)} />;
  }

  if (!currentBot) {
    return <BotListScreen onSelect={setCurrentBot} />;
  }

  return (
    <div className="flex flex-col h-[100dvh] w-full max-w-md mx-auto bg-[var(--bg)] shadow-xl overflow-hidden relative">
      {/* Header for Bot Switcher */}
      <header className="flex items-center justify-between p-3 bg-[var(--surface-strong)] border-b border-[var(--border)] shrink-0">
        <button 
          onClick={() => setShowSwitcher(true)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-[var(--border)] transition-colors"
        >
          <Menu className="w-5 h-5" />
          <span className="font-semibold">{currentBot}</span>
        </button>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden relative">
        {currentTab === "chat" && <ChatScreen botAlias={currentBot} />}
        {currentTab === "files" && <FilesScreen botAlias={currentBot} />}
        {currentTab === "settings" && <SettingsScreen onLogout={() => { setIsLoggedIn(false); setCurrentBot(null); }} />}
      </div>

      {/* Bottom Navigation */}
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

      {showSwitcher && (
        <BotSwitcherSheet 
          bots={bots} 
          currentAlias={currentBot} 
          onSelect={(alias) => { setCurrentBot(alias); setCurrentTab("chat"); }} 
          onClose={() => setShowSwitcher(false)} 
        />
      )}
    </div>
  );
}
