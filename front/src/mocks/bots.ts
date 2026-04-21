import { BotSummary } from "../services/types";
import { DEMO_MAIN_WORKDIR, DEMO_TEAM_WORKDIR } from "./demoEnvironment";

export const mockBots: BotSummary[] = [
  {
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: DEMO_MAIN_WORKDIR,
    lastActiveText: "刚刚活跃",
    avatarName: "avatar_01.png",
  },
  {
    alias: "team2",
    cliType: "claude",
    status: "busy",
    workingDir: DEMO_TEAM_WORKDIR,
    lastActiveText: "处理中",
    avatarName: "avatar_02.png",
  },
];
