import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { AvatarAsset } from "../services/types";
import { pickAvailableAvatarName } from "../utils/avatar";
import { ChatAvatar } from "./ChatAvatar";

type Props = {
  assets: AvatarAsset[];
  selectedName: string;
  previewAlt: string;
  selectLabel: string;
  onSelect: (avatarName: string) => void;
  kind?: "user" | "bot";
  disabled?: boolean;
};

export function AvatarPicker({
  assets,
  selectedName,
  previewAlt,
  selectLabel,
  onSelect,
  kind = "bot",
  disabled = false,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const effectiveName = pickAvailableAvatarName(selectedName, assets, kind);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className="relative inline-flex">
      <button
        type="button"
        aria-label={selectLabel}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        disabled={disabled}
        onClick={() => setIsOpen((prev) => !prev)}
        className="relative inline-flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] shadow-sm transition hover:bg-[var(--surface-strong)] disabled:cursor-not-allowed disabled:opacity-60"
      >
        <ChatAvatar alt={previewAlt} avatarName={effectiveName} kind={kind} size={34} />
        <span className="absolute -bottom-0.5 -right-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-strong)] text-[var(--muted)]">
          <ChevronDown className="h-3 w-3" />
        </span>
      </button>

      {isOpen ? (
        <div className="absolute right-0 top-[calc(100%+0.5rem)] z-30 w-64 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-[var(--shadow-card)]">
          <div className="max-h-72 overflow-y-auto">
            {assets.map((asset) => {
              const isSelected = asset.name === effectiveName;
              return (
                <button
                  key={asset.name}
                  type="button"
                  aria-label={`选择头像 ${asset.name}`}
                  onClick={() => {
                    onSelect(asset.name);
                    setIsOpen(false);
                  }}
                  className={
                    isSelected
                      ? "flex w-full items-center gap-3 rounded-xl border border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-2 text-left"
                      : "flex w-full items-center gap-3 rounded-xl border border-transparent px-3 py-2 text-left hover:bg-[var(--surface-strong)]"
                  }
                >
                  <ChatAvatar alt={`${asset.name} 预览`} avatarName={asset.name} kind={kind} size={28} />
                  <span className="min-w-0 flex-1 truncate text-sm text-[var(--text)]">{asset.name}</span>
                  {isSelected ? (
                    <span className="rounded-full bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--muted)]">当前</span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
