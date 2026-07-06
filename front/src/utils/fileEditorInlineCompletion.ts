import {
  StateEffect,
  StateField,
  type Extension,
} from "@codemirror/state";
import {
  Decoration,
  EditorView,
  keymap,
  ViewPlugin,
  WidgetType,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import type { InlineCompletionRequest, InlineCompletionResult } from "../services/types";

export type FileEditorInlineCompletionOptions = {
  editorId: string;
  path: string;
  languageId: string;
  lastModifiedNs?: string;
  disabled?: boolean;
  autoTriggerEnabled?: boolean;
  manualTriggerEnabled?: boolean;
  autoTriggerDelayMs?: number;
  request: (input: InlineCompletionRequest, signal?: AbortSignal) => Promise<InlineCompletionResult>;
};

type InlineSuggestion = {
  from: number;
  insertText: string;
  displayText: string;
  requestId: string;
  replaceFrom?: number;
  replaceTo?: number;
};

const setInlineSuggestion = StateEffect.define<InlineSuggestion | null>();

const inlineSuggestionField = StateField.define<InlineSuggestion | null>({
  create() {
    return null;
  },
  update(value, transaction) {
    for (const effect of transaction.effects) {
      if (effect.is(setInlineSuggestion)) {
        return effect.value;
      }
    }
    if (transaction.docChanged || transaction.selection) {
      return null;
    }
    return value;
  },
  provide: (field) => EditorView.decorations.compute([field], (state): DecorationSet => {
    const suggestion = state.field(field);
    if (!suggestion?.displayText) {
      return Decoration.none;
    }
    const widget = Decoration.widget({
      widget: new InlineGhostTextWidget(suggestion.displayText),
      side: 1,
    });
    return Decoration.set([widget.range(suggestion.from)]);
  }),
});

class InlineGhostTextWidget extends WidgetType {
  constructor(private readonly text: string) {
    super();
  }

  eq(other: InlineGhostTextWidget) {
    return this.text === other.text;
  }

  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-ai-inline-ghost";
    span.textContent = this.text;
    span.setAttribute("aria-hidden", "true");
    return span;
  }

  ignoreEvent() {
    return true;
  }
}

function cursorPayload(view: EditorView) {
  const offset = view.state.selection.main.head;
  const line = view.state.doc.lineAt(offset);
  return {
    line: line.number,
    column: offset - line.from + 1,
    offset,
  };
}

function clearInlineSuggestion(view: EditorView) {
  if (!view.state.field(inlineSuggestionField, false)) {
    return false;
  }
  view.dispatch({ effects: setInlineSuggestion.of(null) });
  return true;
}

function acceptInlineSuggestion(view: EditorView) {
  const suggestion = view.state.field(inlineSuggestionField, false);
  if (!suggestion) {
    return false;
  }
  const from = suggestion.replaceFrom ?? suggestion.from;
  const to = suggestion.replaceTo ?? suggestion.from;
  view.dispatch({
    changes: { from, to, insert: suggestion.insertText },
    selection: { anchor: from + suggestion.insertText.length },
    effects: setInlineSuggestion.of(null),
    userEvent: "input.complete",
  });
  return true;
}

export function createFileEditorInlineCompletion(options: FileEditorInlineCompletionOptions): Extension[] {
  class InlineCompletionController {
    private timer: ReturnType<typeof setTimeout> | null = null;
    private abortController: AbortController | null = null;
    private seq = 0;
    private composing = false;

    constructor(private readonly view: EditorView) {}

    update(update: ViewUpdate) {
      if (options.disabled) {
        this.cancel();
        clearInlineSuggestion(update.view);
        return;
      }
      if (update.docChanged || update.selectionSet) {
        this.cancel();
        clearInlineSuggestion(update.view);
      }
      if (update.docChanged && options.autoTriggerEnabled !== false) {
        this.scheduleAuto();
      }
    }

    destroy() {
      this.cancel();
    }

    onCompositionStart() {
      this.composing = true;
      this.cancel();
      clearInlineSuggestion(this.view);
    }

    onCompositionEnd() {
      this.composing = false;
      this.scheduleAuto();
    }

    requestManual() {
      if (options.manualTriggerEnabled === false) {
        return false;
      }
      this.cancel();
      void this.request("manual");
      return true;
    }

    private scheduleAuto() {
      this.cancelTimer();
      if (options.disabled || this.composing || this.view.composing) {
        return;
      }
      this.timer = setTimeout(() => {
        void this.request("auto");
      }, Math.max(100, options.autoTriggerDelayMs ?? 500));
    }

    private cancel() {
      this.cancelTimer();
      if (this.abortController) {
        this.abortController.abort();
        this.abortController = null;
      }
    }

    private cancelTimer() {
      if (this.timer !== null) {
        clearTimeout(this.timer);
        this.timer = null;
      }
    }

    private async request(trigger: "auto" | "manual") {
      if (options.disabled || this.composing || this.view.composing || this.view.state.selection.ranges.length !== 1) {
        return;
      }
      const docSnapshot = this.view.state.doc;
      const cursor = cursorPayload(this.view);
      const requestId = `${options.editorId}-${Date.now()}-${++this.seq}`;
      const abortController = new AbortController();
      this.abortController = abortController;
      const input: InlineCompletionRequest = {
        requestId,
        editorId: options.editorId,
        path: options.path,
        languageId: options.languageId,
        cursor,
        prefix: this.view.state.doc.sliceString(0, cursor.offset),
        suffix: this.view.state.doc.sliceString(cursor.offset),
        trigger,
        ...(options.lastModifiedNs ? { lastModifiedNs: options.lastModifiedNs } : {}),
      };
      try {
        const result = await options.request(input, abortController.signal);
        if (
          abortController.signal.aborted
          || result.requestId !== requestId
          || this.view.state.doc !== docSnapshot
          || this.view.state.selection.main.head !== cursor.offset
        ) {
          return;
        }
        const item = result.items[0];
        if (!item?.insertText) {
          clearInlineSuggestion(this.view);
          return;
        }
        this.view.dispatch({
          effects: setInlineSuggestion.of({
            from: cursor.offset,
            insertText: item.insertText,
            displayText: item.displayText || item.insertText.split(/\r?\n/, 1)[0] || item.insertText,
            requestId,
            replaceFrom: item.replaceFrom,
            replaceTo: item.replaceTo,
          }),
        });
      } catch (error) {
        if ((error as { name?: string })?.name !== "AbortError") {
          clearInlineSuggestion(this.view);
        }
      } finally {
        if (this.abortController === abortController) {
          this.abortController = null;
        }
      }
    }
  }

  const controllerPlugin = ViewPlugin.fromClass(InlineCompletionController, {
    eventHandlers: {
      compositionstart(_event, view) {
        view.plugin(controllerPlugin)?.onCompositionStart();
      },
      compositionend(_event, view) {
        view.plugin(controllerPlugin)?.onCompositionEnd();
      },
    },
  });

  return [
    inlineSuggestionField,
    controllerPlugin,
    keymap.of([
      { key: "Tab", run: acceptInlineSuggestion },
      { key: "Escape", run: clearInlineSuggestion },
      {
        key: "Alt-\\",
        run(view) {
          const controller = view.plugin(controllerPlugin);
          return controller?.requestManual() ?? false;
        },
      },
    ]),
    EditorView.baseTheme({
      ".cm-ai-inline-ghost": {
        color: "var(--muted)",
        opacity: "0.55",
        pointerEvents: "none",
        whiteSpace: "pre",
      },
    }),
  ];
}
