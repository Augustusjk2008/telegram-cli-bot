import type { ComponentProps } from "react";
import { createPortal } from "react-dom";
import type { PluginInstallBatchItem, PluginInstallBatchResult, PluginInstallOutcome } from "../../services/types";
import { StateBadge } from "../StateBadge";
import { SurfacePanel } from "../SurfacePanel";
import { toolbarButtonClass } from "../ToolbarButton";

type Props = {
  result: PluginInstallBatchResult;
  onClose: () => void;
};

const OUTCOME_LABELS: Record<PluginInstallOutcome, string> = {
  installed: "新安装",
  upgraded: "升级",
  reinstalled: "重新安装",
  downgraded: "降级",
};

const OUTCOME_TONES: Record<PluginInstallOutcome, ComponentProps<typeof StateBadge>["tone"]> = {
  installed: "success",
  upgraded: "accent",
  reinstalled: "neutral",
  downgraded: "warning",
};

function describeCounts(items: PluginInstallBatchItem[]) {
  const counts: Record<PluginInstallOutcome, number> = { installed: 0, upgraded: 0, reinstalled: 0, downgraded: 0 };
  for (const item of items) {
    counts[item.installOutcome] += 1;
  }
  // Always answer "how many new, how many upgraded"; rarer outcomes appear only when they happened.
  return [
    `新安装 ${counts.installed} 个`,
    `升级 ${counts.upgraded} 个`,
    ...(counts.reinstalled ? [`重新安装 ${counts.reinstalled} 个`] : []),
    ...(counts.downgraded ? [`降级 ${counts.downgraded} 个`] : []),
  ].join("，");
}

function describeVersion(item: PluginInstallBatchItem) {
  const version = item.version ? `v${item.version}` : "";
  const changed = item.installOutcome === "upgraded" || item.installOutcome === "downgraded";
  return changed && item.previousVersion ? `v${item.previousVersion} → ${version}` : version;
}

function describeResult(items: PluginInstallBatchItem[]) {
  if (items.length === 0) {
    return "所选目录中没有可安装的插件";
  }
  // A host started before install outcomes existed still lists the plugins, just without outcomes.
  if (!items.every((item) => item.installOutcome in OUTCOME_LABELS)) {
    return `已安装 ${items.length} 个插件`;
  }
  return describeCounts(items);
}

export function PluginInstallResultDialog({ result, onClose }: Props) {
  const items = result.installed;
  const dialog = (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="plugin-install-result-title"
      aria-describedby="plugin-install-result-summary"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay-backdrop-50)] p-4"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          onClose();
        }
      }}
    >
      {/* Opened from the desktop workbench; the popover class keeps its button typography and overlay chrome. */}
      <SurfacePanel className="desktop-workbench-popover flex max-h-[80vh] w-full max-w-md flex-col p-4">
        <h2 id="plugin-install-result-title" className="text-base font-semibold text-[var(--text)]">插件安装完成</h2>
        <p id="plugin-install-result-summary" className="mt-2 text-sm text-[var(--text)]">
          {describeResult(items)}
        </p>
        {items.length > 0 ? (
          <ul
            aria-label="插件安装明细"
            className="mt-3 min-h-0 flex-1 divide-y divide-[var(--workbench-hairline)] overflow-y-auto rounded-[var(--radius-control)] border border-[var(--workbench-hairline)]"
          >
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate text-[var(--text)]" title={item.name || item.id}>{item.name || item.id}</span>
                <span className="shrink-0 text-xs tabular-nums text-[var(--muted)]">{describeVersion(item)}</span>
                {item.installOutcome in OUTCOME_LABELS ? (
                  <StateBadge tone={OUTCOME_TONES[item.installOutcome]} className="shrink-0">
                    {OUTCOME_LABELS[item.installOutcome]}
                  </StateBadge>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-4 flex justify-end">
          <button type="button" autoFocus onClick={onClose} className={toolbarButtonClass("primary", "sm", "min-w-16")}>
            确定
          </button>
        </div>
      </SurfacePanel>
    </div>
  );
  return typeof document === "undefined" ? dialog : createPortal(dialog, document.body);
}
