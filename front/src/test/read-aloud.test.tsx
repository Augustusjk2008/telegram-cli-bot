import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatFinalAnswerActions } from "../components/ChatFinalAnswerActions";
import { ChatReadAloudButton, ReadAloudContext } from "../components/ChatReadAloudButton";
import { CliTranscript } from "../components/CliTranscript";
import { stopReadAloud } from "../services/browserReadAloud";
import { readAloudText, splitReadAloudText } from "../utils/readAloudText";

class Utterance {
  lang = "";
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onboundary: ((event: { charIndex: number }) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  constructor(public text: string) {}
}

let utterances: Utterance[];
let synth: {
  speak: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
  pause: ReturnType<typeof vi.fn>;
  resume: ReturnType<typeof vi.fn>;
  getVoices: ReturnType<typeof vi.fn>;
  paused: boolean;
};

beforeEach(() => {
  utterances = [];
  synth = {
    speak: vi.fn((utterance: Utterance) => { utterances.push(utterance); utterance.onstart?.(); }),
    cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(), getVoices: vi.fn(() => []), paused: false,
  };
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal("SpeechSynthesisUtterance", Utterance);
});

afterEach(() => {
  cleanup();
  stopReadAloud();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("read-aloud text", () => {
  it("reads Markdown prose and link labels without code, math, hidden reasoning or URLs", () => {
    const text = readAloudText([
      "<thinking>private reasoning</thinking>", "", "# **Hello** &amp; 你好", "",
      "Read [the guide](https://example.com) and `README.md`.", "",
      "- First", "- Second", "", "```python", "secret_code()", "```", "",
      "    indented_code()", "", "$$x^2$$", "", "![image](https://example.com/image)", "",
      "| Name | Value |", "| --- | --- |", "| One | Two |",
    ].join("\n"));
    expect(text.replace(/\s+/g, " ")).toBe("Hello & 你好 Read the guide and README.md. First Second Name Value One Two");
    expect(readAloudText("```js\nonlyCode()\n```\n<think>unfinished")).toBe("");
  });

  it("splits long Chinese and English answers without dropping text or breaking surrogate pairs", () => {
    const text = "这是一段中文。 Next sentence with spaces! ".repeat(40) + "长".repeat(199) + "😀结尾";
    const chunks = splitReadAloudText(text);
    expect(chunks.length).toBeGreaterThan(2);
    expect(chunks.every((chunk) => chunk.length <= 200 && !/[\uD800-\uDBFF]$/.test(chunk))).toBe(true);
    expect(chunks.join("").replace(/\s/g, "")).toBe(text.replace(/\s/g, ""));
  });
});

describe("browser read-aloud controls", () => {
  it("plays, pauses, resumes, stops and replays without a request or another chat turn", () => {
    const onContinue = vi.fn();
    render(<ChatFinalAnswerActions readAloudText="你好，世界。" canContinue onContinue={onContinue} />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(utterances[0].text).toBe("你好，世界。");
    expect(utterances[0].lang).toBe("zh-CN");
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    expect(synth.cancel).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    expect(utterances[1].text).toBe("你好，世界。");
    fireEvent.click(screen.getByRole("button", { name: "停止朗读" }));
    expect(synth.cancel).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(utterances).toHaveLength(3);
    act(() => utterances[2].onend?.());
    expect(screen.queryByRole("button", { name: "停止朗读" })).not.toBeInTheDocument();
    expect(onContinue).not.toHaveBeenCalled();
  });

  it("replaces the previous answer and ignores its delayed callbacks and unmount", () => {
    const first = render(<ChatReadAloudButton text="First answer" />);
    fireEvent.click(within(first.container).getByRole("button", { name: "朗读回答" }));
    const second = render(<ChatReadAloudButton text="Second answer" />);
    fireEvent.click(within(second.container).getByRole("button", { name: "朗读回答" }));
    expect(synth.cancel).toHaveBeenCalledOnce();
    expect(within(first.container).getByRole("button", { name: "朗读回答" })).toBeEnabled();
    act(() => { utterances[0].onend?.(); utterances[0].onerror?.({ error: "interrupted" }); });
    first.unmount();
    expect(synth.cancel).toHaveBeenCalledOnce();
    expect(within(second.container).getByRole("button", { name: "暂停朗读" })).toBeEnabled();
  });

  it.each(["text", "scope", "enabled", "unmount"])("cancels playback on %s changes", (change) => {
    const view = (text = "Original answer", scope = "conversation-1", enabled = true) => (
      <ReadAloudContext.Provider value={{ scope, enabled }}><ChatReadAloudButton text={text} /></ReadAloudContext.Provider>
    );
    const { rerender, unmount } = render(view());
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    if (change === "unmount") unmount();
    else rerender(view(change === "text" ? "翻译后的回答" : undefined, change === "scope" ? "conversation-2" : undefined, change !== "enabled"));
    expect(synth.cancel).toHaveBeenCalledOnce();
    act(() => utterances[0].onend?.());
    expect(utterances).toHaveLength(1);
    if (change === "enabled") expect(screen.getByRole("button", { name: "当前无法朗读" })).toBeDisabled();
  });

  it("reads all chunks in order and loads voices again when they become available", () => {
    const text = "这是中文回答。 ".repeat(70);
    render(<ChatReadAloudButton text={text} />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(utterances[0].voice).toBeNull();
    const voice = { name: "中文", lang: "zh-CN", localService: true };
    synth.getVoices.mockReturnValue([voice]);
    const chunks = splitReadAloudText(readAloudText(text));
    for (let index = 0; index < chunks.length; index += 1) {
      expect(utterances[index].text).toBe(chunks[index]);
      if (index > 0) expect(utterances[index].voice).toBe(voice);
      act(() => utterances[index].onend?.());
    }
    expect(screen.getByRole("button", { name: "朗读回答" })).toBeEnabled();
  });

  it("does not advance to a new chunk while paused", () => {
    render(<ChatReadAloudButton text={"A long answer. ".repeat(40)} />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    act(() => utterances[0].onend?.());
    expect(utterances).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    expect(utterances).toHaveLength(2);
  });

  it.each(["silent-resume", "pause-cancels"])("resumes by speaking saved text when native playback has %s", (failure) => {
    if (failure === "pause-cancels") {
      synth.pause.mockImplementation(() => utterances.at(-1)?.onerror?.({ error: "interrupted" }));
    }
    render(<ChatReadAloudButton text="First sentence. Second sentence." />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    act(() => utterances[0].onboundary?.({ charIndex: 16 }));
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    // A changed button label alone is not evidence that speech was restarted.
    expect(utterances.map((utterance) => utterance.text)).toEqual(["First sentence. Second sentence.", "Second sentence."]);
    expect(synth.pause).not.toHaveBeenCalled();
    expect(synth.resume).not.toHaveBeenCalled();
  });

  it("preserves progress across repeated pauses and ignores cancellation callbacks", () => {
    synth.cancel.mockImplementation(() => {
      utterances.at(-1)?.onend?.();
      utterances.at(-1)?.onerror?.({ error: "canceled" });
    });
    render(<ChatReadAloudButton text="One two three four." />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    act(() => utterances[0].onboundary?.({ charIndex: 4 }));
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    expect(utterances[1].text).toBe("two three four.");
    act(() => {
      utterances[0].onboundary?.({ charIndex: 17 });
      utterances[0].onend?.();
      utterances[0].onerror?.({ error: "interrupted" });
      utterances[1].onboundary?.({ charIndex: 4 });
    });
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    expect(utterances[2].text).toBe("three four.");
    act(() => utterances[2].onend?.());
    expect(screen.getByRole("button", { name: "朗读回答" })).toBeEnabled();
  });

  it("repeats only the current chunk when the voice does not report word boundaries", () => {
    const text = "First passage. ".repeat(20) + "Last passage. ".repeat(20);
    const chunks = splitReadAloudText(readAloudText(text));
    render(<ChatReadAloudButton text={text} />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    act(() => utterances[0].onend?.());
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    act(() => utterances[1].onend?.());
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    expect(utterances.map((utterance) => utterance.text)).toEqual([chunks[0], chunks[1], chunks[1]]);
    act(() => utterances[2].onend?.());
    expect(utterances[3].text).toBe(chunks[2]);
  });

  it("waits for resumed audio to start and keeps cancellation available", () => {
    vi.useFakeTimers();
    render(<ChatReadAloudButton text="An answer." />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    fireEvent.click(screen.getByRole("button", { name: "暂停朗读" }));
    synth.speak.mockImplementation((utterance: Utterance) => { utterances.push(utterance); });
    fireEvent.click(screen.getByRole("button", { name: "继续朗读" }));
    expect(screen.getByRole("button", { name: "正在准备朗读" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "停止朗读" })).toBeEnabled();
    act(() => vi.advanceTimersByTime(15000));
    expect(screen.getByRole("alert")).toHaveTextContent("语音未能启动");
    expect(screen.getByRole("button", { name: "朗读回答" })).toBeEnabled();
  });

  it("disables unsupported browsers and omits answers containing only code", () => {
    vi.stubGlobal("speechSynthesis", undefined);
    const { rerender } = render(<ChatReadAloudButton text="An answer" />);
    expect(screen.getByRole("button", { name: "当前浏览器不支持朗读" })).toBeDisabled();
    rerender(<ChatReadAloudButton text={'```js\ncode()\n```'} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("reports voice errors and permits a retry", () => {
    render(<ChatReadAloudButton text="你好" />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    act(() => utterances[0].onerror?.({ error: "language-unavailable" }));
    expect(screen.getByRole("alert")).toHaveTextContent("没有可用的朗读语音");
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(utterances).toHaveLength(2);
  });

  it("allows cancelling speech before it starts and reports a stalled speech service", () => {
    vi.useFakeTimers();
    synth.speak.mockImplementation((utterance: Utterance) => { utterances.push(utterance); });
    render(<ChatReadAloudButton text="An answer" />);
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(screen.getByRole("button", { name: "正在准备朗读" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "停止朗读" }));
    act(() => vi.advanceTimersByTime(15000));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    act(() => vi.advanceTimersByTime(15000));
    expect(screen.getByRole("alert")).toHaveTextContent("语音未能启动");
  });

  it("reads the CLI's displayed translation without fetching or narrating trace details", () => {
    const onLoadFullTrace = vi.fn();
    const { rerender } = render(
      <CliTranscript entries={[]} resultText="这是译文。" originalResultText="Original answer." state="done"
        traceCount={3} onLoadFullTrace={onLoadFullTrace} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "朗读回答" }));
    expect(utterances[0].text).toBe("这是译文。");
    expect(onLoadFullTrace).not.toHaveBeenCalled();
    rerender(<CliTranscript entries={[]} resultText="输出中" state="streaming" />);
    expect(screen.queryByRole("button", { name: "朗读回答" })).not.toBeInTheDocument();
    expect(synth.cancel).toHaveBeenCalledOnce();
  });
});
