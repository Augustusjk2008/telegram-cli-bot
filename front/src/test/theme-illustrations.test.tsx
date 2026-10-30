import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";
import { builtinIllustrationScene } from "../theme/illustrationPresets";

function appearanceFor(setId: "forest-grove" | "none" = "forest-grove") {
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
    expect(layer.querySelector("[data-theme-illustration-layer-id=workbench-background]")).toHaveStyle({ width: "100%", height: "100%" });
    expect(layer.querySelector("[data-theme-illustration-layer-id=left-edge-foliage]")).toHaveStyle({ width: "27%", height: "92%" });
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
});
