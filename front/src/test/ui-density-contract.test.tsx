import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatComposer } from "../components/ChatComposer";
import { SurfacePanel } from "../components/SurfacePanel";
import { ToolbarButton } from "../components/ToolbarButton";

function readSource(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

describe("compact UI contract", () => {
  it("separates flat surfaces from floating overlays", () => {
    const tokens = readSource("../styles/tokens.css");

    expect(tokens).toContain("--shadow-surface: none");
    expect(tokens).toContain("--shadow-float: var(--shadow-soft)");
    expect(tokens).toContain("--shadow-modal: var(--shadow-card)");
    expect(tokens).toContain("--space-4: 12px");
  });

  it("keeps shared panels compact while preserving 32px toolbar targets", () => {
    render(
      <SurfacePanel padded data-testid="panel">
        <ToolbarButton>操作</ToolbarButton>
      </SurfacePanel>,
    );

    expect(screen.getByTestId("panel")).toHaveClass("p-3", "shadow-[var(--shadow-surface)]");
    expect(screen.getByRole("button", { name: "操作" })).toHaveClass("h-8");
  });

  it("keeps the cluster strip and message input flat with one divider", () => {
    render(
      <ChatComposer
        onSend={() => undefined}
        onAttachFiles={() => undefined}
        onRemoveAttachment={() => undefined}
        attachments={[]}
        clusterMode
        agents={[
          {
            id: "tester",
            name: "测试专家",
            systemPrompt: "",
            enabled: true,
            isMain: false,
          },
        ]}
      />,
    );

    const clusterStrip = screen.getByTestId("chat-composer-cluster-strip");
    const inputSurface = screen.getByTestId("chat-composer-input-surface");

    expect(clusterStrip).toHaveClass("border-b", "border-[var(--workbench-hairline)]");
    expect(clusterStrip).not.toHaveClass(
      "rounded-lg",
      "border",
      "bg-[var(--workbench-panel-elevated-bg)]",
    );
    expect(inputSurface).not.toHaveClass(
      "rounded-lg",
      "border",
      "bg-[var(--workbench-panel-bg)]",
      "shadow-[var(--shadow-surface)]",
    );
    expect(
      clusterStrip.compareDocumentPosition(inputSurface) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("keeps mobile safety and chat reading contracts intact", () => {
    const mobileShell = readSource("../app/MobileShell.tsx");
    const globalStyles = readSource("../styles/global.css");
    const theme = readSource("../theme.ts");

    expect(mobileShell).toContain("h-[100dvh]");
    expect(mobileShell).toContain("safe-area-inset-bottom");
    expect(mobileShell).not.toContain("shadow-xl");
    expect(globalStyles).toContain("var(--chat-body-paragraph-spacing)");
    expect(theme).toContain("CHAT_BODY_LINE_HEIGHT_OPTIONS");
  });
});
