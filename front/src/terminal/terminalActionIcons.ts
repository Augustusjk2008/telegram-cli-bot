import {
  Bolt,
  Bug,
  CheckCircle2,
  Code2,
  Download,
  Hammer,
  Package,
  Play,
  RefreshCw,
  Rocket,
  Server,
  Settings,
  SquareTerminal,
  Terminal,
  TestTube2,
  Trash2,
  Upload,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";

export const TERMINAL_ACTION_ICON_OPTIONS = [
  "Terminal",
  "SquareTerminal",
  "Play",
  "Hammer",
  "TestTube2",
  "Rocket",
  "RefreshCw",
  "Package",
  "Settings",
  "Wrench",
  "Bug",
  "Code2",
  "Server",
  "Download",
  "Upload",
  "Trash2",
  "Bolt",
  "Zap",
  "CheckCircle2",
] as const;

export type TerminalActionIconName = typeof TERMINAL_ACTION_ICON_OPTIONS[number];

const ICONS: Record<TerminalActionIconName, LucideIcon> = {
  Bolt,
  Bug,
  CheckCircle2,
  Code2,
  Download,
  Hammer,
  Package,
  Play,
  RefreshCw,
  Rocket,
  Server,
  Settings,
  SquareTerminal,
  Terminal,
  TestTube2,
  Trash2,
  Upload,
  Wrench,
  Zap,
};

export function getTerminalActionIcon(name: string | undefined): LucideIcon {
  if (name && Object.prototype.hasOwnProperty.call(ICONS, name)) {
    return ICONS[name as TerminalActionIconName];
  }
  return Terminal;
}
