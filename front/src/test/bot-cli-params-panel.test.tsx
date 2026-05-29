import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { BotCliParamsPanel } from "../components/BotCliParamsPanel";
import { MockWebBotClient } from "../services/mockWebBotClient";
import type { CliParamsPayload } from "../services/types";

const MODEL_OPTIONS = ["gpt-5.5", "gpt-5.4", "claude-opus-4-7", "claude-sonnet-4-6", "none"];

function cliParamsWithModel(params: Partial<Record<string, unknown>> = {}): CliParamsPayload {
  return {
    cliType: "codex",
    params: {
      model: "gpt-5.5",
      reasoning_effort: "xhigh",
      ...params,
    },
    defaults: {
      model: "gpt-5.4",
      reasoning_effort: "xhigh",
    },
    schema: {
      model: {
        type: "string",
        description: "模型选择",
        nullable: true,
        enum: MODEL_OPTIONS,
      },
      reasoning_effort: {
        type: "string",
        description: "推理努力程度",
        enum: ["xhigh", "high", "medium", "low"],
      },
    },
  };
}

function kimiCliParams(params: Partial<Record<string, unknown>> = {}): CliParamsPayload {
  return {
    cliType: "kimi",
    params: {
      model: "kimi-code/kimi-for-coding",
      thinking: "default",
      stream_json: true,
      ...params,
    },
    defaults: {
      model: "kimi-code/kimi-for-coding",
      thinking: "default",
      stream_json: true,
    },
    schema: {
      model: {
        type: "string",
        description: "模型选择",
        nullable: true,
        enum: ["kimi-code/kimi-for-coding", "none"],
      },
      thinking: {
        type: "string",
        description: "Thinking 模式",
        enum: ["enabled", "disabled", "default"],
      },
      stream_json: {
        type: "boolean",
        description: "启用 stream-json 输出",
      },
    },
  };
}

test("bot cli params panel hides model and only saves visible params", async () => {
  const user = userEvent.setup();
  const updateCliParam = vi.fn(async (_botAlias: string, key: string, value: unknown) => (
    cliParamsWithModel({ [key]: value })
  ));
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCliParams").mockResolvedValue(cliParamsWithModel());
  vi.spyOn(client, "updateCliParam").mockImplementation(updateCliParam);

  render(<BotCliParamsPanel botAlias="main" client={client} />);

  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.queryByLabelText("模型选择")).not.toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("推理努力程度"), "high");
  await user.click(screen.getByRole("button", { name: "保存参数" }));

  await waitFor(() => {
    expect(updateCliParam).toHaveBeenCalledWith("main", "reasoning_effort", "high");
  });
  expect(updateCliParam).not.toHaveBeenCalledWith("main", "model", expect.anything());
});

test("bot cli params panel reset preserves current chat model", async () => {
  const user = userEvent.setup();
  const resetCliParams = vi.fn(async () => cliParamsWithModel({ model: "gpt-5.4" }));
  const updateCliParam = vi.fn(async (_botAlias: string, _key: string, value: unknown) => (
    cliParamsWithModel({ model: value })
  ));
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCliParams").mockResolvedValue(cliParamsWithModel());
  vi.spyOn(client, "resetCliParams").mockImplementation(resetCliParams);
  vi.spyOn(client, "updateCliParam").mockImplementation(updateCliParam);

  render(<BotCliParamsPanel botAlias="main" client={client} />);

  await user.click(await screen.findByRole("button", { name: "恢复默认参数" }));

  await waitFor(() => {
    expect(updateCliParam).toHaveBeenCalledWith("main", "model", "gpt-5.5", "codex");
  });
});

test("bot cli params panel keeps kimi model hidden and saves visible kimi params", async () => {
  const user = userEvent.setup();
  const updateCliParam = vi.fn(async (_botAlias: string, key: string, value: unknown) => (
    kimiCliParams({ [key]: value })
  ));
  const client = new MockWebBotClient();
  vi.spyOn(client, "getCliParams").mockResolvedValue(kimiCliParams());
  vi.spyOn(client, "updateCliParam").mockImplementation(updateCliParam);

  render(<BotCliParamsPanel botAlias="main" client={client} />);

  expect(await screen.findByText("CLI 参数")).toBeInTheDocument();
  expect(screen.queryByLabelText("模型选择")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Thinking 模式")).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("Thinking 模式"), "enabled");
  await user.click(screen.getByRole("button", { name: "保存参数" }));

  await waitFor(() => {
    expect(updateCliParam).toHaveBeenCalledWith("main", "thinking", "enabled");
  });
  expect(updateCliParam).not.toHaveBeenCalledWith("main", "model", expect.anything());
});
