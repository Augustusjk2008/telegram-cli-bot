import { BotSummary } from "../services/types";
import { DEMO_MAIN_WORKDIR, DEMO_TEAM_WORKDIR } from "./demoEnvironment";

export const mockBots: BotSummary[] = [
  {
    alias: "main",
    cliType: "kimi",
    status: "running",
    workingDir: DEMO_MAIN_WORKDIR,
    lastActiveText: "刚刚活跃",
  },
  {
    alias: "team2",
    cliType: "claude",
    status: "busy",
    workingDir: DEMO_TEAM_WORKDIR,
    lastActiveText: "处理中",
  },
];
