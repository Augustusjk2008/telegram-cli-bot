import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { JsonPreview } from "../components/JsonPreview";
import * as jsonPreview from "../utils/jsonPreview";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function getEditor(container: HTMLElement) {
  const content = container.querySelector<HTMLElement>(".cm-content")!;
  expect(content).not.toBeNull();
  return EditorView.findFromDOM(content)!;
}

test("JSON 以只读高亮文本展示，可选择复制且不解析字符串中的 HTML", () => {
  const content = '{"html":"<img src=x onerror=alert(1)>","value":1}';
  const formatted = '{\n  "html": "<img src=x onerror=alert(1)>",\n  "value": 1\n}';
  const { container } = render(<JsonPreview content={content} isFullContent />);
  const view = getEditor(container);
  expect(view.state.doc.toString()).toBe(formatted);
  expect(view.state.facet(EditorState.readOnly)).toBe(true);
  expect(view.state.facet(EditorView.editable)).toBe(false);
  expect(view.contentDOM).toHaveAttribute("tabindex", "0");
  expect(view.contentDOM).toHaveAttribute("aria-readonly", "true");
  expect(view.contentDOM.textContent).toContain("<img src=x onerror=alert(1)>");
  expect(container.querySelector("img, script")).toBeNull();
  expect(view.contentDOM.querySelector("span[class]")).not.toBeNull();

  act(() => view.dispatch({ selection: { anchor: 0, head: view.state.doc.length } }));
  const selection = view.state.selection.main;
  expect(view.state.sliceDoc(selection.from, selection.to)).toBe(formatted);
  fireEvent.keyDown(view.contentDOM, { key: "Backspace", code: "Backspace" });
  fireEvent.paste(view.contentDOM, { clipboardData: { getData: () => "changed" } });
  expect(view.state.doc.toString()).toBe(formatted);
});

test.each([
  { content: ' {"a":1} ', isFullContent: false, message: "内容未完整读取，暂无法格式化" },
  { content: ' {"a":} ', isFullContent: true, message: "JSON 格式错误" },
  { content: "[".repeat(1600) + "]".repeat(1600), isFullContent: true, message: "格式化结果超过 4 MiB，已显示原文" },
])("$message，并展示原文", ({ content, isFullContent, message }) => {
  const { container } = render(<JsonPreview content={content} isFullContent={isFullContent} />);
  expect(screen.getByRole("status")).toHaveTextContent(message);
  expect(getEditor(container).state.doc.toString()).toBe(content);
});

test("完整空文件显示空状态", () => {
  const { container } = render(<JsonPreview content="" isFullContent />);
  expect(screen.getByRole("status")).toHaveTextContent("文件为空");
  expect(container.querySelector(".cm-editor")).toBeNull();
});

test("格式化仅随内容或完整读取标记变化重新计算", () => {
  const format = vi.spyOn(jsonPreview, "formatJsonPreview");
  const { rerender } = render(<JsonPreview content='{"a":1}' isFullContent />);
  expect(format).toHaveBeenCalledTimes(1);
  rerender(<JsonPreview content='{"a":1}' isFullContent desktop />);
  expect(format).toHaveBeenCalledTimes(1);
  rerender(<JsonPreview content='{"a":1}' isFullContent={false} desktop />);
  expect(format).toHaveBeenCalledTimes(2);
  rerender(<JsonPreview content='{"a":2}' isFullContent={false} desktop />);
  expect(format).toHaveBeenCalledTimes(3);
});
