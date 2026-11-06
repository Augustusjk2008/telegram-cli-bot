import { TransferProgressBar } from "../components/TransferProgressBar";
import { formatTransferDetail } from "../utils/transferProgress";

type Props = {
  verb: "上传" | "下载";
  target: string;
  transferredBytes: number;
  totalBytes?: number;
  percent?: number;
  awaitingServer?: boolean;
  onCancel: () => void;
};

export function WorkbenchTransferStatus({
  verb,
  target,
  transferredBytes,
  totalBytes,
  percent,
  awaitingServer = false,
  onCancel,
}: Props) {
  const detail = formatTransferDetail(transferredBytes, totalBytes);
  const valueText = awaitingServer
    ? "处理中"
    : typeof percent === "number" ? `${percent}%` : detail;
  return (
    <div className="flex items-center gap-2">
      <span
        role="status"
        aria-label={`${verb}进度`}
        title={`${verb} ${target} · ${awaitingServer ? `${detail} · 等待服务器处理` : detail}`}
        className="flex min-w-0 items-center gap-2"
      >
        <span className="max-w-[8rem] truncate xl:max-w-[16rem]">{verb} {target}</span>
        <TransferProgressBar label={`${target} ${verb}进度`} percent={percent} className="h-1.5 w-20 shrink-0" />
        <span className="shrink-0 font-mono">{valueText}</span>
      </span>
      <button
        type="button"
        onClick={onCancel}
        className="rounded border border-[var(--workbench-hairline)] px-2 py-0.5 text-[var(--danger)] hover:bg-[var(--workbench-hover-bg)]"
      >
        取消{verb}
      </button>
    </div>
  );
}
