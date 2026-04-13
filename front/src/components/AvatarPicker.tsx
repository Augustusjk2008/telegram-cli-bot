import type { AvatarAsset } from "../services/types";
import { ChatAvatar } from "./ChatAvatar";

type Props = {
  assets: AvatarAsset[];
  selectedName: string;
  previewAlt: string;
  onSelect: (avatarName: string) => void;
};

export function AvatarPicker({ assets, selectedName, previewAlt, onSelect }: Props) {
  return (
    <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="flex items-center gap-3">
        <ChatAvatar alt={previewAlt} avatarName={selectedName} kind="bot" size={36} />
        <div className="min-w-0">
          <div className="text-sm font-medium text-[var(--text)]">当前头像</div>
          <div className="truncate text-xs text-[var(--muted)]">{selectedName}</div>
          <div className="text-[11px] text-[var(--muted)]">规格固定为 64x64，建议使用 PNG/JPG/WebP。</div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {assets.map((asset) => {
          const selected = asset.name === selectedName;
          return (
            <button
              key={asset.name}
              type="button"
              aria-label={`选择头像 ${asset.name}`}
              onClick={() => onSelect(asset.name)}
              className={selected
                ? "flex items-center gap-2 rounded-xl border border-[var(--accent)] bg-[var(--accent)]/5 px-2 py-2 text-left"
                : "flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-2 py-2 text-left hover:bg-[var(--surface-strong)]"}
            >
              <ChatAvatar alt={`${asset.name} 预览`} avatarName={asset.name} kind="bot" size={28} />
              <span className="min-w-0 truncate text-xs text-[var(--text)]">{asset.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
