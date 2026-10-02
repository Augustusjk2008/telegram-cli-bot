import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HexView } from "../components/plugin-renderers/HexView";
import type { HexViewPayload } from "../services/types";

function makePayload(path = "sample.bin", rowCount = 16_384): HexViewPayload {
  return {
    path,
    fileSizeBytes: rowCount * 16,
    previewBytes: rowCount ? (rowCount - 1) * 16 + 3 : 0,
    bytesPerRow: 16,
    entropyBuckets: [],
    rows: Array.from({ length: rowCount }, (_, index) => ({
      offset: index * 16,
      hex: index === rowCount - 1 ? ["42", "43", "44"] : Array<string>(16).fill("41"),
      ascii: index === rowCount - 1 ? "BCD" : "A".repeat(16),
    })),
  };
}

describe("HexView", () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(240);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("mounts only visible rows and overscan for a large preview", () => {
    render(<HexView title="sample.bin" payload={makePayload()} />);

    const list = screen.getByTestId("virtualized-hex-rows");
    expect(within(list).getAllByTestId("hex-row").length).toBeLessThanOrEqual(30);
    expect(within(list).getByText("00000000")).toBeInTheDocument();
    expect(within(list).queryByText("0003FFF0")).not.toBeInTheDocument();
  });

  it("renders the final partial row after scrolling to the end", async () => {
    const payload = makePayload();
    render(<HexView title="sample.bin" payload={payload} />);
    const list = screen.getByTestId("virtualized-hex-rows");
    list.scrollTop = payload.rows.length * 24 - 240;
    fireEvent.scroll(list);

    const address = await within(list).findByText("0003FFF0");
    const row = address.closest('[data-testid="hex-row"]') as HTMLElement;
    expect(within(row).getByText("42 43 44")).toBeInTheDocument();
    expect(within(row).getByText("BCD")).toBeInTheDocument();
    expect(within(list).queryByText("00000000")).not.toBeInTheDocument();
  });

  it("renders an empty preview without rows", () => {
    render(<HexView title="empty.bin" payload={makePayload("empty.bin", 0)} />);

    expect(screen.getByTestId("hex-view")).toBeInTheDocument();
    expect(screen.queryAllByTestId("hex-row")).toHaveLength(0);
  });

  it("resets the scroll position when switching paths with the same filename", async () => {
    const payload = makePayload("first/sample.bin");
    const { rerender } = render(<HexView title="sample.bin" payload={payload} />);
    const list = screen.getByTestId("virtualized-hex-rows");
    list.scrollTop = payload.rows.length * 24 - 240;
    fireEvent.scroll(list);
    await within(list).findByText("0003FFF0");

    rerender(<HexView title="sample.bin" payload={{ ...payload, path: "second/sample.bin" }} />);

    const nextList = screen.getByTestId("virtualized-hex-rows");
    await waitFor(() => expect(nextList.scrollTop).toBe(0));
    expect(within(nextList).getByText("00000000")).toBeInTheDocument();
    expect(within(nextList).queryByText("0003FFF0")).not.toBeInTheDocument();
  });
});
