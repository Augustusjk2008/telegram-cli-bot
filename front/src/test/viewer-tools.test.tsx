import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { DocumentView } from "../components/plugin-renderers/DocumentView";
import { MockWebBotClient } from "../services/mockWebBotClient";

function setScrollable(element: HTMLElement) {
  element.style.overflowX = "auto";
  element.style.overflowY = "auto";
  Object.defineProperty(element, "scrollHeight", { configurable: true, value: 2000 });
  Object.defineProperty(element, "clientHeight", { configurable: true, value: 400 });
  Object.defineProperty(element, "scrollWidth", { configurable: true, value: 1600 });
  Object.defineProperty(element, "clientWidth", { configurable: true, value: 800 });
  // jsdom does not lay out, so keep scroll offsets as plain writable values.
  Object.defineProperty(element, "scrollTop", { configurable: true, writable: true, value: 0 });
  Object.defineProperty(element, "scrollLeft", { configurable: true, writable: true, value: 0 });
}

test("document hand tool pans the scroller by dragging while select tool leaves it alone", () => {
  render(
    <DocumentView
      botAlias="main"
      client={new MockWebBotClient()}
      view={{
        pluginId: "docx-preview",
        viewId: "document",
        title: "报告",
        renderer: "document",
        mode: "snapshot",
        payload: { path: "report.docx", formatting: "document", blocks: [{ type: "paragraph", runs: [{ text: "正文内容" }] }] },
      }}
    />,
  );
  const scroller = screen.getByTestId("document-view");
  setScrollable(scroller);
  const text = screen.getByText("正文内容");
  const drag = () => {
    fireEvent.pointerDown(text, { button: 0, pointerId: 1, pointerType: "mouse", clientX: 300, clientY: 300 });
    fireEvent.pointerMove(text, { pointerId: 1, pointerType: "mouse", clientX: 250, clientY: 180 });
    fireEvent.pointerUp(text, { pointerId: 1, pointerType: "mouse" });
  };

  const selectButton = screen.getByRole("button", { name: "选择" });
  expect(selectButton).toHaveAttribute("aria-pressed", "true");
  drag();
  expect(scroller.scrollTop).toBe(0);

  fireEvent.click(screen.getByRole("button", { name: "抓手" }));
  expect(screen.getByTestId("document-section-content")).toHaveClass("viewer-hand-tool");
  drag();
  expect(scroller.scrollTop).toBe(120);
  expect(scroller.scrollLeft).toBe(50);

  fireEvent.click(selectButton);
  expect(screen.getByTestId("document-section-content")).not.toHaveClass("viewer-hand-tool");
});
