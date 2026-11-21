import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CliTranscript } from "../components/CliTranscript";
import { buildCliTranscriptEntries, mergeChatTraceEvents, type CliTranscriptEntry } from "../utils/cliTranscript";
import type { ChatTraceEvent } from "../services/types";

function processEntry(
  id: string,
  summary: string,
  seq: number,
  traceKind: "commentary" | "reasoning" | "status" = "commentary",
): CliTranscriptEntry {
  return {
    id,
    seq,
    kind: "process",
    label: "过程",
    summary,
    collapsedByDefault: false,
    trace: {
      id: "trace-" + id,
      sequence: seq,
      kind: traceKind,
      summary,
      source: "codex",
    },
  };
}

function toolEntry(
  id: string,
  kind: "tool_call" | "tool_result",
  summary: string,
  seq: number,
): CliTranscriptEntry {
  const isCall = kind === "tool_call";
  return {
    id,
    seq,
    kind: isCall ? "tool" : "event",
    label: isCall ? "read" : "工具结果",
    summary,
    body: summary,
    collapsedByDefault: true,
    trace: {
      id: `trace-${id}`,
      sequence: seq,
      kind,
      summary,
      source: "deepseek",
      rawType: `deepseek_${kind}`,
      callId: "call-" + id,
      payload: { output: summary },
    },
  };
}

describe("CliTranscript", () => {

  it("collapses CLI details on mobile while keeping the current progress visible", () => {
    const entry = processEntry("cli-process", "正在检查文件", 1);
    render(
      <CliTranscript
        entries={[entry]}
        resultText=""
        state="streaming"
        traceCount={1}
        processCount={1}
        traceLoaded
        mobileLayout
      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    expect(within(transcript).getByRole("status")).toHaveTextContent("正在检查文件");
    expect(transcript.querySelector('[data-transcript-entry-id="cli-process"]')).not.toBeInTheDocument();
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    expect(transcript.querySelector('[data-transcript-entry-id="cli-process"]')).toBeInTheDocument();
  });

  it("splits DeepSeek tool events at each process boundary", () => {
    render(
      <CliTranscript
        entries={[
          processEntry("step-1", "开始步骤 1", 1, "status"),
          toolEntry("call-1", "tool_call", "读取文件 A", 2),
          toolEntry("result-1", "tool_result", "文件 A 已读取", 3),
          processEntry("step-2", "先分析文件 B", 4, "reasoning"),
          toolEntry("call-2", "tool_call", "读取文件 B", 5),
          toolEntry("result-2", "tool_result", "文件 B 已读取", 6),
        ]}
        resultText=""
        state="streaming"
        traceCount={6}
        processCount={2}
        toolCallCount={2}
        traceLoaded
      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    expect(within(transcript).getAllByTestId("cli-event-group")).toHaveLength(2);
    expect(within(transcript).getAllByText("过程 1")).toHaveLength(1);
    expect(within(transcript).getAllByText("过程 2")).toHaveLength(1);
  });

  it("keeps endless errors and Continue records collapsed", () => {
    const entries: CliTranscriptEntry[] = [
      {
        id: "endless-error-1",
        seq: 1,
        kind: "endless_error",
        label: "错误",
        summary: "临时失败",
        collapsedByDefault: true,
      },
      {
        id: "endless-continue-1",
        seq: 2,
        kind: "endless_continue",
        label: "Continue",
        summary: "Continue",
        collapsedByDefault: true,
      },
    ];

    render(
      <CliTranscript
        entries={entries}
        resultText="最终回答"
        state="done"
      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    expect(within(transcript).getByRole("button", { name: "展开过程详情" })).toHaveAttribute("aria-expanded", "false");
    expect(within(transcript).queryByText("临时失败")).not.toBeInTheDocument();

    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const retryGroup = within(transcript).getByTestId("cli-retry-group");
    expect(retryGroup.querySelector("summary")).toBeTruthy();
    expect(within(retryGroup).queryByText("临时失败")).not.toBeInTheDocument();
    fireEvent.click(retryGroup.querySelector("summary") as HTMLElement);
    expect(within(transcript).getByText("临时失败")).toBeInTheDocument();
  });

  it("aggregates adjacent endless retries across attempts", () => {
    const entries: CliTranscriptEntry[] = [
      {
        id: "endless-error-1",
        seq: 1,
        kind: "endless_error",
        label: "错误",
        summary: "第一次失败",
        attempt: 1,
        collapsedByDefault: true,
      },
      {
        id: "endless-continue-1",
        seq: 2,
        kind: "endless_continue",
        label: "Continue",
        summary: "Continue 1",
        attempt: 1,
        collapsedByDefault: true,
      },
      {
        id: "endless-error-2",
        seq: 3,
        kind: "endless_error",
        label: "错误",
        summary: "第二次失败",
        attempt: 2,
        collapsedByDefault: true,
      },
      {
        id: "endless-continue-2",
        seq: 4,
        kind: "endless_continue",
        label: "Continue",
        summary: "Continue 2",
        attempt: 2,
        collapsedByDefault: true,
      },
    ];

    render(
      <CliTranscript
        entries={entries}
        resultText="最终回答"
        state="done"
      />,
    );

    const transcript = screen.getByTestId("cli-transcript");
    fireEvent.click(within(transcript).getByRole("button", { name: "展开过程详情" }));
    const retryGroups = within(transcript).getAllByTestId("cli-retry-group");
    expect(retryGroups).toHaveLength(1);
    expect(within(retryGroups[0]).getByText("连续重试")).toBeInTheDocument();

    fireEvent.click(retryGroups[0].querySelector("summary") as HTMLElement);
    expect(within(retryGroups[0]).getByText("第一次失败")).toBeInTheDocument();
    expect(within(retryGroups[0]).getByText("第二次失败")).toBeInTheDocument();
  });

});

describe("CliTranscript with capped trace previews", () => {
  const previewTrace: ChatTraceEvent = {
    id: "trace-result",
    kind: "tool_result",
    summary: "输出开头",
    callId: "call-1",
    payload: { output: "输出开头" },
    payloadChars: 90_000,
    summaryChars: 80_000,
  };
  const fullTrace: ChatTraceEvent = {
    id: "trace-result",
    kind: "tool_result",
    summary: "输出开头……完整摘要",
    callId: "call-1",
    payload: { output: "输出开头……完整输出" },
  };
  const entries = () => buildCliTranscriptEntries({ trace: [previewTrace] });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the preview at once and swaps in the full payload when the entry is opened", async () => {
    const loadDetail = vi.fn(async () => fullTrace);
    render(
      <CliTranscript entries={entries()} resultText="" state="streaming" traceLoaded onLoadTraceEventDetail={loadDetail} />,
    );
    const transcript = screen.getByTestId("cli-transcript");
    // Nothing is fetched while the entry stays collapsed.
    expect(loadDetail).not.toHaveBeenCalled();

    const row = transcript.querySelector("details") as HTMLDetailsElement;
    row.open = true;
    fireEvent(row, new Event("toggle"));

    expect(row.querySelector("pre")).toHaveTextContent("输出开头");
    await waitFor(() => expect(row.querySelector("pre")).toHaveTextContent("输出开头……完整输出"));
    expect(loadDetail).toHaveBeenCalledTimes(1);
    expect(loadDetail).toHaveBeenCalledWith(expect.objectContaining({ id: "trace-result", callId: "call-1" }));

    // Closing and reopening reuses the loaded payload.
    row.open = false;
    fireEvent(row, new Event("toggle"));
    row.open = true;
    fireEvent(row, new Event("toggle"));
    expect(row.querySelector("pre")).toHaveTextContent("输出开头……完整输出");
    expect(loadDetail).toHaveBeenCalledTimes(1);
  });

  it("keeps the preview and offers a retry when the full payload cannot be read", async () => {
    const loadDetail = vi.fn<(trace: ChatTraceEvent) => Promise<ChatTraceEvent | null>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(fullTrace);
    render(
      <CliTranscript entries={entries()} resultText="" state="streaming" traceLoaded onLoadTraceEventDetail={loadDetail} />,
    );
    const row = screen.getByTestId("cli-transcript").querySelector("details") as HTMLDetailsElement;
    row.open = true;
    fireEvent(row, new Event("toggle"));

    await screen.findByText("完整内容加载失败");
    expect(row.querySelector("pre")).toHaveTextContent("输出开头");
    fireEvent.click(within(row).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(row.querySelector("pre")).toHaveTextContent("输出开头……完整输出"));
    expect(screen.queryByText("完整内容加载失败")).not.toBeInTheDocument();
  });

  it("copies the complete transcript by reading the full trace first", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const loadFullTrace = vi.fn(async () => [fullTrace]);
    render(
      <CliTranscript
        entries={entries()}
        resultText="最终回答"
        state="done"
        traceLoaded
        onCopyFinalAnswer={() => true}
        onLoadFullTrace={loadFullTrace}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "复制完整回答" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(loadFullTrace).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(
      "[工具结果] 输出开头……完整摘要\n输出开头……完整输出\n\n[最终回答]\n最终回答",
    );
  });

  it("does not copy a cut-off transcript when the full trace cannot be read", async () => {
    const writeText = vi.fn(async (_text: string) => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const loadFullTrace = vi.fn<() => Promise<ChatTraceEvent[] | null>>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([fullTrace]);
    render(
      <CliTranscript
        entries={entries()}
        resultText="最终回答"
        state="done"
        traceLoaded
        onCopyFinalAnswer={() => true}
        onLoadFullTrace={loadFullTrace}
      />,
    );
    const copyButton = () => screen.getByRole("button", { name: /复制完整回答/ });

    // A failed download and a trace that does not resolve the preview both leave the clipboard alone.
    fireEvent.click(copyButton());
    await waitFor(() => expect(loadFullTrace).toHaveBeenCalledTimes(1));
    await act(async () => {});
    fireEvent.click(copyButton());
    await waitFor(() => expect(loadFullTrace).toHaveBeenCalledTimes(2));
    await act(async () => {});
    expect(writeText).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "已复制完整回答" })).not.toBeInTheDocument();

    fireEvent.click(copyButton());
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toContain("输出开头……完整输出");
    await screen.findByRole("button", { name: "已复制完整回答" });
  });

  it("starts the clipboard write inside the click when the browser accepts a pending item", async () => {
    const write = vi.fn(async (items: Array<{ data: Record<string, Promise<Blob>> }>) => {
      await items[0].data["text/plain"];
    });
    class FakeClipboardItem {
      constructor(public data: Record<string, Promise<Blob>>) {}
    }
    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { write, writeText: vi.fn() } });
    let releaseTrace!: (trace: ChatTraceEvent[]) => void;
    const loadFullTrace = vi.fn(() => new Promise<ChatTraceEvent[]>((resolve) => { releaseTrace = resolve; }));
    render(
      <CliTranscript
        entries={entries()}
        resultText="最终回答"
        state="done"
        traceLoaded
        onCopyFinalAnswer={() => true}
        onLoadFullTrace={loadFullTrace}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "复制完整回答" }));
    // The write is issued before the download finishes; further clicks do not start another download.
    expect(write).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "复制完整回答" }));
    expect(loadFullTrace).toHaveBeenCalledTimes(1);

    await act(async () => { releaseTrace([fullTrace]); });
    await screen.findByRole("button", { name: "已复制完整回答" });
    const blob = await write.mock.calls[0][0][0].data["text/plain"];
    expect(await blob.text()).toBe("[工具结果] 输出开头……完整摘要\n输出开头……完整输出\n\n[最终回答]\n最终回答");
  });

  it("opens rows whose body is already complete without any request", async () => {
    const loadDetail = vi.fn(async () => fullTrace);
    const summaryOnly: ChatTraceEvent = {
      id: "trace-summary-only", kind: "tool_result", summary: "摘要开头", callId: "call-3",
      payload: { output: "完整的短输出" }, summaryChars: 9_000,
    };
    const noBody: ChatTraceEvent = {
      id: "trace-unknown", kind: "unknown", summary: "未知事件", payload: { detail: "开头" }, payloadChars: 9_000,
    };
    for (const trace of [summaryOnly, noBody]) {
      const view = render(
        <CliTranscript
          entries={buildCliTranscriptEntries({ trace: [trace] })}
          resultText=""
          state="streaming"
          traceLoaded
          onLoadTraceEventDetail={loadDetail}
        />,
      );
      const row = view.container.querySelector("details") as HTMLDetailsElement;
      row.open = true;
      fireEvent(row, new Event("toggle"));
      await act(async () => {});
      view.unmount();
    }
    expect(loadDetail).not.toHaveBeenCalled();
  });

  it("copies without any request when nothing in the transcript is a preview", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const loadFullTrace = vi.fn(async () => [fullTrace]);
    render(
      <CliTranscript
        entries={buildCliTranscriptEntries({ trace: [fullTrace] })}
        resultText="最终回答"
        state="done"
        traceLoaded
        onCopyFinalAnswer={() => true}
        onLoadFullTrace={loadFullTrace}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "复制完整回答" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(loadFullTrace).not.toHaveBeenCalled();
  });

  it("keeps the richer version when a preview meets another copy of the same event", () => {
    const smaller: ChatTraceEvent = { kind: "tool_call", summary: "ls", callId: "call-2", payload: { command: "ls" } };
    const preview: ChatTraceEvent = {
      kind: "tool_call",
      summary: "写入文件",
      callId: "call-2",
      payload: { content: "开头" },
      payloadChars: 50_000,
    };

    // A later, smaller copy must not displace the preview of a much larger payload.
    expect(mergeChatTraceEvents([[preview], [smaller]])?.[0]).toMatchObject({ summary: "写入文件", payloadChars: 50_000 });
    expect(mergeChatTraceEvents([[smaller], [preview]])?.[0]).toMatchObject({ summary: "写入文件", payloadChars: 50_000 });
  });
});
