import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { RealWebBotClient } from "../services/realWebBotClient";

const request = {
  kind: "definition" as const,
  requestId: "nav-request",
  document: {
    path: "main.py",
    languageId: "python",
    version: 1,
    content: "greet()\n",
  },
  position: { line: 1, column: 2 },
};

function rawLocation(path: string, line: number, column: number) {
  return {
    target_type: "workspace" as const,
    path,
    provider: "python-lsp",
    range: {
      start: { line, column: 1 },
      end: { line, column: 12 },
    },
    selection_range: {
      start: { line, column },
      end: { line, column: column + 5 },
    },
  };
}

function jsonOk(data: unknown) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

describe("代码导航客户端", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  test("将单个语义位置归一化为结果数组并透传取消信号", async () => {
    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(jsonOk({
      request_id: "nav-single",
      message: "",
      items: rawLocation("pkg/service.py", 3, 5),
    }));

    const result = await new RealWebBotClient().resolveCodeNavigation("main", request, controller.signal);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/workspace/code-navigation/resolve",
      expect.objectContaining({
        method: "POST",
        signal: controller.signal,
      }),
    );
    expect(result).toEqual({
      requestId: "nav-single",
      message: "",
      items: [{
        targetType: "workspace",
        path: "pkg/service.py",
        provider: "python-lsp",
        range: {
          start: { line: 3, column: 1 },
          end: { line: 3, column: 12 },
        },
        selectionRange: {
          start: { line: 3, column: 5 },
          end: { line: 3, column: 10 },
        },
      }],
    });
  });

  test("保留多个位置，并将 null 或缺失结果视为无结果", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        request_id: "nav-multiple",
        message: "",
        items: [
          rawLocation("pkg/one.py", 3, 5),
          rawLocation("pkg/two.py", 8, 2),
        ],
      }))
      .mockResolvedValueOnce(jsonOk({
        request_id: "nav-empty-items",
        message: "未找到语义定义",
        items: null,
      }))
      .mockResolvedValueOnce(jsonOk(null));

    const client = new RealWebBotClient();
    const multiple = await client.resolveCodeNavigation("main", request);
    const nullItems = await client.resolveCodeNavigation("main", request);
    const nullResult = await client.resolveCodeNavigation("main", request);

    expect(multiple.items.map((item) => item.path)).toEqual(["pkg/one.py", "pkg/two.py"]);
    expect(nullItems).toEqual({
      requestId: "nav-empty-items",
      message: "未找到语义定义",
      items: [],
    });
    expect(nullResult).toEqual({
      requestId: request.requestId,
      message: "",
      items: [],
    });
  });

  test("调用方取消请求时保留 AbortError", async () => {
    const controller = new AbortController();
    let receivedSignal: AbortSignal | undefined;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/cancel")) {
        return Promise.resolve(jsonOk({ cancelled: true }));
      }
      receivedSignal = init?.signal ?? undefined;
      return new Promise((_resolve, reject) => {
        controller.signal.addEventListener("abort", () => {
          reject(new DOMException("请求已取消", "AbortError"));
        }, { once: true });
      });
    });

    const pending = new RealWebBotClient().resolveCodeNavigation("main", request, controller.signal);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(receivedSignal).toBe(controller.signal);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bots/main/workspace/code-navigation/cancel",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ requestId: request.requestId }),
      }),
    );
    const cancelCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/cancel"));
    expect(cancelCall?.[1]?.signal).toBeUndefined();
  });
});
