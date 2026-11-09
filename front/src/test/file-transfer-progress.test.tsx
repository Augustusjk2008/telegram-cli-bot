import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { FilesScreen } from "../screens/FilesScreen";
import { MockWebBotClient } from "../services/mockWebBotClient";
import { PersistentTerminalProvider } from "../terminal/PersistentTerminalProvider";
import { DesktopWorkbench } from "../workbench/DesktopWorkbench";

function pendingUntilAborted(signal?: AbortSignal) {
  return new Promise<void>((_resolve, reject) => {
    signal?.addEventListener("abort", () => {
      reject(new DOMException("已取消", "AbortError"));
    }, { once: true });
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

test("mobile files screen shows upload progress, blocks another upload and cancels quietly", async () => {
  const client = new MockWebBotClient();
  const list = vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "C:\\workspace",
    entries: [{ name: "README.md", isDir: false }],
  });
  let uploadSignal: AbortSignal | undefined;
  vi.spyOn(client, "uploadFile").mockImplementation(((_botAlias, _file, onProgress, signal) => {
    uploadSignal = signal;
    onProgress?.({ uploadedBytes: 2 * 1024 * 1024, totalBytes: 5 * 1024 * 1024, percent: 40 });
    return pendingUntilAborted(signal);
  }) as typeof client.uploadFile);
  render(<FilesScreen botAlias="main" client={client} />);
  await screen.findByText("README.md");
  list.mockClear();

  fireEvent.change(screen.getByLabelText("上传文件"), { target: { files: [new File(["x"], "video.mp4")] } });

  expect(await screen.findByRole("progressbar", { name: "video.mp4 上传进度" })).toHaveAttribute("aria-valuenow", "40");
  expect(screen.getByRole("status", { name: "上传进度" })).toHaveTextContent("2.0 MB / 5.0 MB");
  expect(screen.getByLabelText("上传文件")).toBeDisabled();

  fireEvent.click(screen.getByRole("button", { name: "取消上传" }));

  await waitFor(() => expect(screen.queryByRole("status", { name: "上传进度" })).not.toBeInTheDocument());
  expect(uploadSignal?.aborted).toBe(true);
  expect(screen.getByLabelText("上传文件")).toBeEnabled();
  expect(screen.queryByText("已取消")).not.toBeInTheDocument();
  expect(list).not.toHaveBeenCalled();
});

test("asks for Chinese confirmation before uploading a file larger than 20MB", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({ workingDir: "C:\\workspace", entries: [] });
  const upload = vi.spyOn(client, "uploadFile").mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<FilesScreen botAlias="main" client={client} />);
  await waitFor(() => expect(screen.getByLabelText("上传文件")).toBeEnabled());

  const file = new File(["x"], "large.bin");
  Object.defineProperty(file, "size", { configurable: true, value: 20 * 1024 * 1024 + 1 });
  fireEvent.change(screen.getByLabelText("上传文件"), { target: { files: [file] } });

  expect(confirm).toHaveBeenCalledWith("文件“large.bin”大于 20MB，是否继续上传？");
  expect(upload).not.toHaveBeenCalled();
});

test("desktop status bar shows progress bars for file-tree downloads and uploads", async () => {
  const client = new MockWebBotClient();
  vi.spyOn(client, "listFiles").mockResolvedValue({
    workingDir: "C:\\workspace",
    entries: [{ name: "large.bin", isDir: false, size: 4096 }],
  });
  vi.spyOn(client, "downloadFile").mockImplementation(((_botAlias, _filename, onProgress, signal) => {
    onProgress?.({ downloadedBytes: 1024, totalBytes: 4096, percent: 25 });
    return pendingUntilAborted(signal);
  }) as typeof client.downloadFile);
  let uploadSignal: AbortSignal | undefined;
  vi.spyOn(client, "uploadFile").mockImplementation(((_botAlias, _file, onProgress, signal) => {
    uploadSignal = signal;
    onProgress?.({ uploadedBytes: 600, totalBytes: 1000, percent: 60 });
    return pendingUntilAborted(signal);
  }) as typeof client.uploadFile);
  render(
    <PersistentTerminalProvider client={client}>
      <DesktopWorkbench botAlias="main" client={client} chatPaneContent={<div>Chat</div>} />
    </PersistentTerminalProvider>,
  );
  const statusBar = await screen.findByTestId("desktop-workbench-statusbar");

  fireEvent.contextMenu(await screen.findByRole("button", { name: "打开 large.bin" }));
  fireEvent.click(screen.getByRole("button", { name: "下载" }));
  expect(await within(statusBar).findByRole("progressbar", { name: "large.bin 下载进度" })).toHaveAttribute("aria-valuenow", "25");

  fireEvent.drop(screen.getByTestId("desktop-file-tree-dropzone"), {
    dataTransfer: { files: [new File(["x"], "report.txt")], types: ["Files"] },
  });
  expect(await within(statusBar).findByRole("progressbar", { name: "report.txt 上传进度" })).toHaveAttribute("aria-valuenow", "60");

  fireEvent.click(within(statusBar).getByRole("button", { name: "取消上传" }));
  await waitFor(() => expect(within(statusBar).queryByRole("status", { name: "上传进度" })).not.toBeInTheDocument());
  expect(uploadSignal?.aborted).toBe(true);

  fireEvent.click(within(statusBar).getByRole("button", { name: "取消下载" }));
  await waitFor(() => expect(within(statusBar).queryByRole("progressbar")).not.toBeInTheDocument());
});
