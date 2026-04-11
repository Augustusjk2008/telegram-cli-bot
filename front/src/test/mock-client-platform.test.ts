import { describe, expect, test } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";

describe("MockWebBotClient platform defaults", () => {
  test("listBots uses linux-style demo working directories by default", async () => {
    const client = new MockWebBotClient();

    const bots = await client.listBots();

    expect(bots.map((bot) => bot.workingDir)).toEqual([
      "/srv/telegram-cli-bridge/demo",
      "/srv/telegram-cli-bridge/plans",
    ]);
  });

  test("getGitOverview uses linux-style repo paths by default", async () => {
    const client = new MockWebBotClient();

    const overview = await client.getGitOverview("main");

    expect(overview.workingDir).toBe("/srv/telegram-cli-bridge/demo");
    expect(overview.repoPath).toBe("/srv/telegram-cli-bridge/demo");
  });

  test("listSystemScripts exposes a linux-friendly frontend build script", async () => {
    const client = new MockWebBotClient();

    const scripts = await client.listSystemScripts();

    expect(scripts).toEqual([
      {
        scriptName: "build_web_frontend",
        displayName: "重建前端",
        description: "安装依赖并重新构建 Web 前端",
        path: "/opt/telegram-cli-bridge/scripts/build_web_frontend.sh",
      },
    ]);
  });

  test("runSystemScriptStream emits platform-neutral build logs", async () => {
    const client = new MockWebBotClient();
    const logs: string[] = [];

    await client.runSystemScriptStream("build_web_frontend", (line) => {
      logs.push(line);
    });

    expect(logs).toEqual([
      "cd front",
      "npm run build",
      "Web 前端构建完成",
    ]);
  });
});
