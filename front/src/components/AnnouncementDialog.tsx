import { X } from "lucide-react";
import type { AnnouncementItem } from "../services/types";
import { AnnouncementTimeline } from "./AnnouncementContent";

type Props = {
  open: boolean;
  items: AnnouncementItem[];
  latestId: string;
  onClose: (latestId: string) => void;
};

export function AnnouncementDialog({ open, items, latestId, onClose }: Props) {
  if (!open) {
    return null;
  }

  return (
    <div className="orbit-backdrop fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="公告"
        className="orbit-dialog grid max-h-[88dvh] w-full grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden sm:max-h-[80vh] sm:w-[min(680px,calc(100vw-32px))]"
      >
        <header className="flex items-center justify-between px-5 pb-2 pt-4">
          <div>
            <h2 className="text-[17px] font-semibold text-[var(--text)]">公告</h2>
            <p className="mt-0.5 text-xs text-[var(--muted)]">新版本与运维通知</p>
          </div>
          <button
            type="button"
            aria-label="关闭公告"
            onClick={() => onClose(latestId)}
            className="orbit-btn orbit-btn--ghost orbit-btn--icon"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="overflow-y-auto px-5 pb-4 pt-2">
          {items.length === 0 ? (
            <div className="rounded-[var(--radius-card)] bg-[var(--fill-subtle)] p-6 text-center text-sm text-[var(--muted)]">
              暂无公告
            </div>
          ) : (
            <AnnouncementTimeline items={items} />
          )}
        </div>

        <footer className="flex justify-end border-t border-[var(--hairline)] px-5 py-3">
          <button
            type="button"
            onClick={() => onClose(latestId)}
            className="orbit-btn orbit-btn--primary min-w-24 sm:w-auto"
          >
            关闭
          </button>
        </footer>
      </section>
    </div>
  );
}
