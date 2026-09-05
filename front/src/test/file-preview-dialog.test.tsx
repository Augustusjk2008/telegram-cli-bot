import { render } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FilePreviewDialog } from "../components/FilePreviewDialog";
import { FilePreviewSurface } from "../components/FilePreviewSurface";
import type { FileReadResult } from "../services/types";

vi.mock("../components/FilePreviewSurface", () => ({ FilePreviewSurface: vi.fn(() => null) }));

test.each(["desktop", "mobile"] as const)("%s dialog forwards the original read result, including empty content and metadata", (variant) => {
  const result: FileReadResult = { content: "", mode: "head", isFullContent: true, fileSizeBytes: 0 };
  render(<FilePreviewDialog title="empty.json" result={result} variant={variant} onClose={() => {}} />);
  expect(vi.mocked(FilePreviewSurface).mock.lastCall?.[0].result).toBe(result);
});
