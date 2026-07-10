import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useFrameBatchedQueue } from "../hooks/useFrameBatchedQueue";

describe("useFrameBatchedQueue", () => {
  it("coalesces synchronous items into one frame", () => {
    const consumed = vi.fn();
    let callback: FrameRequestCallback | undefined;
    const requestAnimationFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((next) => {
      callback = next;
      return 1;
    });
    const { result } = renderHook(() => useFrameBatchedQueue(consumed));
    act(() => {
      result.current.enqueue("a");
      result.current.enqueue("b");
    });
    act(() => callback?.(0));
    expect(consumed).toHaveBeenCalledTimes(1);
    expect(consumed).toHaveBeenLastCalledWith(["a", "b"]);
    requestAnimationFrame.mockRestore();
  });

  it("flushes pending entries and cancels the scheduled frame", () => {
    const consumed = vi.fn();
    let callback: FrameRequestCallback | undefined;
    const requestAnimationFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((next) => {
      callback = next;
      return 7;
    });
    const cancelAnimationFrame = vi.spyOn(window, "cancelAnimationFrame");
    const { result } = renderHook(() => useFrameBatchedQueue(consumed));
    act(() => result.current.enqueue("final"));
    act(() => result.current.flush());
    callback?.(0);
    expect(consumed).toHaveBeenCalledTimes(1);
    expect(consumed).toHaveBeenCalledWith(["final"]);
    expect(cancelAnimationFrame).toHaveBeenCalledWith(7);
    requestAnimationFrame.mockRestore();
    cancelAnimationFrame.mockRestore();
  });
});
