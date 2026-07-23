import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { useLanguageServerStatus } from "../workbench/useLanguageServerStatus";

afterEach(() => {
  vi.useRealTimers();
});

test("language service status does not reload when switching between files of the same provider", async () => {
  const client = new MockWebBotClient();
  const getCatalog = vi.spyOn(client, "getLanguageServerCatalog");
  const install = vi.spyOn(client, "installLanguageServer");
  const { result, rerender } = renderHook(
    ({ path }) => useLanguageServerStatus(client, "main", path),
    { initialProps: { path: "src/main.py" } },
  );

  await waitFor(() => expect(result.current.status?.provider).toBe("pyright"));
  expect(getCatalog).toHaveBeenCalledTimes(1);
  expect(getCatalog).toHaveBeenCalledWith("main", "pyright");

  rerender({ path: "src/types.pyi" });

  expect(result.current.status?.provider).toBe("pyright");
  expect(getCatalog).toHaveBeenCalledTimes(1);
  expect(install).not.toHaveBeenCalled();
});

test("language service status polls while indexing and stops after ready", async () => {
  vi.useFakeTimers();
  const client = new MockWebBotClient();
  const baseStatus = {
    provider: "pyright" as const,
    status: "available" as const,
    source: "path" as const,
    version: "1.1.410",
    commandSummary: "pyright-langserver --stdio",
    canInstall: false,
    canUpdate: false,
    message: "使用 PATH 中的命令",
    error: "",
  };
  const getCatalog = vi.spyOn(client, "getLanguageServerCatalog")
    .mockResolvedValueOnce({
      canRefresh: true,
      providers: [{ ...baseStatus, runtimeState: "indexing" }],
    })
    .mockResolvedValueOnce({
      canRefresh: true,
      providers: [{ ...baseStatus, runtimeState: "ready" }],
    });

  const { result } = renderHook(() => useLanguageServerStatus(client, "main", "src/main.py"));
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(result.current.status?.runtimeState).toBe("indexing");
  expect(getCatalog).toHaveBeenCalledTimes(1);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(result.current.status?.runtimeState).toBe("ready");
  expect(getCatalog).toHaveBeenCalledTimes(2);

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(getCatalog).toHaveBeenCalledTimes(2);
});
