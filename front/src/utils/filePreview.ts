import type { FileReadResult } from "../services/types";

export const FILE_PREVIEW_FULL_READ_LIMIT_BYTES = 200 * 1024;

export function isFilePreviewTooLarge(fileSizeBytes?: number) {
  return typeof fileSizeBytes === "number" && fileSizeBytes > FILE_PREVIEW_FULL_READ_LIMIT_BYTES;
}

export function isFilePreviewFullyLoaded(result: FileReadResult | null) {
  if (!result) {
    return false;
  }
  return result.mode === "cat" || Boolean(result.isFullContent);
}

export function getFilePreviewStatusText(result: FileReadResult | null) {
  if (!result) {
    return "";
  }
  if (isFilePreviewTooLarge(result.fileSizeBytes)) {
    return "文件超过200KB，请下载后读取全文";
  }
  if (isFilePreviewFullyLoaded(result)) {
    return "已加载全文";
  }
  return "";
}
