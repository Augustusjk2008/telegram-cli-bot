import { history, isolateHistory, redo, undo } from "@codemirror/commands";
import { EditorSelection, EditorState, Prec, Transaction, type ChangeSet, type Extension } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";

type ViewPosition = { selection: EditorSelection; top: number; left: number };
type AttachedView = { id: string; onChange: (value: string) => void };

/** One history per open document; editor states only own presentation and selection. */
export class FileEditorDocument {
  private state: EditorState;
  private readonly views = new Map<EditorView, AttachedView>();
  private readonly positions = new Map<string, ViewPosition>();
  private canonicalValue: string;
  private pendingValues: string[] = [];
  private lastEditingView: EditorView | null = null;
  private hasLocalEdits = false;
  revision = 0;

  constructor(value: string) {
    this.canonicalValue = value;
    this.state = EditorState.create({
      doc: value,
      extensions: [history(), EditorState.allowMultipleSelections.of(true)],
    });
  }

  get value() {
    return this.state.doc.toString();
  }

  closeHistoryGroup() {
    this.state = this.state.update({ annotations: isolateHistory.of("full") }).state;
    this.lastEditingView = null;
  }

  /** Apply canonical loads/reloads, ignoring superseded render snapshots and edit echoes. */
  synchronize(value: string, renderedRevision: number) {
    if (renderedRevision !== this.revision) return;
    if (value === this.value) {
      this.canonicalValue = value;
      this.pendingValues = [];
      return;
    }
    if (value === this.canonicalValue) return;
    const pendingIndex = this.pendingValues.lastIndexOf(value);
    if (pendingIndex >= 0) {
      this.canonicalValue = value;
      this.pendingValues.splice(0, pendingIndex + 1);
      return;
    }
    this.canonicalValue = value;
    this.pendingValues = [];
    const transaction = this.state.update({
      changes: { from: 0, to: this.state.doc.length, insert: value },
      annotations: [isolateHistory.of("full"), Transaction.addToHistory.of(this.hasLocalEdits)],
    });
    this.state = transaction.state;
    this.revision += 1;
    this.mirror(transaction.changes);
  }

  createView(parent: HTMLElement, id: string, extensions: Extension[], onChange: (value: string) => void) {
    const position = this.positions.get(id);
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: this.state.doc,
        selection: position?.selection,
        extensions: [...extensions, this.historyExtensions()],
      }),
      dispatchTransactions: (transactions, source) => this.dispatch(transactions, source),
    });
    this.views.set(view, { id, onChange });
    if (position) {
      view.scrollDOM.scrollTop = position.top;
      view.scrollDOM.scrollLeft = position.left;
    }
    return view;
  }

  releaseView(view: EditorView) {
    const entry = this.views.get(view);
    if (!entry) return;
    this.positions.set(entry.id, {
      selection: view.state.selection,
      top: view.scrollDOM.scrollTop,
      left: view.scrollDOM.scrollLeft,
    });
    this.views.delete(view);
    if (this.lastEditingView === view) this.lastEditingView = null;
    view.destroy();
  }

  historyExtensions(): Extension {
    return [
      Prec.highest(keymap.of([
        { key: "Mod-z", run: (view) => this.undo(view), preventDefault: true },
        { key: "Mod-Shift-z", run: (view) => this.redo(view), preventDefault: true },
        { key: "Mod-y", run: (view) => this.redo(view), preventDefault: true },
      ])),
      EditorView.domEventHandlers({
        beforeinput: (event, view) => {
          if (event.inputType !== "historyUndo" && event.inputType !== "historyRedo") return false;
          event.preventDefault();
          return event.inputType === "historyUndo" ? this.undo(view) : this.redo(view);
        },
      }),
    ];
  }

  undo(view: EditorView) {
    return this.applyHistory(view, undo);
  }

  redo(view: EditorView) {
    return this.applyHistory(view, redo);
  }

  private applyHistory(view: EditorView, command: typeof undo) {
    if (!this.views.has(view) || view.state.readOnly || !view.state.facet(EditorView.editable)) return false;
    this.state = this.state.update({
      selection: view.state.selection,
      annotations: Transaction.addToHistory.of(false),
    }).state;
    return command({
      state: this.state,
      dispatch: (transaction) => {
        this.state = transaction.state;
        this.revision += 1;
        this.lastEditingView = null;
        this.mirror(transaction.changes, view, transaction.newSelection);
        this.publish(view);
      },
    });
  }

  private dispatch(transactions: readonly Transaction[], source: EditorView) {
    let changed = false;
    for (const transaction of transactions) {
      if (!transaction.docChanged) continue;
      this.state = this.state.update({
        selection: transaction.startState.selection,
        annotations: Transaction.addToHistory.of(false),
      }).state;
      this.state = this.state.update({
        changes: transaction.changes,
        selection: transaction.newSelection,
        annotations: [
          Transaction.time.of(transaction.annotation(Transaction.time) ?? Date.now()),
          Transaction.userEvent.of(transaction.annotation(Transaction.userEvent) ?? "input"),
          Transaction.addToHistory.of(transaction.annotation(Transaction.addToHistory) !== false),
          ...(transaction.annotation(isolateHistory)
            ? [isolateHistory.of(transaction.annotation(isolateHistory)!)]
            : this.lastEditingView !== source ? [isolateHistory.of("before")] : []),
        ],
      }).state;
      this.lastEditingView = source;
      this.revision += 1;
      this.mirror(transaction.changes, source);
      changed = true;
    }
    source.update(transactions);
    if (changed) this.publish(source);
  }

  private mirror(changes: ChangeSet, source?: EditorView, selection?: EditorSelection) {
    for (const position of this.positions.values()) {
      position.selection = position.selection.map(changes);
    }
    for (const view of this.views.keys()) {
      if (view === source && !selection) continue;
      view.update([view.state.update({
        changes,
        ...(view === source ? { selection, scrollIntoView: true } : {}),
        annotations: Transaction.addToHistory.of(false),
        filter: false,
      })]);
    }
  }

  private publish(source: EditorView) {
    const value = this.value;
    this.hasLocalEdits = true;
    this.pendingValues.push(value);
    this.views.get(source)?.onChange(value);
  }
}

const sessions = new WeakMap<object, Map<string, FileEditorDocument>>();

export function getFileEditorDocument(sessionKey: object, path: string, value: string) {
  let session = sessions.get(sessionKey);
  if (!session) {
    session = new Map();
    sessions.set(sessionKey, session);
  }
  let document = session.get(path);
  if (!document) {
    document = new FileEditorDocument(value);
    session.set(path, document);
  }
  return document;
}

export function pruneFileEditorDocuments(sessionKey: object, paths: readonly string[]) {
  const session = sessions.get(sessionKey);
  const openPaths = new Set(paths);
  for (const path of session?.keys() ?? []) {
    if (!openPaths.has(path)) session!.delete(path);
  }
}
