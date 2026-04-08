import { BotSummary } from "../services/types";

export const mockBots: BotSummary[] = [
  {
    alias: "main",
    cliType: "kimi",
    status: "running",
    workingDir: "C:\\workspace\\demo",
    lastActiveText: "刚刚活跃",
  },
  {
    alias: "team2",
    cliType: "claude",
    status: "busy",
    workingDir: "C:\\workspace\\plans",
    lastActiveText: "处理中",
  },
];
