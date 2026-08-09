import { act, renderHook } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import {
  useCodeNavigationHistory,
  type CodeNavigationHistoryLocation,
} from "../workbench/useCodeNavigationHistory";

function location(path: string, line = 1, column = 1): CodeNavigationHistoryLocation {
  return { path, line, column };
}

test("navigation history moves backward and forward through semantic jumps", async () => {
  const onNavigate = vi.fn(async () => true);
  const { result } = renderHook(() => useCodeNavigationHistory({ scopeKey: "main:root-a", onNavigate }));
  const a = location("a.py", 1, 2);
  const b = location("b.py", 3, 4);
  const c = location("c.py", 5, 6);

  act(() => {
    result.current.recordNavigation(a, b);
    result.current.recordNavigation(b, c);
  });
  await act(async () => expect(await result.current.goBack()).toBe(true));
  expect(onNavigate).toHaveBeenLastCalledWith(b);
  expect(result.current.forwardStack).toEqual([c]);

  await act(async () => expect(await result.current.goForward()).toBe(true));
  expect(onNavigate).toHaveBeenLastCalledWith(c);
  expect(result.current.forwardStack).toEqual([]);
});

test("a repeated jump is deduplicated and bounded", () => {
  const { result } = renderHook(() => useCodeNavigationHistory({
    scopeKey: "main:root-a",
    onNavigate: async () => true,
  }));
  const a = location("same.py");
  const b = location("target.py", 2, 2);

  act(() => {
    result.current.recordNavigation(a, b);
    result.current.recordNavigation(a, b);
  });
  expect(result.current.backStack).toEqual([a]);
});
