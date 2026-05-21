import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ClusterTemplatePanel } from "../components/ClusterTemplatePanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { DEFAULT_CLUSTER_PANEL_JSON } from "./fixtures/cluster";

test("cluster template panel previews and applies a template after confirmation", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const preview = vi.spyOn(client, "previewClusterTemplate");
  const apply = vi.spyOn(client, "applyClusterTemplate");
  vi.spyOn(window, "confirm").mockReturnValue(true);

  render(<ClusterTemplatePanel botAlias="main" client={client} canManage onApplied={() => {}} />);

  await user.click(await screen.findByRole("button", { name: "预览 全量测试集群" }));
  expect(preview).toHaveBeenCalledWith("main", "full_test");
  expect(await screen.findByText("将新增")).toBeInTheDocument();
  expect(screen.getAllByText("tester").length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "覆盖应用 全量测试集群" }));
  expect(apply).toHaveBeenCalledWith("main", "full_test", true);
});

test("cluster template panel previews llm json bundle", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  const preview = vi.spyOn(client, "previewClusterConfigBundle");

  render(<ClusterTemplatePanel botAlias="main" client={client} canManage onApplied={() => {}} />);

  await user.click(await screen.findByRole("button", { name: "JSON 配置" }));
  fireEvent.change(screen.getByLabelText("集群 JSON 配置"), {
    target: { value: JSON.stringify(DEFAULT_CLUSTER_PANEL_JSON) },
  });
  await user.click(screen.getByRole("button", { name: "预览 JSON 配置" }));

  await waitFor(() => {
    expect(preview).toHaveBeenCalledTimes(1);
  });
});
