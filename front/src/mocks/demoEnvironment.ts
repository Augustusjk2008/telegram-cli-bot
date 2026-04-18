import type { SystemScript } from "../services/types";

export const DEMO_MAIN_WORKDIR = "/srv/telegram-cli-bridge/demo";
export const DEMO_TEAM_WORKDIR = "/srv/telegram-cli-bridge/plans";

export const DEMO_SYSTEM_SCRIPTS_BY_BOT: Record<string, SystemScript[]> = {
  main: [
    {
      scriptName: "build_web_frontend.sh",
      displayName: "构建前端",
      description: "构建 Web 前端资源",
      path: `${DEMO_MAIN_WORKDIR}/scripts/build_web_frontend.sh`,
    },
  ],
  team2: [
    {
      scriptName: "sync_docs.sh",
      displayName: "同步文档",
      description: "同步 plans 目录下的文档脚本",
      path: `${DEMO_TEAM_WORKDIR}/scripts/sync_docs.sh`,
    },
  ],
};
