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

  test("listSystemScripts returns bot-scoped mock system functions", async () => {
    const client = new MockWebBotClient();

    expect(await client.listSystemScripts("main")).toEqual([
      {
        scriptName: "build_web_frontend.sh",
        displayName: "构建前端",
        description: "构建 Web 前端资源",
        path: "/srv/telegram-cli-bridge/demo/scripts/build_web_frontend.sh",
      },
    ]);

    expect(await client.listSystemScripts("team2")).toEqual([
      {
        scriptName: "sync_docs.sh",
        displayName: "同步文档",
        description: "同步 plans 目录下的文档脚本",
        path: "/srv/telegram-cli-bridge/plans/scripts/sync_docs.sh",
      },
    ]);
  });

  test("runSystemScriptStream emits platform-neutral build logs", async () => {
    const client = new MockWebBotClient();
    const logs: string[] = [];

    await client.runSystemScriptStream("main", "build_web_frontend.sh", (line) => {
      logs.push(line);
    });

    expect(logs).toEqual([
      "cd scripts",
      "build_web_frontend.sh",
      "系统功能执行完成",
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

  test("updateBotWorkdir requires confirmation when visible history exists", async () => {
    const client = new MockWebBotClient();

    await expect(client.updateBotWorkdir("main", "/srv/telegram-cli-bridge/new-root")).rejects.toMatchObject({
      name: "WebApiClientError",
      code: "workdir_change_requires_reset",
      status: 409,
      data: {
        currentWorkingDir: "/srv/telegram-cli-bridge/demo",
        requestedWorkingDir: "/srv/telegram-cli-bridge/new-root",
        historyCount: 1,
        messageCount: 1,
        botMode: "cli",
      },
    });
  });

  test("updateBotWorkdir resets the current browser path to the new working directory", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");

    const updated = await client.updateBotWorkdir("main", "/srv/telegram-cli-bridge/new-root", { forceReset: true });
    const listing = await client.listFiles("main");

    expect(updated.workingDir).toBe("/srv/telegram-cli-bridge/new-root");
    expect(await client.getCurrentPath("main")).toBe("/srv/telegram-cli-bridge/new-root");
    expect(listing.workingDir).toBe("/srv/telegram-cli-bridge/new-root");
  });

  test("createTextFile accepts an explicit parent path for tree actions", async () => {
    const client = new MockWebBotClient();

    await client.createTextFile("main", "draft.md", "# draft\n", "/srv/telegram-cli-bridge/demo/docs");

    const listing = await client.listFiles("main", "/srv/telegram-cli-bridge/demo/docs");
    expect(listing.entries).toContainEqual(
      expect.objectContaining({
        name: "draft.md",
        isDir: false,
      }),
    );
  });
});
