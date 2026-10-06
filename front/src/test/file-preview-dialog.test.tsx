import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { FilePreviewPane } from "../components/FilePreviewPane";
import { FilePreviewSurface } from "../components/FilePreviewSurface";
import type { FileReadResult } from "../services/types";

vi.mock("../components/FilePreviewSurface", () => ({ FilePreviewSurface: vi.fn(() => null) }));

test.each(["desktop", "mobile"] as const)("%s dialog forwards the original read result, including empty content and metadata", (variant) => {
  const result: FileReadResult = { content: "", mode: "head", isFullContent: true, fileSizeBytes: 0 };
  render(<FilePreviewDialog title="empty.json" result={result} variant={variant} onClose={() => {}} />);
  expect(vi.mocked(FilePreviewSurface).mock.lastCall?.[0].result).toBe(result);
});

test("file preview pane exposes full read for an incomplete remote cat preview", () => {
  const onLoadFull = vi.fn();
  render(
    <FilePreviewPane
      title="/remote/project/app.py"
      result={{ content: "partial", mode: "cat", isFullContent: false }}
      onLoadFull={onLoadFull}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "全文读取" }));
  expect(onLoadFull).toHaveBeenCalledTimes(1);
});
