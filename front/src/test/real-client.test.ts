import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { EventType } from "../services/agUiProtocol";
import { RealWebBotClient } from "../services/realWebBotClient";
import { WebApiClientError } from "../services/types";
import { buildFileDownloadUrl } from "../utils/fileLinks";
import { isAbortError } from "../utils/errorMessage";

describe("RealWebBotClient", () => {
  const fetchMock = vi.fn();

  function jsonOk(data: unknown) {
    return {
      ok: true,
      json: async () => ({ ok: true, data }),
    };
  }

  function streamOk(...frames: string[]) {
    const encoder = new TextEncoder();
    return {
      ok: true,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          frames.forEach((frame) => controller.enqueue(encoder.encode(frame)));
          controller.close();
        },
      }),
      json: async () => ({ ok: true, data: {} }),
    };
  }

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    delete window.__TCB_PUBLIC_ENV__;
    vi.stubGlobal("__PUBLIC_ENV__", {});
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    delete window.__TCB_PUBLIC_ENV__;
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  test("maps persisted update jobs and check failures without dropping legacy fields", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      current_version: "1.0.0", update_enabled: true, revision: 7,
      last_available_version: "2.0.0", update_available: true, pending_update_notes: "Release notes",
      last_check: { checked_at: "2026-10-24", ok: false, cached: true, error: "Release unavailable" },
      launcher: { supported: true, protocol: 1, command: "start.bat", reason: "" },
      job: { job_id: "job-1", revision: 7, phase: "failed", current_version: "1.0.0", target_version: "2.0.0",
        package_kind: "portable", package_sha256: "abc", progress: { phase: "verify", downloaded_bytes: 50, total_bytes: 100, percent: 50, message: "校验中" },
        error: "Hash mismatch", backup_dir: "D:/backup", job_dir: "D:/job", preparation_log: "D:/job/prepare.log", runner_log: "", result: { recovered: true }, requires_preparation: true },
    }));
    const status = await new RealWebBotClient().getCurrentUpdateJob();
    expect(status).toMatchObject({ currentVersion: "1.0.0", updateAvailable: true, pendingUpdateNotes: "Release notes", revision: 7,
      lastCheck: { checkedAt: "2026-10-24", ok: false, cached: true, error: "Release unavailable" },
      job: { jobId: "job-1", revision: 7, phase: "failed", targetVersion: "2.0.0", packageKind: "portable", packageSha256: "abc",
        progress: { downloadedBytes: 50, totalBytes: 100, percent: 50 }, error: "Hash mismatch", backupDir: "D:/backup", jobDir: "D:/job", preparationLog: "D:/job/prepare.log", runnerLog: "", result: { recovered: true }, requiresPreparation: true },
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/admin/update/jobs/current");
  });

  test("binds update actions to job and revision, preserving the node prefix and upload multipart", async () => {
    window.history.replaceState(null, "", "/node/update-host/");
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/update-host" });
    fetchMock.mockResolvedValue(jsonOk({ current_version: "1", update_enabled: false }));
    const client = new RealWebBotClient();
    await client.applyUpdateJob("job/id", 9);
    await client.cancelUpdateJob("job/id", 10);
    await client.retryUpdateJob("job/id", 11);
    for (const [index, action] of ["apply", "cancel", "retry"].entries()) {
      expect(fetchMock.mock.calls[index][0]).toBe(`/node/update-host/api/admin/update/jobs/job%2Fid/${action}`);
      expect(JSON.parse(fetchMock.mock.calls[index][1].body)).toEqual({ revision: 9 + index });
      expect(fetchMock.mock.calls[index][1].method).toBe("POST");
    }
    const file = new File(["zip"], "update.zip");
    await client.uploadOfflineUpdate(file);
    const [url, request] = fetchMock.mock.calls[3];
    expect(url).toBe(`/node/update-host/api/admin/update/offline/upload?size=${file.size}`);
    expect(request.body.get("file")).toBe(file);
    expect(request.headers["Content-Type"]).toBeUndefined();
  });

  class FakeUploadXhr {
    static instances: FakeUploadXhr[] = [];
    method = "";
    url = "";
    headers: Record<string, string> = {};
    body: FormData | null = null;
    status = 0;
    responseText = "";
    contentType = "application/json";
    aborted = false;
    upload: {
      onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
      onload: (() => void) | null;
    } = { onprogress: null, onload: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;

    constructor() {
      FakeUploadXhr.instances.push(this);
    }

    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }

    setRequestHeader(name: string, value: string) {
      this.headers[name] = value;
    }

    getResponseHeader(name: string) {
      return name.toLowerCase() === "content-type" ? this.contentType : null;
    }

    send(body: FormData) {
      this.body = body;
    }

    abort() {
      this.aborted = true;
      this.onabort?.();
    }

    respond(status: number, body: unknown, contentType = "application/json") {
      this.status = status;
      this.responseText = typeof body === "string" ? body : JSON.stringify(body);
      this.contentType = contentType;
      this.onload?.();
    }
  }

  test("uploads multipart files with request progress under the node prefix", async () => {
    window.history.replaceState(null, "", "/node/files-host/");
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/files-host" });
    FakeUploadXhr.instances = [];
    vi.stubGlobal("XMLHttpRequest", FakeUploadXhr);
    const file = new File(["0123456789"], "report.txt", { type: "text/plain" });
    const progress = vi.fn();

    const upload = new RealWebBotClient().uploadFile("main bot", file, progress);
    const xhr = FakeUploadXhr.instances[0];
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/node/files-host/api/bots/main%20bot/files/upload");
    expect(xhr.body?.get("file")).toBe(file);
    expect(xhr.headers["Content-Type"]).toBeUndefined();
    // The multipart request is larger than the file; progress is scaled back to the file size.
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 60, total: 120 });
    xhr.upload.onload?.();
    xhr.respond(200, { ok: true, data: { filename: "report.txt", saved_path: "C:/workspace/report.txt", size: 10 } });

    await expect(upload).resolves.toBeUndefined();
    expect(progress.mock.calls.map(([event]) => event)).toEqual([
      { uploadedBytes: 0, totalBytes: 10, percent: 0 },
      { uploadedBytes: 5, totalBytes: 10, percent: 50 },
      { uploadedBytes: 10, totalBytes: 10, percent: 100 },
    ]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("upload failures keep the API message and cancelled uploads reject as aborts", async () => {
    FakeUploadXhr.instances = [];
    vi.stubGlobal("XMLHttpRequest", FakeUploadXhr);
    const client = new RealWebBotClient();
    const file = new File(["x"], "large.bin");

    const apiFailure = client.uploadChatAttachment("main", file);
    expect(FakeUploadXhr.instances[0].url).toBe("/api/bots/main/chat/attachments");
    FakeUploadXhr.instances[0].respond(413, { ok: false, error: { code: "upload_failed", message: "文件上传失败" } });
    await expect(apiFailure).rejects.toMatchObject({ status: 413, code: "upload_failed", message: "文件上传失败" });

    const proxyFailure = client.uploadFile("main", file);
    FakeUploadXhr.instances[1].respond(502, "<html>Bad Gateway</html>", "text/html");
    await expect(proxyFailure).rejects.toThrow("上传失败（HTTP 502）");

    const controller = new AbortController();
    const cancelled = client.uploadFile("main", file, undefined, controller.signal);
    controller.abort();
    expect(isAbortError(await cancelled.catch((error: unknown) => error))).toBe(true);
    expect(FakeUploadXhr.instances[2].aborted).toBe(true);
  });

  test("update apply conflicts retain the API error and never replay the mutation", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 409, json: async () => ({ ok: false, error: { code: "revision_conflict", message: "任务已变化" } }) });
    await expect(new RealWebBotClient().applyUpdateJob("job", 1)).rejects.toMatchObject({ status: 409, code: "revision_conflict", message: "任务已变化" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("legacy update stream disconnect never becomes an accepted completion", async () => {
    fetchMock.mockResolvedValue(streamOk('event: progress\ndata: {"phase":"download","percent":100}\n\n'));
    await expect(new RealWebBotClient().downloadUpdateStream(vi.fn())).rejects.toThrow("连接已中断");
  });

  test("preserves DeepSeek through creation, editing and overview mapping", async () => {
    const bot = { alias: "deepseek", cli_type: "deepseek", status: "running", working_dir: "C:/workspace" };
    const client = new RealWebBotClient();
    fetchMock.mockResolvedValueOnce(jsonOk({ bot }));
    const created = await client.addBot({ alias: "deepseek", cliType: "deepseek", cliPath: "", workingDir: "C:/workspace" });
    expect(created).toMatchObject({ cliType: "deepseek", cliPath: "dsh", supportedExecutionModes: ["cli"], executionMode: "cli" });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      cli_type: "deepseek", cli_path: "dsh", supported_execution_modes: ["cli"], default_execution_mode: "cli",
      bypass_approval_and_sandbox: false,
    });

    fetchMock.mockResolvedValueOnce(jsonOk({ bot: { ...bot, cli_path: "C:/tools/dsh.cmd" } }));
    const edited = await client.updateBotCli("deepseek", "deepseek", "C:/tools/dsh.cmd");
    expect(edited).toMatchObject({ cliType: "deepseek", cliPath: "C:/tools/dsh.cmd" });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ cli_type: "deepseek", cli_path: "C:/tools/dsh.cmd" });

    fetchMock.mockResolvedValueOnce(jsonOk({
      bot: { ...bot, supported_execution_modes: ["cli", "native_agent"], default_execution_mode: "native_agent" },
      session: { working_dir: "C:/workspace", message_count: 0, history_count: 0, is_processing: false },
      voice: { enabled: true },
    }));
    expect(await client.getBotOverview("deepseek")).toMatchObject({
      cliType: "deepseek", executionMode: "cli", supportedExecutionModes: ["cli"], voice: { enabled: false },
    });
  });

  test("sends DeepSeek selection atomically and maps the provider catalog", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      cli_type: "deepseek",
      params: { provider: "siliconflow", model: "deepseek-v4-pro", reasoning_effort: "high" },
      defaults: { provider: null, model: null, reasoning_effort: null },
      schema: { model: { type: "string", enum: ["none", "deepseek-v4-pro"] } },
      provider_options: [
        { id: "deepseek", label: "DeepSeek" },
        { id: "siliconflow", label: "SiliconFlow", default_model: "deepseek-v4-pro" },
      ],
      model_options_by_provider: {
        siliconflow: [{ id: "deepseek-v4-pro", label: "DeepSeek V4 Pro", reasoning_efforts: ["low", "high"] }],
      },
      selected_provider: "siliconflow",
      catalog_status: "ready",
      provider_changed: true,
      session_reset: true,
      selection_notice: "下一轮建立新会话",
    }));

    const result = await new RealWebBotClient().updateDeepSeekSelection("deepseek", {
      provider: "siliconflow",
      model: "deepseek-v4-pro",
      reasoningEffort: "high",
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/deepseek/cli-params");
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      cli_type: "deepseek",
      selection: { provider: "siliconflow", model: "deepseek-v4-pro", reasoning_effort: "high" },
    });
    expect(result).toMatchObject({
      cliType: "deepseek",
      selectedProvider: "siliconflow",
      catalogStatus: "ready",
      providerChanged: true,
      sessionReset: true,
      selectionNotice: "下一轮建立新会话",
      modelOptionsByProvider: {
        siliconflow: [{ id: "deepseek-v4-pro", label: "DeepSeek V4 Pro", reasoningEfforts: ["low", "high"] }],
      },
    });
  });

  test("creates a scoped voice WebSocket and cleans up after remote close", async () => {
    class FakeWebSocket {
      static OPEN = 1;
      static last: FakeWebSocket;
      readonly url: string;
      readyState = 0;
      readonly sent: string[] = [];
      private listeners = new Map<string, Set<(event?: MessageEvent) => void>>();
      constructor(url: string) {
        this.url = url;
        FakeWebSocket.last = this;
      }
      addEventListener(name: string, listener: (event?: MessageEvent) => void) {
        const listeners = this.listeners.get(name) || new Set();
        listeners.add(listener);
        this.listeners.set(name, listeners);
      }
      removeEventListener(name: string, listener: (event?: MessageEvent) => void) {
        this.listeners.get(name)?.delete(listener);
      }
      emit(name: string, event?: MessageEvent) {
        this.listeners.get(name)?.forEach((listener) => listener(event));
      }
      send(value: string) { this.sent.push(value); }
      close = vi.fn(() => { this.readyState = 3; this.emit("close"); });
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);
    window.history.replaceState(null, "", "/node/laptop/");
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/laptop" });
    const onMessage = vi.fn();
    const onClose = vi.fn();
    const connection = new RealWebBotClient().connectCodexVoice("main", {
      agentId: "reviewer",
      conversationId: "conversation-1",
      sessionEpoch: 4,
      recoveryToken: "recovery-1",
      clientGeneration: "generation-1",
      threadId: "thread-1",
      codexTurnId: "codex-turn-1",
      tcbTurnId: "tcb-turn-1",
      onMessage,
      onClose,
    });
    const socket = FakeWebSocket.last;
    const url = new URL(socket.url);
    expect(url.pathname).toBe("/node/laptop/api/bots/main/chat/voice");
    expect(url.searchParams.get("agent_id")).toBe("reviewer");
    expect(url.searchParams.get("execution_mode")).toBe("cli");
    expect(url.searchParams.get("protocol_version")).toBe("1");
    expect(url.searchParams.get("conversation_id")).toBe("conversation-1");
    expect(url.searchParams.get("session_epoch")).toBe("4");
    expect(url.searchParams.get("recovery_token")).toBe("recovery-1");
    expect(url.searchParams.get("client_generation")).toBe("generation-1");
    expect(url.searchParams.get("thread_id")).toBe("thread-1");
    expect(url.searchParams.get("codex_turn_id")).toBe("codex-turn-1");
    expect(url.searchParams.get("tcb_turn_id")).toBe("tcb-turn-1");
    socket.readyState = 1;
    socket.emit("open");
    await connection.ready;
    connection.send({ op: "summary" });
    expect(JSON.parse(socket.sent[0])).toMatchObject({ op: "summary", id: expect.any(String) });
    socket.emit("message", { data: JSON.stringify({ type: "voice.state", seq: 1, state: "active" }) } as MessageEvent);
    expect(onMessage).toHaveBeenCalledWith({ type: "voice.state", seq: 1, state: "active" });
    socket.emit("message", { data: JSON.stringify({
      type: "voice.task",
      seq: 2,
      tcb_turn_id: "tcb-turn-1",
      assistant_message_id: "assistant-1",
      codex_turn_id: "codex-turn-1",
      realtime_session_id: "realtime-1",
      conversation_id: "conversation-1",
      state: "active",
      transcript_state: "syncing",
      session_epoch: 4,
    }) } as MessageEvent);
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "voice.task", tcb_turn_id: "tcb-turn-1" }));
    socket.emit("close");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(socket.close).toHaveBeenCalled();
  });

  test("posts voice steering binding and maps the accepted response", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      status: "accepted",
      request_id: "request-1",
      turn_id: "tcb-turn-1",
      assistant_message_id: "assistant-1",
      user_message_id: "user-1",
      conversation_id: "conversation-1",
      user_message: {
        id: "user-1",
        turn_id: "tcb-turn-1",
        role: "user",
        content: "补充要求",
        created_at: "2026-10-04T01:00:00Z",
        state: "done",
      },
    }));

    const result = await new RealWebBotClient().steerMessage("main", "补充要求", "tcb-turn-1", {
      agentId: "main",
      executionMode: "cli",
      conversationId: "conversation-1",
      sessionEpoch: 4,
      codexTurnId: "codex-turn-1",
      requestId: "request-1",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      turn_id: "tcb-turn-1",
      conversation_id: "conversation-1",
      session_epoch: 4,
      codex_turn_id: "codex-turn-1",
      request_id: "request-1",
    });
    expect(result).toMatchObject({
      status: "accepted",
      requestId: "request-1",
      assistantMessageId: "assistant-1",
      userMessageId: "user-1",
      message: { id: "user-1", turnId: "tcb-turn-1" },
    });
  });

  test("restores voice task metadata from history", async () => {
    fetchMock.mockResolvedValue(jsonOk({ items: [{
      id: "assistant-voice",
      role: "assistant",
      content: "语音回答",
      meta: {
        voice: {
          tcb_turn_id: "tcb-turn-1",
          assistant_message_id: "assistant-voice",
          codex_turn_id: "codex-turn-1",
          conversation_id: "conversation-1",
          state: "unknown",
          transcript_state: {
            user: { item_id: "user-item", is_final: true, persisted: true },
            assistant: { item_id: "assistant-item", is_final: true, persisted: true },
            user_final: true,
            assistant_final: true,
          },
          session_epoch: 4,
        },
      },
    }] }));

    const snapshot = await new RealWebBotClient().listMessages("main");
    expect(snapshot.items[0]).toMatchObject({
      meta: {
        voice: {
          tcbTurnId: "tcb-turn-1",
          state: "unknown",
          transcriptState: "saved",
          transcriptDetails: {
            user: { item_id: "user-item", persisted: true },
            assistant: { item_id: "assistant-item", persisted: true },
          },
          sessionEpoch: 4,
        },
      },
    });
  });

  test.each([false, true])("sends explicit read-only deletion confirmation=%s", async (confirmed) => {
    fetchMock.mockResolvedValue(jsonOk({}));
    const client = new RealWebBotClient();

    await client.deletePath("main", "reference.pdf", confirmed ? { confirmReadonly: true } : undefined);

    expect(fetchMock).toHaveBeenCalledWith("/api/bots/main/files/delete", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ path: "reference.pdf", ...(confirmed ? { confirm_readonly: true } : {}) }),
    }));
  });

  test.each([true, false])("preserves directory listing paths with URLSearchParams.size support=%s", async (supportsSize) => {
    const descriptor = Object.getOwnPropertyDescriptor(URLSearchParams.prototype, "size");
    if (!supportsSize) {
      Reflect.deleteProperty(URLSearchParams.prototype, "size");
    }
    try {
      fetchMock.mockResolvedValue(jsonOk({ working_dir: "C:/workspace", entries: [] }));
      const client = new RealWebBotClient();
      await client.listFiles("company-researcher");
      for (const path of ["C:/workspace/reviews", "C:/workspace/reviews/研究 notes"]) {
        await client.listFiles("company-researcher", path, { includeChildCounts: true });
        const url = new URL(fetchMock.mock.calls.at(-1)![0], "https://example.test");
        expect(url.pathname).toBe("/api/bots/company-researcher/ls");
        expect(url.searchParams.get("path")).toBe(path);
        expect(url.searchParams.get("include_child_counts")).toBe("1");
      }
      expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/company-researcher/ls");
    } finally {
      if (descriptor) {
        Object.defineProperty(URLSearchParams.prototype, "size", descriptor);
      }
    }
  });

  test("maps Git capabilities with their confirmation requirements", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        capabilities: {
          tree_status: { available: true, reason: "", requires_confirmation: false },
          commit_graph: { available: false, reason: "remote_feature_unavailable", requires_confirmation: false },
          branches: { available: false, reason: "remote_feature_unavailable", requires_confirmation: false },
          branch_mutation: { available: false, reason: "remote_feature_unavailable", requires_confirmation: true },
          discard: { available: false, reason: "remote_feature_unavailable", requires_confirmation: true },
          stash: { available: false, reason: "remote_feature_unavailable", requires_confirmation: true },
          stash_create: { available: false, reason: "remote_feature_unavailable", requires_confirmation: true },
          identity: { available: false, reason: "remote_feature_unavailable", requires_confirmation: false },
          fetch: { available: false, reason: "remote_feature_unavailable", requires_confirmation: false },
          pull: { available: false, reason: "remote_feature_unavailable", requires_confirmation: true },
          push: { available: false, reason: "remote_feature_unavailable", requires_confirmation: true },
          commit_message_generation: { available: false, reason: "remote_feature_unavailable", requires_confirmation: false },
          smart_commit: { available: false, reason: "remote_feature_unavailable", requires_confirmation: false },
        },
      }));

    const capabilities = await new RealWebBotClient().getGitCapabilities("remote");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/remote/git/capabilities");
    expect(capabilities.capabilities.tree_status).toEqual({
      available: true,
      reason: "",
      requiresConfirmation: false,
    });
    expect(capabilities.capabilities.branch_mutation.requiresConfirmation).toBe(true);
    expect(capabilities.capabilities.stash_create).toEqual({
      available: false,
      reason: "remote_feature_unavailable",
      requiresConfirmation: true,
    });
  });

  test("maps Git remotes and GitHub account endpoints without exposing tokens", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        repo_found: true,
        current_branch: "main",
        upstream: "origin/main",
        has_commits: true,
        github_account_auth: true,
        remotes: [{
          name: "origin",
          fetch_url: "https://github.com/acme/demo.git",
          protocol: "https",
          has_embedded_credentials: false,
          github: { owner: "acme", repo: "demo", full_name: "acme/demo", html_url: "https://github.com/acme/demo", protocol: "https" },
        }],
      }))
      .mockResolvedValueOnce(jsonOk({ connected: true, login: "octocat", auth_method: "token", scopes: ["repo"], device_flow_available: false }))
      .mockResolvedValueOnce(jsonOk({ status: "connected", interval: 5, account: { connected: true, login: "octocat", auth_method: "device" } }));
    const client = new RealWebBotClient();

    const remotes = await client.listGitRemotes("main bot");
    const account = await client.connectGitHubWithToken("ghp_secret");
    const poll = await client.pollGitHubDeviceLogin("flow/1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/bots/main%20bot/git/remotes");
    expect(remotes.remotes[0]).toMatchObject({ name: "origin", pushUrl: "https://github.com/acme/demo.git", github: { fullName: "acme/demo" } });
    expect(remotes.githubAccountAuth).toBe(true);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/github/account/token");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify({ token: "ghp_secret" }) });
    expect(account).toMatchObject({ connected: true, login: "octocat", authMethod: "token", deviceFlowAvailable: false });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/github/device/flow%2F1/poll");
    expect(poll.status).toBe("connected");
    expect(poll.account?.authMethod).toBe("device");
  });

  test("maps the latest notifiable answer timestamp from bot summaries", async () => {
    fetchMock.mockResolvedValue(jsonOk([{
      alias: "main",
      cli_type: "codex",
      status: "running",
      working_dir: "C:\\repo",
      last_answer_completed_at: "2026-08-27T01:00:00Z",
      last_answer_terminal_at: "2026-08-27T01:10:00Z",
    }]));

    const bots = await new RealWebBotClient().listBots();

    expect(bots[0]).toMatchObject({
      lastAnswerCompletedAt: "2026-08-27T01:00:00Z",
      lastAnswerTerminalAt: "2026-08-27T01:10:00Z",
    });
  });

  test("maps bot archive state and uses archive lifecycle endpoints", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({ bot: {
        alias: "team2",
        cli_type: "codex",
        status: "stopped",
        working_dir: "C:\\repo",
        is_archived: true,
      } }))
      .mockResolvedValueOnce(jsonOk({ bot: {
        alias: "team2",
        cli_type: "codex",
        status: "stopped",
        working_dir: "C:\\repo",
        archived: false,
      } }));

    const client = new RealWebBotClient();
    const archived = await client.archiveBot("team2");
    const restored = await client.unarchiveBot("team2");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/admin/bots/team2/archive",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/bots/team2/unarchive",
      expect.objectContaining({ method: "POST" }),
    );
    expect(archived.archived).toBe(true);
    expect(restored.archived).toBe(false);
  });

  test("loads archived bots only through the management endpoint", async () => {
    fetchMock.mockResolvedValue(jsonOk([]));
    const client = new RealWebBotClient();
    await client.listBots();
    await client.listBots({ includeArchived: true });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/bots", "/api/admin/bots"]);
  });

  test("retries a failed GET once after a fetch network error", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonOk([]));

    const pending = new RealWebBotClient().listBots();
    await vi.advanceTimersByTimeAsync(500);

    await expect(pending).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("does not retry an aborted GET", async () => {
    const abortError = new DOMException("请求已取消", "AbortError");
    fetchMock.mockRejectedValueOnce(abortError);

    await expect(new RealWebBotClient().listBots()).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("does not retry write requests after a network error", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(new RealWebBotClient().logout()).rejects.toThrow("Failed to fetch");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("does not retry HTTP errors", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ ok: false, error: { message: "服务器错误" } }),
    });

    await expect(new RealWebBotClient().listBots()).rejects.toMatchObject({
      status: 500,
      message: "服务器错误",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("uses the active public base path for auth requests and download links", async () => {
    window.history.replaceState(null, "", "/node/nanjing-laptop/");
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/nanjing-laptop" });
    fetchMock.mockResolvedValue(jsonOk({ user_id: 1001 }));

    const session = await new RealWebBotClient().login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/node/nanjing-laptop/api/auth/me",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ Authorization: "Bearer secret-token" }),
      }),
    );
    expect(buildFileDownloadUrl("main", "docs/readme.md")).toBe(
      "/node/nanjing-laptop/api/bots/main/files/download?filename=docs%2Freadme.md",
    );
    expect(session).toMatchObject({ isLoggedIn: true, token: "" });
  });

  test("uses the runtime base path when the server serves the app from root", async () => {
    window.__TCB_PUBLIC_ENV__ = { VITE_API_BASE_URL: "/node/local" };
    fetchMock.mockResolvedValue(jsonOk({ user_id: 1001 }));

    await new RealWebBotClient().login({ username: "alice", password: "secret" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/node/local/api/auth/login",
      expect.any(Object),
    );
  });

  test("ignores a stale configured public base path when served from root", async () => {
    vi.stubGlobal("__PUBLIC_ENV__", { VITE_API_BASE_URL: "/node/local" });
    fetchMock.mockResolvedValue(jsonOk({ user_id: 1001 }));

    await new RealWebBotClient().login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/me", expect.any(Object));
  });

  test("maps valid Codex rate limit samples and filters invalid samples", async () => {
    fetchMock.mockResolvedValue(jsonOk({
      rate_limit_samples: [
        {
          limit_id: "codex_bengalfox",
          sampled_at: "2026-08-11T12:57:53+08:00",
          used_percent: 8,
          window_minutes: 10080,
          resets_at: "2026-08-18T08:01:25+08:00",
          plan_type: "pro",
          credits_balance: "1234.50",
          origin: "laptop",
        },
        {
          limit_id: "codex",
          sampled_at: "2026-08-11T13:00:00+08:00",
          used_percent: 100,
          window_minutes: 60,
          resets_at: "1970-01-01T00:00:00Z",
          origin: null,
        },
        { sampled_at: "invalid", used_percent: 8, window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:01:00+08:00", used_percent: -1, window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:02:00+08:00", used_percent: 101, window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:03:00+08:00", used_percent: "8", window_minutes: 60, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:04:00+08:00", used_percent: 8, window_minutes: 0, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:05:00+08:00", used_percent: 8, window_minutes: 1.5, resets_at: "2026-08-18T08:01:25+08:00" },
        { sampled_at: "2026-08-11T13:06:00+08:00", used_percent: 8, window_minutes: 60, resets_at: "invalid" },
        { sampled_at: "2026-08-11T13:07:00+08:00", used_percent: 8, window_minutes: 60, resets_at: "1969-12-31T23:59:59Z" },
      ],
    }));

    const stats = await new RealWebBotClient().getCodexUsageStats();

    expect(fetchMock).toHaveBeenCalledWith("/api/admin/codex-usage/stats", expect.objectContaining({ cache: "no-store" }));
    expect(stats.rateLimitSamples).toEqual([
      {
        limitId: "codex_bengalfox",
        sampledAt: "2026-08-11T12:57:53+08:00",
        usedPercent: 8,
        windowMinutes: 10080,
        resetsAt: "2026-08-18T08:01:25+08:00",
        planType: "pro",
        creditsBalance: "1234.50",
        origin: "laptop",
      },
      {
        limitId: "codex",
        sampledAt: "2026-08-11T13:00:00+08:00",
        usedPercent: 100,
        windowMinutes: 60,
        resetsAt: "1970-01-01T00:00:00Z",
        planType: null,
      },
    ]);
  });

  test("exports the sample document itself and imports files as raw JSON", async () => {
    const sampleDocument = { format: "orbit-quota-samples", version: 1, source: "laptop", samples: [] };
    fetchMock.mockResolvedValueOnce(jsonOk({
      filename: "orbit-quota-samples-laptop.json",
      sample_count: 0,
      document: sampleDocument,
    }));
    const originalObjectUrls = { createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL };
    const createObjectURL = vi.fn((_blob: Blob) => "blob:usage-samples");
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    try {
      const client = new RealWebBotClient();
      await expect(client.exportUsageSamples()).resolves.toEqual({
        filename: "orbit-quota-samples-laptop.json",
        sampleCount: 0,
      });
      // The saved file must be importable on another machine, so it holds
      // the document rather than the API envelope.
      expect(JSON.parse(await createObjectURL.mock.calls[0][0].text())).toEqual(sampleDocument);
      expect(click).toHaveBeenCalledTimes(1);

      fetchMock.mockResolvedValueOnce(jsonOk({
        total: 4,
        inserted: 3,
        duplicates: 1,
        invalid: 0,
        inserted_by_provider: { codex: 2, claude: 1 },
      }));
      const fileText = JSON.stringify(sampleDocument);
      await expect(client.importUsageSamples(new File([fileText], "laptop.json"))).resolves.toEqual({
        total: 4,
        inserted: 3,
        duplicates: 1,
        invalid: 0,
        insertedByProvider: { codex: 2, claude: 1 },
      });
      expect(fetchMock).toHaveBeenLastCalledWith("/api/admin/usage-samples/import", expect.objectContaining({
        method: "POST",
        body: fileText,
      }));
    } finally {
      click.mockRestore();
      Object.assign(URL, originalObjectUrls);
    }
  });

  test("omits cluster task output only when requested", async () => {
    const status = {
      tasks: [],
      queued_count: 0,
      running_count: 0,
      completed_count: 0,
      failed_count: 0,
      pending_count: 0,
    };
    fetchMock.mockResolvedValue(jsonOk(status));
    const client = new RealWebBotClient();

    await client.getClusterTaskStatus("main", "run-1", { includeOutput: false });
    await client.getClusterTaskStatus("main", "run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/bots/main/cluster/runs/run-1/tasks?include_output=0",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/cluster/runs/run-1/tasks?include_output=1",
      expect.any(Object),
    );
  });

  test("maps conversation teams and dynamic cluster run snapshots", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        active_conversation_id: "conv-1",
        items: [{
          id: "conv-1",
          active: true,
          cluster_team_revision: 3,
          cluster_team: {
            version: 1,
            assignments: [{
              agent_id: "cluster-slot-1",
              name: "前端审查",
              responsibility: "检查前端回归",
              assignment_revision: 2,
            }],
          },
        }],
      }))
      .mockResolvedValueOnce(jsonOk({
        bot: { alias: "main", cli_type: "codex", cluster: { enabled: true, max_parallel_agents: 4 } },
        session: { working_dir: "C:\\workspace", message_count: 0, history_count: 0, is_processing: true },
        active_cluster_run: {
          run_id: "run-team",
          status: "running",
          team_revision: 3,
          capacity: 4,
          free_slots: 3,
          slots: [{
            agent_id: "cluster-slot-1",
            assigned: true,
            role_name: "前端审查",
            responsibility: "检查前端回归",
            assignment_revision: 2,
            status: "running",
          }],
          team: {
            version: 1,
            assignments: [{
              agent_id: "cluster-slot-1",
              name: "前端审查",
              responsibility: "检查前端回归",
              assignment_revision: 2,
            }],
          },
          tasks: {
            tasks: [{
              task_id: "task-1",
              agent_id: "cluster-slot-1",
              role_name: "动态测试角色",
              responsibility: "验证任务快照",
              team_revision: 3,
              assignment_revision: 2,
              status: "running",
            }],
            running_count: 1,
            pending_count: 1,
          },
        },
      }));

    const client = new RealWebBotClient();
    const conversations = await client.listConversations("main");
    const overview = await client.getBotOverview("main");

    expect(conversations.items[0]).toMatchObject({
      clusterTeamRevision: 3,
      clusterTeam: { assignments: [{ agentId: "cluster-slot-1", name: "前端审查", assignmentRevision: 2 }] },
    });
    expect(overview.cluster).toMatchObject({
      enabled: true,
      writePolicy: "all_agents",
      maxParallelAgents: 4,
      defaultTimeoutSeconds: 1800,
    });
    expect(overview.activeClusterRun).toMatchObject({
      runId: "run-team",
      teamRevision: 3,
      capacity: 4,
      freeSlots: 3,
      slots: [{
        agentId: "cluster-slot-1",
        assigned: true,
        roleName: "前端审查",
        responsibility: "检查前端回归",
        assignmentRevision: 2,
        status: "running",
      }],
      tasks: {
        tasks: [{
          roleName: "动态测试角色",
          responsibility: "验证任务快照",
          teamRevision: 3,
          assignmentRevision: 2,
        }],
      },
    });
  });

  test("never sends legacy cluster or mention dispatch fields", async () => {
    fetchMock.mockResolvedValue(streamOk("event: done\ndata: {\"type\":\"done\",\"output\":\"完成\"}\n\n"));
    const legacyOptions = {
      cluster: true,
      mentions: [{ agentId: "reviewer", label: "审查", start: 0, end: 9 }],
    } as unknown as Parameters<RealWebBotClient["sendMessage"]>[5];

    await new RealWebBotClient().sendMessage("main", "@reviewer 请审查", () => undefined, undefined, undefined, legacyOptions);

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body)) as Record<string, unknown>;
    expect(body.message).toBe("@reviewer 请审查");
    expect(body).not.toHaveProperty("cluster");
    expect(body).not.toHaveProperty("mentions");
  });

  test("maps cluster resize blockers to camelCase error data", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        ok: false,
        error: {
          code: "cluster_resize_blocked",
          message: "缩容受阻",
          data: {
            code: "cluster_resize_blocked",
            target_size: 2,
            minimum_size: 4,
            blockers: [{
              conversation_id: "conv-old",
              title: "旧会话",
              execution_mode: "native_agent",
              role_count: 3,
              outside_agent_ids: ["cluster-slot-4"],
              minimum_size: 4,
            }],
          },
        },
      }),
    });

    const request = new RealWebBotClient().updateClusterConfig("main", { maxParallelAgents: 2 });

    await expect(request).rejects.toBeInstanceOf(WebApiClientError);
    await expect(request).rejects.toEqual(expect.objectContaining({
      code: "cluster_resize_blocked",
      data: {
        code: "cluster_resize_blocked",
        targetSize: 2,
        minimumSize: 4,
        blockers: [{
          conversationId: "conv-old",
          title: "旧会话",
          executionMode: "native_agent",
          roleCount: 3,
          outsideAgentIds: ["cluster-slot-4"],
          minimumSize: 4,
        }],
      },
    }));
  });

  test.each(["meta", "status", "trace", "done"] as const)(
    "preserves top-level turn binding from legacy %s frames",
    async (eventType) => {
      const turnId = `turn-${eventType}`;
      const assistantMessageId = `assistant-${eventType}`;
      const bindingFrame = eventType === "meta"
        ? `event: meta\ndata: {"type":"meta","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}"}\n\n`
        : eventType === "status"
          ? `event: status\ndata: {"type":"status","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}","preview_text":"处理中"}\n\n`
          : eventType === "trace"
            ? `event: trace\ndata: {"type":"trace","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}","event":{"kind":"tool_call","summary":"dir","tool_name":"shell_command"}}\n\n`
            : `event: done\ndata: {"type":"done","turn_id":"${turnId}","assistant_message_id":"${assistantMessageId}","output":"完成"}\n\n`;
      const terminalFrame = eventType === "done"
        ? undefined
        : "event: done\ndata: {\"type\":\"done\",\"output\":\"完成\"}\n\n";
      fetchMock.mockResolvedValue(streamOk(...[bindingFrame, terminalFrame].filter((frame): frame is string => Boolean(frame))));

      const statuses: Array<{ turnId?: string; assistantMessageId?: string }> = [];
      const traces: string[] = [];
      const message = await new RealWebBotClient().sendMessage(
        "main",
        "hello",
        () => undefined,
        (status) => statuses.push(status),
        (trace) => traces.push(`${trace.kind}:${trace.summary}`),
      );

      expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
        message: "hello",
        stream_protocol_version: 2,
      });
      expect(message).toMatchObject({ id: assistantMessageId, turnId, text: "完成", state: "done" });
      if (eventType === "meta" || eventType === "status") {
        expect(statuses).toContainEqual(expect.objectContaining({ turnId, assistantMessageId }));
      }
      if (eventType === "trace") {
        expect(traces).toEqual(["tool_call:dir"]);
      }
    },
  );

  test("keeps the endless stream open after an intermediate error", async () => {
    const errorMessage = {
      id: "assistant-endless-error",
      turn_id: "turn-endless-error",
      role: "assistant",
      content: "Continue 失败",
      created_at: "2026-10-26T00:00:00Z",
      state: "error",
      meta: { completion_state: "error" },
    };
    fetchMock.mockResolvedValue(streamOk(
      'event: endless_error\ndata: ' + JSON.stringify({
        type: "endless_error",
        turn_id: "turn-endless-error",
        assistant_message_id: "assistant-endless-error",
        attempt: 1,
        message: errorMessage,
        output: "Continue 失败",
        next_delay_ms: 2000,
      }) + "\n\n",
      'event: endless_continue\ndata: ' + JSON.stringify({
        type: "endless_continue",
        attempt: 1,
        text: "Continue",
      }) + "\n\n",
      'event: done\ndata: ' + JSON.stringify({
        type: "done",
        turn_id: "turn-endless-success",
        assistant_message_id: "assistant-endless-success",
        output: "最终成功",
        message: {
          id: "assistant-endless-success",
          turn_id: "turn-endless-success",
          role: "assistant",
          content: "最终成功",
          state: "done",
        },
      }) + "\n\n",
    ));

    const errors: Array<{ text: string; attempt: number; nextDelayMs?: number }> = [];
    const continues: Array<{ text: string; attempt: number }> = [];
    const message = await new RealWebBotClient().sendMessage(
      "main",
      "Continue",
      () => undefined,
      undefined,
      undefined,
      { endlessMode: true, skipInputTranslation: true },
      undefined,
      (error, attempt, nextDelayMs) => errors.push({ text: error.text, attempt, nextDelayMs }),
      (attempt) => continues.push({ text: "Continue", attempt }),
    );

    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      message: "Continue",
      endless_mode: true,
      skip_input_translation: true,
    });
    expect(errors).toEqual([{ text: "Continue 失败", attempt: 1, nextDelayMs: 2000 }]);
    expect(continues).toEqual([{ text: "Continue", attempt: 1 }]);
    expect(message).toMatchObject({ id: "assistant-endless-success", text: "最终成功", state: "done" });
  });

  test("falls back to the declared delay when retry_at_ms is already expired", async () => {
    const now = Date.now();
    fetchMock.mockResolvedValue(streamOk(
      `event: endless_error\ndata: ${JSON.stringify({
        type: "endless_error",
        attempt: 1,
        output: "过期时间戳",
        next_delay_ms: 2500,
        retry_at_ms: now - 100,
        message: { id: "assistant-expired-error", role: "assistant", content: "过期时间戳", state: "error" },
      })}\n\n`,
      `event: done\ndata: ${JSON.stringify({
        type: "done",
        output: "完成",
        message: { id: "assistant-expired-retry", role: "assistant", content: "完成", state: "done" },
      })}\n\n`,
    ));

    const errors: Array<{ nextDelayMs?: number; retryAtMs?: number }> = [];
    await new RealWebBotClient().sendMessage(
      "main",
      "Continue",
      () => undefined,
      undefined,
      undefined,
      { endlessMode: true },
      undefined,
      (_message, _attempt, nextDelayMs, retryAtMs) => errors.push({ nextDelayMs, retryAtMs }),
    );

    expect(errors[0]?.nextDelayMs).toBe(2500);
    expect(errors[0]?.retryAtMs).toBe(now - 100);
  });

  test("maps compact CLI v1 and v2 terminal frames to identical final messages", async () => {
    const persistedMessage = {
      id: "assistant-compact-cli",
      turn_id: "turn-compact-cli",
      role: "assistant",
      content: "CLI 最终答复",
      created_at: "2026-08-08T00:00:00Z",
      state: "done",
    };
    const terminalEvents = [
      {
        type: "done",
        turn_id: "turn-compact-cli",
        assistant_message_id: "assistant-compact-cli",
        output: "CLI 最终答复",
        message: persistedMessage,
      },
      {
        type: "done",
        turn_id: "turn-compact-cli",
        assistant_message_id: "assistant-compact-cli",
        message: persistedMessage,
      },
    ];
    const messages = [];
    for (const doneEvent of terminalEvents) {
      fetchMock.mockResolvedValueOnce(streamOk(`event: done\ndata: ${JSON.stringify(doneEvent)}\n\n`));
      messages.push(await new RealWebBotClient().sendMessage("main", "hello", () => undefined));
    }

    expect(messages[0]).toEqual(messages[1]);
    expect(messages[0]).toMatchObject({
      id: "assistant-compact-cli",
      turnId: "turn-compact-cli",
      text: "CLI 最终答复",
      state: "done",
    });
    for (const request of fetchMock.mock.calls) {
      expect(JSON.parse(String(request[1].body))).toMatchObject({ stream_protocol_version: 2 });
    }
  });

  test("uses minimal plugin install, update, and uninstall routes with a trusted dev source path", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({ id: "dev-plugin" }))
      .mockResolvedValueOnce(jsonOk({ id: "dev-plugin", enabled: false }))
      .mockResolvedValueOnce(jsonOk({}));
    const client = new RealWebBotClient();

    await client.installPlugin({
      sourcePath: "C:\\plugins\\dev-plugin",
      force: true,
      allowDevSourcePath: true,
    });
    await client.updatePlugin("dev-plugin", { enabled: false });
    await client.uninstallPlugin("dev-plugin");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/plugins/install", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        sourcePath: "C:\\plugins\\dev-plugin",
        force: true,
        allowDevSourcePath: true,
      }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/plugins/dev-plugin", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ enabled: false }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/plugins/dev-plugin", expect.objectContaining({ method: "DELETE" }));
  });

  test("uses AG-UI for native requests and keeps native trace out of legacy callbacks", async () => {
    fetchMock.mockResolvedValue(streamOk(
      "event: message\ndata: {\"type\":\"RUN_STARTED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\"}\n\n",
      "event: message\ndata: {\"type\":\"ACTIVITY_SNAPSHOT\",\"messageId\":\"activity-1\",\"activityType\":\"TCB_NATIVE_AGENT_TRACE\",\"replace\":true,\"content\":{\"id\":\"activity-1\",\"source\":\"native_agent\",\"rawKind\":\"commentary\",\"summary\":\"检查目录\"}}\n\n",
      "event: message\ndata: {\"type\":\"RUN_FINISHED\",\"threadId\":\"thread-1\",\"runId\":\"run-1\",\"result\":{\"content\":\"原生完成\"},\"outcome\":{\"type\":\"success\"}}\n\n",
    ));

    const legacyTraces: string[] = [];
    const agUiEvents: string[] = [];
    const message = await new RealWebBotClient().sendMessage(
      "main",
      "hello",
      () => undefined,
      undefined,
      (trace) => legacyTraces.push(trace.summary),
      { executionMode: "native_agent" },
      (event) => agUiEvents.push(event.type),
    );

    const request = fetchMock.mock.calls[0];
    expect(request[0]).toBe("/api/bots/main/chat/stream?protocol=ag-ui");
    expect(JSON.parse(String(request[1].body))).toMatchObject({
      execution_mode: "native_agent",
      protocol: "ag-ui",
      stream_protocol_version: 2,
    });
    expect(agUiEvents).toEqual([EventType.RUN_STARTED, EventType.ACTIVITY_SNAPSHOT, EventType.RUN_FINISHED]);
    expect(legacyTraces).toEqual([]);
    expect(message).toMatchObject({ text: "原生完成", state: "done" });
    expect(message.meta).toMatchObject({ tracePresentation: "native_agent_flat", traceCount: 1 });
  });

  test("maps compact AG-UI v1 and v2 terminal frames to identical final messages", async () => {
    const persistedMessage = {
      id: "assistant-compact-native",
      turn_id: "turn-compact-native",
      role: "assistant",
      content: "原生最终答复",
      created_at: "2026-08-08T00:00:00Z",
      state: "done",
    };
    const results = [
      { content: "原生最终答复", message: persistedMessage },
      { message: persistedMessage },
    ];
    const messages = [];
    for (const result of results) {
      fetchMock.mockResolvedValueOnce(streamOk(
        `event: message\ndata: ${JSON.stringify({
          type: EventType.RUN_FINISHED,
          threadId: "thread-compact-native",
          runId: "run-compact-native",
          result: {
            ...result,
            completion_state: "completed",
            turn_id: "turn-compact-native",
            assistant_message_id: "assistant-compact-native",
          },
          outcome: { type: "success" },
        })}\n\n`,
      ));
      messages.push(await new RealWebBotClient().sendMessage(
        "main",
        "hello",
        () => undefined,
        undefined,
        undefined,
        { executionMode: "native_agent" },
      ));
    }

    expect(messages[0]).toEqual(messages[1]);
    expect(messages[0]).toMatchObject({
      id: "assistant-compact-native",
      turnId: "turn-compact-native",
      text: "原生最终答复",
      state: "done",
    });
  });

  test("drains an unterminated done frame at EOF", async () => {
    fetchMock.mockResolvedValue(streamOk('event: done\ndata: {"type":"done","output":"尾帧最终答复"}'));

    const message = await new RealWebBotClient().sendMessage("main", "hi", () => undefined);

    expect(message).toMatchObject({ text: "尾帧最终答复", state: "done" });
  });

  test("reports incomplete EOF with the server turn binding", async () => {
    fetchMock.mockResolvedValue(streamOk(
      'event: meta\ndata: {"type":"meta","turn_id":"turn-incomplete","assistant_message_id":"assistant-incomplete"}\n\n',
      'event: status\ndata: {"type":"status","preview_text":"仍在处理中"}\n\n',
    ));

    await expect(new RealWebBotClient().sendMessage("main", "hi", () => undefined)).rejects.toMatchObject({
      name: "ChatStreamIncompleteError",
      turnId: "turn-incomplete",
      assistantMessageId: "assistant-incomplete",
      partialMessage: expect.objectContaining({ id: "assistant-incomplete", state: "streaming" }),
    });
  });

  test("deduplicates replayed SSE frames by stream sequence", async () => {
    const frame = "event: trace\nid: 17\ndata: {\"event\":{\"kind\":\"commentary\",\"summary\":\"一次过程\",\"source\":\"codex\"}}\n\n";
    fetchMock.mockResolvedValue(streamOk(frame, frame, "event: done\ndata: {\"output\":\"ok\"}\n\n"));

    const traces: string[] = [];
    const message = await new RealWebBotClient().sendMessage("main", "hi", () => undefined, undefined, (trace) => {
      traces.push(trace.summary);
    });

    expect(traces).toEqual(["一次过程"]);
    expect(message.meta?.trace).toHaveLength(1);
  });

  test("scopes agent history and conversations by agent and execution mode", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({ items: [] }))
      .mockResolvedValueOnce(jsonOk({
        active_conversation_id: "conv-1",
        items: [{
          id: "conv-1",
          title: "审查",
          last_message_preview: "完成",
          message_count: 2,
          pinned: false,
          active: true,
          status: "active",
          bot_alias: "main",
          cli_type: "codex",
          working_dir: "C:\\repo",
          agent_id: "reviewer",
          native_provider: "codex",
          native_session_id: "thread-1",
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:01:00Z",
        }],
      }));

    const client = new RealWebBotClient();
    const history = await client.listMessages("main", { agentId: "reviewer", executionMode: "native_agent" });
    const conversations = await client.listConversations("main", "", {
      agentId: "reviewer",
      executionMode: "native_agent",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/bots/main/history?agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/conversations?limit=80&agent_id=reviewer&execution_mode=native_agent",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(conversations.items[0]).toMatchObject({
      agentId: "reviewer",
      nativeSource: { sessionId: "thread-1" },
    });
    expect(history).toEqual({ items: [] });
  });

  test("archives one conversation without using the destructive delete route", async () => {
    fetchMock.mockResolvedValueOnce(jsonOk({
      archived_conversation_id: "conv-old",
      active_conversation_id: "",
      items: [],
    }));

    const result = await new RealWebBotClient().archiveConversation("main", "conv-old", {
      agentId: "main",
      executionMode: "cli",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/conversations/conv-old/archive",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ agent_id: "main", execution_mode: "cli" }),
      }),
    );
    expect(result).toEqual({
      archivedConversationId: "conv-old",
      activeConversationId: "",
      items: [],
    });
  });

  test.each([
    [{ items: [], current_revision: 7 }, 7],
    [{ items: [], revision: 0 }, 0],
    [{ items: [] }, undefined],
  ])("maps history snapshot revision from compatible response fields", async (payload, revision) => {
    fetchMock.mockResolvedValueOnce(jsonOk(payload));

    const snapshot = await new RealWebBotClient().listMessages("main");

    expect(snapshot.items).toEqual([]);
    expect(snapshot.revision).toBe(revision);
  });
});
