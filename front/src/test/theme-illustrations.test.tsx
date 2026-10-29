import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";
import { builtinIllustrationAsset } from "../theme/illustrationPresets";

function appearanceFor(setId: "forest-grove" | "none" = "forest-grove") {
  const asset = (surface: "workbench" | "adminCenter" | "agentManager") => builtinIllustrationAsset(setId, surface);
  return resolveAppearance({
    ...BUILTIN_THEME,
    appearance: {
      ...BUILTIN_THEME.appearance,
      illustrations: {
        opacity: setId === "none" ? 0 : 0.12,
        surfaces: {
          workbench: setId !== "none",
          adminCenter: false,
          agentManager: false,
        },
        scenes: {
          workbench: asset("workbench"),
          adminCenter: asset("adminCenter"),
          agentManager: asset("agentManager"),
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
    expect(layer.style.getPropertyValue("--theme-illustration-image")).toContain(
      "/assets/theme-illustrations/forest-grove/workbench.webp",
    );
    expect(layer.querySelector(".theme-illustration-art")).toBeInTheDocument();
  });
});
