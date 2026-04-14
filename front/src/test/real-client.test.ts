import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";

describe("RealWebBotClient", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
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
              cli_type: "kimi",
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

    expect(bots).toEqual([
      {
        alias: "main",
        cliType: "kimi",
        status: "busy",
        workingDir: "C:\\workspace\\demo",
        lastActiveText: "处理中",
        avatarName: "bot-default.png",
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

  test("createDirectory posts to the mkdir endpoint", async () => {
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
            name: "docs",
            created_path: "C:\\workspace\\demo\\docs",
          },
        }),
      });

    const client = new RealWebBotClient() as RealWebBotClient & {
      createDirectory: (botAlias: string, name: string) => Promise<void>;
    };
    await client.login("secret-token");
    await client.createDirectory("main", "docs");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/files/mkdir",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ name: "docs" }),
      }),
    );
  });

  test("deletePath posts to the delete endpoint", async () => {
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
            path: "docs",
            deleted_type: "directory",
          },
        }),
      });

    const client = new RealWebBotClient() as RealWebBotClient & {
      deletePath: (botAlias: string, path: string) => Promise<void>;
    };
    await client.login("secret-token");
    await client.deletePath("main", "docs");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/files/delete",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ path: "docs" }),
      }),
    );
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

  test("updateBotWorkdir patches admin workdir endpoint", async () => {
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
              is_processing: false,
              working_dir: "C:\\workspace\\next",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bot = await client.updateBotWorkdir("main", "C:\\workspace\\next");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots/main/workdir",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ working_dir: "C:\\workspace\\next" }),
      }),
    );
    expect(bot).toEqual({
      alias: "main",
      cliType: "codex",
      status: "running",
      workingDir: "C:\\workspace\\next",
      lastActiveText: "运行中",
      avatarName: "bot-default.png",
    });
  });

  test("updateBotCli patches admin cli endpoint", async () => {
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
              cli_type: "claude",
              cli_path: "claude.cmd",
              status: "running",
              is_processing: false,
              working_dir: "C:\\workspace\\demo",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bot = await client.updateBotCli("main", "claude", "claude.cmd");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots/main/cli",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ cli_type: "claude", cli_path: "claude.cmd" }),
      }),
    );
    expect(bot).toEqual({
      alias: "main",
      cliType: "claude",
      status: "running",
      workingDir: "C:\\workspace\\demo",
      lastActiveText: "运行中",
      cliPath: "claude.cmd",
      avatarName: "bot-default.png",
    });
  });

  test("addBot posts admin bots endpoint", async () => {
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
              alias: "team3",
              cli_type: "codex",
              cli_path: "codex",
              bot_mode: "cli",
              status: "running",
              is_processing: false,
              working_dir: "C:\\workspace\\team3",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bot = await client.addBot({
      alias: "team3",
      token: "333:abc",
      botMode: "cli",
      cliType: "codex",
      cliPath: "codex",
      workingDir: "C:\\workspace\\team3",
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          alias: "team3",
          token: "333:abc",
          bot_mode: "cli",
          cli_type: "codex",
          cli_path: "codex",
          working_dir: "C:\\workspace\\team3",
        }),
      }),
    );
    expect(bot.alias).toBe("team3");
    expect(bot.cliType).toBe("codex");
  });

  test("renameBot patches admin alias endpoint", async () => {
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
              alias: "planner",
              cli_type: "claude",
              cli_path: "claude",
              status: "running",
              is_processing: false,
              working_dir: "C:\\workspace\\plans",
            },
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const bot = await client.renameBot("team2", "planner");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots/team2/alias",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ new_alias: "planner" }),
      }),
    );
    expect(bot.alias).toBe("planner");
  });

  test("removeBot deletes admin bot endpoint", async () => {
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
            removed: true,
            alias: "team2",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    await client.removeBot("team2");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/bots/team2",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });

  test("restartService posts to admin restart endpoint", async () => {
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
            restart_requested: true,
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    await client.restartService();

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
    expect(settings).toEqual({ port: "7897" });
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
            port: "",
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const settings = await client.updateGitProxySettings("");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/git-proxy",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ port: "" }),
      }),
    );
    expect(settings).toEqual({ port: "" });
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
    expect(content).toBe("full file content");
  });

  test("listSystemScripts returns available admin scripts", async () => {
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
                script_name: "network_traffic",
                display_name: "网络流量",
                description: "查看网络状态",
                path: "C:\\scripts\\network_traffic.ps1",
              },
            ],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const scripts = await client.listSystemScripts();

    expect(scripts).toEqual([
      {
        scriptName: "network_traffic",
        displayName: "网络流量",
        description: "查看网络状态",
        path: "C:\\scripts\\network_traffic.ps1",
      },
    ]);
  });

  test("runSystemScriptStream forwards log events and returns final result", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode("event: log\ndata: {\"text\":\"npm run build\"}\n\n"));
        controller.enqueue(encoder.encode("event: log\ndata: {\"text\":\"vite build finished\"}\n\n"));
        controller.enqueue(encoder.encode("event: done\ndata: {\"script_name\":\"build_web_frontend\",\"success\":true,\"output\":\"Web 前端构建完成\"}\n\n"));
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

    const logs: string[] = [];
    const result = await client.runSystemScriptStream("build_web_frontend", (line) => {
      logs.push(line);
    });

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/scripts/run/stream",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ script_name: "build_web_frontend" }),
      }),
    );
    expect(logs).toEqual(["npm run build", "vite build finished"]);
    expect(result).toEqual({
      scriptName: "build_web_frontend",
      success: true,
      output: "Web 前端构建完成",
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

  test("restartTunnel posts to admin tunnel restart endpoint", async () => {
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
            mode: "cloudflare_quick",
            status: "running",
            source: "quick_tunnel",
            public_url: "https://fresh.trycloudflare.com",
            local_url: "http://127.0.0.1:8765",
            last_error: "",
            pid: 1234,
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    const snapshot = await client.restartTunnel();

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/admin/tunnel/restart",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
    expect(snapshot).toEqual({
      mode: "cloudflare_quick",
      status: "running",
      source: "quick_tunnel",
      publicUrl: "https://fresh.trycloudflare.com",
      localUrl: "http://127.0.0.1:8765",
      lastError: "",
      pid: 1234,
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

  test("initGitRepository posts to the init endpoint", async () => {
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
            is_clean: true,
            ahead_count: 0,
            behind_count: 0,
            changed_files: [],
            recent_commits: [],
          },
        }),
      });

    const client = new RealWebBotClient();
    await client.login("secret-token");
    await client.initGitRepository("main");

    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/bots/main/git/init",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer secret-token",
        }),
      }),
    );
  });
});
