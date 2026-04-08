import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

type Props = {
  status: "running" | "busy" | "offline";
  className?: string;
};

export function StatusPill({ status, className }: Props) {
  const statusMap = {
    running: { label: "运行中", color: "bg-green-100 text-green-800 border-green-200" },
    busy: { label: "处理中", color: "bg-yellow-100 text-yellow-800 border-yellow-200" },
    offline: { label: "离线", color: "bg-gray-100 text-gray-800 border-gray-200" },
  };

  const config = statusMap[status];

  return (
    <span className={twMerge(clsx("px-2 py-0.5 text-xs rounded-full border", config.color), className)}>
      {config.label}
    </span>
  );
}
