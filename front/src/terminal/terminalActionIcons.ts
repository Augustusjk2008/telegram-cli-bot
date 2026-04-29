import {
  Bolt,
  Bug,
  CircleStop,
  CheckCircle2,
  Code2,
  Download,
  Hammer,
  Lock,
  LockOpen,
  MonitorOff,
  MoonStar,
  Package,
  Play,
  Power,
  PowerOff,
  RefreshCw,
  Rocket,
  RotateCcw,
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
  "RotateCcw",
  "Package",
  "Settings",
  "Wrench",
  "Bug",
  "Code2",
  "Server",
  "Download",
  "Upload",
  "Trash2",
  "CircleStop",
  "Power",
  "PowerOff",
  "MonitorOff",
  "MoonStar",
  "Lock",
  "LockOpen",
  "Bolt",
  "Zap",
  "CheckCircle2",
] as const;

export type TerminalActionIconName = typeof TERMINAL_ACTION_ICON_OPTIONS[number];

const ICONS: Record<TerminalActionIconName, LucideIcon> = {
  Bolt,
  Bug,
  CircleStop,
  CheckCircle2,
  Code2,
  Download,
  Hammer,
  Lock,
  LockOpen,
  MonitorOff,
  MoonStar,
  Package,
  Play,
  Power,
  PowerOff,
  RefreshCw,
  Rocket,
  RotateCcw,
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

const ICON_LABELS: Record<TerminalActionIconName, string> = {
  Terminal: "终端",
  SquareTerminal: "终端框",
  Play: "运行",
  Hammer: "构建",
  TestTube2: "测试",
  Rocket: "发布",
  RefreshCw: "刷新",
  RotateCcw: "重启",
  Package: "打包",
  Settings: "设置",
  Wrench: "维护",
  Bug: "调试",
  Code2: "代码",
  Server: "服务",
  Download: "下载",
  Upload: "上传",
  Trash2: "清理",
  CircleStop: "停止",
  Power: "电源",
  PowerOff: "关机",
  MonitorOff: "息屏",
  MoonStar: "休眠",
  Lock: "锁定",
  LockOpen: "解锁",
  Bolt: "快速",
  Zap: "加速",
  CheckCircle2: "完成",
};

export function getTerminalActionIcon(name: string | undefined): LucideIcon {
  if (name && Object.prototype.hasOwnProperty.call(ICONS, name)) {
    return ICONS[name as TerminalActionIconName];
  }
  return Terminal;
}

export function getTerminalActionIconLabel(name: string | undefined): string {
  if (name && Object.prototype.hasOwnProperty.call(ICON_LABELS, name)) {
    return ICON_LABELS[name as TerminalActionIconName];
  }
  return ICON_LABELS.Terminal;
}
