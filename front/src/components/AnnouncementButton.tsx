import { Megaphone } from "lucide-react";

type Props = {
  hasUnseen: boolean;
  onClick: () => void;
};

export function AnnouncementButton({ hasUnseen, onClick }: Props) {
  return (
    <button
      type="button"
      aria-label="公告"
      title="公告"
      onClick={onClick}
      className="relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface-strong)]"
    >
      <Megaphone className="h-4 w-4" aria-hidden="true" />
      {hasUnseen ? (
        <span
          data-testid="announcement-unseen-dot"
          aria-hidden="true"
          className="pointer-events-none absolute right-1 top-1 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-[var(--surface-strong)]"
        />
      ) : null}
    </button>
  );
}
