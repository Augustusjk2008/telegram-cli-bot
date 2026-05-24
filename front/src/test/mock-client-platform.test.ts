import { describe, expect, test } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";

describe("MockWebBotClient platform defaults", () => {
  test("changeDirectory keeps the bot workingDir while moving only the browser path", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");

    const overview = await client.getBotOverview("main");
    const listing = await client.listFiles("main");

    expect(overview.workingDir).toBe("/Users/demo/orbit-safe-claw");
    expect(await client.getCurrentPath("main")).toBe("/Users/demo/orbit-safe-claw");
    expect(listing.workingDir).toBe("/Users/demo/orbit-safe-claw/docs");
  });

  test("changeDirectory accepts an absolute path when resetting the browser path", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");
    await client.changeDirectory("main", "/Users/demo/orbit-safe-claw");

    const listing = await client.listFiles("main");
    expect(listing.workingDir).toBe("/Users/demo/orbit-safe-claw");
  });

  test("updateBotWorkdir requires confirmation when visible history exists", async () => {
    const client = new MockWebBotClient();

    await expect(client.updateBotWorkdir("main", "/Users/demo/new-root")).rejects.toMatchObject({
      name: "WebApiClientError",
      code: "workdir_change_requires_reset",
      status: 409,
      data: {
        currentWorkingDir: "/Users/demo/orbit-safe-claw",
        requestedWorkingDir: "/Users/demo/new-root",
        historyCount: 1,
        messageCount: 1,
        botMode: "cli",
      },
    });
  });

  test("updateBotWorkdir resets the current browser path to the new working directory", async () => {
    const client = new MockWebBotClient();

    await client.changeDirectory("main", "docs");

    const updated = await client.updateBotWorkdir("main", "/Users/demo/new-root", { forceReset: true });
    const listing = await client.listFiles("main");

    expect(updated.workingDir).toBe("/Users/demo/new-root");
    expect(await client.getCurrentPath("main")).toBe("/Users/demo/new-root");
    expect(listing.workingDir).toBe("/Users/demo/new-root");
  });

  test("createTextFile accepts an explicit parent path for tree actions", async () => {
    const client = new MockWebBotClient();

    await client.createTextFile("main", "draft.md", "# draft\n", "/Users/demo/orbit-safe-claw/docs");

    const listing = await client.listFiles("main", "/Users/demo/orbit-safe-claw/docs");
    expect(listing.entries).toContainEqual(
      expect.objectContaining({
        name: "draft.md",
        isDir: false,
      }),
    );
  });
});
