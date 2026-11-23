import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ImmersiveToggleButton } from "../components/ImmersiveToggleButton";

function sizedContainer(clientWidth: number, clientHeight: number, visualWidth: number, visualHeight: number) {
  const container = document.createElement("main");
  Object.defineProperty(container, "clientWidth", { configurable: true, value: clientWidth });
  Object.defineProperty(container, "clientHeight", { configurable: true, value: clientHeight });
  vi.spyOn(container, "getBoundingClientRect").mockReturnValue({
    width: visualWidth,
    height: visualHeight,
    top: 0,
    right: visualWidth,
    bottom: visualHeight,
    left: 0,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
  return container;
}

test("keeps the floating toggle inside the zoomed chat bounds", () => {
  const container = sizedContainer(533, 800, 400, 600);
  const containerRef = { current: container };
  const view = render(
    <ImmersiveToggleButton
      containerRef={containerRef}
      isImmersive={false}
      storageKey="test:immersive-toggle"
      onToggle={vi.fn()}
      zoom={0.75}
    />,
  );

  expect(screen.getByRole("button", { name: "进入沉浸模式" })).toHaveStyle({
    transform: "translate3d(469px, 432px, 0)",
  });

  Object.defineProperty(container, "clientWidth", { configurable: true, value: 320 });
  view.rerender(
    <ImmersiveToggleButton
      containerRef={containerRef}
      isImmersive={false}
      storageKey="test:immersive-toggle"
      onToggle={vi.fn()}
      zoom={1.25}
    />,
  );

  expect(screen.getByRole("button", { name: "进入沉浸模式" })).toHaveStyle({
    transform: "translate3d(264px, 432px, 0)",
  });
});
