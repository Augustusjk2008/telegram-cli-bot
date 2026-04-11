import type { SystemScript } from "../services/types";

export const DEMO_MAIN_WORKDIR = "/srv/telegram-cli-bridge/demo";
export const DEMO_TEAM_WORKDIR = "/srv/telegram-cli-bridge/plans";
export const DEMO_SCRIPTS_DIR = "/opt/telegram-cli-bridge/scripts";

export const DEMO_SYSTEM_SCRIPTS: SystemScript[] = [
  {
    scriptName: "build_web_frontend",
    displayName: "重建前端",
    description: "安装依赖并重新构建 Web 前端",
    path: `${DEMO_SCRIPTS_DIR}/build_web_frontend.sh`,
  },
];
