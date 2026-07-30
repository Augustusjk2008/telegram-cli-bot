import { StateEffect, StateField, type Extension } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin } from "@codemirror/view";
import type { CodeNavigationIntent } from "../services/types";

export type FileEditorCodeNavigationHoverOptions = {
  path: string;
  hoverDelayMs?: number;
  request: (input: CodeNavigationIntent, signal: AbortSignal) => Promise<boolean>;
};

type DefinitionLink = {
  from: number;
  to: number;
  intent: CodeNavigationIntent;
};

type SymbolRange = {
  from: number;
  to: number;
  symbol: string;
};

function isSymbolChar(char: string) {
  return /[A-Za-z0-9_$]/.test(char);
}

function extractSymbolRangeAt(text: string, index: number): SymbolRange | null {
  if (!text) {
    return null;
  }
  const boundedIndex = Math.min(Math.max(index, 0), text.length - 1);
  if (!isSymbolChar(text[boundedIndex] || "")) {
    return null;
  }
  let start = boundedIndex;
  let end = boundedIndex;
  while (start > 0 && isSymbolChar(text[start - 1] || "")) {
    start -= 1;
  }
  while (end + 1 < text.length && isSymbolChar(text[end + 1] || "")) {
    end += 1;
  }
  return { from: start, to: end + 1, symbol: text.slice(start, end + 1) };
}

export function extractFileEditorSymbolAt(text: string, index: number) {
  return extractSymbolRangeAt(text, index)?.symbol || "";
}

export function resolveFileEditorNavigationTargetAtPosition(
  view: EditorView,
  path: string,
  position: number,
  kind: CodeNavigationIntent["kind"],
): CodeNavigationIntent {
  const lineInfo = view.state.doc.lineAt(position);
  const offset = position - lineInfo.from;
  const symbol = extractFileEditorSymbolAt(lineInfo.text, Math.max(0, offset));
  return {
    kind,
    path,
    line: lineInfo.number,
    column: Array.from(lineInfo.text.slice(0, offset)).length + 1,
    ...(symbol ? { symbol } : {}),
  };
}

export function resolveFileEditorNavigationTargetAtCoordinates(
  view: EditorView,
  path: string,
  clientX: number,
  clientY: number,
  kind: CodeNavigationIntent["kind"],
) {
  const position = view.posAtCoords({ x: clientX, y: clientY });
  return position === null
    ? null
    : resolveFileEditorNavigationTargetAtPosition(view, path, position, kind);
}

function resolveDefinitionLink(view: EditorView, path: string, position: number): DefinitionLink | null {
  const lineInfo = view.state.doc.lineAt(position);
  const symbolRange = extractSymbolRangeAt(lineInfo.text, position - lineInfo.from);
  if (!symbolRange) {
    return null;
  }
  return {
    from: lineInfo.from + symbolRange.from,
    to: lineInfo.from + symbolRange.to,
    intent: resolveFileEditorNavigationTargetAtPosition(view, path, position, "definition"),
  };
}

export function createFileEditorCodeNavigationHover(
  options: FileEditorCodeNavigationHoverOptions,
): Extension[] {
  const setDefinitionLink = StateEffect.define<{ from: number; to: number } | null>();
  const definitionLinkField = StateField.define({
    create: () => Decoration.none,
    update(value, transaction) {
      for (const effect of transaction.effects) {
        if (effect.is(setDefinitionLink)) {
          return effect.value
            ? Decoration.set([
                Decoration.mark({
                  class: "cm-code-navigation-link",
                  attributes: { "data-code-navigation-link": "true" },
                }).range(effect.value.from, effect.value.to),
              ])
            : Decoration.none;
        }
      }
      return transaction.docChanged ? Decoration.none : value;
    },
    provide: (field) => EditorView.decorations.from(field),
  });

  class DefinitionLinkController {
    private hoverKey = "";
    private timer: number | null = null;
    private abortController: AbortController | null = null;
    private sequence = 0;
    private hasDecoration = false;
    private destroyed = false;

    private readonly handleWindowKeyUp = (event: KeyboardEvent) => {
      if ((event.key === "Control" || event.key === "Meta") && !event.ctrlKey && !event.metaKey) {
        this.resetHover();
      }
    };

    private readonly handleWindowBlur = () => {
      this.resetHover();
    };

    constructor(private readonly view: EditorView) {
      window.addEventListener("keyup", this.handleWindowKeyUp);
      window.addEventListener("blur", this.handleWindowBlur);
    }

    update(update: { docChanged: boolean }) {
      if (!update.docChanged) {
        return;
      }
      this.hoverKey = "";
      this.hasDecoration = false;
      this.cancelPending();
    }

    destroy() {
      this.destroyed = true;
      this.cancelPending();
      window.removeEventListener("keyup", this.handleWindowKeyUp);
      window.removeEventListener("blur", this.handleWindowBlur);
    }

    onMouseMove(event: MouseEvent) {
      if (!event.ctrlKey && !event.metaKey) {
        this.resetHover();
        return;
      }
      const position = this.view.posAtCoords({ x: event.clientX, y: event.clientY });
      if (position === null) {
        this.resetHover();
        return;
      }
      const link = resolveDefinitionLink(this.view, options.path, position);
      if (!link) {
        this.resetHover();
        return;
      }
      const hoverKey = `${link.from}:${link.to}`;
      if (hoverKey === this.hoverKey) {
        return;
      }
      this.cancelPending();
      this.clearDecoration();
      this.hoverKey = hoverKey;
      this.timer = window.setTimeout(() => {
        this.timer = null;
        void this.probe(link, hoverKey);
      }, Math.max(0, options.hoverDelayMs ?? 120));
    }

    onMouseLeave() {
      this.resetHover();
    }

    private async probe(link: DefinitionLink, hoverKey: string) {
      const controller = new AbortController();
      const sequence = this.sequence + 1;
      const docSnapshot = this.view.state.doc;
      this.sequence = sequence;
      this.abortController = controller;
      try {
        const available = await options.request(link.intent, controller.signal);
        if (
          !available
          || controller.signal.aborted
          || this.destroyed
          || this.sequence !== sequence
          || this.hoverKey !== hoverKey
          || this.view.state.doc !== docSnapshot
        ) {
          return;
        }
        this.hasDecoration = true;
        this.view.dispatch({ effects: setDefinitionLink.of({ from: link.from, to: link.to }) });
      } catch {
        // Hover probing is intentionally silent; an explicit jump still reports errors.
      } finally {
        if (this.abortController === controller) {
          this.abortController = null;
        }
      }
    }

    private resetHover() {
      this.hoverKey = "";
      this.cancelPending();
      this.clearDecoration();
    }

    private cancelPending() {
      this.sequence += 1;
      if (this.timer !== null) {
        window.clearTimeout(this.timer);
        this.timer = null;
      }
      if (this.abortController) {
        this.abortController.abort();
        this.abortController = null;
      }
    }

    private clearDecoration() {
      if (!this.hasDecoration || this.destroyed) {
        return;
      }
      this.hasDecoration = false;
      this.view.dispatch({ effects: setDefinitionLink.of(null) });
    }
  }

  const controllerPlugin = ViewPlugin.fromClass(DefinitionLinkController, {
    eventHandlers: {
      mousemove(event, view) {
        view.plugin(controllerPlugin)?.onMouseMove(event);
      },
      mouseleave(_event, view) {
        view.plugin(controllerPlugin)?.onMouseLeave();
      },
    },
  });

  return [
    definitionLinkField,
    controllerPlugin,
    EditorView.baseTheme({
      ".cm-code-navigation-link": {
        cursor: "pointer",
        textDecoration: "underline",
        textUnderlineOffset: "2px",
      },
    }),
  ];
}
