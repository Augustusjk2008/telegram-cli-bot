import { splitReadAloudText } from "../utils/readAloudText";

export type ReadAloudState = { status: "idle" | "loading" | "playing" | "paused" | "error"; error?: string };
type Reading = {
  owner: symbol;
  synth: SpeechSynthesis;
  chunks: string[];
  index: number;
  /** Last reported word/sentence boundary within the current chunk. */
  offset: number;
  paused: boolean;
  utterance?: SpeechSynthesisUtterance;
  startTimer?: ReturnType<typeof setTimeout>;
  notify: (state: ReadAloudState) => void;
};

// The browser owns one speech queue, shared by every answer and workbench pane.
let active: Reading | undefined;

export function supportsReadAloud(): boolean {
  return typeof window !== "undefined"
    && typeof window.speechSynthesis?.speak === "function"
    && typeof window.SpeechSynthesisUtterance === "function";
}

export function stopReadAloud(owner?: symbol): void {
  if (!active || (owner && active.owner !== owner)) return;
  const reading = active;
  active = undefined; // Ignore delayed end/error events from cancel().
  clearTimeout(reading.startTimer);
  try { reading.synth.cancel(); } catch { /* Already unavailable. */ }
  reading.notify({ status: "idle" });
}

function fail(reading: Reading, error: string) {
  if (active !== reading) return;
  stopReadAloud(reading.owner);
  reading.notify({ status: "error", error });
}

function languageFor(text: string): string {
  if (/[\u3040-\u30ff]/.test(text)) return "ja-JP";
  if (/[\uac00-\ud7af]/.test(text)) return "ko-KR";
  if (/\p{Script=Han}/u.test(text)) return "zh-CN";
  if (/[a-z]/i.test(text)) return "en-US";
  return navigator.language || "zh-CN";
}

function speakNext(reading: Reading) {
  if (active !== reading || reading.paused) return;
  const chunk = reading.chunks[reading.index];
  if (!chunk) {
    active = undefined;
    reading.notify({ status: "idle" });
    return;
  }
  try {
    const startOffset = reading.offset;
    const text = chunk.slice(startOffset);
    const utterance = new SpeechSynthesisUtterance(text);
    reading.utterance = utterance; // Keep a strong reference until this chunk finishes.
    utterance.lang = languageFor(chunk);
    // Voices can load asynchronously; query again for every utterance, falling back
    // to the browser's selection by language when its voice list is still empty.
    const voices = reading.synth.getVoices();
    const language = utterance.lang.toLowerCase();
    const matches = voices.filter((voice) => voice.lang.toLowerCase().replaceAll("_", "-") === language);
    utterance.voice = matches.find((voice) => voice.localService) || matches[0]
      || voices.find((voice) => voice.lang.toLowerCase().split(/[-_]/)[0] === language.split("-")[0]) || null;
    const current = () => active === reading && reading.utterance === utterance;
    utterance.onstart = () => {
      if (!current()) return;
      clearTimeout(reading.startTimer);
      reading.notify({ status: reading.paused ? "paused" : "playing" });
    };
    utterance.onboundary = (event) => {
      if (!current() || !Number.isInteger(event.charIndex) || event.charIndex < 0 || event.charIndex >= text.length) return;
      let offset = startOffset + event.charIndex;
      // A buggy voice must not leave the resumed string inside a surrogate pair.
      if (/[\uDC00-\uDFFF]/.test(chunk[offset]) && /[\uD800-\uDBFF]/.test(chunk[offset - 1] || "")) offset -= 1;
      reading.offset = Math.max(reading.offset, offset);
    };
    utterance.onend = () => {
      if (!current()) return;
      clearTimeout(reading.startTimer);
      reading.utterance = undefined;
      reading.index += 1;
      reading.offset = 0;
      speakNext(reading);
    };
    utterance.onerror = (event) => {
      if (!current()) return;
      if (event.error === "canceled" || event.error === "interrupted") {
        stopReadAloud(reading.owner);
      } else {
        fail(reading, event.error === "language-unavailable" || event.error === "voice-unavailable"
          ? "没有可用的朗读语音，请在系统中安装相应语言的语音。"
          : "朗读失败，请检查浏览器语音支持后重试。");
      }
    };
    reading.notify({ status: "loading" });
    reading.startTimer = setTimeout(() => {
      if (current()) fail(reading, "语音未能启动，请检查系统语音设置后重试。");
    }, 15000);
    // Clear an inherited native paused flag before queuing fresh speech.
    if (reading.synth.paused) reading.synth.resume();
    reading.synth.speak(utterance);
  } catch {
    fail(reading, "朗读失败，请检查浏览器语音支持后重试。");
  }
}

/** Called directly from the click handler to retain browser user activation. */
export function startReadAloud(owner: symbol, text: string, notify: Reading["notify"]) {
  stopReadAloud();
  if (!supportsReadAloud()) return;
  const reading: Reading = {
    owner, synth: window.speechSynthesis, chunks: splitReadAloudText(text), index: 0, offset: 0, paused: false, notify,
  };
  active = reading;
  speakNext(reading);
}

export function pauseReadAloud(owner: symbol) {
  if (!active || active.owner !== owner || active.paused) return;
  const reading = active;
  try {
    reading.paused = true;
    // Some engines cancel on pause or silently fail to resume. Keep our own
    // position and resume with a new utterance instead of native pause/resume.
    // Invalidate first: cancel() may deliver end/error callbacks synchronously.
    reading.utterance = undefined;
    clearTimeout(reading.startTimer);
    reading.synth.cancel();
    if (active === reading) reading.notify({ status: "paused" });
  } catch {
    fail(reading, "当前浏览器无法暂停朗读，请重新播放。");
  }
}

export function resumeReadAloud(owner: symbol) {
  if (!active || active.owner !== owner || !active.paused) return;
  const reading = active;
  reading.paused = false;
  // No boundary support means replaying this short chunk, never skipping it.
  // Only onstart may change the UI from loading to playing.
  speakNext(reading);
}
