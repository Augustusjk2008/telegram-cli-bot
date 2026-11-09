export const LARGE_FILE_UPLOAD_THRESHOLD_BYTES = 20 * 1024 * 1024;

export function confirmLargeFileUpload(file: Pick<File, "name" | "size">): boolean {
  if (file.size <= LARGE_FILE_UPLOAD_THRESHOLD_BYTES) {
    return true;
  }
  return window.confirm(`文件“${file.name}”大于 20MB，是否继续上传？`);
}

export function confirmLargeFileUploads(files: readonly Pick<File, "name" | "size">[]): boolean {
  return files.every(confirmLargeFileUpload);
}
