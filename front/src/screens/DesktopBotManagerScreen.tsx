import { BotListScreen } from "./BotListScreen";
import type { BotSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  client?: WebBotClient;
  currentAlias: string | null;
  onSelect: (alias: string) => void;
  onOpenBotSettings?: (alias: string) => void;
  onBotCreated?: (alias: string) => void;
  onLogout?: () => void;
  onBotsChange?: (bots: BotSummary[]) => void;
  canManage?: boolean;
  canCreateWorkdirDirectory?: boolean;
  canRunUnsafeCli?: boolean;
};

export function DesktopBotManagerScreen({
  client,
  currentAlias: _currentAlias,
  onSelect,
  onOpenBotSettings,
  onBotCreated,
  onLogout,
  onBotsChange,
  canManage = true,
  canCreateWorkdirDirectory = true,
  canRunUnsafeCli = false,
}: Props) {
  return (
    <div data-testid="desktop-bot-manager" className="h-full min-h-0 overflow-y-auto bg-[var(--bg)]">
      <BotListScreen
        client={client}
        onSelect={onSelect}
        onOpenBotSettings={onOpenBotSettings}
        onBotCreated={onBotCreated}
        onLogout={onLogout}
        onBotsChange={onBotsChange}
        canManage={canManage}
        canCreateWorkdirDirectory={canCreateWorkdirDirectory}
        canRunUnsafeCli={canRunUnsafeCli}
      />
    </div>
  );
}
