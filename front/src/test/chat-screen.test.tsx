import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatScreen } from "../screens/ChatScreen";

test("shows a user message after sending text", async () => {
  render(<ChatScreen botAlias="main" />);
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "修一下这个 bug");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("修一下这个 bug")).toBeInTheDocument();
});

test("shows streaming state before assistant message completes", async () => {
  render(<ChatScreen botAlias="main" />);
  await userEvent.type(screen.getByPlaceholderText("输入消息"), "继续");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText(/正在生成/)).toBeInTheDocument();
});
