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

test("pastes clipboard images as chat attachments", () => {
  const onAttachFiles = vi.fn();
  const image = new File(["image data"], "", { type: "image/png" });
  render(
    <ChatComposer
      onSend={vi.fn()}
      onAttachFiles={onAttachFiles}
      attachments={[]}
      onRemoveAttachment={vi.fn()}
    />,
  );

  fireEvent.paste(screen.getByRole("textbox"), {
    clipboardData: {
      items: [{ kind: "file", type: "image/png", getAsFile: () => image }],
    },
  });

  expect(onAttachFiles).toHaveBeenCalledOnce();
  const [files] = onAttachFiles.mock.calls[0];
  expect(files).toHaveLength(1);
  expect(files[0]).toBeInstanceOf(File);
  expect(files[0].type).toBe("image/png");
  expect(files[0].name).toMatch(/^pasted-image-\d+-0\.png$/);
});
