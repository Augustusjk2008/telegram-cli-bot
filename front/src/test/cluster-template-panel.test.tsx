import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ClusterTemplatePanel } from "../components/ClusterTemplatePanel";
import { MockWebBotClient } from "../services/mockWebBotClient";

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
  fireEvent.change(screen.getByLabelText("集群 JSON 配置"), { target: { value: JSON.stringify({
    id: "custom",
    name: "自定义",
    description: "测试",
    cluster: { enabled: true, writePolicy: "main_only", conflictPolicy: "snapshot_diff", maxParallelAgents: 1, defaultTimeoutSeconds: 600, modelTiers: { low: "", medium: "", high: "" } },
    agents: [{ id: "tester", name: "测试", systemPrompt: "跑测试", enabled: true, cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 600 } }],
  }) } });
  await user.click(screen.getByRole("button", { name: "预览 JSON 配置" }));

  await waitFor(() => {
    expect(preview).toHaveBeenCalledTimes(1);
  });
});
