import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useChatHistorySync } from "../hooks/useChatHistorySync";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useChatHistorySync", () => {
  it("uses a short initial refresh then a lower-frequency idle interval", async () => {
    vi.useFakeTimers();
    const sync = vi.fn(async () => true);

    renderHook(() => useChatHistorySync({
      enabled: true,
      isStreaming: false,
      isSseHealthy: () => false,
      sync,
      initialDelayMs: 5_000,
      idleIntervalMs: 10_000,
    }));

    await act(async () => vi.advanceTimersByTimeAsync(4_999));
    expect(sync).not.toHaveBeenCalled();

    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(sync).toHaveBeenCalledTimes(1);

    await act(async () => vi.advanceTimersByTimeAsync(9_999));
    expect(sync).toHaveBeenCalledTimes(1);

    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(sync).toHaveBeenCalledTimes(2);
  });

  it("does not poll while a healthy SSE stream is active", async () => {
    vi.useFakeTimers();
    const sync = vi.fn(async () => true);

    renderHook(() => useChatHistorySync({
      enabled: true,
      isStreaming: true,
      isSseHealthy: () => true,
      sync,
      initialDelayMs: 5_000,
      idleIntervalMs: 10_000,
    }));

    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(sync).not.toHaveBeenCalled();
  });

  it("pauses while hidden and resumes with the initial delay", async () => {
    vi.useFakeTimers();
    let visibilityState: DocumentVisibilityState = "hidden";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibilityState);
    const sync = vi.fn(async () => true);

    renderHook(() => useChatHistorySync({
      enabled: true,
      isStreaming: false,
      isSseHealthy: () => false,
      sync,
      initialDelayMs: 5_000,
      idleIntervalMs: 10_000,
    }));

    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(sync).not.toHaveBeenCalled();

    visibilityState = "visible";
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it("uses fixed polling when incremental sync is disabled", async () => {
    vi.useFakeTimers();
    const sync = vi.fn(async () => true);

    renderHook(() => useChatHistorySync({
      enabled: true,
      isStreaming: true,
      isSseHealthy: () => true,
      sync,
      idleIntervalMs: 10_000,
      incrementalEnabled: false,
    }));

    await act(async () => vi.advanceTimersByTimeAsync(20_000));
    expect(sync).toHaveBeenCalledTimes(2);
  });
});
