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

  test("listSystemScripts only exposes the codex switch-source script", async () => {
    const client = new MockWebBotClient();

    const scripts = await client.listSystemScripts();

    expect(scripts).toEqual([
      {
        scriptName: "codex_switch_source",
        displayName: "Codex 换源",
        description: "切换 Codex 当前配置与备份配置",
        path: "/opt/telegram-cli-bridge/scripts/codex_switch_source.bat",
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

  test("changeDirectory keeps the bot workingDir while moving only the browser path", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");

    const overview = await client.getBotOverview("main");
    const listing = await client.listFiles("main");

    expect(overview.workingDir).toBe("/srv/telegram-cli-bridge/demo");
    expect(await client.getCurrentPath("main")).toBe("/srv/telegram-cli-bridge/demo");
    expect(listing.workingDir).toBe("/srv/telegram-cli-bridge/demo/docs");
  });

  test("changeDirectory accepts an absolute path when resetting the browser path", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");
    await client.changeDirectory("main", "/srv/telegram-cli-bridge/demo");

    const listing = await client.listFiles("main");
    expect(listing.workingDir).toBe("/srv/telegram-cli-bridge/demo");
  });

  test("updateBotWorkdir resets the current browser path to the new working directory", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");

    const updated = await client.updateBotWorkdir("main", "/srv/telegram-cli-bridge/new-root");
    const listing = await client.listFiles("main");

    expect(updated.workingDir).toBe("/srv/telegram-cli-bridge/new-root");
    expect(await client.getCurrentPath("main")).toBe("/srv/telegram-cli-bridge/new-root");
    expect(listing.workingDir).toBe("/srv/telegram-cli-bridge/new-root");
  });
});
