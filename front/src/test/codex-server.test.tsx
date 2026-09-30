import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { GitCommitCliConfigPanel } from "../components/GitCommitCliConfigPanel";
import { SettingsScreen } from "../screens/SettingsScreen";
import { buildCreateDraft } from "../screens/useBotManager";
import { draftFromBot } from "../screens/botManagerModel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { RealWebBotClient } from "../services/realWebBotClient";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("real client preserves the server entry in bot and Git config requests and responses", async () => {
  const bot = { alias: "server", cli_type: "codex_server", cli_path: "codex", working_dir: "C:/work", execution_mode: "cli" };
  const fetchMock = vi.fn().mockImplementation(async (_url, init) => {
    const data = JSON.parse(init?.body || "{}");
    return { ok: true, json: async () => ({ ok: true, data: { bot, ...data } }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new RealWebBotClient();
  const created = await client.addBot({ alias: "server", cliType: "codex_server", cliPath: "codex" });
  expect(created).toMatchObject({ cliType: "codex_server", cliPath: "codex", executionMode: "cli" });
  expect(JSON.parse(fetchMock.mock.calls.at(-1)![1].body)).toMatchObject({ cli_type: "codex_server", cli_path: "codex" });
  expect(await client.updateBotCli("server", "codex_server", "codex")).toMatchObject({ cliType: "codex_server" });
  expect(await client.updateGitCommitMessageConfig("server", { cliType: "codex_server" }))
    .toMatchObject({ cliType: "codex_server", cliPath: "codex" });
  await client.updateCliParam("server", "reasoning_effort", "high", "codex_server");
  expect(JSON.parse(fetchMock.mock.calls.at(-1)![1].body)).toMatchObject({ cli_type: "codex_server", key: "reasoning_effort", value: "high" });
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, data: {
    items: [{ id: "history", cli_type: "codex_server", native_provider: "codex_server", native_session_id: "thread-id" }],
  } }) });
  expect((await client.listConversations("server")).items[0])
    .toMatchObject({ cliType: "codex_server", nativeSource: { provider: "codex", sessionId: "thread-id" } });
});

test("mock client retains per-entry parameters through switching, renaming and reset", async () => {
  const client = new MockWebBotClient();
  await client.login({ username: "127.0.0.1", password: "test" });
  const draft = buildCreateDraft("codex_server");
  const bot = await client.addBot({ ...draft, alias: "server" });
  expect(bot).toMatchObject({ cliType: "codex_server", cliPath: "codex", defaultExecutionMode: "cli" });
  expect(draftFromBot({ ...bot, cliPath: undefined }).cliPath).toBe("codex");
  await client.updateCliParam("server", "model", "server-model", "codex_server");
  await client.updateBotCli("server", "codex", "codex");
  expect((await client.getCliParams("server")).params.model).not.toBe("server-model");
  await client.updateCliParam("server", "model", "exec-model", "codex");
  await client.renameBot("server", "renamed");
  await client.updateBotCli("renamed", "codex_server", "codex");
  expect(await client.getCliParams("renamed")).toMatchObject({ cliType: "codex_server", params: { model: "server-model" } });
  await client.resetCliParams("renamed", "codex_server");
  await client.updateBotCli("renamed", "codex", "codex");
  expect((await client.getCliParams("renamed")).params.model).toBe("exec-model");
});

test("mock Git configuration inherits the entry and stores Codex parameters separately", async () => {
  const client = new MockWebBotClient();
  await client.updateBotCli("main", "codex_server", "codex");
  expect(await client.getGitCommitMessageConfig("main")).toMatchObject({ cliType: "codex_server", cliPath: "codex" });
  await client.updateGitCommitMessageConfig("main", { params: { model: "server-model" } });
  await client.updateGitCommitMessageConfig("main", { cliType: "codex", params: { model: "exec-model" } });
  expect(await client.updateGitCommitMessageConfig("main", { cliType: "codex_server" }))
    .toMatchObject({ cliType: "codex_server", params: { model: "server-model" } });
});

test("settings saves codex server without changing CLI execution mode", async () => {
  const client = new MockWebBotClient();
  const user = userEvent.setup();
  await client.login({ username: "127.0.0.1", password: "test" });
  render(<SettingsScreen botAlias="main" client={client} onLogout={() => undefined} />);
  await user.selectOptions(await screen.findByLabelText("CLI 类型"), "codex_server");
  await user.click(screen.getByRole("button", { name: "保存 CLI 配置" }));
  await waitFor(async () => expect(await client.getBotOverview("main")).toMatchObject({ cliType: "codex_server", cliPath: "codex", defaultExecutionMode: "cli" }));
  expect(screen.getByLabelText("CLI 类型")).toHaveValue("codex_server");
  expect(await screen.findByText("当前 CLI: codex server")).toBeInTheDocument();
});

test("Git config selector saves codex server with the codex executable", async () => {
  const client = new MockWebBotClient();
  const user = userEvent.setup();
  render(<GitCommitCliConfigPanel botAlias="main" client={client} />);
  await user.selectOptions(await screen.findByLabelText("Commit Message CLI 类型"), "codex_server");
  expect(screen.getByLabelText("Commit Message CLI 路径")).toHaveValue("codex");
  await user.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByText("Commit Message CLI 配置已保存");
  expect(await client.getGitCommitMessageConfig("main")).toMatchObject({ cliType: "codex_server", cliPath: "codex" });
});
