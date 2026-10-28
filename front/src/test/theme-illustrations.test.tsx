import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";

function appearanceFor(
  setId: "forest-grove" | "none" = "forest-grove",
) {
  return resolveAppearance({
    ...BUILTIN_THEME,
    appearance: {
      ...BUILTIN_THEME.appearance,
      illustrations: {
        setId,
        opacity: setId === "none" ? 0 : 0.12,
        surfaces: {
          workbench: setId !== "none",
          chat: setId !== "none",
          topbar: false,
          management: false,
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
      "/assets/theme-illustrations/forest-grove-workbench.svg",
    );
    expect(layer.querySelector(".theme-illustration-art")).toBeInTheDocument();
  });
});
