import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { PluginCatalog } from "../components/PluginCatalog";
import type { PluginSummary } from "../services/types";

function plugin(overrides: Partial<PluginSummary>): PluginSummary {
  return {
    id: "sample",
    schemaVersion: 2,
    name: "Sample",
    version: "1.0.0",
    description: "",
    enabled: true,
    views: [{ id: "main", title: "Main", renderer: "table", viewMode: "snapshot", dataProfile: "light" }],
    fileHandlers: [],
    catalogActions: [],
    runtime: {
      type: "python",
      entry: "main.py",
      protocol: "jsonrpc-stdio",
      permissions: { workspaceRead: true, workspaceList: false, workspaceWrite: false, tempArtifacts: false },
    },
    ...overrides,
  };
}

test("uses the manifest icon when provided and a generated icon otherwise, and filters by search", () => {
  render(
    <PluginCatalog
      plugins={[
        plugin({ id: "branded", name: "Branded", iconUrl: "data:image/svg+xml;base64,PHN2Zy8+" }),
        plugin({
          id: "csv-preview",
          name: "CSV Preview",
          fileHandlers: [{ id: "csv", label: "CSV", extensions: [".csv"], viewId: "main" }],
        }),
      ]}
    />,
  );

  expect(screen.getByTestId("plugin-icon-branded").dataset.iconSource).toBe("manifest");
  expect(screen.getByTestId("plugin-icon-csv-preview").dataset.iconSource).toBe("generated");

  fireEvent.change(screen.getByRole("searchbox", { name: "搜索插件" }), { target: { value: ".csv" } });

  expect(screen.queryByTestId("plugin-catalog-item-branded")).toBeNull();
  expect(screen.getByTestId("plugin-catalog-item-csv-preview")).toBeTruthy();
});
