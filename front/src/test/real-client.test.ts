import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";

describe("RealWebBotClient", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  test("login validates token through auth/me", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          user_id: 1001,
        },
      }),
    });

    const client = new RealWebBotClient();
    const session = await client.login("secret-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(session.isLoggedIn).toBe(true);
    expect(session.currentBotAlias).toBe("");
  });

  test("cluster setup endpoints map snake case responses", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          enabled: true,
          model_tiers: { low: "fast-model", medium: "balanced-model", high: "strong-model" },
          mcp: {
            server_name: "tcb-cluster",
            active_cli_type: "kimi",
            runtime: { state: "runtime_ready", message: "运行态可用" },
            codex: { state: "not_checked", message: "未使用" },
            claude: { state: "not_checked", message: "未使用" },
            kimi: { state: "installed", message: "已安装" },
          },
          agents: [{ id: "reviewer", name: "代码审查", enabled: true, allow_cluster: true, allow_write: false }],
        },
      }),
    });

    const client = new RealWebBotClient();
    const status = await client.getClusterStatus("main");

    expect(fetchMock).toHaveBeenCalledWith("/api/bots/main/cluster/status", expect.objectContaining({ cache: "no-store" }));
    expect(status.enabled).toBe(true);
    expect(status.mcp.serverName).toBe("tcb-cluster");
    expect(status.mcp.activeCliType).toBe("kimi");
    expect(status.mcp.runtime?.state).toBe("runtime_ready");
    expect(status.mcp.kimi.state).toBe("installed");
    expect(status.modelTiers.low).toBe("fast-model");
    expect(status.agents[0].allowWrite).toBe(false);
  });

  test("cluster template endpoints map preview and apply results", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          templates: [{ id: "full_test", name: "全量测试", description: "跑测试", agent_count: 3, write_agent_count: 0, max_parallel_agents: 3 }],
        },
      }),
    }).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          version: 1,
          schema: { type: "object" },
          instructions: "只输出 JSON bundle",
        },
      }),
    }).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          bundle: {
            id: "full_test",
            name: "全量测试集群",
            description: "跑测试",
            cluster: { enabled: true, write_policy: "main_only", conflict_policy: "snapshot_diff", max_parallel_agents: 3, default_timeout_seconds: 900, model_tiers: { low: "", medium: "", high: "" } },
            agents: [{ id: "tester", name: "测试专家", system_prompt: "跑测试", enabled: true, cluster: { allow_cluster: true, allow_write: false, session_policy: "ephemeral", timeout_seconds: 900 } }],
          },
          diff: { delete_agents: [], create_agents: ["tester"], update_agents: [], cluster_changes: {}, overwrites_agents: true },
        },
      }),
    }).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          cluster: { enabled: true, write_policy: "main_only", conflict_policy: "snapshot_diff", max_parallel_agents: 3, default_timeout_seconds: 900, model_tiers: { low: "", medium: "", high: "" } },
          agents: [{ id: "tester", name: "测试专家", system_prompt: "跑测试", enabled: true, is_main: false, cluster: { allow_cluster: true, allow_write: false, session_policy: "ephemeral", timeout_seconds: 900 } }],
          bundle: {
            id: "full_test",
            name: "全量测试集群",
            description: "跑测试",
            cluster: { enabled: true, write_policy: "main_only", conflict_policy: "snapshot_diff", max_parallel_agents: 3, default_timeout_seconds: 900, model_tiers: { low: "", medium: "", high: "" } },
            agents: [{ id: "tester", name: "测试专家", system_prompt: "跑测试", enabled: true, cluster: { allow_cluster: true, allow_write: false, session_policy: "ephemeral", timeout_seconds: 900 } }],
          },
          diff: { delete_agents: [], create_agents: ["tester"], update_agents: [], cluster_changes: {}, overwrites_agents: true },
          status: {
            enabled: true,
            model_tiers: { low: "", medium: "", high: "" },
            mcp: {
              server_name: "tcb-cluster",
              active_cli_type: "codex",
              runtime: { state: "runtime_ready", message: "运行态可用" },
              codex: { state: "installed", message: "已安装" },
              claude: { state: "not_checked", message: "未使用" },
            },
            agents: [{ id: "tester", name: "测试专家", enabled: true, allow_cluster: true, allow_write: false }],
          },
        },
      }),
    });

    const client = new RealWebBotClient();
    const list = await client.getClusterTemplates("main");
    const schema = await client.getClusterBundleSchema("main");
    const preview = await client.previewClusterTemplate("main", "full_test");
    const apply = await client.applyClusterTemplate("main", "full_test", true);

    expect(list.templates[0].agentCount).toBe(3);
    expect(schema.instructions).toContain("只输出 JSON bundle");
    expect(preview.bundle.agents[0].systemPrompt).toBe("跑测试");
    expect(apply.bundle.id).toBe("full_test");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/bots/main/cluster/templates/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ template_id: "full_test" }),
      }),
    );
  });

  test("getClusterTaskStatus maps async task output", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            tasks: [
              {
                task_id: "clt_1",
                agent_id: "tester",
                message: "跑测试",
                status: "completed",
                model_tier: "low",
                timeout_seconds: 900,
                deadline_exceeded: false,
                allow_write: false,
                created_at: "2026-05-06T10:00:00+08:00",
                started_at: "2026-05-06T10:00:01+08:00",
                completed_at: "2026-05-06T10:00:02+08:00",
                message_count: 2,
                latest_message_sequence: 2,
                messages: [
                  {
                    sequence: 1,
                    task_id: "clt_1",
                    agent_id: "tester",
                    kind: "progress",
                    content: "开始跑测试",
                    created_at: "2026-05-06T10:00:01+08:00",
                  },
                  {
                    sequence: 2,
                    task_id: "clt_1",
                    agent_id: "tester",
                    kind: "final",
                    content: "测试完成",
                    created_at: "2026-05-06T10:00:02+08:00",
                  },
                ],
                output: "3 passed",
                error: "",
              },
            ],
            queued_count: 0,
            running_count: 0,
            completed_count: 1,
            failed_count: 0,
            pending_count: 0,
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const status = await client.getClusterTaskStatus("main", "clr_1");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/cluster/runs/clr_1/tasks?include_output=1",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(status.completedCount).toBe(1);
    expect(status.tasks[0]).toMatchObject({
      taskId: "clt_1",
      agentId: "tester",
      message: "跑测试",
      status: "completed",
      timeoutSeconds: 900,
      deadlineExceeded: false,
      messageCount: 2,
      latestMessageSequence: 2,
      output: "3 passed",
    });
    expect(status.tasks[0].messages).toEqual([
      {
        sequence: 1,
        taskId: "clt_1",
        agentId: "tester",
        kind: "progress",
        content: "开始跑测试",
        createdAt: "2026-05-06T10:00:01+08:00",
      },
      {
        sequence: 2,
        taskId: "clt_1",
        agentId: "tester",
        kind: "final",
        content: "测试完成",
        createdAt: "2026-05-06T10:00:02+08:00",
      },
    ]);
  });

  test("sendMessage includes cluster mention payload", async () => {
    const encoder = new TextEncoder();
    fetchMock.mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: vi.fn()
            .mockResolvedValueOnce({
              value: encoder.encode("data: {\"type\":\"done\",\"output\":\"ok\"}\n\n"),
              done: false,
            })
            .mockResolvedValueOnce({ value: undefined, done: true }),
          cancel: vi.fn().mockResolvedValue(undefined),
        }),
      },
    });

    const client = new RealWebBotClient();
    await client.sendMessage("main", "@reviewer 看一下", vi.fn(), undefined, undefined, {
      cluster: true,
      mentions: [{ agentId: "reviewer", label: "代码审查", start: 0, end: 9 }],
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body.cluster).toBe(true);
    expect(body.mentions[0]).toMatchObject({ agent_id: "reviewer", label: "代码审查" });
  });

  test("login posts username/password and maps account session fields", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          token: "web_sess_123",
          username: "alice",
          role: "member",
          capabilities: ["chat_send", "view_file_tree"],
          current_bot_alias: "main",
          current_path: "C:\\workspace",
        },
      }),
    });

    const client = new RealWebBotClient();
    const session = await client.login({ username: "alice", password: "pw-123" });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          username: "alice",
          password: "pw-123",
        }),
      }),
    );
    expect(session).toEqual(expect.objectContaining({
      isLoggedIn: true,
      token: "web_sess_123",
      username: "alice",
      role: "member",
      capabilities: ["chat_send", "view_file_tree"],
      currentBotAlias: "main",
      currentPath: "C:\\workspace",
    }));
  });

  test("register posts register_code and returns a logged-in session", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          token: "web_sess_reg",
          username: "alice",
          role: "member",
          capabilities: ["chat_send"],
        },
      }),
    });

    const client = new RealWebBotClient();
    const session = await client.register({
      username: "alice",
      password: "pw-123",
      registerCode: "INVITE-001",
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/register",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          username: "alice",
          password: "pw-123",
          register_code: "INVITE-001",
        }),
      }),
    );
    expect(session).toEqual(expect.objectContaining({
      token: "web_sess_reg",
      username: "alice",
      role: "member",
      capabilities: ["chat_send"],
    }));
  });

  test("guest login and logout use auth guest/logout endpoints", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            token: "web_sess_guest",
            username: "guest",
            role: "guest",
            capabilities: ["view_file_tree"],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    const session = await client.loginGuest();
    await client.logout();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/auth/guest",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/logout",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer web_sess_guest",
        }),
      }),
    );
    expect(session).toEqual(expect.objectContaining({
      token: "web_sess_guest",
      username: "guest",
      role: "guest",
      capabilities: ["view_file_tree"],
    }));
  });

  test("restoreSession can use loopback auto auth without bearer token", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          username: "127.0.0.1",
          role: "member",
          capabilities: ["admin_ops", "manage_register_codes", "chat_send"],
        },
      }),
    });

    const client = new RealWebBotClient();
    const session = await client.restoreSession("");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/auth/me",
      expect.objectContaining({
        headers: expect.not.objectContaining({
          Authorization: expect.any(String),
        }),
      }),
    );
    expect(session).toEqual(expect.objectContaining({
      username: "127.0.0.1",
      role: "member",
      capabilities: ["admin_ops", "manage_register_codes", "chat_send"],
    }));
  });

  test("register code admin endpoints map fields", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                code_id: "invite-1",
                code_preview: "INV***001",
                disabled: false,
                max_uses: 2,
                used_count: 1,
                remaining_uses: 1,
                created_at: "2026-04-22T01:00:00Z",
                created_by: "127.0.0.1",
                last_used_at: "2026-04-22T02:00:00Z",
                usage: [{ used_at: "2026-04-22T02:00:00Z", used_by: "alice" }],
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            code_id: "invite-2",
            code: "INV-ABC",
            code_preview: "INV***ABC",
            disabled: false,
            max_uses: 3,
            used_count: 0,
            remaining_uses: 3,
            created_at: "2026-04-22T03:00:00Z",
            created_by: "127.0.0.1",
            last_used_at: "",
            usage: [],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            code_id: "invite-1",
            code_preview: "INV***001",
            disabled: true,
            max_uses: 4,
            used_count: 1,
            remaining_uses: 3,
            created_at: "2026-04-22T01:00:00Z",
            created_by: "127.0.0.1",
            last_used_at: "2026-04-22T02:00:00Z",
            usage: [{ used_at: "2026-04-22T02:00:00Z", used_by: "alice" }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { deleted: true } }),
      });

    const client = new RealWebBotClient();
    const listed = await client.listRegisterCodes();
    const created = await client.createRegisterCode(3);
    const updated = await client.updateRegisterCode("invite-1", { maxUsesDelta: 2, disabled: true });
    await client.deleteRegisterCode("invite-1");

    expect(listed[0]).toEqual(expect.objectContaining({
      codeId: "invite-1",
      codePreview: "INV***001",
      usage: [{ usedAt: "2026-04-22T02:00:00Z", usedBy: "alice" }],
    }));
    expect(created.code).toBe("INV-ABC");
    expect(updated).toEqual(expect.objectContaining({ codeId: "invite-1", maxUses: 4, disabled: true }));
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/admin/register-codes", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/admin/register-codes", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "/api/admin/register-codes/invite-1", expect.objectContaining({ method: "PATCH" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "/api/admin/register-codes/invite-1", expect.objectContaining({ method: "DELETE" }));
  });

  test("resolveWorkspaceDefinition maps snake_case payload fields", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            token: "secret-token",
            username: "alice",
            role: "member",
            capabilities: ["chat_send"],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                path: "src/service.py",
                line: 12,
                column: 3,
                match_kind: "workspace_search",
                confidence: 0.78,
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const result = await client.resolveWorkspaceDefinition("main", {
      path: "src/app.py",
      line: 2,
      column: 2,
      symbol: "run",
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/workspace/resolve-definition",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          path: "src/app.py",
          line: 2,
          column: 2,
          symbol: "run",
        }),
      }),
    );
    expect(result).toEqual({
      items: [
        {
          path: "src/service.py",
          line: 12,
          column: 3,
          matchKind: "workspace_search",
          confidence: 0.78,
        },
      ],
    });
  });

  test("listBots maps backend fields to frontend shape", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: [
            {
              alias: "main",
              cli_type: "codex",
              status: "running",
              is_processing: true,
              service_status: "online",
              activity_status: "busy",
              busy_agent_ids: ["reviewer"],
              busy_agent_names: ["代码审查"],
              busy_agent_count: 1,
              working_dir: "C:\\workspace\\demo",
            },
          ],
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bots = await client.listBots();

    expect(bots).toEqual([
      {
        alias: "main",
        cliType: "codex",
        status: "busy",
        serviceStatus: "online",
        activityStatus: "busy",
        busyAgentIds: ["reviewer"],
        busyAgentNames: ["代码审查"],
        busyAgentCount: 1,
        workingDir: "C:\\workspace\\demo",
        lastActiveText: "处理中",
        avatarName: "",
      },
    ]);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("listBots marks assistant with queued runtime work as busy", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: [
            {
              alias: "assistant1",
              cli_type: "codex",
              status: "running",
              is_processing: false,
              working_dir: "C:\\workspace\\assistant",
              bot_mode: "assistant",
              assistant_runtime: {
                pending_count: 1,
                queued_count: 1,
                active: null,
                queue: [
                  {
                    run_id: "run_queued",
                    source: "web",
                    status: "queued",
                    task_mode: "standard",
                    interactive: true,
                    visible_text: "排队任务",
                    enqueued_at: "2026-04-09T10:40:01",
                  },
                ],
              },
            },
          ],
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bots = await client.listBots();

    expect(bots[0]).toMatchObject({
      alias: "assistant1",
      status: "busy",
      lastActiveText: "处理中",
      botMode: "assistant",
    });
  });

  test("listBots treats legacy processing without busy agents as main agent busy", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: [
            {
              alias: "main",
              cli_type: "codex",
              status: "running",
              is_processing: true,
              working_dir: "C:\\workspace\\demo",
            },
          ],
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bots = await client.listBots();

    expect(bots[0]).toMatchObject({
      status: "busy",
      activityStatus: "busy",
      busyAgentIds: ["main"],
      busyAgentNames: ["主 agent"],
      busyAgentCount: 1,
    });
  });

  test("listFiles maps snake_case directory entries to camelCase", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            working_dir: "C:\\workspace\\demo",
            entries: [
              {
                name: "src",
                is_dir: true,
              },
              {
                name: "package.json",
                is_dir: false,
                size: 1024,
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const listing = await client.listFiles("main");

    expect(listing).toEqual({
      workingDir: "C:\\workspace\\demo",
      entries: [
        {
          name: "src",
          isDir: true,
        },
        {
          name: "package.json",
          isDir: false,
          size: 1024,
        },
      ],
    });
  });

  test("listFiles appends the explicit path query when provided", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            working_dir: "C:\\workspace\\demo\\src",
            entries: [],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    await client.listFiles("main", "C:\\workspace\\demo\\src");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/ls?path=C%3A%5Cworkspace%5Cdemo%5Csrc",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("uploadChatAttachment posts to the chat attachment endpoint and maps saved path", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            filename: "report.txt",
            saved_path: "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
            size: 5,
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const file = new File(["hello"], "report.txt", { type: "text/plain" });
    const result = await client.uploadChatAttachment("main", file);

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/chat/attachments",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
        body: expect.any(FormData),
      }),
    );
    const requestInit = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect((requestInit.body as FormData).get("file")).toBe(file);
    expect(result).toEqual({
      filename: "report.txt",
      savedPath: "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
      size: 5,
    });
  });

  test("deleteChatAttachment posts to the chat attachment delete endpoint", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            filename: "report.txt",
            saved_path: "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
            existed: true,
            deleted: true,
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const result = await client.deleteChatAttachment(
      "main",
      "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
    );

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/chat/attachments/delete",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          saved_path: "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
        }),
      }),
    );
    expect(result).toEqual({
      filename: "report.txt",
      savedPath: "C:\\Users\\demo\\.tcb\\chat-attachments\\main\\1001\\report.txt",
      existed: true,
      deleted: true,
    });
  });

  test("getBotOverview maps running reply snapshot", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            bot: {
              alias: "main",
              cli_type: "codex",
              status: "running",
              working_dir: "C:\\workspace\\profile",
              assistant_runtime: {
                pending_count: 2,
                queued_count: 1,
                active: {
                  run_id: "run_active",
                  source: "cron",
                  status: "running",
                  task_mode: "dream",
                  interactive: false,
                  job_id: "daily_dream",
                  job_title: "每日自整理",
                  visible_text: "dream prompt",
                  enqueued_at: "2026-04-09T10:39:59",
                },
                queue: [
                  {
                    run_id: "run_queued",
                    source: "web",
                    status: "queued",
                    task_mode: "standard",
                    interactive: true,
                    visible_text: "帮我总结今天进度",
                    enqueued_at: "2026-04-09T10:40:01",
                  },
                ],
              },
            },
            session: {
              working_dir: "C:\\workspace\\session",
              message_count: 3,
              history_count: 2,
              is_processing: true,
              running_reply: {
                preview_text: "处理中预览",
                started_at: "2026-04-09T10:40:00",
                updated_at: "2026-04-09T10:40:05",
              },
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const overview = await client.getBotOverview("main");

    expect(overview.workingDir).toBe("C:\\workspace\\session");
    expect(overview.status).toBe("busy");
    expect(overview.runningReply).toEqual({
      previewText: "处理中预览",
      startedAt: "2026-04-09T10:40:00",
      updatedAt: "2026-04-09T10:40:05",
    });
    expect(overview.assistantRuntime).toEqual({
      pendingCount: 2,
      queuedCount: 1,
      active: {
        runId: "run_active",
        source: "cron",
        status: "running",
        taskMode: "dream",
        interactive: false,
        jobId: "daily_dream",
        jobTitle: "每日自整理",
        visibleText: "dream prompt",
        enqueuedAt: "2026-04-09T10:39:59",
      },
      queue: [
        {
          runId: "run_queued",
          source: "web",
          status: "queued",
          taskMode: "standard",
          interactive: true,
          visibleText: "帮我总结今天进度",
          enqueuedAt: "2026-04-09T10:40:01",
        },
      ],
    });
  });

  test("getBotOverview preserves active cluster task messages", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            bot: {
              alias: "main",
              cli_type: "codex",
              status: "running",
              working_dir: "C:\\workspace\\profile",
            },
            session: {
              working_dir: "C:\\workspace\\session",
              message_count: 3,
              history_count: 2,
              is_processing: false,
            },
            agents: [
              {
                id: "reviewer",
                name: "代码审查",
                system_prompt: "先列风险",
                enabled: true,
                is_main: false,
              },
            ],
            active_cluster_run: {
              run_id: "clr_active",
              status: "running",
              tasks: {
                tasks: [
                  {
                    task_id: "clt_active",
                    agent_id: "reviewer",
                    message: "检查改动",
                    status: "running",
                    model_tier: "high",
                    timeout_seconds: 600,
                    deadline_exceeded: false,
                    allow_write: false,
                    created_at: "2026-05-04T00:00:03Z",
                    started_at: "2026-05-04T00:00:04Z",
                    completed_at: "",
                    message_count: 1,
                    latest_message_sequence: 1,
                    messages: [
                      {
                        sequence: 1,
                        task_id: "clt_active",
                        agent_id: "reviewer",
                        kind: "progress",
                        content: "正在检查 diff",
                        created_at: "2026-05-04T00:00:05Z",
                      },
                    ],
                    error: "",
                  },
                ],
                queued_count: 0,
                running_count: 1,
                completed_count: 0,
                failed_count: 0,
                pending_count: 1,
              },
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const overview = await client.getBotOverview("main");

    expect(overview.activeClusterRun?.runId).toBe("clr_active");
    expect(overview.activeClusterRun?.tasks?.pendingCount).toBe(1);
    expect(overview.activeClusterRun?.tasks?.tasks[0]).toMatchObject({
      taskId: "clt_active",
      agentId: "reviewer",
      message: "检查改动",
      status: "running",
      timeoutSeconds: 600,
      deadlineExceeded: false,
      messageCount: 1,
      latestMessageSequence: 1,
    });
    expect(overview.activeClusterRun?.tasks?.tasks[0].messages).toEqual([
      {
        sequence: 1,
        taskId: "clt_active",
        agentId: "reviewer",
        kind: "progress",
        content: "正在检查 diff",
        createdAt: "2026-05-04T00:00:05Z",
      },
    ]);
  });

  test("agent endpoints and scoped chat requests use agent_id", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [{
              id: "reviewer",
              name: "代码审查",
              system_prompt: "先列风险",
              enabled: true,
              is_main: false,
            }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            agent: {
              id: "writer",
              name: "文档",
              system_prompt: "写文档",
              enabled: true,
              is_main: false,
            },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            bot: {
              alias: "main",
              cli_type: "codex",
              status: "running",
              working_dir: "C:\\workspace",
            },
            session: {
              working_dir: "C:\\workspace",
              message_count: 0,
              history_count: 0,
              is_processing: false,
            },
            agents: [],
            active_agent_id: "reviewer",
            busy_agent_ids: [],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: { items: [] },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            active_conversation_id: "",
            items: [],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            conversation: {
              id: "conv-1",
              title: "审查",
              last_message_preview: "",
              message_count: 0,
              pinned: false,
              active: true,
              status: "active",
              bot_alias: "main",
              bot_mode: "cli",
              cli_type: "codex",
              working_dir: "C:\\workspace",
              agent_id: "reviewer",
              created_at: "2026-05-04T00:00:00Z",
              updated_at: "2026-05-04T00:00:00Z",
            },
            messages: [],
          },
        }),
      });

    const client = new RealWebBotClient();
    const agents = await client.listAgents("main");
    const created = await client.createAgent("main", {
      id: "writer",
      name: "文档",
      systemPrompt: "写文档",
      enabled: true,
    });
    await client.getBotOverview("main", { agentId: "reviewer" });
    await client.listMessages("main", { agentId: "reviewer" });
    await client.listConversations("main", "", { agentId: "reviewer" });
    await client.createConversation("main", "审查", { agentId: "reviewer" });

    expect(agents.items[0]).toEqual(expect.objectContaining({
      id: "reviewer",
      name: "代码审查",
      systemPrompt: "先列风险",
    }));
    expect(created.agent).toEqual(expect.objectContaining({
      id: "writer",
      systemPrompt: "写文档",
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/bots/main/agents",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/bots/main/agents",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          id: "writer",
          name: "文档",
          system_prompt: "写文档",
          enabled: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/bots/main?agent_id=reviewer",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/bots/main/history?agent_id=reviewer",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/bots/main/conversations?limit=80&agent_id=reviewer",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/bots/main/conversations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          title: "审查",
          agent_id: "reviewer",
        }),
      }),
    );
  });

  test("listMessages maps persisted elapsed seconds from history", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                timestamp: "2026-04-10T00:00:00",
                role: "assistant",
                content: "最终结果",
                elapsed_seconds: 6,
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const messages = await client.listMessages("main");

    expect(messages).toEqual([
      {
        id: "2026-04-10T00:00:00-0",
        role: "assistant",
        text: "最终结果",
        createdAt: "2026-04-10T00:00:00",
        elapsedSeconds: 6,
        state: "done",
      },
    ]);
  });

  test("listConversations maps native session metadata", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          active_conversation_id: "conv-1",
          items: [{
            id: "conv-1",
            title: "修复 diff",
            last_message_preview: "完成",
            message_count: 2,
            pinned: false,
            active: true,
            status: "active",
            bot_alias: "main",
            bot_mode: "cli",
            cli_type: "codex",
            working_dir: "C:\\repo",
            native_provider: "codex",
            native_session_id: "thread-1",
            created_at: "2026-05-03T00:00:00Z",
            updated_at: "2026-05-03T00:01:00Z",
          }],
        },
      }),
    });

    const client = new RealWebBotClient();
    const data = await client.listConversations("main");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/conversations?limit=80",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(data.activeConversationId).toBe("conv-1");
    expect(data.items[0].title).toBe("修复 diff");
    expect(data.items[0].nativeSource?.sessionId).toBe("thread-1");
  });

  test("listMessages maps rich native history meta and lazy trace counters", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                id: "codex-thread-1-0-user",
                created_at: "2026-04-14T10:00:00",
                role: "user",
                content: "列出当前目录",
                meta: {
                  native_source: {
                    provider: "codex",
                    session_id: "thread-1",
                  },
                },
              },
              {
                id: "codex-thread-1-0",
                created_at: "2026-04-14T10:00:00",
                role: "assistant",
                content: "目录已读取完成。",
                meta: {
                  summary_kind: "final",
                  completion_state: "completed",
                  trace_version: 1,
                  trace_count: 3,
                  tool_call_count: 1,
                  process_count: 1,
                  native_source: {
                    provider: "codex",
                    session_id: "thread-1",
                  },
                },
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const messages = await client.listMessages("main");

    expect(messages).toEqual([
      {
        id: "codex-thread-1-0-user",
        role: "user",
        text: "列出当前目录",
        createdAt: "2026-04-14T10:00:00",
        state: "done",
        meta: {
          nativeSource: {
            provider: "codex",
            sessionId: "thread-1",
          },
        },
      },
      {
        id: "codex-thread-1-0",
        role: "assistant",
        text: "目录已读取完成。",
        createdAt: "2026-04-14T10:00:00",
        state: "done",
        meta: {
          summaryKind: "final",
          completionState: "completed",
          traceVersion: 1,
          traceCount: 3,
          toolCallCount: 1,
          processCount: 1,
          nativeSource: {
            provider: "codex",
            sessionId: "thread-1",
          },
        },
      },
    ]);
  });

  test("getMessageTrace maps rich native trace payload for one history message", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            message_id: "codex-thread-1-0",
            trace_count: 3,
            tool_call_count: 1,
            process_count: 1,
            trace: [
              {
                kind: "commentary",
                source: "native",
                raw_type: "agent_message",
                summary: "我先检查目录结构。",
              },
              {
                kind: "tool_call",
                source: "native",
                raw_type: "function_call",
                title: "shell_command",
                tool_name: "shell_command",
                call_id: "call_1",
                summary: "Get-ChildItem -Force",
                payload: {
                  arguments: {
                    command: "Get-ChildItem -Force",
                  },
                },
              },
              {
                kind: "tool_result",
                source: "native",
                raw_type: "function_call_output",
                call_id: "call_1",
                summary: "bot/web/api_service.py",
                payload: {
                  output: "bot/web/api_service.py",
                },
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const traceDetails = await client.getMessageTrace("main", "codex-thread-1-0");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/history/codex-thread-1-0/trace",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(traceDetails).toEqual({
      traceCount: 3,
      toolCallCount: 1,
      processCount: 1,
      trace: [
        {
          kind: "commentary",
          rawType: "agent_message",
          summary: "我先检查目录结构。",
          source: "native",
        },
        {
          kind: "tool_call",
          rawType: "function_call",
          title: "shell_command",
          toolName: "shell_command",
          callId: "call_1",
          summary: "Get-ChildItem -Force",
          source: "native",
          payload: {
            arguments: {
              command: "Get-ChildItem -Force",
            },
          },
        },
        {
          kind: "tool_result",
          rawType: "function_call_output",
          callId: "call_1",
          summary: "bot/web/api_service.py",
          source: "native",
          payload: {
            output: "bot/web/api_service.py",
          },
        },
      ],
    });
  });

  test("requestJson throws WebApiClientError with structured workdir conflict data", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          ok: false,
          error: {
            code: "workdir_change_requires_reset",
            message: "切换工作目录会丢失当前会话，确认后重试",
            data: {
              current_working_dir: "C:\\workspace\\old",
              requested_working_dir: "C:\\workspace\\new",
              history_count: 2,
              message_count: 5,
              bot_mode: "cli",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    await expect(client.updateBotWorkdir("main", "C:\\workspace\\new")).rejects.toMatchObject({
      name: "WebApiClientError",
      code: "workdir_change_requires_reset",
      status: 409,
      data: {
        currentWorkingDir: "C:\\workspace\\old",
        requestedWorkingDir: "C:\\workspace\\new",
        historyCount: 2,
        messageCount: 5,
        botMode: "cli",
      },
    });
  });

  test("getGitProxySettings reads admin git proxy endpoint", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            address: "192.168.1.10:7897",
            port: "7897",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const settings = await client.getGitProxySettings();

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/git-proxy",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(settings).toEqual({ address: "192.168.1.10:7897", port: "7897" });
  });

  test("updateGitProxySettings patches admin git proxy endpoint", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            address: "127.0.0.1:7897",
            port: "7897",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const settings = await client.updateGitProxySettings("7897");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/git-proxy",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ address: "7897" }),
      }),
    );
    expect(settings).toEqual({ address: "127.0.0.1:7897", port: "7897" });
  });

  test("getUpdateStatus maps backend update payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { user_id: 1001 } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_version: "1.0.0",
            current_package_kind: "installer",
            update_enabled: true,
            update_channel: "release",
            last_checked_at: "2026-04-15T10:00:00+08:00",
            last_available_version: "1.0.1",
            last_available_release_url: "https://github.com/owner/repo/releases/tag/v1.0.1",
            last_available_notes: "Bugfixes",
            pending_update_version: "",
            pending_update_path: "",
            pending_update_notes: "",
            pending_update_platform: "",
            pending_update_package_kind: "installer",
            update_last_error: "",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const status = await client.getUpdateStatus();

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/update",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer secret-token" }),
      }),
    );
    expect(status.currentVersion).toBe("1.0.0");
    expect(status.currentPackageKind).toBe("installer");
    expect(status.latestVersion).toBe("1.0.1");
    expect(status.pendingUpdatePackageKind).toBe("installer");
  });

  test("downloadUpdateStream forwards progress events and returns the final update status", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            "event: progress\ndata: {\"phase\":\"downloading\",\"downloaded_bytes\":512,\"total_bytes\":1024,\"percent\":50}\n\n",
          ),
        );
        controller.enqueue(
          encoder.encode(
            "event: done\ndata: {\"status\":{\"current_version\":\"1.0.0\",\"current_package_kind\":\"installer\",\"update_enabled\":true,\"update_channel\":\"release\",\"last_checked_at\":\"2026-04-15T10:00:00+08:00\",\"last_available_version\":\"1.0.1\",\"last_available_release_url\":\"https://github.com/owner/repo/releases/tag/v1.0.1\",\"last_available_notes\":\"Bugfixes\",\"pending_update_version\":\"1.0.1\",\"pending_update_path\":\".updates/cli-bridge-windows-x64-installer.zip\",\"pending_update_notes\":\"Bugfixes\",\"pending_update_platform\":\"windows-x64-installer\",\"pending_update_package_kind\":\"installer\",\"update_last_error\":\"\"}}\n\n",
          ),
        );
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient() as RealWebBotClient & {
      downloadUpdateStream: (
        onProgress: (event: { phase: string; downloadedBytes: number; totalBytes?: number; percent?: number }) => void,
      ) => Promise<{
        pendingUpdateVersion: string;
        pendingUpdatePath: string;
        pendingUpdatePackageKind: string;
      }>;
    };
    await client.login("secret-token");

    const progressEvents: Array<{ phase: string; downloadedBytes: number; totalBytes?: number; percent?: number }> = [];
    const status = await client.downloadUpdateStream((event) => {
      progressEvents.push(event);
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/update/download/stream",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({}),
      }),
    );
    expect(progressEvents).toEqual([
      {
        phase: "downloading",
        downloadedBytes: 512,
        totalBytes: 1024,
        percent: 50,
      },
    ]);
    expect(status.pendingUpdateVersion).toBe("1.0.1");
    expect(status.pendingUpdatePath).toBe(".updates/cli-bridge-windows-x64-installer.zip");
    expect(status.pendingUpdatePackageKind).toBe("installer");
  });

  test("requestJson reports a friendly error when the server returns HTML", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        headers: {
          get: (name: string) => (name.toLowerCase() === "content-type" ? "text/html; charset=utf-8" : null),
        },
        clone: () => ({
          text: async () => "<!doctype html><html></html>",
        }),
        json: async () => {
          throw new SyntaxError("Unexpected token '<'");
        },
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    await expect(client.getTunnelStatus()).rejects.toThrow(
      "服务返回了页面内容而不是 JSON，请确认 Web API 已启动，并且前后端版本已同步更新",
    );
  });

  test("restartService tolerates connection reset caused by server restart", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const client = new RealWebBotClient();
    await client.login("secret-token");

    await expect(client.restartService()).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/restart",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        keepalive: true,
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("restartService tolerates a hung restart request by aborting after a short timeout", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockImplementationOnce((_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        }),
      );

    const client = new RealWebBotClient();
    await client.login("secret-token");

    const restartPromise = client.restartService();
    await vi.advanceTimersByTimeAsync(5000);

    await expect(restartPromise).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/restart",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        keepalive: true,
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    vi.useRealTimers();
  });

  test("readFileFull uses cat mode endpoint", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            content: "full file content",
            mode: "cat",
            file_size_bytes: 123,
            is_full_content: true,
            last_modified_ns: "1776420510390927700",
            encoding: "gb18030",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const content = await client.readFileFull("main", "README.md");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/files/read?filename=README.md&mode=cat&lines=0",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(content).toEqual({
      content: "full file content",
      mode: "cat",
      workingDir: "",
      fileSizeBytes: 123,
      isFullContent: true,
      lastModifiedNs: "1776420510390927700",
      encoding: "gb18030",
    });
  });

  test("readFile maps raster image preview payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            content: "",
            mode: "head",
            preview_kind: "image",
            content_type: "image/png",
            content_base64: "AA==",
            file_size_bytes: 4,
            is_full_content: true,
            last_modified_ns: "1776420510390927700",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const content = await client.readFile("main", "diagram.png");

    expect(content).toEqual({
      content: "",
      mode: "head",
      workingDir: "",
      fileSizeBytes: 4,
      isFullContent: true,
      lastModifiedNs: "1776420510390927700",
      previewKind: "image",
      contentType: "image/png",
      contentBase64: "AA==",
    });
  });

  test("getPluginArtifactBlob fetches artifact bytes with auth headers", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce(
        {
          ok: true,
          blob: async () => new Blob(["image"], { type: "image/png" }),
        },
      );

    const client = new RealWebBotClient();
    await client.restoreSession("secret-token");
    const blob = await client.getPluginArtifactBlob("main", "artifact-1");

    expect(blob.type).toBe("image/png");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/plugins/artifacts/artifact-1",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("writeFile preserves string file versions in the request body", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            path: "README.md",
            file_size_bytes: 16,
            last_modified_ns: "1776420510390927700",
            encoding: "gb18030",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const result = await client.writeFile("main", "README.md", "updated content", "1776420510390927700", "gb18030");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/files/write",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          path: "README.md",
          content: "updated content",
          expected_mtime_ns: "1776420510390927700",
          encoding: "gb18030",
        }),
      }),
    );
    expect(result).toEqual({
      path: "README.md",
      fileSizeBytes: 16,
      lastModifiedNs: "1776420510390927700",
      encoding: "gb18030",
    });
  });

  test("getCliParams maps backend cli param payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            cli_type: "codex",
            params: {
              reasoning_effort: "xhigh",
              extra_args: ["--search"],
            },
            defaults: {
              reasoning_effort: "xhigh",
              extra_args: [],
            },
            schema: {
              reasoning_effort: {
                type: "string",
                enum: ["xhigh", "high", "medium", "low"],
                description: "推理努力程度",
              },
              extra_args: {
                type: "string_list",
                description: "额外参数",
              },
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const payload = await client.getCliParams("main");

    expect(payload).toEqual({
      cliType: "codex",
      params: {
        reasoning_effort: "xhigh",
        extra_args: ["--search"],
      },
      defaults: {
        reasoning_effort: "xhigh",
        extra_args: [],
      },
      schema: {
        reasoning_effort: {
          type: "string",
          enum: ["xhigh", "high", "medium", "low"],
          description: "推理努力程度",
        },
        extra_args: {
          type: "string_list",
          description: "额外参数",
        },
      },
    });
  });

  test("getCliParams maps kimi backend cli param payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            cli_type: "kimi",
            params: {
              thinking: "disabled",
              stream_json: true,
              max_steps_per_turn: 3,
            },
            defaults: {
              thinking: "default",
              stream_json: true,
              max_steps_per_turn: null,
            },
            schema: {
              thinking: {
                type: "string",
                enum: ["enabled", "disabled", "default"],
                description: "Thinking 模式",
              },
              stream_json: {
                type: "boolean",
                description: "启用 stream-json 输出",
              },
              max_steps_per_turn: {
                type: "number",
                description: "单轮最大步数",
                integer: true,
                nullable: true,
              },
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const payload = await client.getCliParams("main");

    expect(payload).toEqual({
      cliType: "kimi",
      params: {
        thinking: "disabled",
        stream_json: true,
        max_steps_per_turn: 3,
      },
      defaults: {
        thinking: "default",
        stream_json: true,
        max_steps_per_turn: null,
      },
      schema: {
        thinking: {
          type: "string",
          enum: ["enabled", "disabled", "default"],
          description: "Thinking 模式",
        },
        stream_json: {
          type: "boolean",
          description: "启用 stream-json 输出",
        },
        max_steps_per_turn: {
          type: "number",
          description: "单轮最大步数",
          integer: true,
          nullable: true,
        },
      },
    });
  });

  test("sendMessage forwards status events before final output", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: meta\ndata: {\"type\":\"meta\",\"cli_type\":\"codex\"}\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: {\"elapsed_seconds\":2,\"preview_text\":\"处理中预览\"}\n\n"));
        controller.enqueue(encoder.encode("event: done\ndata: {\"output\":\"最终结果\",\"elapsed_seconds\":4}\n\n"));
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    const statuses: Array<{ elapsedSeconds?: number; previewText?: string }> = [];
    const message = await client.sendMessage("main", "hello", () => undefined, (status) => {
      statuses.push(status);
    });

    expect(statuses).toEqual([
      {
        elapsedSeconds: 2,
        previewText: "处理中预览",
      },
    ]);
    expect(message.text).toBe("最终结果");
    expect(message.elapsedSeconds).toBe(4);
  });

  test("sendMessage resolves once done arrives even if the stream stays open", async () => {
    const encoder = new TextEncoder();
    let cancelled = false;
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: meta\ndata: {\"type\":\"meta\",\"cli_type\":\"codex\"}\n\n"));
        controller.enqueue(encoder.encode("event: done\ndata: {\"output\":\"最终结果\",\"elapsed_seconds\":4}\n\n"));
      },
      cancel() {
        cancelled = true;
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    const messagePromise = client.sendMessage("main", "hello", () => undefined);
    const timeoutPromise = new Promise<never>((_, reject) => {
      window.setTimeout(() => reject(new Error("sendMessage did not resolve after done")), 200);
    });
    const message = await Promise.race([messagePromise, timeoutPromise]);

    expect(message.text).toBe("最终结果");
    expect(message.elapsedSeconds).toBe(4);
    expect(cancelled).toBe(true);
  });

  test("sendMessage forwards trace events and prefers done.message over done.output", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: trace\ndata: {\"event\":{\"kind\":\"commentary\",\"source\":\"native\",\"raw_type\":\"agent_message\",\"summary\":\"我先检查目录结构。\"}}\n\n"));
        controller.enqueue(encoder.encode("event: trace\ndata: {\"event\":{\"kind\":\"tool_call\",\"source\":\"native\",\"raw_type\":\"function_call\",\"title\":\"shell_command\",\"tool_name\":\"shell_command\",\"call_id\":\"call_1\",\"summary\":\"Get-ChildItem -Force\",\"payload\":{\"arguments\":{\"command\":\"Get-ChildItem -Force\"}}}}\n\n"));
        controller.enqueue(encoder.encode("event: done\ndata: {\"output\":\"fallback output\",\"elapsed_seconds\":4,\"message\":{\"id\":\"codex-thread-1-0\",\"role\":\"assistant\",\"content\":\"目录已读取完成。\",\"created_at\":\"2026-04-14T10:00:00\",\"meta\":{\"summary_kind\":\"final\",\"completion_state\":\"completed\",\"trace_version\":1,\"native_source\":{\"provider\":\"codex\",\"session_id\":\"thread-1\"},\"trace\":[{\"kind\":\"commentary\",\"source\":\"native\",\"raw_type\":\"agent_message\",\"summary\":\"我先检查目录结构。\"}]}}}\n\n"));
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    const traces: unknown[] = [];
    const message = await (client.sendMessage as unknown as (
      botAlias: string,
      text: string,
      onChunk: (chunk: string) => void,
      onStatus?: (status: unknown) => void,
      onTrace?: (trace: unknown) => void,
    ) => Promise<unknown>)(
      "main",
      "hello",
      () => undefined,
      undefined,
      (trace) => {
        traces.push(trace);
      },
    ) as {
      text: string;
      elapsedSeconds?: number;
      meta?: {
        summaryKind?: string;
        completionState?: string;
        nativeSource?: { provider?: string; sessionId?: string };
        trace?: Array<{ kind?: string; summary?: string; toolName?: string; callId?: string }>;
      };
    };

    expect(traces).toEqual([
      {
        kind: "commentary",
        rawType: "agent_message",
        summary: "我先检查目录结构。",
        source: "native",
      },
      {
        kind: "tool_call",
        rawType: "function_call",
        title: "shell_command",
        toolName: "shell_command",
        callId: "call_1",
        summary: "Get-ChildItem -Force",
        source: "native",
        payload: {
          arguments: {
            command: "Get-ChildItem -Force",
          },
        },
      },
    ]);
    expect(message.text).toBe("目录已读取完成。");
    expect(message.elapsedSeconds).toBe(4);
    expect(message.meta?.summaryKind).toBe("final");
    expect(message.meta?.completionState).toBe("completed");
    expect(message.meta?.nativeSource).toEqual({
      provider: "codex",
      sessionId: "thread-1",
    });
    expect(message.meta?.trace).toEqual([
      {
        kind: "commentary",
        rawType: "agent_message",
        summary: "我先检查目录结构。",
        source: "native",
      },
      {
        kind: "tool_call",
        rawType: "function_call",
        title: "shell_command",
        toolName: "shell_command",
        callId: "call_1",
        summary: "Get-ChildItem -Force",
        source: "native",
        payload: {
          arguments: {
            command: "Get-ChildItem -Force",
          },
        },
      },
    ]);
  });

  test("sendMessage posts task options for assistant proposal patch handoff", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: done\ndata: {\"output\":\"patch 已生成\",\"elapsed_seconds\":4}\n\n"));
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    await client.sendMessage(
      "assistant1",
      "为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch",
      () => undefined,
      undefined,
      undefined,
      {
        taskMode: "proposal_patch",
        taskPayload: {
          proposalId: "pr_sync_memory_index",
          targetAlias: "main",
          regenerate: false,
        },
        visibleText: "为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch",
      },
    );

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/assistant1/chat/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          message: "为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch",
          task_mode: "proposal_patch",
          task_payload: {
            proposalId: "pr_sync_memory_index",
            targetAlias: "main",
            regenerate: false,
          },
          visible_text: "为已批准 proposal《补 memory index 审计》在目标工程 main 生成 patch",
        }),
      }),
    );
  });

  test("getGitOverview maps git workspace payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            repo_found: true,
            can_init: false,
            working_dir: "C:\\workspace\\repo",
            repo_path: "C:\\workspace\\repo",
            repo_name: "repo",
            current_branch: "main",
            is_clean: false,
            ahead_count: 1,
            behind_count: 0,
            changed_files: [
              {
                path: "tracked.txt",
                status: "M ",
                staged: true,
                unstaged: false,
                untracked: false,
              },
            ],
            recent_commits: [
              {
                hash: "abcdef",
                short_hash: "abcdef",
                author_name: "Web Bot",
                authored_at: "2026-04-09 21:00:00 +0800",
                subject: "feat: initial commit",
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const overview = await client.getGitOverview("main");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/git",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(overview.repoFound).toBe(true);
    expect(overview.currentBranch).toBe("main");
    expect(overview.changedFiles[0].path).toBe("tracked.txt");
  });

  test("getGitTreeStatus maps git tree payload", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            repo_found: true,
            working_dir: "C:\\workspace\\repo",
            repo_path: "C:\\workspace\\repo",
            items: {
              "src/app.ts": "modified",
              "new.ts": "added",
              "dist": "ignored",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const status = await client.getGitTreeStatus("main");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/git/tree-status",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(status).toEqual({
      repoFound: true,
      workingDir: "C:\\workspace\\repo",
      repoPath: "C:\\workspace\\repo",
      items: {
        "src/app.ts": "modified",
        "new.ts": "added",
        "dist": "ignored",
      },
    });
  });

  test("git workflow client maps branches stashes and blame", async () => {
    const rawOverview = {
      repo_found: true,
      can_init: false,
      working_dir: "C:\\workspace\\repo",
      repo_path: "C:\\workspace\\repo",
      repo_name: "repo",
      current_branch: "main",
      is_clean: false,
      ahead_count: 0,
      behind_count: 0,
      changed_files: [],
      recent_commits: [],
    };

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { user_id: 1001 } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_branch: "main",
            branches: [{ name: "main", current: true, upstream: "origin/main", short_hash: "abc1234", subject: "init" }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_branch: "main",
            branches: [{ name: "feature/new", current: false, upstream: "", short_hash: "abc1234", subject: "created" }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_branch: "feature/new",
            branches: [{ name: "feature/new", current: true, upstream: "", short_hash: "abc1234", subject: "created" }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [{ ref: "stash@{0}", hash: "abc1234", created_at: "2026-04-28", message: "On main: stash" }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { message: "已应用 stash", overview: rawOverview } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { message: "已删除 stash", overview: rawOverview } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            path: "tracked.txt",
            lines: [
              {
                line: 1,
                commit: "abcdef",
                short_commit: "abcdef0",
                author_name: "Web Bot",
                author_mail: "web@example.com",
                authored_at: "2026-04-28",
                summary: "init",
                content: "line",
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");

    await expect(client.listGitBranches("main")).resolves.toMatchObject({ currentBranch: "main" });
    await expect(client.createGitBranch("main", "feature/new", "")).resolves.toMatchObject({ branches: [{ name: "feature/new" }] });
    await expect(client.switchGitBranch("main", "feature/new")).resolves.toMatchObject({ currentBranch: "feature/new" });
    await expect(client.listGitStashes("main")).resolves.toMatchObject({ items: [{ ref: "stash@{0}" }] });
    await expect(client.applyGitStash("main", "stash@{0}")).resolves.toMatchObject({ message: "已应用 stash" });
    await expect(client.dropGitStash("main", "stash@{0}")).resolves.toMatchObject({ message: "已删除 stash" });
    await expect(client.getGitBlame("main", "tracked.txt")).resolves.toMatchObject({
      path: "tracked.txt",
      lines: [{ line: 1, authorName: "Web Bot" }],
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/bots/main/git/branches/switch",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/git/blame?path=tracked.txt",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer secret-token" }),
      }),
    );
  });

  test("git identity config maps payload and saves scoped identity", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, data: { user_id: 1001 } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            repo_found: true,
            repo_path: "C:\\workspace\\repo",
            global: { name: "Global User", email: "global@example.com" },
            local: { name: "Local User", email: "local@example.com" },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            repo_found: true,
            repo_path: "C:\\workspace\\repo",
            global: { name: "Global User", email: "global@example.com" },
            local: { name: "Saved User", email: "saved@example.com" },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const config = await client.getGitIdentityConfig("main");
    const saved = await client.updateGitIdentityConfig("main", {
      scope: "local",
      name: "Saved User",
      email: "saved@example.com",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/git/identity",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer secret-token" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/bots/main/git/identity",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          scope: "local",
          name: "Saved User",
          email: "saved@example.com",
        }),
      }),
    );
    expect(config.global.email).toBe("global@example.com");
    expect(config.local.name).toBe("Local User");
    expect(saved.local.email).toBe("saved@example.com");
  });

  test("assistant proposal endpoints map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                id: "pr_1",
                kind: "code",
                title: "补审计",
                body: "- body",
                status: "proposed",
                created_at: "2026-04-28T00:00:00Z",
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                alias: "target1",
                working_dir: "C:\\workspace\\target1",
                repo_root: "C:\\workspace\\target1",
                head: "deadbeef",
                dirty: false,
                dirty_paths: [],
                bot_mode: "cli",
                cli_type: "codex",
                cli_path: "codex",
                available: true,
                reason: "",
              },
            ],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            proposal: {
              id: "pr_1",
              kind: "code",
              title: "补审计",
              body: "- body",
              status: "approved",
              created_at: "2026-04-28T00:00:00Z",
            },
            diff: {
              available: true,
              source: "upgrades/pending/pr_1.patch",
              text: "diff --git",
            },
            apply: {
              available: false,
              applied: false,
              last_error: "",
              last_error_at: "",
              last_error_log_path: "",
            },
            upgrade: {
              state: "pending",
              target_alias: "target1",
              target_repo_root: "C:\\workspace\\target1",
              base_commit: "deadbeef",
              patch_source: "upgrades/pending/pr_1.patch",
              generation_status: "succeeded",
              sensitive_hits: [],
              can_generate: true,
              can_approve_patch: true,
              can_dry_run: false,
              can_apply: false,
            },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            id: "pr_1",
            proposal_id: "pr_1",
            state: "pending",
            target_alias: "target1",
            target_working_dir: "C:\\workspace\\target1",
            target_repo_root: "C:\\workspace\\target1",
            base_commit: "deadbeef",
            worktree_path: "C:\\workspace\\.assistant\\upgrades\\worktrees\\pr_1",
            patch_path: "upgrades/pending/pr_1.patch",
            generated_at: "2026-04-28T01:00:00Z",
            generated_by: "1001",
            generator: {
              cli_type: "codex",
              cli_path: "codex",
              status: "succeeded",
              elapsed_seconds: 3,
            },
            dry_run: {
              ok: false,
              checked_at: "",
              stderr: "",
            },
            sensitive_hits: [],
            changed_files: ["bot/x.py"],
            additions: 3,
            deletions: 1,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            id: "pr_1",
            proposal_id: "pr_1",
            state: "approved",
            target_alias: "target1",
            target_working_dir: "C:\\workspace\\target1",
            target_repo_root: "C:\\workspace\\target1",
            base_commit: "deadbeef",
            worktree_path: "C:\\workspace\\.assistant\\upgrades\\worktrees\\pr_1",
            patch_path: "upgrades/approved/pr_1.patch",
            generated_at: "2026-04-28T01:00:00Z",
            generated_by: "1001",
            approved_by: "1001",
            approved_at: "2026-04-28T01:10:00Z",
            generator: {
              cli_type: "codex",
              cli_path: "codex",
              status: "succeeded",
              elapsed_seconds: 3,
            },
            dry_run: {
              ok: false,
              checked_at: "",
              stderr: "",
            },
            sensitive_hits: [],
            changed_files: ["bot/x.py"],
            additions: 3,
            deletions: 1,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            proposal: {
              id: "pr_1",
              kind: "code",
              title: "补审计",
              body: "- body",
              status: "approved",
              created_at: "2026-04-28T00:00:00Z",
            },
            diff: {
              available: true,
              source: "upgrades/approved/pr_1.patch",
              text: "diff --git",
            },
            apply: {
              available: true,
              applied: false,
              last_error: "",
              last_error_at: "",
              last_error_log_path: "",
            },
            upgrade: {
              state: "approved",
              target_alias: "target1",
              target_repo_root: "C:\\workspace\\target1",
              base_commit: "deadbeef",
              patch_source: "upgrades/approved/pr_1.patch",
              generation_status: "succeeded",
              sensitive_hits: [],
              dry_run: {
                ok: true,
                checked_at: "2026-04-28T01:12:00Z",
                stdout: "Patch cleanly applies",
                stderr: "",
                patch_path: "upgrades/approved/pr_1.patch",
                repo_root: "C:\\workspace\\target1",
              },
              can_generate: true,
              can_approve_patch: false,
              can_dry_run: true,
              can_apply: true,
            },
            generation_log: {
              available: true,
              source: "upgrades/logs/pr_1.generate.jsonl",
              items: [
                {
                  event: "failed",
                  created_at: "2026-04-28T01:00:00Z",
                  code: "TimeoutExpired",
                  error: "timed out",
                },
              ],
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const proposals = await client.listAssistantProposals("assistant1", "proposed");
    const targets = await client.listAssistantUpgradeTargets("assistant1");
    const pendingDetail = await client.getAssistantProposal("assistant1", "pr_1");
    const pendingPatch = await client.generateAssistantProposalPatch("assistant1", "pr_1", {
      targetAlias: "target1",
      regenerate: true,
    });
    const approvedPatch = await client.approveAssistantProposalPatch("assistant1", "pr_1");
    const detail = await client.getAssistantProposal("assistant1", "pr_1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/bots/assistant1/assistant/proposals?status=proposed",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/admin/bots/assistant1/assistant/upgrade-targets",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1/patch",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          target_alias: "target1",
          regenerate: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1/patch/approve",
      expect.objectContaining({
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      "/api/admin/bots/assistant1/assistant/proposals/pr_1",
      expect.any(Object),
    );
    expect(proposals[0]).toEqual(expect.objectContaining({
      id: "pr_1",
      title: "补审计",
      status: "proposed",
    }));
    expect(targets[0]).toEqual(expect.objectContaining({
      alias: "target1",
      repoRoot: "C:\\workspace\\target1",
      available: true,
      dirtyPaths: [],
    }));
    expect(pendingDetail.upgrade.state).toBe("pending");
    expect(pendingPatch.targetAlias).toBe("target1");
    expect(approvedPatch.approvedBy).toBe("1001");
    expect(detail.diff.available).toBe(true);
    expect(detail.apply.available).toBe(true);
    expect(detail.upgrade.canDryRun).toBe(true);
    expect(detail.upgrade.dryRun.stdout).toBe("Patch cleanly applies");
    expect(detail.generationLog.items[0]).toEqual(expect.objectContaining({
      event: "failed",
      code: "TimeoutExpired",
      error: "timed out",
    }));
  });

  test("assistant patch stream forwards status trace log and returns metadata", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            "event: status\ndata: {\"phase\":\"setup\",\"message\":\"准备生成\",\"lifecycle\":\"running\"}\n\n",
          ),
        );
        controller.enqueue(
          encoder.encode(
            "event: log\ndata: {\"text\":\"开始生成 patch\"}\n\n",
          ),
        );
        controller.enqueue(
          encoder.encode(
            "event: trace\ndata: {\"event\":{\"kind\":\"tool_call\",\"summary\":\"git worktree add\",\"tool_name\":\"git\",\"call_id\":\"call_git_add\"}}\n\n",
          ),
        );
        controller.enqueue(
          encoder.encode(
            "event: trace\ndata: {\"event\":{\"kind\":\"tool_result\",\"summary\":\"Exit code: 0\\nWall time: 1s\",\"tool_name\":\"git\",\"call_id\":\"call_git_add\"}}\n\n",
          ),
        );
        controller.enqueue(
          encoder.encode(
            "event: done\ndata: {\"metadata\":{\"id\":\"pr_1\",\"proposal_id\":\"pr_1\",\"state\":\"pending\",\"lifecycle\":\"pending\",\"target_alias\":\"target1\",\"target_working_dir\":\"C:\\\\workspace\\\\target1\",\"target_repo_root\":\"C:\\\\workspace\\\\target1\",\"base_commit\":\"deadbeef\",\"worktree_path\":\"C:\\\\workspace\\\\.assistant\\\\upgrades\\\\worktrees\\\\pr_1\",\"patch_path\":\"upgrades/pending/pr_1.patch\",\"generated_at\":\"2026-04-30T01:00:00Z\",\"generated_by\":\"1001\",\"generator\":{\"cli_type\":\"codex\",\"cli_path\":\"codex\",\"status\":\"succeeded\",\"elapsed_seconds\":3},\"dry_run\":{\"ok\":false,\"checked_at\":\"\",\"stderr\":\"\"},\"sensitive_hits\":[],\"changed_files\":[\"bot/x.py\"],\"additions\":3,\"deletions\":1}}\n\n",
          ),
        );
        controller.close();
      },
    });

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        body: stream,
        json: async () => ({
          ok: true,
          data: {},
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const statuses: Array<{ phase?: string; message?: string; lifecycle?: string }> = [];
    const logs: string[] = [];
    const traces: Array<{ kind: string; summary: string }> = [];

    const result = await client.generateAssistantProposalPatchStream(
      "assistant1",
      "pr_1",
      { targetAlias: "target1", regenerate: true },
      {
        onStatus: (event) => statuses.push(event),
        onLog: (text) => logs.push(text),
        onTrace: (event) => traces.push({ kind: event.kind, summary: event.summary }),
      },
    );

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots/assistant1/assistant/proposals/pr_1/patch/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          target_alias: "target1",
          regenerate: true,
        }),
      }),
    );
    expect(statuses).toEqual([{ phase: "setup", message: "准备生成", lifecycle: "running" }]);
    expect(logs).toEqual(["开始生成 patch"]);
    expect(traces).toEqual([
      { kind: "tool_call", summary: "git worktree add" },
      { kind: "tool_result", summary: "Exit code: 0\nWall time: 1s" },
    ]);
    expect(result.targetAlias).toBe("target1");
    expect(result.lifecycle).toBe("pending");
  });

  test("assistant diagnostics endpoint maps stage durations", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            user_id: 1001,
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [
              {
                run_id: "run_1",
                created_at: "2026-04-28T00:00:00Z",
                bot_alias: "assistant1",
                source: "web",
                task_mode: "standard",
                interactive: true,
                user_id: 1001,
                status: "completed",
                stage_durations: {
                  sync_ms: 10,
                  index_ms: 11,
                  recall_ms: 12,
                  cli_ms: 1000,
                  db_ms: 9,
                  trace_ms: 15,
                  plugin_ms: 0,
                },
                elapsed_ms: 1100,
                prompt_chars: 100,
                output_chars: 80,
                trace_count: 3,
                tool_call_count: 1,
                process_count: 1,
              },
            ],
            summary: {
              total: 1,
              success: 1,
              failed: 0,
              avg_elapsed_ms: 1100,
              p95_elapsed_ms: 1100,
              by_source: { web: 1 },
              by_status: { completed: 1 },
              slow_stages: [
                { stage: "cli", total_ms: 1000, avg_ms: 1000 },
              ],
              error_groups: [],
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const result = await client.getAssistantDiagnostics("assistant1", { limit: 5 });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots/assistant1/assistant/diagnostics/perf?limit=5",
      expect.any(Object),
    );
    expect(result.items[0].stageDurations).toEqual({
      syncMs: 10,
      indexMs: 11,
      recallMs: 12,
      cliMs: 1000,
      dbMs: 9,
      traceMs: 15,
      pluginMs: 0,
    });
    expect(result.summary.p95ElapsedMs).toBe(1100);
  });

  test("admin center user permission APIs map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [{
              account_id: "member_1",
              username: "alice",
              role: "member",
              disabled: false,
              created_at: "2026-05-12T00:00:00Z",
              allowed_bots: ["main"],
              owned_bots: ["team1"],
              owned_bot_count: 1,
              bot_create_limit: 3,
            }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            account_id: "member_1",
            allowed_bots: ["main", "sub1"],
          },
        }),
      });

    const client = new RealWebBotClient();
    const users = await client.listAdminUsers();
    const updated = await client.updateUserBotPermissions("member_1", ["main", "sub1"]);

    expect(users[0].allowedBots).toEqual(["main"]);
    expect(users[0].ownedBotCount).toBe(1);
    expect(users[0].botCreateLimit).toBe(3);
    expect(updated.allowedBots).toEqual(["main", "sub1"]);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/admin/users/member_1/permissions",
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  test("offline update APIs map payloads", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            artifacts_dir: ".release-local/artifacts",
            items: [{
              name: "offline.zip",
              path: "C:\\pkg\\offline.zip",
              version: "1.2.3",
              package_kind: "installer",
              size_bytes: 10,
              valid: true,
              error: "",
            }],
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            current_version: "1.0.0",
            current_package_kind: "installer",
            update_enabled: true,
            update_channel: "release",
            last_checked_at: "",
            latest_version: "1.2.3",
            latest_release_url: "",
            latest_notes: "",
            pending_update_version: "1.2.3",
            pending_update_path: "C:\\pkg\\offline.zip",
            pending_update_notes: "",
            pending_update_platform: "windows-x64-installer",
            pending_update_package_kind: "installer",
            last_error: "",
          },
        }),
      });

    const client = new RealWebBotClient();
    const packages = await client.listOfflineUpdatePackages();
    const status = await client.prepareOfflineUpdate("C:\\pkg\\offline.zip", "1.2.3");

    expect(packages.items[0].valid).toBe(true);
    expect(packages.items[0].sizeBytes).toBe(10);
    expect(status.pendingUpdateVersion).toBe("1.2.3");
    expect(status.pendingUpdatePath).toBe("C:\\pkg\\offline.zip");
  });

  test("maps lan chat config and sends messages", async () => {
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/admin/lan-chat/config" && init?.method === "PATCH") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            data: {
              mode: "host",
              room_name: "工作室",
              instance_id: "inst_a",
              instance_name: "A-PC",
              host_url: "",
              room_key: "tcbr_full_1234",
              room_key_preview: "tcbr...1234",
              lan_only: true,
              auto_connect: true,
            },
          }),
        };
      }
      if (url === "/api/lan-chat/conversations/group%3Adefault/messages" && init?.method === "POST") {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            data: {
              id: "msg_1",
              seq: 1,
              conversation_id: "group:default",
              kind: "group",
              sender: {
                room_user_id: "inst_a:member_1",
                account_id: "member_1",
                username: "alice",
                display_name: "alice",
                instance_id: "inst_a",
                instance_name: "A-PC",
                online: true,
                last_seen_at: "2026-05-18T12:00:00+08:00",
              },
              text: "你好",
              created_at: "2026-05-18T12:00:00+08:00",
            },
          }),
        };
      }
      return {
        ok: false,
        status: 404,
        json: async () => ({ ok: false, error: { code: "missing", message: "missing" } }),
      };
    });

    const client = new RealWebBotClient();
    const config = await client.updateLanChatConfig({ mode: "host", roomName: "工作室", instanceName: "A-PC" });
    const message = await client.sendLanChatMessage("group:default", "你好");

    expect(config.roomName).toBe("工作室");
    expect(config.instanceName).toBe("A-PC");
    expect(config.roomKey).toBe("tcbr_full_1234");
    expect(message.conversationId).toBe("group:default");
    expect(message.text).toBe("你好");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/lan-chat/config",
      expect.objectContaining({
        body: JSON.stringify({ mode: "host", room_name: "工作室", instance_name: "A-PC" }),
      }),
    );
  });

  test("lan chat socket includes current auth token", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          token: "web_sess_lan",
          username: "alice",
          role: "member",
          capabilities: ["view_chat_history"],
        },
      }),
    });
    const sockets: Array<{ url: string; close: () => void; addEventListener: () => void }> = [];
    class MockSocket {
      url: string;

      constructor(url: string) {
        this.url = url;
        sockets.push(this);
      }

      addEventListener() {}
      close() {}
    }
    vi.stubGlobal("WebSocket", MockSocket);
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { protocol: "http:", host: "127.0.0.1:8765" },
    });

    try {
      const client = new RealWebBotClient();
      await client.loginGuest();
      const close = client.openLanChatSocket(vi.fn());
      close();

      expect(sockets[0].url).toBe("ws://127.0.0.1:8765/lan-chat/ws?token=web_sess_lan");
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });
});
