import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ChatComposer } from "../components/ChatComposer";

test("a running task turns the empty-draft send button into terminate, while a typed draft can still be sent", () => {
  const onSend = vi.fn();
  const onStop = vi.fn();
  const view = render(<ChatComposer onSend={onSend} onStop={onStop} attachments={[]} onRemoveAttachment={vi.fn()} />);

  expect(screen.queryByRole("button", { name: "发送" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "终止任务" }));
  expect(onStop).toHaveBeenCalledOnce();

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "补充说明" } });
  expect(screen.queryByRole("button", { name: "终止任务" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(onSend).toHaveBeenCalledWith("补充说明");

  view.rerender(<ChatComposer onSend={onSend} attachments={[]} onRemoveAttachment={vi.fn()} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
  expect(screen.getByRole("button", { name: "发送" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "终止任务" })).not.toBeInTheDocument();
});
