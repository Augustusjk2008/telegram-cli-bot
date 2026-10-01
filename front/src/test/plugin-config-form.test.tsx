import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PluginConfigForm } from "../components/plugins/PluginConfigForm";
import type { PluginSummary } from "../services/types";

const plugin = {
  id: "hex-preview",
  schemaVersion: 2,
  name: "Hex Preview",
  version: "1.0.0",
  description: "",
  views: [],
  fileHandlers: [],
  catalogActions: [],
  runtime: {
    type: "python",
    entry: "backend/main.py",
    protocol: "jsonrpc-stdio",
    permissions: { workspaceRead: true, workspaceList: false, tempArtifacts: false },
  },
  config: {},
  configSchema: {
    title: "Hex settings",
    sections: [{
      id: "preview",
      fields: [
        { key: "maxPreviewBytes", label: "Maximum bytes", type: "integer", default: 16384, minimum: 256, maximum: 262144 },
        { key: "bytesPerRow", label: "Bytes per row", type: "integer", default: 16, minimum: 8, maximum: 32 },
      ],
    }],
  },
} as PluginSummary;

describe("PluginConfigForm", () => {
  it("renders schema defaults and validates numeric ranges before saving", () => {
    const onSubmit = vi.fn();
    render(<PluginConfigForm plugin={plugin} onSubmit={onSubmit} />);

    const maxBytes = screen.getByLabelText("Maximum bytes") as HTMLInputElement;
    expect(maxBytes.value).toBe("16384");
    expect(screen.getByLabelText("Bytes per row")).toHaveValue(16);

    fireEvent.change(maxBytes, { target: { value: "128" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 Hex Preview 设置" }));
    expect(screen.getByText("Maximum bytes 不能小于 256")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(maxBytes, { target: { value: "32768" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 Hex Preview 设置" }));
    expect(onSubmit).toHaveBeenCalledWith({ config: { maxPreviewBytes: 32768, bytesPerRow: 16 } });
  });
});
