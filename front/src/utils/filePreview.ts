import type { FileReadResult } from "../services/types";

export const FILE_PREVIEW_FULL_READ_LIMIT_BYTES = 1024 * 1024;

export function isFilePreviewTooLarge(result: FileReadResult | null) {
  return Boolean(
    result
    && result.previewKind !== "image"
    && typeof result.fileSizeBytes === "number"
    && result.fileSizeBytes > FILE_PREVIEW_FULL_READ_LIMIT_BYTES,
  );
}

export function isFilePreviewFullyLoaded(result: FileReadResult | null) {
  if (!result) {
    return false;
  }
  if (result.previewKind === "image") {
    return true;
  }
  return result.mode === "cat" || Boolean(result.isFullContent);
}

export function getFilePreviewStatusText(result: FileReadResult | null) {
  if (!result) {
    return "";
  }
  if (result.previewKind === "image") {
    return "已加载图片预览";
  }
  if (isFilePreviewTooLarge(result)) {
    return "文件超过1MB，请下载后读取全文";
  }
  if (isFilePreviewFullyLoaded(result)) {
    return "已加载全文";
  }
  return "";
}
