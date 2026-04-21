import { lazy, Suspense } from "react";
import { DEFAULT_UI_THEME, type UiThemeName } from "../theme";
import type { WebBotClient } from "../services/webBotClient";
import type { TerminalWorkbenchStatus } from "./workbenchTypes";

const TerminalScreen = lazy(() =>
  import("../screens/TerminalScreen").then((module) => ({ default: module.TerminalScreen })),
);

type Props = {
  authToken: string;
  botAlias: string;
  client: WebBotClient;
  preferredWorkingDir: string;
  pendingWorkingDir?: string;
  themeName?: UiThemeName;
  visible?: boolean;
  focused?: boolean;
  onToggleFocus?: () => void;
  onAcceptPendingWorkingDir?: () => void;
  onCancelPendingWorkingDir?: () => void;
  onWorkbenchStatusChange?: (status: TerminalWorkbenchStatus) => void;
};

export function TerminalPane({
  authToken,
  botAlias,
  client,
  preferredWorkingDir,
  pendingWorkingDir,
  themeName = DEFAULT_UI_THEME,
  visible = true,
  focused = false,
  onToggleFocus,
  onAcceptPendingWorkingDir,
  onCancelPendingWorkingDir,
  onWorkbenchStatusChange,
}: Props) {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-[var(--muted)]">加载终端...</div>}>
      <TerminalScreen
        authToken={authToken}
        botAlias={botAlias}
        client={client}
        isVisible={visible}
        preferredWorkingDir={preferredWorkingDir}
        pendingWorkingDir={pendingWorkingDir}
        themeName={themeName}
        embedded
        focused={focused}
        onToggleFocus={onToggleFocus}
        onAcceptPendingWorkingDir={onAcceptPendingWorkingDir}
        onCancelPendingWorkingDir={onCancelPendingWorkingDir}
        onWorkbenchStatusChange={onWorkbenchStatusChange}
      />
    </Suspense>
  );
}
