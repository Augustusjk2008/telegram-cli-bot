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

  it("coalesces 1000 synchronous items into one consumer call", () => {
    const consumed = vi.fn();
    let callback: FrameRequestCallback | undefined;
    const requestAnimationFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((next) => {
      callback = next;
      return 3;
    });
    const { result } = renderHook(() => useFrameBatchedQueue(consumed));
    act(() => {
      for (let index = 0; index < 1_000; index += 1) {
        result.current.enqueue(index);
      }
    });
    act(() => callback?.(0));
    expect(consumed).toHaveBeenCalledTimes(1);
    expect(consumed.mock.calls[0]?.[0]).toHaveLength(1_000);
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

  it("consumes immediately when batching is disabled", () => {
    const consumed = vi.fn();
    const requestAnimationFrame = vi.spyOn(window, "requestAnimationFrame");
    const { result } = renderHook(() => useFrameBatchedQueue(consumed, false));

    act(() => {
      result.current.enqueue("a");
      result.current.enqueue("b");
    });

    expect(consumed.mock.calls).toEqual([[["a"]], [["b"]]]);
    expect(requestAnimationFrame).not.toHaveBeenCalled();
    requestAnimationFrame.mockRestore();
  });
});
