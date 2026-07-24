import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
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

  test("映射外部源码位置的 targetType/sourceId，并读取只读源码快照", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonOk({
        request_id: "external-nav",
        message: "",
        items: {
          target_type: "external",
          display_path: "依赖 / stdlib / pathlib.py",
          source_id: "src_external_1",
          provider: "pyright",
          range: {
            start: { line: 10, column: 1 },
            end: { line: 12, column: 8 },
          },
          selection_range: {
            start: { line: 11, column: 5 },
            end: { line: 11, column: 12 },
          },
        },
      }))
      .mockResolvedValueOnce(jsonOk({
        source_id: "src_external_1",
        display_path: "依赖 / stdlib / pathlib.py",
        content: "class Path:\n    pass\n",
        encoding: "utf-8",
        language_id: "python",
        file_size_bytes: 22,
        last_modified_ns: 123,
        target_type: "external",
        read_only: true,
      }));

    const client = new RealWebBotClient();
    const navigation = await client.resolveCodeNavigation("main", request);
    const source = await client.readExternalSource("main", "src_external_1");

    expect(navigation).toEqual({
      requestId: "external-nav",
      message: "",
      items: [{
        targetType: "external",
        path: "依赖 / stdlib / pathlib.py",
        displayPath: "依赖 / stdlib / pathlib.py",
        sourceId: "src_external_1",
        provider: "pyright",
        range: {
          start: { line: 10, column: 1 },
          end: { line: 12, column: 8 },
        },
        selectionRange: {
          start: { line: 11, column: 5 },
          end: { line: 11, column: 12 },
        },
      }],
    });
    expect(source).toEqual({
      sourceId: "src_external_1",
      displayPath: "依赖 / stdlib / pathlib.py",
      content: "class Path:\n    pass\n",
      encoding: "utf-8",
      languageId: "python",
      fileSizeBytes: 22,
      lastModifiedNs: "123",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/bots/main/workspace/external-sources/src_external_1",
      expect.objectContaining({ cache: "no-store" }),
    );
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

  test("mock 客户端提供外部源码快照和可识别的失效错误", async () => {
    const client = new MockWebBotClient();
    await expect(client.readExternalSource("main", "mock-external-source")).resolves.toMatchObject({
      sourceId: "mock-external-source",
      displayPath: "依赖 / stdlib / example.py",
      content: expect.stringContaining("external_example"),
    });
    await expect(client.readExternalSource("main", "expired")).rejects.toMatchObject({
      code: "external_source_expired",
      status: 410,
    });
  });
});
