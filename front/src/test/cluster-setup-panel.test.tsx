import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ClusterModelTiersPanel } from "../components/ClusterModelTiersPanel";
import { ClusterSetupPanel } from "../components/ClusterSetupPanel";
import { ClusterTemplatePanel } from "../components/ClusterTemplatePanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { DEFAULT_CLUSTER_PANEL_JSON } from "./fixtures/cluster";

test("cluster setup panel shows status and prepare command", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();

  render(<ClusterSetupPanel botAlias="main" client={client} />);

  expect(await screen.findByText("集群 MCP")).toBeInTheDocument();
  expect(screen.getByText("tcb-cluster")).toBeInTheDocument();
  expect(screen.getByText(/Codex：/)).toBeInTheDocument();
  expect(screen.queryByText(/Claude：/)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "生成安装命令" }));

  await waitFor(() => {
    expect(screen.getByText(/codex mcp add tcb-cluster/)).toBeInTheDocument();
  });
});

test("cluster setup panel shows kimi status and prepare command for kimi bot", async () => {
  const user = userEvent.setup();
  const client = new MockWebBotClient();
  await client.addBot({
    alias: "kimi-team",
    botMode: "cli",
    cliType: "kimi",
    cliPath: "kimi",
    workingDir: "C:\\workspace\\kimi-team",
    avatarName: "avatar_01.png",
  });

  render(<ClusterSetupPanel botAlias="kimi-team" client={client} />);

  expect(await screen.findByText("集群 MCP")).toBeInTheDocument();
  expect(screen.getByText(/Kimi：/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "生成安装命令" }));

  await waitFor(() => {
    expect(screen.getByText(/kimi mcp add --transport stdio tcb-cluster --/)).toBeInTheDocument();
  });
});

test("cluster model tiers panel updates selected tier", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();

  render(
    <ClusterModelTiersPanel
      value={{ low: "", medium: "balanced-model", high: "" }}
      modelOptions={["fast-model", "balanced-model", "strong-model"]}
      onChange={onChange}
    />,
  );

  await user.selectOptions(screen.getByLabelText(/低档/), "fast-model");

  expect(onChange).toHaveBeenCalledWith({
    low: "fast-model",
    medium: "balanced-model",
    high: "",
  });
});

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
