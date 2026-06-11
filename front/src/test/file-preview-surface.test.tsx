import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { FilePreviewSurface } from "../components/FilePreviewSurface";
import type { FileReadResult } from "../services/types";

function result(overrides: Partial<FileReadResult>): FileReadResult {
  return {
    content: "",
    mode: "cat",
    fileSizeBytes: 0,
    isFullContent: true,
    ...overrides,
  };
}

test("renders markdown preview with shared surface", () => {
  render(
    <FilePreviewSurface
      title="README.md"
      result={result({ content: "# Hello\n\nShared preview" })}
    />,
  );

  expect(screen.getByRole("heading", { name: "Hello" })).toBeInTheDocument();
  expect(screen.getByText("Shared preview")).toBeInTheDocument();
});

test("renders image preview with shared surface", () => {
  render(
    <FilePreviewSurface
      title="logo.png"
      result={result({
        previewKind: "image",
        contentType: "image/png",
        contentBase64: "aGVsbG8=",
      })}
    />,
  );

  expect(screen.getByRole("img", { name: "logo.png" })).toHaveAttribute(
    "src",
    "data:image/png;base64,aGVsbG8=",
  );
});

test("resolves relative markdown images through bot download url", () => {
  render(
    <FilePreviewSurface
      title="docs/README.md"
      botAlias="main"
      result={result({ content: "![Diagram](images/flow.png)" })}
    />,
  );

  expect(screen.getByRole("img", { name: "Diagram" })).toHaveAttribute(
    "src",
    "/api/bots/main/files/download?filename=docs%2Fimages%2Fflow.png",
  );
});

test("renders svg preview from file content", () => {
  render(
    <FilePreviewSurface
      title="logo.svg"
      result={result({ content: "<svg><circle /></svg>" })}
    />,
  );

  expect(screen.getByRole("img", { name: "logo.svg" }).getAttribute("src")).toMatch(
    /^(blob:|data:image\/svg\+xml;charset=utf-8,)/,
  );
});

test("keeps existing preview visible while loading refreshes", () => {
  render(
    <FilePreviewSurface
      title="README.md"
      loading
      result={result({ content: "# Existing" })}
    />,
  );

  expect(screen.getByRole("heading", { name: "Existing" })).toBeInTheDocument();
  expect(screen.queryByText("加载预览...")).not.toBeInTheDocument();
});

test("renders html preview in sandboxed iframe", () => {
  render(
    <FilePreviewSurface
      title="index.html"
      result={result({ content: "<h1>HTML</h1>", previewKind: "html" })}
    />,
  );

  const iframe = screen.getByTitle("index.html");
  expect(iframe).toHaveAttribute("sandbox", "");
  expect(iframe).toHaveAttribute("srcdoc", "<h1>HTML</h1>");
});

test("renders plain text preview without editor actions", () => {
  render(
    <FilePreviewSurface
      title="notes.txt"
      result={result({ content: "plain text" })}
    />,
  );

  expect(screen.getByText("plain text")).toBeInTheDocument();
  expect(screen.queryByText("在编辑器中打开")).not.toBeInTheDocument();
  expect(screen.queryByText("下载")).not.toBeInTheDocument();
  expect(screen.queryByText("全文读取")).not.toBeInTheDocument();
});

test("delegates markdown file link clicks", async () => {
  const user = userEvent.setup();
  const onFileLinkClick = vi.fn();

  render(
    <FilePreviewSurface
      title="docs/README.md"
      result={result({ content: "[Open guide](guide.md)" })}
      onFileLinkClick={onFileLinkClick}
    />,
  );

  await user.click(screen.getByRole("link", { name: "Open guide" }));

  expect(onFileLinkClick).toHaveBeenCalledTimes(1);
  expect(onFileLinkClick).toHaveBeenCalledWith("guide.md");
});
