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
};

export function AvatarPicker({
  assets,
  selectedName,
  previewAlt,
  selectLabel,
  onSelect,
  kind = "bot",
}: Props) {
  const effectiveName = pickAvailableAvatarName(selectedName, assets, kind);

  return (
    <div className="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
      <div className="flex items-center gap-3">
        <ChatAvatar alt={previewAlt} avatarName={effectiveName} kind={kind} size={36} />
        <div className="min-w-0">
          <div className="text-sm font-medium text-[var(--text)]">当前头像</div>
          <div className="truncate text-xs text-[var(--muted)]">{effectiveName}</div>
          <div className="text-[11px] text-[var(--muted)]">规格固定为 64x64，建议使用 PNG/JPG/WebP。</div>
        </div>
      </div>
      <label className="block space-y-1">
        <span className="text-sm text-[var(--text)]">{selectLabel}</span>
        <select
          aria-label={selectLabel}
          value={effectiveName}
          onChange={(event) => onSelect(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)]"
        >
          {assets.map((asset) => (
            <option key={asset.name} value={asset.name}>
              {asset.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
