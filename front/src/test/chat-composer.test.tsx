import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ChatComposer } from "../components/ChatComposer";

test("attachment input forwards selected files to the upload handler", async () => {
  const user = userEvent.setup();
  const onAttachFiles = vi.fn();
  const file = new File(["hello"], "report.txt", { type: "text/plain" });

  render(
    <ChatComposer
      onSend={() => {}}
      onAttachFiles={onAttachFiles}
      onRemoveAttachment={() => {}}
      attachments={[]}
    />,
  );

  await user.upload(screen.getByLabelText("上传附件"), file);

  expect(onAttachFiles).toHaveBeenCalledTimes(1);
  expect(onAttachFiles).toHaveBeenCalledWith([
    expect.objectContaining({
      name: "report.txt",
    }),
  ]);
});
