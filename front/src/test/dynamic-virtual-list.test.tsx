import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DynamicVirtualList, type DynamicVirtualListHandle } from "../components/virtual/DynamicVirtualList";

type ResizeObserverCallbackLike = ConstructorParameters<typeof ResizeObserver>[0];

class TestResizeObserver {
  static instances: TestResizeObserver[] = [];

  readonly callback: ResizeObserverCallbackLike;
  target: Element | null = null;

  constructor(callback: ResizeObserverCallbackLike) {
    this.callback = callback;
    TestResizeObserver.instances.push(this);
  }

  observe(target: Element) {
    this.target = target;
  }

  unobserve() {}

  disconnect() {
    this.target = null;
  }

  trigger(height: number) {
    if (!this.target) {
      throw new Error("ResizeObserver target is not attached");
    }
    this.callback(
      [{ target: this.target, contentRect: { height } } as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
}

function rowObserver(label: string) {
  const observer = TestResizeObserver.instances.find((instance) => instance.target?.textContent === label);
  if (!observer) {
    throw new Error(`Missing row observer for ${label}`);
  }
  return observer;
}

describe("DynamicVirtualList", () => {
  beforeEach(() => {
    TestResizeObserver.instances = [];
    vi.stubGlobal("ResizeObserver", TestResizeObserver);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(120);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("limits mounted rows for large collections", () => {
    const items = Array.from({ length: 1_000 }, (_, index) => `row-${index}`);

    render(
      <DynamicVirtualList
        items={items}
        getKey={(item) => item}
        renderItem={(item) => <div>{item}</div>}
        estimateHeight={20}
        overscan={2}
        dataTestId="list"
      />,
    );

    const list = screen.getByTestId("list");
    expect(list.querySelectorAll(".absolute").length).toBeLessThan(20);
    expect(screen.getByText("row-0")).toBeInTheDocument();
    expect(screen.queryByText("row-999")).not.toBeInTheDocument();
  });

  it("recomputes total height after a measured row changes", () => {
    render(
      <DynamicVirtualList
        items={["row-0", "row-1", "row-2"]}
        getKey={(item) => item}
        renderItem={(item) => <div>{item}</div>}
        estimateHeight={20}
        dataTestId="list"
      />,
    );

    const spacer = screen.getByTestId("list").firstElementChild as HTMLElement;
    expect(spacer.style.height).toBe("60px");

    act(() => rowObserver("row-0").trigger(50));

    expect(spacer.style.height).toBe("90px");
  });

  it("preserves the visible anchor when rows are prepended and remeasured", () => {
    const { rerender } = render(
      <DynamicVirtualList
        items={["row-a", "row-b", "row-c"]}
        getKey={(item) => item}
        renderItem={(item) => <div>{item}</div>}
        estimateHeight={20}
        preserveScrollOnPrepend
        dataTestId="list"
      />,
    );
    const list = screen.getByTestId("list");
    list.scrollTop = 40;
    fireEvent.scroll(list);

    rerender(
      <DynamicVirtualList
        items={["row-new", "row-a", "row-b", "row-c"]}
        getKey={(item) => item}
        renderItem={(item) => <div>{item}</div>}
        estimateHeight={20}
        preserveScrollOnPrepend
        dataTestId="list"
      />,
    );

    expect(list.scrollTop).toBe(60);

    act(() => rowObserver("row-new").trigger(40));

    expect(list.scrollTop).toBe(80);
  });

  it("scrolls by stable key and exposes the visible range", () => {
    const ref = createRef<DynamicVirtualListHandle>();
    const items = Array.from({ length: 100 }, (_, index) => `row-${index}`);
    render(
      <DynamicVirtualList
        ref={ref}
        items={items}
        getKey={(item) => item}
        renderItem={(item) => <div>{item}</div>}
        estimateHeight={20}
        dataTestId="list"
      />,
    );

    let scrolled = false;
    act(() => {
      scrolled = ref.current?.scrollToKey("row-50", { align: "center" }) || false;
    });
    expect(scrolled).toBe(true);
    expect(screen.getByTestId("list").scrollTop).toBe(950);
    expect(ref.current?.getVisibleRange()).toEqual({
      startIndex: 47,
      endIndex: 53,
      keys: ["row-47", "row-48", "row-49", "row-50", "row-51", "row-52", "row-53"],
    });
    expect(ref.current?.scrollToKey("missing")).toBe(false);
  });

  it("invalidates cached measurements", () => {
    const ref = createRef<DynamicVirtualListHandle>();
    render(
      <DynamicVirtualList
        ref={ref}
        items={["row-0", "row-1"]}
        getKey={(item) => item}
        renderItem={(item) => <div>{item}</div>}
        estimateHeight={20}
        dataTestId="list"
      />,
    );
    const spacer = screen.getByTestId("list").firstElementChild as HTMLElement;
    act(() => rowObserver("row-0").trigger(50));
    expect(spacer.style.height).toBe("70px");

    act(() => ref.current?.invalidateMeasurement("row-0"));
    expect(spacer.style.height).toBe("40px");
  });
});
