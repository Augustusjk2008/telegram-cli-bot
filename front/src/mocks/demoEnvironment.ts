import type { SystemScript } from "../services/types";

export const DEMO_MAIN_WORKDIR = "/srv/telegram-cli-bridge/demo";
export const DEMO_TEAM_WORKDIR = "/srv/telegram-cli-bridge/plans";
export const DEMO_SCRIPTS_DIR = "/opt/telegram-cli-bridge/scripts";

export const DEMO_SYSTEM_SCRIPTS: SystemScript[] = [
  {
    scriptName: "codex_switch_source",
    displayName: "Codex 换源",
    description: "切换 Codex 当前配置与备份配置",
    path: `${DEMO_SCRIPTS_DIR}/codex_switch_source.bat`,
  },
];
