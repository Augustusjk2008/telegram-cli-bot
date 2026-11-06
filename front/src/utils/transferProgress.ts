export function formatTransferBytes(value: number) {
  if (value >= 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

export function formatTransferDetail(transferredBytes: number, totalBytes?: number) {
  if (typeof totalBytes === "number" && totalBytes > 0) {
    return `${formatTransferBytes(transferredBytes)} / ${formatTransferBytes(totalBytes)}`;
  }
  return formatTransferBytes(transferredBytes);
}
