import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { LoginScreen } from "../screens/LoginScreen";

test("login screen submits username and password", async () => {
  const user = userEvent.setup();
  const onLogin = vi.fn();

  render(<LoginScreen onLogin={onLogin} />);

  await user.type(screen.getByLabelText("访问口令"), "alice");
  await user.type(screen.getByLabelText("密码"), "pw-123");
  await user.click(screen.getByRole("button", { name: "登录" }));

  expect(onLogin).toHaveBeenCalledWith({
    username: "alice",
    password: "pw-123",
  });
});

test("login screen switches to register mode and submits register code", async () => {
  const user = userEvent.setup();
  const onRegister = vi.fn();

  render(<LoginScreen onRegister={onRegister} />);

  await user.click(screen.getByRole("tab", { name: "注册" }));
  expect(screen.getByLabelText("注册码")).toBeInTheDocument();

  await user.type(screen.getByLabelText("用户名"), "alice");
  await user.type(screen.getByLabelText("密码"), "pw-123");
  await user.type(screen.getByLabelText("注册码"), "INVITE-001");
  await user.click(screen.getByRole("button", { name: "注册并登录" }));

  expect(onRegister).toHaveBeenCalledWith({
    username: "alice",
    password: "pw-123",
    registerCode: "INVITE-001",
  });
});

test("login screen exposes guest entry", async () => {
  const user = userEvent.setup();
  const onGuestLogin = vi.fn();

  render(<LoginScreen onGuestLogin={onGuestLogin} />);

  await user.click(screen.getByRole("button", { name: "以 guest 进入" }));

  expect(onGuestLogin).toHaveBeenCalledTimes(1);
});
