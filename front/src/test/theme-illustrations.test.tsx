import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";
import { builtinIllustrationScene } from "../theme/illustrationPresets";

function appearanceFor(
  setId: "forest-grove" | "apollo-plan" | "none" = "forest-grove",
) {
  const scene = (surface: "workbench" | "adminCenter" | "agentManager") => builtinIllustrationScene(setId, surface);
  return resolveAppearance({
    ...BUILTIN_THEME,
    appearance: {
      ...BUILTIN_THEME.appearance,
      illustrations: {
        opacity: setId === "none" ? 0 : 0.12,
        surfaces: {
          workbench: setId !== "none",
          adminCenter: setId !== "none",
          agentManager: setId !== "none",
        },
        scenes: {
          workbench: scene("workbench"),
          adminCenter: scene("adminCenter"),
          agentManager: scene("agentManager"),
        },
      },
    },
  });
}

describe("ThemeIllustrationLayer", () => {
  it("does not add a layer for the default no-illustration theme", () => {
    render(<ThemeIllustrationLayer surface="workbench" appearance={appearanceFor("none")} />);
    expect(screen.queryByTestId("theme-illustration-layer-workbench")).not.toBeInTheDocument();
  });

  it("renders a decorative, non-interactive fixed asset layer", () => {
    render(<ThemeIllustrationLayer surface="workbench" appearance={appearanceFor()} />);
    const layer = screen.getByTestId("theme-illustration-layer-workbench");
    expect(layer).toHaveAttribute("aria-hidden", "true");
    expect(layer).toHaveStyle({ pointerEvents: "none" });
    expect(layer).toHaveAttribute("data-theme-illustration-count", "2");
    expect(layer.querySelectorAll(".theme-illustration-art")).toHaveLength(2);
  });

  it("renders the independent admin and agent layer groups in manifest order", () => {
    const appearance = appearanceFor();
    render(
      <>
        <ThemeIllustrationLayer surface="adminCenter" appearance={appearance} />
        <ThemeIllustrationLayer surface="agentManager" appearance={appearance} />
      </>,
    );
    expect(screen.getByTestId("theme-illustration-layer-adminCenter")).toHaveAttribute("data-theme-illustration-count", "1");
    expect(screen.getByTestId("theme-illustration-layer-agentManager")).toHaveAttribute("data-theme-illustration-count", "1");
    expect(screen.getByTestId("theme-illustration-layer-adminCenter").querySelector("img")?.getAttribute("data-theme-illustration-layer-id")).toBe("adminCenter-background");
    expect(screen.getByTestId("theme-illustration-layer-agentManager").querySelector("img")?.getAttribute("data-theme-illustration-layer-id")).toBe("agentManager-background");
  });

  it("resolves and renders the Apollo Plan scene assets", () => {
    const appearance = appearanceFor("apollo-plan");
    expect(appearance.illustrations.resources.workbench).toBe(
      "/assets/theme-illustrations/apollo-plan/workbench/background.webp",
    );
    expect(appearance.illustrations.resources.adminCenter).toBe(
      "/assets/theme-illustrations/apollo-plan/admin-center/background.webp",
    );
    expect(appearance.illustrations.resources.agentManager).toBe(
      "/assets/theme-illustrations/apollo-plan/agent-manager/background.webp",
    );
    render(
      <>
        <ThemeIllustrationLayer surface="workbench" appearance={appearance} />
        <ThemeIllustrationLayer surface="adminCenter" appearance={appearance} />
        <ThemeIllustrationLayer surface="agentManager" appearance={appearance} />
      </>,
    );
    expect(screen.getByTestId("theme-illustration-layer-workbench")).toHaveAttribute(
      "data-theme-illustration-count",
      "1",
    );
    expect(screen.getByTestId("theme-illustration-layer-adminCenter").querySelector("img"))
      .toHaveAttribute("data-theme-illustration-asset", "apollo-plan-admin-center");
    expect(screen.getByTestId("theme-illustration-layer-agentManager").querySelector("img"))
      .toHaveAttribute("data-theme-illustration-asset", "apollo-plan-agent-manager");
  });

  it("scopes the workbench illustration to the main area and sidebar area", () => {
    const appearance = appearanceFor();
    render(
      <>
        <ThemeIllustrationLayer surface="workbench" zone="main" appearance={appearance} />
        <ThemeIllustrationLayer surface="workbench" zone="sidebar" appearance={appearance} />
      </>,
    );
    const layers = screen.getAllByTestId("theme-illustration-layer-workbench");
    const main = layers.find((layer) => layer.getAttribute("data-theme-illustration-zone") === "main");
    const sidebar = layers.find((layer) => layer.getAttribute("data-theme-illustration-zone") === "sidebar");
    expect(main).toHaveAttribute("data-theme-illustration-count", "1");
    expect(main?.querySelector("img")).toHaveAttribute("data-theme-illustration-layer-id", "workbench-background");
    expect(sidebar).toHaveAttribute("data-theme-illustration-count", "1");
    expect(sidebar?.querySelector("img")).toHaveAttribute("data-theme-illustration-layer-id", "left-edge-foliage");
  });
});
