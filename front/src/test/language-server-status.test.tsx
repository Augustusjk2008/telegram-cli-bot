import { renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { useLanguageServerStatus } from "../workbench/useLanguageServerStatus";

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

  rerender({ path: "src/types.pyi" });

  expect(result.current.status?.provider).toBe("pyright");
  expect(getCatalog).toHaveBeenCalledTimes(1);
  expect(install).not.toHaveBeenCalled();
});
