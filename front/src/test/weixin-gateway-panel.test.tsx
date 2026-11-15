import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { WeixinGatewayPanel } from "../components/admin/WeixinGatewayPanel";
import { MockWebBotClient } from "../services/mockWebBotClient";

afterEach(() => {
  vi.useRealTimers();
});

function setup(status: "waiting_scan" | "confirmed" | "expired" | "cancelled" = "waiting_scan") {
  return {
    setupId: "setup-1",
    status,
    accountId: status === "confirmed" ? "bot@….bot" : "",
    enabled: status === "confirmed",
    configured: status === "confirmed",
    needsRestart: status === "confirmed",
    expiresAt: 1_900_000_000,
    errorCode: status === "expired" ? "weixin_setup_expired" : "",
    errorMessage: status === "expired" ? "二维码已过期" : "",
    qrCodeUrl: "https://weixin.example/qr",
    qrCodeContent: "https://weixin.example/qr",
    qrCodeImage: "data:image/png;base64,qr-image",
  } as const;
}

test("微信面板轮询扫码状态并在成功后提示重启，页面不显示 token", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const client = new MockWebBotClient();
  vi.spyOn(client, "getWeixinStatus").mockResolvedValue({
    enabled: false,
    configured: false,
    accountId: "",
    allowedUserCount: 1,
    connectionStatus: "disabled",
    setup: null,
  });
  vi.spyOn(client, "startWeixinSetup").mockResolvedValue(setup("waiting_scan"));
  vi.spyOn(client, "getWeixinSetup").mockResolvedValue(setup("confirmed"));
  const notice = vi.fn();
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  render(<WeixinGatewayPanel client={client} onNotice={notice} />);

  await screen.findByText("消息网关");
  await user.click(screen.getByRole("button", { name: "开始扫码" }));
  expect(await screen.findByAltText("微信扫码二维码")).toBeInTheDocument();
  expect(screen.queryByText("super-secret-token")).not.toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(1_100);
  await waitFor(() => expect(screen.getByText("微信配置已保存，需要重启应用。")));
  expect(notice).toHaveBeenCalledWith("微信扫码成功，配置已保存，需要重启应用。");
});

test("微信面板展示过期状态并支持取消活动扫码", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "getWeixinStatus").mockResolvedValue({
    enabled: false,
    configured: false,
    accountId: "",
    allowedUserCount: 0,
    connectionStatus: "disabled",
    setup: null,
  });
  const start = vi.spyOn(client, "startWeixinSetup").mockResolvedValue(setup("waiting_scan"));
  const cancel = vi.spyOn(client, "cancelWeixinSetup").mockResolvedValue(setup("cancelled"));
  render(<WeixinGatewayPanel client={client} />);
  const user = userEvent.setup();
  await screen.findByText("消息网关");
  await user.click(screen.getByRole("button", { name: "开始扫码" }));
  expect(start).toHaveBeenCalledTimes(1);
  await user.click(await screen.findByRole("button", { name: "取消扫码" }));
  expect(cancel).toHaveBeenCalledWith("setup-1");
  expect(screen.queryByText("二维码已过期")).not.toBeInTheDocument();
  expect(screen.getByText("已取消")).toBeInTheDocument();
});
